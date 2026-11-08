"""The ``.rehuco`` file: one set of folder roots browsed together, read and written
([[data-model#local-file-trio]], [[mounts-and-storage#rehuco-scope]], [[mounts-and-storage#rehuroot]], #371, #514,
#577).

A ``.rehuco`` is shareable: it may sit on the share and be opened from every machine, so it holds nothing that is a
fact about one machine. Nor does it hold the roots themselves: each is a ``.rehuroot`` file of its own
(:class:`~rehuco_core.rehuroot_file.RehurootFile`), shared by every catalog that lists it, and the ``.rehuco`` keeps
an ordered list of references to them, each a path relative to the ``.rehuco``. The shape::

    {
      "format_version": 4,
      "id": "6f1c5e0a-...",
      "roots": [ { "file": "tutorials.rehuroot" } ]
    }

**The file's ``id`` is the rehuco id**: the ``.rehudb`` cache is named by it rather than by the file's path, so
moving or renaming a ``.rehuco`` keeps its cache. A root's **id**, **label** and **location** are its ``.rehuroot``'s
(:class:`RehucoRoot`). A reference whose file is missing or cannot be read is **kept**, as a root with a
:attr:`~RehucoRoot.problem`: the catalog opens, the root shows why it is not there, and the reference survives a save.

What this build does not understand is carried: an unknown top-level key, and an unknown key on a reference, come
back out of a save unchanged (invariant 1 of ``how-it-works.md``). A file stamped newer than this build loads, but
read-only, with the reason stated (invariant 2); one stamped older is refused, since its roots are inline
(:class:`RehucoFileError`).

A save writes each changed ``.rehuroot`` first, then re-reads the ``.rehuco`` under its lock and writes it only if it
is still what this machine last read or wrote (:class:`RehucoChangedError` otherwise), so two machines editing the
roots never overwrite each other silently.
"""

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from borco_core import atomic_write_text

from .lock_reasons import LockReason, LockReasonKind
from .migrations import CURRENT_REHUCO_VERSION, RehucoTooOldError, migrate_rehuco_data
from .record_file_lock import RecordFileLock
from .rehu_format import FORMAT_VERSION_KEY
from .rehuroot_file import DEFAULT_LAYOUTS, REHUROOT_SUFFIX, RehurootFile, RehurootFileError
from .sanitized_names import sanitize_name
from .shared_file_digest import disk_digest, text_digest

REHUCO_ID_KEY: Final = "id"
"""The file's top-level key holding the rehuco id, a UUID string."""

REHUCO_ROOTS_KEY: Final = "roots"
"""The file's top-level key holding its references to root files, in display order."""

ROOT_FILE_KEY: Final = "file"
"""A reference's key holding its ``.rehuroot``'s path, relative to the ``.rehuco`` and spelled with ``/``."""

DEFAULT_ROOT_FILE_STEM: Final = "root"
"""The name a new root file takes when its label sanitizes to nothing."""


class RootStorage(StrEnum):
    """What a root's folder lives on, as this machine's drive or mount table says -- never declared by the user.

    The member values are what a machine's mapping stores.
    """

    LOCAL = "local"
    """A folder on one of this machine's own disks."""

    NETWORK = "network"
    """A folder on a share another computer serves."""

    REMOVABLE = "removable"
    """A folder on a removable drive: a USB stick or an external disk."""

    COMPACT_DISK = "compact_disk"
    """A folder on a CD or DVD."""


class RehucoFileError(ValueError):
    """A ``.rehuco`` file this build cannot read at all.

    Not text, not JSON, not an object, no usable rehuco id, roots that are not a list of references, two references to
    one file or to one root, or a layout older than this build reads. A file merely stamped *newer* than this build is
    not one of these: it loads, read-only (:attr:`RehucoFile.lock_reason`); nor is a reference whose file cannot be
    read, which is kept as a root with a problem.
    """


class RehucoChangedError(RuntimeError):
    """A save found the ``.rehuco`` changed on disk since this machine last read or wrote it.

    Nothing was written; the caller reloads the file and the edit is made again on what is there.
    """


