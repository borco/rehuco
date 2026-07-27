"""Renames a ``.rehu`` resource's files on disk -- the **execute** end of the rename design
([[plugins#toolkit-surfaces]]'s compute -> present/command -> execute split).

The name arrives already chosen (a clicked rename suggestion, sanitized by the widget that offered it);
this is what makes it true on disk. Core-side and GUI-free, the same split
:mod:`rehuco_core.tc_conversion` sits on: the agent's view-model orchestrates and reports, this decides
which files move and moves them.

Both resource scopes ([[data-model#resource-scoping]]) reduce to one **plan** of ``(source,
destination)`` pairs *within a single directory*, which is what makes every rename here same-filesystem
by construction -- the checksum-gated cross-filesystem move ([[mounts-and-storage#safe-move-rename]]) is
a different operation with a different destination. A directory-scoped ``info.rehu`` renames its parent
directory (one pair, atomic); a file-scoped ``foo.rehu`` renames every file named after it -- ``foo.``
anything, or ``foo`` followed by a digit, so ``foobar.zip`` is left to whoever it belongs to. The whole
plan is collision-checked before the first rename runs, and a failure part-way through renames the
completed steps back, so a sibling set is never left split between two names
([[data-model#write-integrity]]).

Nothing is attempted at all for a resource whose ``.rehu`` is not on disk: a missing file is not a
resource to rename but a record to fix ([[data-model#write-integrity]]'s fix-retry loop), and guessing
what its sibling set *would* have been is exactly the guess a rename must not make.
"""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from .constants import INFO_REHU_FILENAME, REHU_SUFFIX


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


