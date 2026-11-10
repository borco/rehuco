"""Renames a ``.rehu`` resource's files on disk -- the **execute** end of the rename design
([[plugins#toolkit-surfaces]]'s compute -> present/command -> execute split).

The name arrives already chosen (a clicked rename suggestion, sanitized by the widget that offered it);
this is what makes it true on disk. Core-side and GUI-free, the same split
:mod:`rehuco_core.tc_conversion` sits on: the agent's view-model orchestrates and reports, this decides
which files move and moves them.

Both resource scopes ([[data-model#resource-scoping]]) reduce to one **plan** of ``(source,
destination)`` pairs whose destinations share **one folder**: the record's own, for a rename, or another under the
same root, for a move in place (#579), whose missing parents are made first. Either is a rename on one filesystem --
the checksum-gated cross-filesystem move ([[mounts-and-storage#safe-move-rename]]) is a different operation. A
directory-scoped ``info.rehu`` renames its parent directory (one pair, atomic); a file-scoped ``foo.rehu`` renames
every file named after it -- ``foo.`` anything, or ``foo`` followed by a digit, so ``foobar.zip`` is left to whoever
it belongs to. The whole plan is collision-checked before the first rename runs, and a failure part-way through
renames the completed steps back and removes the folders it made, so a sibling set is never left split between two
names ([[data-model#write-integrity]]).

Nothing is attempted at all for a resource whose ``.rehu`` is not on disk: a missing file is not a
resource to rename but a record to fix ([[data-model#write-integrity]]'s fix-retry loop), and guessing
what its sibling set *would* have been is exactly the guess a rename must not make.
"""

import errno
import logging
import os
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .checksum_record import checksum_record_path, rename_checksum_entries, update_checksum_record
from .checksum_trust import DEFAULT_CHECKSUM_TRUST, ChecksumTrust
from .constants import REHU_SUFFIX
from .path_keys import path_key
from .record_file_lock import RecordFileLock, is_lock_name
from .relocation import Relocation
from .resource_scoping import is_directory_scoped

LOG: Final = logging.getLogger(__name__)

TRANSIENT_LOCK_ERRORS: Final = frozenset({5, 32})
"""The Windows errors a refused rename step is retried on (#355): ``ERROR_ACCESS_DENIED`` and
``ERROR_SHARING_VIOLATION``. They are what a file briefly held by someone else answers -- Defender or the
Search indexer scanning a freshly scraped image, a thumbnail extractor -- and what it stops answering a
moment later. Any other error is a fact about the rename and fails at once."""

RETRY_DELAYS: Final = (0.05, 0.1, 0.2, 0.4)
"""How long to wait before each retry of a step refused with a :data:`TRANSIENT_LOCK_ERRORS` error, in
seconds -- ~0.75 s in all. Long enough for a scanner to finish with a file; short enough that a lock that
is *not* transient (an Explorer window open on the folder) is still reported promptly, since the rename
blocks the GUI thread that asked for it."""


CROSS_DEVICE_WINERROR: Final = 17
"""``ERROR_NOT_SAME_DEVICE``: what Windows answers a rename to another drive or share."""


def is_cross_device(error: OSError) -> bool:
    """Whether a rename failed only because its two ends are on different volumes -- the one refusal a move answers
    with a verified copy instead (#339, [[mounts-and-storage#safe-move-rename]]).

    :param error: what the rename raised.
    :returns: ``EXDEV``, or Windows' ``ERROR_NOT_SAME_DEVICE``.
    """
    return error.errno == errno.EXDEV or getattr(error, "winerror", None) == CROSS_DEVICE_WINERROR


class PartialRenameError(OSError):
    """A rename failed part-way through **and** rolling the completed steps back failed too, leaving the
    resource's files split between their old and new names ([[data-model#write-integrity]]).

    The one outcome :class:`RehuRenamer` cannot make clean, and so the one worth its own type: an
    ordinary failure re-raises the ``OSError`` that caused it with every file back under its original
    name, while this says the set on disk is now inconsistent and only the user can settle it. An
    ``OSError`` subclass, so a caller that treats every rename failure alike still catches it; the
    original failure that started the rollback is its ``__cause__``.
    """