@dataclass(frozen=True, slots=True)
class RehucoRoot:
    """One root of a ``.rehuco``, as its ``.rehuroot`` says -- the view callers reason over.

    :param root_id: the root's stable id; for an unreadable root, one derived from its file's path, never written.
    :param label: the name the browser shows and a folder filter addresses; for an unreadable root, its file's stem.
    :param location: where the root is, spelled the same on every machine; empty for an unreadable root.
    :param layouts: the path template of each type's main key, ``*`` for any type not named.
    :param fallbacks: what each placeholder renders as when a record leaves it empty.
    :param file: the root's ``.rehuroot``; ``None`` for a root built by hand.
    :param problem: why the root's file could not be read, or ``""`` when it was.
    """

    root_id: UUID
    label: str
    location: str
    layouts: Mapping[str, str] = field(default=DEFAULT_LAYOUTS, compare=False)
    fallbacks: Mapping[str, str] = field(default_factory=dict, compare=False)
    file: Path | None = None
    problem: str = ""

    @property
    def readable(self) -> bool:
        """Whether the root's file was read -- what every use of the root but showing it needs."""
        return not self.problem


# the public surface is the file's own verbs -- load, save, and each edit of its roots -- which the Roots view
# drives one by one; splitting them would split one file's state
class RehucoFile:  # pylint: disable=too-many-public-methods
    """A ``.rehuco`` in memory: its rehuco id and its ordered roots, each read from its ``.rehuroot``.

    The parsed JSON object is the source of truth for the references; every root operation edits it in place, and
    :meth:`save` writes it back atomically, after each changed root file. The ordering operations speak the vocabulary
    of ``borco_pyside``'s ``ItemOrderingEditor`` -- each takes a row and returns the row the root ends up at -- so a
    toolbar can drive them directly.

    :param data: the parsed JSON object; migrated in place to the current layout.
    :param path: the file it was read from, or ``None`` for one not yet saved; its folder is what references are
        relative to, so a file with references needs one.
    :param loaded_text: the text ``data`` was parsed from, which a save compares the file on disk with; ``None`` for a
        file not read from disk.
    :raises RehucoFileError: the object does not have a ``.rehuco``'s shape.
    """

    @dataclass(slots=True)
    class Reference:
        """One entry of the ``roots`` list: the raw object the file keeps, the root file it names, and that file as
        read.

        :param raw: the object as read, any unknown key in it carried.
        :param path: the root file, joined onto the ``.rehuco``'s folder and normalized.
        :param root: the root file as read, or ``None`` when it could not be.
        :param problem: why it could not be read, or ``""``.
        """

        raw: dict[str, Any]
        path: Path
        root: RehurootFile | None
        problem: str = ""

        @property
        def shown(self) -> RehucoRoot:
            """The root as callers see it."""
            root = self.root
            if root is None:
                return RehucoRoot(
                    uuid5(NAMESPACE_URL, str(self.path)), self.path.stem, "", file=self.path, problem=self.problem
                )
            return RehucoRoot(root.root_id, root.label, root.location, root.layouts, root.fallbacks, self.path)

    def __init__(self, data: dict[str, Any], path: Path | None = None, *, loaded_text: str | None = None) -> None:
        self.__path = path
        self.__saved_hash = None if loaded_text is None else text_digest(loaded_text)
        try:
            migrate_rehuco_data(data)
        except RehucoTooOldError as error:
            raise self.__error(str(error)) from error
        self.__data: Final = data
        self.__format_version: Final[int] = data[FORMAT_VERSION_KEY]
        self.__rehuco_id: Final = self.__read_uuid(data.get(REHUCO_ID_KEY), "the rehuco id")
        raws = data.get(REHUCO_ROOTS_KEY, [])
        if not isinstance(raws, list):
            raise self.__error(f"'{REHUCO_ROOTS_KEY}' is not a list")
        self.__references: Final[list[RehucoFile.Reference]] = [self.__read_reference(raw) for raw in raws]
        self.__check_distinct()

    @classmethod
    def new(cls) -> RehucoFile:
        """A ``.rehuco`` that has never been saved: a fresh rehuco id and no roots.

        :returns: the file, current-version, with no :attr:`path` until its first :meth:`save`.
        """
        return cls({FORMAT_VERSION_KEY: CURRENT_REHUCO_VERSION, REHUCO_ID_KEY: str(uuid4()), REHUCO_ROOTS_KEY: []})

    @classmethod
    def load(cls, path: Path) -> RehucoFile:
        """Read a ``.rehuco`` file whole, migrated to the current version, and each root file it names.

        :param path: the file.
        :returns: the file; read-only (:attr:`lock_reason`) when it is stamped newer than this build.
        :raises FileNotFoundError: no such file.
        :raises OSError: the file exists and cannot be read.
        :raises RehucoFileError: the file is not a ``.rehuco`` this build can read.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise RehucoFileError(f"Not a text file: {path}") from error
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise RehucoFileError(f"Not JSON: {path}") from error
        if not isinstance(data, dict):
            raise RehucoFileError(f"Not a JSON object: {path}")
        return cls(data, path, loaded_text=text)

    @property
    def path(self) -> Path | None:
        """The file this was read from or last saved to, or ``None`` for one never saved."""
        return self.__path

    @property
    def rehuco_id(self) -> UUID:
        """The rehuco id -- what names this file's ``.rehudb`` cache."""
        return self.__rehuco_id

    @property
    def format_version(self) -> int:
        """The version the file was stamped with, after migration -- above :data:`CURRENT_REHUCO_VERSION` only
        for a file newer than this build."""
        return self.__format_version

    @property
    def lock_reason(self) -> LockReason | None:
        """Why this file is read-only, or ``None`` when it can be saved.

        Only a file newer than this build is read-only (:attr:`LockReasonKind.NEWER_FORMAT`): writing it would
        drop or misstate what the newer build put there.
        """
        if self.__format_version > CURRENT_REHUCO_VERSION:
            return LockReason(
                LockReasonKind.NEWER_FORMAT,
                f"format_version {self.__format_version} is newer than this build understands "
                f"({CURRENT_REHUCO_VERSION}).",
            )
        return None

    @property
    def roots(self) -> tuple[RehucoRoot, ...]:
        """The roots, in display order -- an unreadable one too, with its problem."""
        return tuple(reference.shown for reference in self.__references)

    @property
    def unreadable_files(self) -> tuple[Path, ...]:
        """The ``.rehuroot`` files the catalog lists and cannot read, in display order -- whose roots' rows a cache
        keeps as it keeps an offline root's (:meth:`~rehuco_core.rehudb.CatalogCache.reconcile_roots`)."""
        return tuple(reference.path for reference in self.__references if reference.root is None)

    @property
    def count(self) -> int:
        """How many roots the file holds."""
        return len(self.__references)

    def save(self, path: Path | None = None) -> None:
        """Write each new or changed root file, then the ``.rehuco`` itself as a current-version file, atomically,
        under its lock file like a record ([[mounts-and-storage#rehuco-scope]], #512).

        The ``.rehuco`` is written only when its text would change -- a relabel writes the root's file alone -- and
        then its check comes first, under its lock, so a refused save writes no root file either.

        The layout is canonical: ``format_version`` first, the rehuco id next, any carried unknown key in the
        order it was read, the references last, each naming its file relative to where the ``.rehuco`` is written.

        :param path: where to write; ``None`` writes back to :attr:`path`, which then becomes ``path``.
        :raises ValueError: the file is read-only (:attr:`lock_reason`), or there is nowhere to write it.
        :raises RecordLockedError: someone else held a lock for longer than a save waits.
        :raises RehurootChangedError: a root file on disk is no longer what this machine last read or wrote.
        :raises RehucoChangedError: the file on disk is no longer what this machine last read or wrote.
        :raises OSError: a file could not be written.
        """
        reason = self.lock_reason
        if reason is not None:
            raise ValueError(f"Refusing to save a read-only .rehuco: {reason.message}")
        target = path if path is not None else self.__path
        if target is None:
            raise ValueError("Refusing to save a .rehuco with no path")
        payload: dict[str, Any] = {FORMAT_VERSION_KEY: CURRENT_REHUCO_VERSION, REHUCO_ID_KEY: str(self.__rehuco_id)}
        carried = (FORMAT_VERSION_KEY, REHUCO_ID_KEY, REHUCO_ROOTS_KEY)
        payload.update({key: value for key, value in self.__data.items() if key not in carried})
        payload[REHUCO_ROOTS_KEY] = [
            {**reference.raw, ROOT_FILE_KEY: self.__relative(reference.path, target.parent)}
            for reference in self.__references
        ]
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if target == self.__path and text_digest(text) == self.__saved_hash:
            self.__save_root_files()
            return
        with RecordFileLock(target):
            self.__check_unchanged(target)
            self.__save_root_files()
            atomic_write_text(target, text)
        self.__path = target
        self.__saved_hash = text_digest(text)

    def __save_root_files(self) -> None:
        """Write each root file that is new or changed.

        :raises RecordLockedError: someone else held a root file's lock for longer than a save waits.
        :raises RehurootChangedError: a root file on disk is no longer what this machine last read or wrote.
        :raises OSError: a root file could not be written.
        """
        for reference in self.__references:
            if reference.root is not None and reference.root.dirty:
                reference.root.save()

    def add_root(
        self,
        location: str,
        label: str | None = None,
        *,
        layouts: Mapping[str, str] = DEFAULT_LAYOUTS,
        fallbacks: Mapping[str, str] | None = None,
        file: Path | None = None,
    ) -> int:
        """Append a root, as a new ``.rehuroot`` under a fresh id; the root file is written by the next :meth:`save`.

        :param location: where the root is, as :func:`rehuco_core.root_location.location_of` spells it.
        :param label: the name to show; ``None`` takes the location's last segment. Either way a label already in
            use (case-insensitively) gets a suffix: ``foo``, ``foo (2)``, ``foo (3)``.
        :param layouts: where a record of each type lives under the root; the default keeps any record's name.
        :param fallbacks: what a placeholder renders as when a record leaves it empty; none when ``None``.
        :param file: where the root file goes; ``None`` puts it beside the ``.rehuco``, named after the label
            (:meth:`free_root_file`).
        :returns: the new root's row.
        :raises ValueError: the location is already a root, the file chosen is already there or already listed, or
            the ``.rehuco`` has no folder to put the root file in. Whether its folder overlaps another is the
            caller's to check over this machine's mapped paths (:meth:`RootOverlap.find`).
        """
        if self.__path is None:
            raise ValueError("A root file needs the .rehuco saved first")
        folded = location.casefold()
        if any(root.location.casefold() == folded for root in self.__readable()):
            raise ValueError(f"Already a root: {location}")
        unique = self.__unique_label(label if label else self.default_label(location))
        if file is None:
            file = self.free_root_file(sanitize_name(unique) or DEFAULT_ROOT_FILE_STEM)
        else:
            # a relative file is meant beside the .rehuco, never wherever the process happens to run
            file = Path(os.path.normpath(self.__path.parent / file))
            if self.__lists(file) or file.exists():
                raise ValueError(f"A root file is already there: {file}")
        root = RehurootFile.new(file, location, unique, layouts=layouts, fallbacks=fallbacks)
        reference = {ROOT_FILE_KEY: self.__relative(file, self.__path.parent)}
        self.__references.append(RehucoFile.Reference(reference, file, root))
        return len(self.__references) - 1

    def add_root_file(self, root: RehurootFile) -> int:
        """Append an existing ``.rehuroot``, read already, as a root with its own id, label, location, layouts and
        fallbacks; the next :meth:`save` writes the reference to it, named relative to the ``.rehuco``, and leaves the
        file as it is. Reading it is the caller's, where a read may block (:meth:`RootPlanner.plan
        <rehuco_core.root_candidates.RootPlanner.plan>`).

        :param root: the root file as read -- beside the ``.rehuco`` or anywhere else both reach, such as a share.
        :returns: the new root's row.
        :raises ValueError: the ``.rehuco`` was never saved, the file is already listed, or its root -- by id or by
            location -- already is.
        """
        if self.__path is None:
            raise ValueError("A root file needs the .rehuco saved first")
        file = Path(os.path.normpath(root.path))
        if self.__lists(file):
            raise ValueError(f"Already a root file of this catalog: {file}")
        folded = root.location.casefold()
        if any(other.root_id == root.root_id or other.location.casefold() == folded for other in self.__readable()):
            raise ValueError(f"Already a root of this catalog: {root.location}")
        reference = {ROOT_FILE_KEY: self.__relative(file, self.__path.parent)}
        self.__references.append(RehucoFile.Reference(reference, file, root))
        return len(self.__references) - 1

    def free_root_file(self, stem: str, taken: Iterable[Path] = ()) -> Path:
        """A root file name beside the ``.rehuco`` that no reference names, no file takes and ``taken`` does not hold.

        :param stem: the name wanted, without the extension.
        :param taken: paths to avoid besides -- the root files of roots about to be added.
        :returns: ``<stem>.rehuroot``, or ``<stem> (2).rehuroot`` and on.
        :raises ValueError: the ``.rehuco`` has no folder yet.
        """
        if self.__path is None:
            raise ValueError("A root file needs the .rehuco saved first")
        folder = self.__path.parent
        avoided = {os.path.normcase(os.path.normpath(path)) for path in taken}
        candidate = folder / f"{stem}{REHUROOT_SUFFIX}"
        suffix = 2
        while self.__lists(candidate) or os.path.normcase(str(candidate)) in avoided or candidate.exists():
            candidate = folder / f"{stem} ({suffix}){REHUROOT_SUFFIX}"
            suffix += 1
        return candidate

    def set_root_layouts(self, at: int, layouts: Mapping[str, str], fallbacks: Mapping[str, str]) -> None:
        """Replace a root's layouts and fallbacks, in its ``.rehuroot``; the next :meth:`save` writes it.

        :param at: the root's row.
        :param layouts: where a record of each type lives under the root.
        :param fallbacks: what a placeholder renders as when a record leaves it empty.
        :raises IndexError: no such row.
        :raises ValueError: the root's file is unreadable or read-only.
        """
        self.__check_row(at)
        root = self.__references[at].root
        if root is None:
            raise ValueError(f"The root's file could not be read: {self.__references[at].problem}")
        root.layouts = layouts
        root.fallbacks = fallbacks

    def remove_root(self, at: int) -> RehucoRoot:
        """Drop a root from the file; its ``.rehuroot``, its folder and its files are not touched -- another catalog
        may list it.

        :param at: the root's row.
        :returns: the root removed.
        :raises IndexError: no such row.
        """
        self.__check_row(at)
        return self.__references.pop(at).shown

    def relabel_root(self, at: int, label: str) -> None:
        """Rename a root's label, in its ``.rehuroot``; nothing else on disk changes, and the next :meth:`save` writes
        it.

        :param at: the root's row.
        :param label: the new label; empty is allowed and kept, and any number of roots may be empty.
        :raises IndexError: no such row.
        :raises ValueError: another root already uses the label (case-insensitively), or the root's file is unreadable
            or read-only.
        """
        self.__check_row(at)
        root = self.__references[at].root
        if root is None:
            raise ValueError(f"The root's file could not be read: {self.__references[at].problem}")
        folded = label.casefold()
        if label and any(
            other.root is not None and other.root.label.casefold() == folded
            for row, other in enumerate(self.__references)
            if row != at
        ):
            raise ValueError(f"Another root is already labeled {label!r}")
        root.label = label

    def move(self, at: int, to: int) -> int:
        """Move a root to any row -- what a drag and drop of one asks for.

        :param at: the root's row.
        :param to: the row it should end up at, in the list as it will be: ``0`` puts it first and ``count - 1`` last.
        :returns: the row it ends up at.
        :raises IndexError: no such row, for either.
        """
        self.__check_row(at)
        self.__check_row(to)
        return self.__move(at, to)

    def move_to_top(self, at: int) -> int:
        """Move a root to the first row.

        :param at: the root's row.
        :returns: the row it ends up at.
        :raises IndexError: no such row.
        """
        return self.__move(at, 0)

    def move_up(self, at: int) -> int:
        """Move a root one row up; the first stays where it is.

        :param at: the root's row.
        :returns: the row it ends up at.
        :raises IndexError: no such row.
        """
        return self.__move(at, max(at - 1, 0))

    def move_down(self, at: int) -> int:
        """Move a root one row down; the last stays where it is.

        :param at: the root's row.
        :returns: the row it ends up at.
        :raises IndexError: no such row.
        """
        return self.__move(at, min(at + 1, len(self.__references) - 1))

    def move_to_bottom(self, at: int) -> int:
        """Move a root to the last row.

        :param at: the root's row.
        :returns: the row it ends up at.
        :raises IndexError: no such row.
        """
        return self.__move(at, len(self.__references) - 1)

    def __move(self, at: int, to: int) -> int:
        """Move a root from one row to another, both already checked or clamped.

        :param at: the root's row.
        :param to: the row it ends up at.
        :returns: ``to``.
        :raises IndexError: no such row.
        """
        self.__check_row(at)
        self.__references.insert(to, self.__references.pop(at))
        return to

    def __check_row(self, at: int) -> None:
        """Refuse a row the file does not have.

        :param at: the row.
        :raises IndexError: no such row.
        """
        if not 0 <= at < len(self.__references):
            raise IndexError(f"No root at row {at}")

    def __readable(self) -> list[RehurootFile]:
        """The root files that were read, in display order."""
        return [reference.root for reference in self.__references if reference.root is not None]

    def __read_reference(self, raw: Any) -> RehucoFile.Reference:
        """Read one entry of the ``roots`` list, and the root file it names.

        :param raw: the entry as parsed.
        :returns: the reference; one whose file is missing or unreadable carries the reason instead of the file.
        :raises RehucoFileError: the entry is not a reference, or the ``.rehuco`` has no folder to resolve it against.
        """
        if not isinstance(raw, dict):
            raise self.__error("A root is not an object")
        spelled = raw.get(ROOT_FILE_KEY)
        if not isinstance(spelled, str) or not spelled:
            raise self.__error(f"A root has no '{ROOT_FILE_KEY}'")
        if self.__path is None:
            raise self.__error("A root file cannot be found without the .rehuco's folder")
        path = Path(os.path.normpath(self.__path.parent / spelled))
        try:
            return RehucoFile.Reference(raw, path, RehurootFile.load(path))
        except FileNotFoundError:
            return RehucoFile.Reference(raw, path, None, f"The root file is missing: {path}")
        except (OSError, RehurootFileError) as error:
            return RehucoFile.Reference(raw, path, None, f"The root file cannot be read: {error}")

    def __check_distinct(self) -> None:
        """Refuse a file naming one root file, or one root, twice.

        :raises RehucoFileError: two references share a file or a root id.
        """
        files: set[str] = set()
        ids: set[UUID] = set()
        for reference in self.__references:
            key = os.path.normcase(str(reference.path))
            if key in files:
                raise self.__error(f"Two roots name one file, {reference.path}")
            files.add(key)
            if reference.root is not None:
                if reference.root.root_id in ids:
                    raise self.__error(f"Two roots share the id {reference.root.root_id}")
                ids.add(reference.root.root_id)

    def __lists(self, file: Path) -> bool:
        """Whether a reference names a root file.

        :param file: the root file, normalized.
        :returns: whether one does, compared as the platform compares paths.
        """
        key = os.path.normcase(str(file))
        return any(os.path.normcase(str(reference.path)) == key for reference in self.__references)

    @staticmethod
    def __relative(path: Path, folder: Path) -> str:
        """How a reference names its root file from the ``.rehuco``'s folder.

        :param path: the root file.
        :param folder: the ``.rehuco``'s folder.
        :returns: the relative path with ``/`` separators; the whole path, so spelled, when the two are on different
            drives and no relative one exists.
        """
        try:
            relative = os.path.relpath(path, folder)
        except ValueError:
            relative = str(path)
        return relative.replace("\\", "/")

    def __read_uuid(self, value: Any, what: str) -> UUID:
        """A UUID the file holds.

        :param value: the value as parsed.
        :param what: what it is, for the message.
        :returns: the UUID.
        :raises RehucoFileError: it is missing or is no UUID string.
        """
        if not isinstance(value, str):
            raise self.__error(f"Missing {what}")
        try:
            return UUID(value)
        except ValueError as error:
            raise self.__error(f"Not a UUID: {what}") from error

    def __check_unchanged(self, target: Path) -> None:
        """Refuse to write over a file someone else changed since this one last read or wrote it.

        :param target: where the save is going; checked only when it is the file this one was read from or last
            saved to, since a new file or a save-as has nothing to compare with.
        :raises RehucoChangedError: the file is gone, unreadable as text, or different.
        :raises OSError: the file could not be read.
        """
        if self.__saved_hash is None or target != self.__path:
            return
        if disk_digest(target) != self.__saved_hash:
            raise RehucoChangedError(f"The .rehuco changed on disk: {target}")

    def __error(self, message: str) -> RehucoFileError:
        """An error naming this file, when it has a path.

        :param message: what is wrong.
        :returns: the error.
        """
        return RehucoFileError(f"{message}: {self.__path}" if self.__path is not None else message)

    def __unique_label(self, base: str) -> str:
        """A label no other root uses, case-insensitively.

        :param base: the label wanted.
        :returns: ``base``, or ``base (2)`` and on.
        """
        taken = {root.label.casefold() for root in self.__readable()}
        label = base
        suffix = 2
        while label.casefold() in taken:
            label = f"{base} ({suffix})"
            suffix += 1
        return label

    @staticmethod
    def default_label(path: Path | str) -> str:
        """The label a root gets when none is given: the last segment of its location or folder.

        :param path: a location, or a folder spelled with either separator.
        :returns: the segment; the whole text when it has none.
        """
        # split on both separators rather than through `Path`, so a Windows path labels the same on every platform
        spelled = str(path)
        return spelled.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or spelled