class RehuRenamer:
    """Renames one ``.rehu`` resource's files to a new name ([[plugins#toolkit-surfaces]]).

    Three phases: **plan** (pure reads -- which files this resource's scope owns, and what each is to be
    called), **check** (nothing may occupy a destination), then **execute** (rename each in turn, undoing
    the completed ones if any fails). The check covers the whole plan before the first rename runs, so a
    set that would collide on its last file is refused with nothing on disk touched -- the shape
    :class:`~rehuco_core.TcConverter` already uses for the conversion's own file replacement.

    :param path: the resource's ``.rehu`` file.
    :param new_name: the destination folder/file name; see :func:`rename_rehu_resource`.
    """

    def __init__(self, path: Path, new_name: str) -> None:
        self.__path: Final = path
        self.__new_name: Final = new_name

    def rename(self) -> Path:
        """Run the full plan-check-execute sequence.

        :returns: the resource's ``.rehu`` path under its new name; see :func:`rename_rehu_resource`.
        :raises ValueError: see :func:`rename_rehu_resource`.
        :raises FileNotFoundError: see :func:`rename_rehu_resource`.
        :raises FileExistsError: see :func:`rename_rehu_resource`.
        :raises PartialRenameError: see :func:`rename_rehu_resource`.
        :raises OSError: see :func:`rename_rehu_resource`.
        """
        self.__check_name()
        self.__check_source_exists()
        if self.__new_name == self.__current_name:
            # a rename to the name it already has: not an error, just nothing to do. A rename that
            # differs only in *case* is a real one and falls through -- it is how a name's spelling is
            # corrected on a case-insensitive filesystem.
            return self.__path
        plan = self.__plan()
        self.__check_no_collisions(plan)
        self.__execute(plan)
        return self.__new_document_path()

    def conflict(self) -> Path | None:
        """Whatever already occupies this rename's own destination, or ``None`` when it is free.

        Exactly :meth:`__check_no_collisions`'s rule -- destination taken, and not by the source itself
        under the filesystem's case rules -- applied to the **one** pair every scope has
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
        if os.path.normcase(source) == os.path.normcase(destination):
            return None
        return destination if destination.exists() else None

    @property
    def __directory_scoped(self) -> bool:
        """Whether this resource is the directory it sits in (an ``info.rehu``,
        [[data-model#resource-scoping]]) rather than a file beside its siblings."""
        return self.__path.name == INFO_REHU_FILENAME

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
            return (self.__path.parent, self.__path.parent.with_name(self.__new_name))
        return (self.__path, self.__path.with_name(self.__new_name + self.__path.suffix))

    def __new_document_path(self) -> Path:
        """Where this resource's ``.rehu`` ends up once the plan has run.

        :returns: the renamed directory's ``info.rehu`` for a directory-scoped resource, the renamed
            file for a file-scoped one.
        """
        if self.__directory_scoped:
            return self.__own_pair()[1] / INFO_REHU_FILENAME
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
            (sibling, sibling.with_name(self.__new_name + sibling.name[stem_length:]))
            for sibling in self.__sibling_set()
        ]

    def __sibling_set(self) -> list[Path]:
        """Every file named after this file-scoped resource (:meth:`__named_after`).

        A file-scoped resource carries no manifest of the files it describes
        ([[data-model#resource-scoping]] names that as the gap), so **being named after it is the
        association**: the ``.rehu``, the ``<stem>NN`` screenshots, the ``.sfv``/``.md5`` manifest, and
        the content itself -- one ``foo.zip``, or a ``foo.001``/``foo.002`` multi-part set. Renaming
        only some of them would break the one convention holding them together, which is why membership
        is a naming rule rather than the list of file kinds this build happens to recognize.

        **Directories are skipped.** A file-scoped ``.rehu`` describes files; a directory beside it is
        either a resource of its own (with its own ``info.rehu``) or nothing to do with this one.

        **Another record's files are skipped too.** With ``foo.rehu`` and ``foo2.rehu`` side by side,
        ``foo2``'s whole set is named after ``foo`` by the rule below and would otherwise travel with
        it, silently renaming a record nobody asked about. A sibling ``.rehu`` whose stem extends this
        one's owns everything under that longer stem, so those are excluded -- and that exclusion is a
        **bare prefix**, deliberately wider than the membership rule it undoes: the two asymmetries err
        the same way, toward leaving a file alone.

        Every comparison goes through :func:`os.path.normcase` -- the same rule
        :meth:`__check_no_collisions` uses to decide whether two names are the same name, folding case
        on Windows and exact on POSIX.

        :returns: the ``.rehu`` first (it is the resource's identity), then the rest sorted by name.
        :raises OSError: the directory cannot be listed -- e.g. an offline mount
            ([[mounts-and-storage#offline-mounts]]); nothing is renamed.
        """
        stem = os.path.normcase(self.__path.stem)
        document_name = os.path.normcase(self.__path.name)
        named_after = [
            entry
            for entry in self.__path.parent.iterdir()
            if not entry.is_dir() and self.__named_after(os.path.normcase(entry.name), stem)
        ]
        foreign = self.__foreign_stems(named_after, stem)
        owned = [
            entry
            for entry in named_after
            if os.path.normcase(entry.name) != document_name
            and not any(os.path.normcase(entry.name).startswith(other) for other in foreign)
        ]
        return [self.__path, *sorted(owned, key=lambda entry: entry.name)]

    @staticmethod
    def __named_after(name: str, stem: str) -> bool:
        """Whether the sibling ``name`` is named after the resource whose stem is ``stem``.

        A **separator** decides it, not a bare prefix: what follows the stem must be nothing at all (the
        file simply *is* the resource's name), an extension separator (``foo.zip``, ``foo.sfv``,
        ``foo.001``), or a digit (``foo00.jpg``, and any other numbered continuation). More *letters*
        make a different name that merely starts alike -- ``foobar.zip`` and ``foo_extras.txt`` are
        nobody's business but their own, and nothing need sit beside them to establish that. This is
        what keeps the sweep from turning a shared prefix into a claim of ownership; the sibling-``.rehu``
        exclusion in :meth:`__sibling_set` is then a backstop for the ambiguous digit case, not the only
        thing standing between a rename and somebody else's files.

        :param name: the sibling's normcased filename.
        :param stem: this resource's normcased stem.
        :returns: whether the sibling travels with the resource.
        """
        if not name.startswith(stem):
            return False
        tail = name[len(stem) :]
        return not tail or tail.startswith(os.extsep) or tail[0].isdigit()

    @staticmethod
    def __foreign_stems(named_after: Sequence[Path], stem: str) -> list[str]:
        """The normcased stems of any *other* ``.rehu`` among ``named_after`` -- each one a resource in
        its own right, whose files must not travel with this rename.

        :param named_after: the siblings named after this resource.
        :param stem: this resource's own normcased stem.
        :returns: the extending stems whose files to leave alone.
        """
        return [
            os.path.normcase(entry.stem)
            for entry in named_after
            if entry.suffix.lower() == REHU_SUFFIX and os.path.normcase(entry.stem) != stem
        ]

    @staticmethod
    def __check_no_collisions(plan: Sequence[tuple[Path, Path]]) -> None:
        """Refuse the whole plan if anything already occupies one of its destinations.

        A destination that *is* its own source under the filesystem's case rules -- renaming ``foo`` to
        ``Foo`` on Windows -- is not a collision but the very rename being asked for.
        :func:`os.path.normcase` applies each platform's own rule: folding case on Windows, and identity
        on POSIX, where ``foo`` and ``Foo`` genuinely are two different files and a collision between
        them is real.

        :param plan: the planned renames.
        :raises FileExistsError: something already occupies a destination.
        """
        for source, destination in plan:
            if os.path.normcase(source) == os.path.normcase(destination):
                continue
            if destination.exists():
                raise FileExistsError(f'"{destination.name}" already exists.')

    def __execute(self, plan: Sequence[tuple[Path, Path]]) -> None:
        """Perform every planned rename, undoing the completed ones if any of them fails.

        :param plan: the collision-checked renames.
        :raises PartialRenameError: a rename failed and undoing the completed ones failed too.
        :raises OSError: re-raised from the failing rename, once every completed step is back under its
            original name.
        """
        completed: list[tuple[Path, Path]] = []
        try:
            for source, destination in plan:
                source.rename(destination)
                completed.append((source, destination))
        except OSError as error:
            self.__roll_back(completed, error)
            raise

    def __roll_back(self, completed: Sequence[tuple[Path, Path]], error: OSError) -> None:
        """Rename every completed step back to its original name, most recent first.

        Every step is attempted even after one of them fails, so a rollback recovers as much as the
        filesystem still allows and reports the whole remainder at once, rather than stopping at the
        first refusal and stranding files it could have restored.

        :param completed: the renames that did succeed, in the order they ran.
        :param error: the failure that stopped the run; reported as the raised error's cause.
        :raises PartialRenameError: at least one file could not be put back.
        """
        stranded: list[str] = []
        for source, destination in reversed(completed):
            try:
                destination.rename(source)
            except OSError as restore_error:
                reason = restore_error.strerror or restore_error
                stranded.append(f'"{destination.name}" could not be restored to "{source.name}" ({reason})')
        if stranded:
            raise PartialRenameError(
                f'Renaming "{self.__current_name}" to "{self.__new_name}" failed and could not be undone: '
                f"{'; '.join(stranded)}. The resource's files are split between both names."
            ) from error