def rename_rehu_resource(path: Path, new_name: str) -> Path:
    """Rename the resource at ``path`` to ``new_name`` on disk ([[plugins#toolkit-surfaces]]).

    :param path: the resource's ``.rehu`` file -- ``info.rehu`` for a directory-scoped resource, any
        other name for a file-scoped one ([[data-model#resource-scoping]]).
    :param new_name: the destination folder/file name: a plain name, without extension or directory
        separators.
    :returns: the resource's ``.rehu`` path under its new name; ``path`` unchanged when ``new_name`` is
        already the resource's name (nothing on disk is touched).
    :raises ValueError: ``new_name`` is empty or is anything but a plain file/folder name.
    :raises FileNotFoundError: ``path`` is not on disk; nothing is attempted.
    :raises RecordLockedError: another process holds the record's lock file ([[sync#lock-file]]); nothing is
        attempted, and the error names the holder.
    :raises FileExistsError: something already occupies one of the planned destinations; nothing on disk
        was touched.
    :raises PartialRenameError: a rename failed and undoing the completed ones failed too.
    :raises OSError: propagated from the failing rename, once every completed step is back under its
        original name.
    """
    return RehuRenamer(path, new_name).rename()


def rehu_rename_conflict(path: Path, new_name: str) -> Path | None:
    """Whatever already occupies the destination renaming ``path`` to ``new_name`` would take.

    The **advisory** counterpart of :func:`rename_rehu_resource`, for a caller that wants to show a name
    as unavailable rather than let the user pick it and be told afterwards
    ([[plugins#toolkit-surfaces]]). Never touches anything: one existence check, no plan, no listing.

    :param path: the resource's ``.rehu`` file.
    :param new_name: the candidate folder/file name.
    :returns: the existing directory (directory-scoped) or ``.rehu`` (file-scoped) in the way, or
        ``None`` when the name is free, is the resource's own current name, or is not a plain name at
        all.
    """
    return RehuRenamer(path, new_name).conflict()


def move_rehu_resource(path: Path, into: Path, new_name: str) -> Path:
    """Move the resource at ``path`` into the folder ``into``, under ``new_name`` -- a move in place within its root
    (#579), the folder's missing parents made first.

    :param path: the resource's ``.rehu`` file.
    :param into: the folder the resource's own entry -- its folder, or its file set -- lands in.
    :param new_name: the destination folder/file name; see :func:`rename_rehu_resource`.
    :returns: the resource's ``.rehu`` path where it now is.
    :raises ValueError: ``new_name`` is not a plain name, or a folder would move into itself.
    :raises FileNotFoundError: see :func:`rename_rehu_resource`.
    :raises RecordLockedError: see :func:`rename_rehu_resource`.
    :raises FileExistsError: see :func:`rename_rehu_resource`.
    :raises PartialRenameError: see :func:`rename_rehu_resource`.
    :raises OSError: see :func:`rename_rehu_resource`; also a folder that could not be made.
    """
    return RehuRenamer(path, new_name, into=into).rename()


def rehu_move_conflict(path: Path, into: Path, new_name: str) -> Path | None:
    """Whatever already occupies the destination moving ``path`` into ``into`` as ``new_name`` would take; the advisory
    counterpart of :func:`move_rehu_resource`, as :func:`rehu_rename_conflict` is of a rename.

    :param path: the resource's ``.rehu`` file.
    :param into: the folder the resource's own entry would land in.
    :param new_name: the candidate folder/file name.
    :returns: the entry in the way, or ``None``; see :func:`rehu_rename_conflict`.
    """
    return RehuRenamer(path, new_name, into=into).conflict()


def remove_empty_parents(start: Path, stop_at: Path) -> list[Path]:
    """Remove ``start`` and each folder above it while it is empty, stopping beneath ``stop_at`` (#579).

    What a move in place may leave behind: the folder its record left, emptied, and the ones above it emptied by that.
    Removing stops at the first folder that is not empty or will not go, and never reaches ``stop_at`` itself or
    anything outside it.

    :param start: the deepest folder to try.
    :param stop_at: the folder to stop beneath -- the root's.
    :returns: the folders removed, deepest first.
    """
    removed: list[Path] = []
    stop_parts = tuple(map(path_key, stop_at.parts))
    folder = start
    while len(folder.parts) > len(stop_parts) and tuple(map(path_key, folder.parts[: len(stop_parts)])) == stop_parts:
        try:
            folder.rmdir()
        except OSError:
            break
        removed.append(folder)
        folder = folder.parent
    return removed


class RehuRenamer:
    """Renames one ``.rehu`` resource's files to a new name ([[plugins#toolkit-surfaces]]).

    Three phases: **plan** (pure reads -- which files this resource's scope owns, and what each is to be
    called), **check** (nothing may occupy a destination), then **execute** (rename each in turn, undoing
    the completed ones if any fails). The check covers the whole plan before the first rename runs, so a
    set that would collide on its last file is refused with nothing on disk touched -- the shape
    :class:`~rehuco_core.TcConverter` already uses for the conversion's own file replacement.

    :param path: the resource's ``.rehu`` file.
    :param new_name: the destination folder/file name; see :func:`rename_rehu_resource`.
    :param trust: the checksum trust a completed rename carries to the new name (#357); the process-wide
        one unless a test says otherwise.
    :param into: the folder the resource's own entry lands in -- a move in place (#579), its missing parents made
        before the first step; ``None`` keeps it where it is, a rename.
    """

    def __init__(
        self, path: Path, new_name: str, trust: ChecksumTrust = DEFAULT_CHECKSUM_TRUST, *, into: Path | None = None
    ) -> None:
        self.__path: Final = path
        self.__new_name: Final = new_name
        self.__trust: Final = trust
        self.__into: Final = into
        self.__relocation = Relocation()
        """The plan :meth:`rename` actually carried out, and what :meth:`relocate` answers from. Empty
        until a rename succeeds -- including after one that was rolled back, so a failure leaves every
        path where a caller last saw it rather than pointing at destinations that no longer hold
        anything."""

    def rename(self) -> Path:
        """Run the full plan-check-execute sequence.

        :returns: the resource's ``.rehu`` path under its new name; see :func:`rename_rehu_resource`.
        :raises ValueError: see :func:`rename_rehu_resource`.
        :raises FileNotFoundError: see :func:`rename_rehu_resource`.
        :raises RecordLockedError: see :func:`rename_rehu_resource`.
        :raises FileExistsError: see :func:`rename_rehu_resource`.
        :raises PartialRenameError: see :func:`rename_rehu_resource`.
        :raises OSError: see :func:`rename_rehu_resource`.
        """
        self.__check_name()
        self.__check_source_exists()
        if self.__new_name == self.__current_name and not self.__changes_folder:
            # a rename to the name it already has: not an error, just nothing to do. A rename that
            # differs only in *case* is a real one and falls through -- it is how a name's spelling is
            # corrected on a case-insensitive filesystem.
            return self.__path
        self.__check_not_into_itself()
        # a save elsewhere is between its re-read and its write: moving the record now would leave that write
        # landing under the old name (#512) -- the record's, or its checksum record's
        RecordFileLock(self.__path).refuse_if_held()
        RecordFileLock(checksum_record_path(self.__path)).refuse_if_held()
        plan = self.__plan()
        self.__check_no_collisions(plan)
        made = self.__make_folder()
        try:
            self.__execute(plan)
        except OSError:
            self.__remove_made(made)
            raise
        renamed = self.__new_document_path()
        self.__rename_checksum_entries(plan, renamed)
        # a rename rewrites no bytes, so what was verified under the old name still holds under the new
        # one -- a copy or move made outside the app is never heard of here, and re-verifies (#357)
        self.__trust.moved(self.__path, renamed)
        return renamed

    def __rename_checksum_entries(self, plan: Sequence[tuple[Path, Path]], renamed: Path) -> None:
        """Rename a file record's checksum entries along with its files (#339).

        A file record's entries are its files' own names, so ``foo.zip`` renamed to ``bar.zip`` would otherwise leave
        an entry naming nothing and a file no entry names. A folder record's entries are relative to its folder and
        never change. A record that cannot be rewritten is logged, and the rename stands: the files moved.

        :param plan: the pairs the rename carried out.
        :param renamed: the record's ``.rehu`` where it now is.
        """
        names = {source.name: destination.name for source, destination in plan if source.name != destination.name}
        if self.__directory_scoped or not names:
            return
        try:
            update_checksum_record(checksum_record_path(renamed), lambda record: rename_checksum_entries(record, names))
        except OSError, ValueError:
            LOG.warning("The checksum record of %s still names its files' old names.", renamed, exc_info=True)

    @property
    def executed(self) -> tuple[tuple[Path, Path], ...]:
        """The ``(source, destination)`` pairs this rename carried out, in the order they ran.

        What :meth:`relocate` answers from, handed over whole for a reader that applies the same rule somewhere
        else -- the catalog cache rebasing its rows without re-reading them
        (:meth:`~rehuco_core.CatalogCache.apply_relocation`, #373). Empty whenever :meth:`relocate` would move
        nothing: before :meth:`rename`, after a no-op, and after a failure.

        :returns: the executed plan.
        """
        return self.__relocation.pairs

    @property
    def relocation(self) -> Relocation:
        """The executed plan as a :class:`~rehuco_core.Relocation`, for a holder elsewhere to apply to everything
        it holds -- what :class:`~rehuco_core.RenameCoordinator` announces once a rename lands (#376). Empty
        exactly when :attr:`executed` is.

        :returns: the executed plan.
        """
        return self.__relocation

    def relocate(self, candidate: Path) -> Path:
        """Where ``candidate`` ended up once this rename ran, or ``candidate`` itself if it did not move
        (#241).

        **The rename seen from the outside.** A long job holds paths inside a resource -- the file it is
        reading, the record it will write -- and a rename moves them out from under it. Rather than have
        the job guess, it asks here, and the answer comes from *the plan this instance actually
        executed* rather than from a second traversal that could disagree with it: the same one list of
        pairs :meth:`__execute` renamed, read back the other way.

        Both scopes ([[data-model#resource-scoping]]) are one rule, :meth:`Relocation.relocate`'s -- **a
        path at or beneath a renamed source lands at the same offset beneath its destination** -- with
        case folded as :class:`Relocation` folds it.

        Answers about **this instance's** rename and no other: before :meth:`rename` has run, after one
        that was a no-op, and after one that failed and was rolled back, every path comes back
        unchanged, because in each of those cases nothing moved. After a
        :class:`PartialRenameError` it also answers unchanged, which is deliberate: some files did move
        and could not be put back, and pointing a job at a destination that may or may not hold anything
        would be guessing where reporting the original path lets the job fail where the problem is.

        :param candidate: a path that may sit inside this resource -- a job's content file, its record,
            or the ``.rehu`` itself.
        :returns: the path ``candidate`` now has, or ``candidate`` unchanged when this rename did not
            move it.
        """
        return self.__relocation.relocate(candidate)

    def conflict(self) -> Path | None:
        """Whatever already occupies this rename's own destination, or ``None`` when it is free.

        Exactly :meth:`__check_no_collisions`'s rule -- destination taken, and not by the source itself
        (:meth:`__is_itself`) -- applied to the **one** pair every scope has
        (:meth:`__own_pair`): the folder for a directory-scoped resource, the ``.rehu`` for a
        file-scoped one. Deliberately *not* the whole plan, which for a file-scoped resource must list
        the directory and stat every sibling destination: this answers behind a live suggestion list,
        re-asked as the user types, and that is far too much work to put on a keystroke -- let alone on
        a possibly-offline mount ([[mounts-and-storage#offline-mounts]]).

        So this is an affordance, not the authority. A name it clears can still collide on a sibling at
        execute time, where the full check refuses with nothing touched; what it buys is that the
        collision a user can actually *see* coming -- another resource already sitting under that name
        -- is one they are never invited to attempt.

        **Uncached, deliberately.** Measured at ~15 us per call, so ten candidates cost ~0.15 ms per
        render -- a hundredth of a frame, against ~24 ms if this ran the sibling sweep instead. Memoizing
        would trade that for staleness with no way to detect it: the answers change under a successful
        rename (which is precisely the set of names just asked about), under the first save of a new
        document, and under anything the user does in a file manager while the editor sits open. A stale
        *free* re-invites the failure this exists to prevent; a stale *taken* greys a name out with no
        way back. The speed is the operating system's own attribute cache already doing this job, one
        layer down and with the invalidation this layer cannot see.

        :returns: the entry in the way, or ``None`` when the name is free, is this resource's own
            current name, or is not a plain file/folder name at all (nothing to report -- such a name
            fails for its own reason, and only :meth:`rename` is in a position to say so).
        """
        if not self.__is_plain_name():
            return None
        source, destination = self.__own_pair()
        if self.__is_itself(source, destination):
            return None
        return destination if destination.exists() else None

    def plan(self) -> list[tuple[Path, Path]]:
        """The ``(source, destination)`` pairs this rename would carry out, read from the disk and checked as
        :meth:`rename` checks them -- all but the collisions, which a caller placing the files by other means (a
        verified copy to another filesystem, #339) settles its own way.

        :returns: the planned pairs, the resource's own entry first: its folder, or its ``.rehu`` and the files named
            after it.
        :raises ValueError: see :func:`move_rehu_resource`.
        :raises FileNotFoundError: see :func:`rename_rehu_resource`.
        :raises OSError: the resource's directory cannot be listed.
        """
        self.__check_name()
        self.__check_source_exists()
        self.__check_not_into_itself()
        return self.__plan()

    @property
    def __directory_scoped(self) -> bool:
        """Whether this resource is the directory it sits in (an ``info.rehu``, or the ``info.tc`` a
        conversion has not reached yet, [[data-model#resource-scoping]]) rather than a file beside its
        siblings -- asked of the one place that answers it (#250)."""
        return is_directory_scoped(self.__path)

    @property
    def __current_name(self) -> str:
        """The name this rename replaces: the parent directory's for a directory-scoped resource, the
        file stem for a file-scoped one."""
        return self.__path.parent.name if self.__directory_scoped else self.__path.stem

    def __own_pair(self) -> tuple[Path, Path]:
        """The rename of the resource's **own** entry -- the one pair both scopes have.

        For a directory-scoped resource that entry is the parent directory, and it is the whole plan;
        for a file-scoped one it is the ``.rehu``, which leads the plan its siblings follow. Spelled
        once, so :meth:`__plan` and :meth:`conflict` cannot drift on what "the destination" means.

        :returns: the ``(source, destination)`` pair for the resource's own entry.
        """
        if self.__directory_scoped:
            return (self.__path.parent, self.__folder / self.__new_name)
        return (self.__path, self.__folder / (self.__new_name + self.__path.suffix))

    @property
    def __source_folder(self) -> Path:
        """The folder the resource's own entry is in now: the one holding its folder, or holding its file set."""
        return self.__path.parent.parent if self.__directory_scoped else self.__path.parent

    @property
    def __folder(self) -> Path:
        """The folder the resource's own entry lands in: ``into``, or where it is now."""
        return self.__source_folder if self.__into is None else self.__into

    @property
    def __changes_folder(self) -> bool:
        """Whether the entry lands in another folder than the one it is in -- folded, so a folder spelled in another
        case is the same one."""
        return path_key(self.__folder) != path_key(self.__source_folder)

    def __check_not_into_itself(self) -> None:
        """Refuse moving a resource's folder into itself or beneath it.

        :raises ValueError: the destination folder is the resource's own folder or inside it.
        """
        if not self.__directory_scoped:
            return
        source = tuple(map(path_key, self.__path.parent.parts))
        if tuple(map(path_key, self.__folder.parts[: len(source)])) == source:
            raise ValueError(f'"{self.__current_name}" cannot be moved into itself: {self.__folder}')

    def __make_folder(self) -> list[Path]:
        """Make the destination folder's missing parents, the topmost first.

        :returns: the folders made, in the order they were made; none for a rename, which stays where it is.
        :raises OSError: one could not be made; any made before it are removed again.
        """
        if not self.__changes_folder:
            return []
        missing: list[Path] = []
        folder = self.__folder
        while not folder.exists() and folder != folder.parent:
            missing.append(folder)
            folder = folder.parent
        made: list[Path] = []
        try:
            for folder in reversed(missing):
                folder.mkdir()
                made.append(folder)
        except OSError:
            self.__remove_made(made)
            raise
        return made

    @staticmethod
    def __remove_made(made: Sequence[Path]) -> None:
        """Remove the folders a failed move made, the deepest first; one that will not go is logged and left.

        :param made: the folders made, in the order they were made.
        """
        for folder in reversed(made):
            try:
                folder.rmdir()
            except OSError:
                LOG.warning("Could not remove %s, made for a move that failed.", folder, exc_info=True)

    def __new_document_path(self) -> Path:
        """Where this resource's ``.rehu`` ends up once the plan has run.

        :returns: the renamed directory's record, under the name it already had, for a directory-scoped
            resource; the renamed file for a file-scoped one.
        """
        if self.__directory_scoped:
            return self.__own_pair()[1] / self.__path.name
        return self.__own_pair()[1]

    def __is_plain_name(self) -> bool:
        """Whether ``new_name`` is a plain file/folder name, safe to build a destination from.

        ``Path(name).name`` is what applies the running platform's own rule rather than a hand-written
        separator list: it strips whatever *this* filesystem reads as a directory separator, so a
        backslash stays a legal character in a POSIX filename and is refused on Windows. The relative
        names are spelled out beside it because ``pathlib`` disagrees with itself about them -- ``.``
        normalizes away to an empty name, while ``..`` survives as a name of its own -- and neither is a
        name anything may be renamed to. Whether a surviving name is *desirable* (transliterated, free
        of reserved characters) is settled where the suggestion is offered, not here.

        :returns: whether the name can name a single entry in the resource's own directory.
        """
        name = self.__new_name
        return bool(name) and name not in {os.curdir, os.pardir} and name == Path(name).name

    def __check_name(self) -> None:
        """Refuse a destination that isn't a plain file/folder name (:meth:`__is_plain_name`).

        :raises ValueError: ``new_name`` is empty or names anything but a plain file/folder name.
        """
        if not self.__is_plain_name():
            raise ValueError(f"{self.__new_name!r} is not a plain file or folder name.")

    def __check_source_exists(self) -> None:
        """Refuse to do anything at all when the resource's ``.rehu`` is not on disk.

        Checked here, before the plan is even built, because for a file-scoped resource the plan is
        *derived from the disk*: with the ``.rehu`` gone there is no stem to sweep and nothing to
        establish what the set was. A missing record's remedy is a re-read
        ([[data-model#write-integrity]]'s fix-retry loop), never a rename of whatever else happens to
        still carry its name.

        :raises FileNotFoundError: the ``.rehu`` is missing, or is not a file.
        """
        if not self.__path.is_file():
            raise FileNotFoundError(f'"{self.__path.name}" is no longer on disk.')

    def __plan(self) -> list[tuple[Path, Path]]:
        """Every ``(source, destination)`` rename this resource's scope calls for
        ([[data-model#resource-scoping]]).

        A directory-scoped resource is **one** rename -- its parent directory -- which carries the
        ``.rehu``, the screenshots, and the resource's own content with it in a single atomic operation.
        A file-scoped one is every file named after it (:meth:`__sibling_set`), each keeping whatever
        follows the stem: ``foo.zip`` becomes ``bar.zip``, ``foo00.jpg`` becomes ``bar00.jpg``,
        ``foo.002`` becomes ``bar.002``.

        :returns: the planned renames, the ``.rehu`` itself first.
        :raises OSError: the resource's directory cannot be listed; see :meth:`__sibling_set`.
        """
        if self.__directory_scoped:
            return [self.__own_pair()]
        stem_length = len(self.__path.stem)
        return [
            (sibling, self.__folder / (self.__new_name + sibling.name[stem_length:]))
            for sibling in self.__sibling_set()
        ]

    def __sibling_set(self) -> list[Path]:
        """Every file named after this file-scoped resource (:meth:`__named_after`).

        A file-scoped resource carries no manifest of the files it describes
        ([[data-model#resource-scoping]] names that as the gap), so **being named after it is the
        association**: the ``.rehu``, the ``<stem>NN`` screenshots, the checksum manifest, and
        the content itself -- one ``foo.zip``, or a ``foo.001``/``foo.002`` multi-part set. Renaming
        only some of them would break the one convention holding them together, which is why membership
        is a naming rule rather than the list of file kinds this build happens to recognize.

        **Directories are skipped.** A file-scoped ``.rehu`` describes files; a directory beside it is
        either a resource of its own (with its own ``info.rehu``) or nothing to do with this one. So is a lock
        file (#512): a stale one left beside the record is no part of it, and a fresh one refused the rename.

        **Another record's files are skipped too.** With ``foo.rehu`` and ``foo2.rehu`` side by side,
        ``foo2``'s whole set is named after ``foo`` by the rule below and would otherwise travel with
        it, silently renaming a record nobody asked about. A sibling ``.rehu`` whose stem extends this
        one's owns everything under that longer stem, so those are excluded -- and that exclusion is a
        **bare prefix**, deliberately wider than the membership rule it undoes: the two asymmetries err
        the same way, toward leaving a file alone.

        Every comparison folds case on every platform (:func:`~rehuco_core.path_key`): a resource's files
        share its spelling, and one that does not -- ``FOO.zip`` beside ``foo.rehu`` -- is still one unit.

        :returns: the ``.rehu`` first (it is the resource's identity), then the rest sorted by name.
        :raises OSError: the directory cannot be listed -- e.g. an offline mount
            ([[mounts-and-storage#offline-mounts]]); nothing is renamed.
        """
        stem = path_key(self.__path.stem)
        document_name = path_key(self.__path.name)
        named_after = [
            entry
            for entry in self.__path.parent.iterdir()
            if not entry.is_dir() and not is_lock_name(entry.name) and self.__named_after(entry.name)
        ]
        foreign = self.__foreign_stems(named_after, stem)
        owned = [
            entry
            for entry in named_after
            if path_key(entry.name) != document_name
            and not any(path_key(entry.name).startswith(other) for other in foreign)
        ]
        return [self.__path, *sorted(owned, key=lambda entry: entry.name)]

    def __named_after(self, name: str) -> bool:
        """Whether the sibling ``name`` is named after this resource.

        A **separator** decides it, not a bare prefix: what follows the stem must be nothing at all (the
        file simply *is* the resource's name), an extension separator (``foo.zip``, ``foo.sfv``,
        ``foo.001``), or a digit (``foo00.jpg``, and any other numbered continuation). More *letters*
        make a different name that merely starts alike -- ``foobar.zip`` and ``foo_extras.txt`` are
        nobody's business but their own, and nothing need sit beside them to establish that. This is
        what keeps the sweep from turning a shared prefix into a claim of ownership; the sibling-``.rehu``
        exclusion in :meth:`__sibling_set` is then a backstop for the ambiguous digit case, not the only
        thing standing between a rename and somebody else's files.

        The stem is matched over **as many characters as this resource's stem has**, folded
        (:func:`~rehuco_core.path_key`), which is the slice :meth:`__plan` replaces: a sibling whose spelling folds
        to the stem but at another length (a dotted capital ``İ`` folds to two characters) is left alone rather than
        cut at the wrong place.

        :param name: the sibling's filename, as spelled.
        :returns: whether the sibling travels with the resource.
        """
        length = len(self.__path.stem)
        if path_key(name[:length]) != path_key(self.__path.stem):
            return False
        tail = name[length:]
        return not tail or tail.startswith(os.extsep) or tail[0].isdigit()

    @staticmethod
    def __foreign_stems(named_after: Sequence[Path], stem: str) -> list[str]:
        """The folded stems of any *other* ``.rehu`` among ``named_after`` -- each one a resource in
        its own right, whose files must not travel with this rename.

        :param named_after: the siblings named after this resource.
        :param stem: this resource's own folded stem.
        :returns: the extending stems whose files to leave alone.
        """
        return [
            path_key(entry.stem)
            for entry in named_after
            if entry.suffix.lower() == REHU_SUFFIX and path_key(entry.stem) != stem
        ]

    @staticmethod
    def __check_no_collisions(plan: Sequence[tuple[Path, Path]]) -> None:
        """Refuse the whole plan if anything already occupies one of its destinations, or two of them are one name.

        A destination that is its own source (:meth:`__is_itself`) -- renaming ``foo`` to ``Foo`` -- is not a
        collision but the very rename being asked for. Two siblings a case-sensitive disk keeps apart, ``FOO.zip``
        and ``foo.zip``, fold to one destination; renaming both would put the second over the first, so the plan is
        refused instead.

        :param plan: the planned renames.
        :raises FileExistsError: something already occupies a destination, or two sources share one.
        """
        taken: dict[str, Path] = {}
        for source, destination in plan:
            if not RehuRenamer.__is_itself(source, destination) and destination.exists():
                raise FileExistsError(f'"{destination.name}" already exists.')
            other = taken.setdefault(path_key(destination), source)
            if str(other) != str(source):
                raise FileExistsError(f'"{other.name}" and "{source.name}" would both become "{destination.name}".')

    @staticmethod
    def __is_itself(source: Path, destination: Path) -> bool:
        """Whether a destination is its own source in another case, so a rename to it changes only the case.

        The names must fold to one (:func:`~rehuco_core.path_key`), and the destination must be spelled as the source,
        be missing, or be the source itself: a case-insensitive disk (NTFS, APFS, SMB) shows the source under the new
        spelling, while on a case-sensitive one ``foo`` and ``Foo`` can be two files, and the other one is a real
        collision.

        :param source: the file or folder as it is named now.
        :param destination: the name it would get.
        :returns: whether the rename only changes the case.
        """
        if path_key(source) != path_key(destination):
            return False
        return str(source) == str(destination) or not destination.exists() or destination.samefile(source)

    def __execute(self, plan: Sequence[tuple[Path, Path]]) -> None:
        """Perform every planned rename, undoing the completed ones if any of them fails.

        Records the plan for :meth:`relocate` only once the **whole** of it has run: a rename that was
        rolled back moved nothing in the end, and one that could not be rolled back left the resource
        split between two names, which is not a state to answer relocation questions from.

        :param plan: the collision-checked renames.
        :raises PartialRenameError: a rename failed and undoing the completed ones failed too.
        :raises OSError: re-raised from the failing rename, once every completed step is back under its
            original name.
        """
        completed: list[tuple[Path, Path]] = []
        try:
            for source, destination in plan:
                self.__rename_step(source, destination)
                completed.append((source, destination))
        except OSError as error:
            self.__roll_back(completed, error)
            raise
        self.__relocation = Relocation(tuple(completed))

    @staticmethod
    def __rename_step(current: Path, wanted: Path) -> None:
        """Perform one rename, retrying it while it is refused over a transient lock (#355).

        Safe to retry at any point: a refused rename changed nothing, so the plan is exactly as far along
        as before, and only a failure that outlasts :data:`RETRY_DELAYS` reaches the rollback. Named
        for either direction, since a rollback step is a forward step's pair the other way round.

        :param current: the file or folder as it is named now.
        :param wanted: the name it should have.
        :raises OSError: the rename was refused for good, or for a reason no retry changes.
        """
        for delay in RETRY_DELAYS:
            try:
                current.rename(wanted)
                return
            except OSError as error:
                if getattr(error, "winerror", None) not in TRANSIENT_LOCK_ERRORS:
                    raise
            time.sleep(delay)
        current.rename(wanted)

    def __roll_back(self, completed: Sequence[tuple[Path, Path]], error: OSError) -> None:
        """Rename every completed step back to its original name, most recent first.

        Every step is attempted even after one of them fails, so a rollback recovers as much as the
        filesystem still allows and reports the whole remainder at once, rather than stopping at the
        first refusal and stranding files it could have restored. Each restore is retried over a
        transient lock the same way a forward step is (#355): a scanner tends to open a file right after
        it was renamed, which is exactly when the rollback wants it back.

        :param completed: the renames that did succeed, in the order they ran.
        :param error: the failure that stopped the run; reported as the raised error's cause.
        :raises PartialRenameError: at least one file could not be put back.
        """
        stranded: list[str] = []
        for source, destination in reversed(completed):
            try:
                self.__rename_step(destination, source)
            except OSError as restore_error:
                reason = restore_error.strerror or restore_error
                stranded.append(f'"{destination.name}" could not be restored to "{source.name}" ({reason})')
        if stranded:
            raise PartialRenameError(
                f'Renaming "{self.__current_name}" to "{self.__new_name}" failed and could not be undone: '
                f"{'; '.join(stranded)}. The resource's files are split between both names."
            ) from error
