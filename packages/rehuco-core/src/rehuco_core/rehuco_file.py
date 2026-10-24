"""The ``.rehuco`` file: one set of folder roots browsed together, read and written
([[data-model#local-file-trio]], [[mounts-and-storage#rehuco-scope]], #371, #514).

A ``.rehuco`` is shareable: it may sit on the share and be opened from every machine, so it holds nothing that is a
fact about one machine. The shape::

    {
      "format_version": 3,
      "id": "6f1c5e0a-...",
      "roots": [
        { "id": "a41b9c3d-...", "label": "tutorials", "location": "//nas/data/tutorials" }
      ]
    }

**The file's ``id`` is the rehuco id**: the ``.rehudb`` cache is named by it rather than by the file's path, so
moving or renaming a ``.rehuco`` keeps its cache. **Each root's ``id``** is what the cache keys the root's rows
on, so relabelling it, reordering it or re-pointing it on a machine never orphans them. A root's **label** defaults to
its folder's name, made unique with a suffix on a clash; it is what the browser shows and what a folder filter
addresses (``folder="<label>/<relative path>"``), and changing it touches nothing on disk. The user may empty
it, and an empty label is kept as it is: the views then show the root by its folder. A root's **location**
names the place the same way on every machine (:mod:`rehuco_core.root_location`); where *this* machine finds it, and
what that storage is, lives in the machine's own :class:`~rehuco_core.root_mappings.RootMappings`, not here.

What this build does not understand is carried: an unknown top-level key, and an unknown key on a root, come
back out of a save unchanged (invariant 1 of ``how-it-works.md``). A file stamped newer than this build loads,
but read-only, with the reason stated (invariant 2); one stamped older is refused, since its roots carry paths and
no locations (:class:`RehucoFileError`).

A save re-reads the file under its lock and writes only if it is still what this machine last read or wrote
(:class:`RehucoChangedError` otherwise), so two machines editing the roots never overwrite each other silently.
"""

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

from borco_core import atomic_write_text

from .lock_reasons import LockReason, LockReasonKind
from .migrations import CURRENT_REHUCO_VERSION, RehucoTooOldError, migrate_rehuco_data
from .record_file_lock import RecordFileLock
from .rehu_format import FORMAT_VERSION_KEY

REHUCO_ID_KEY: Final = "id"
"""The file's top-level key holding the rehuco id, a UUID string."""

REHUCO_ROOTS_KEY: Final = "roots"
"""The file's top-level key holding its roots, in display order."""

ROOT_ID_KEY: Final = "id"
"""A root's key holding its stable id, a UUID string."""

ROOT_LOCATION_KEY: Final = "location"
"""A root's key holding its machine-independent location (:mod:`rehuco_core.root_location`)."""

ROOT_LABEL_KEY: Final = "label"
"""A root's key holding the name the browser shows and a folder filter addresses."""


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

    Not text, not JSON, not an object, no usable rehuco id, roots that are not a list of well-formed root
    objects, or a layout older than this build reads. A file merely stamped *newer* than this build is not one of
    these: it loads, read-only (:attr:`RehucoFile.lock_reason`).
    """


class RehucoChangedError(RuntimeError):
    """A save found the ``.rehuco`` changed on disk since this machine last read or wrote it.

    Nothing was written; the caller reloads the file and the edit is made again on what is there.
    """


@dataclass(frozen=True, slots=True)
class RehucoRoot:
    """One root of a ``.rehuco``, as parsed -- the view callers reason over, while the raw root object is what
    the file keeps, so a key this build does not know survives a save.

    :param root_id: the root's stable id.
    :param label: the name the browser shows and a folder filter addresses; unique within the file unless empty.
    :param location: where the root is, spelled the same on every machine.
    """

    root_id: UUID
    label: str
    location: str


class RehucoFile:
    """A ``.rehuco`` in memory: its rehuco id and its ordered, labeled roots.

    The parsed JSON object is the source of truth; every root operation edits it in place, and
    :meth:`save` writes it back atomically. The ordering operations speak the vocabulary of
    ``borco_pyside``'s ``ItemOrderingEditor`` -- each takes a row and returns the row the root ends up at --
    so a toolbar can drive them directly.

    :param data: the parsed JSON object; migrated in place to the current layout.
    :param path: the file it was read from, or ``None`` for one not yet saved.
    :param loaded_text: the text ``data`` was parsed from, which a save compares the file on disk with; ``None`` for a
        file not read from disk.
    :raises RehucoFileError: the object does not have a ``.rehuco``'s shape.
    """

    def __init__(self, data: dict[str, Any], path: Path | None = None, *, loaded_text: str | None = None) -> None:
        self.__path = path
        self.__saved_hash = None if loaded_text is None else self.__digest(loaded_text)
        try:
            migrate_rehuco_data(data)
        except RehucoTooOldError as error:
            raise self.__error(str(error)) from error
        self.__data: Final = data
        self.__format_version: Final[int] = data[FORMAT_VERSION_KEY]
        self.__rehuco_id: Final = self.__read_uuid(data.get(REHUCO_ID_KEY), "the rehuco id")
        roots = data.setdefault(REHUCO_ROOTS_KEY, [])
        if not isinstance(roots, list):
            raise self.__error(f"'{REHUCO_ROOTS_KEY}' is not a list")
        self.__roots: Final[list[dict[str, Any]]] = roots
        seen: set[UUID] = set()
        for raw in roots:
            root_id = self.__parse_root(raw).root_id
            if root_id in seen:
                raise self.__error(f"Two roots share the id {root_id}")
            seen.add(root_id)

    @classmethod
    def new(cls) -> RehucoFile:
        """A ``.rehuco`` that has never been saved: a fresh rehuco id and no roots.

        :returns: the file, current-version, with no :attr:`path` until its first :meth:`save`.
        """
        return cls({FORMAT_VERSION_KEY: CURRENT_REHUCO_VERSION, REHUCO_ID_KEY: str(uuid4()), REHUCO_ROOTS_KEY: []})

    @classmethod
    def load(cls, path: Path) -> RehucoFile:
        """Read a ``.rehuco`` file whole, migrated to the current version.

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
        """The roots, in display order."""
        return tuple(self.__parse_root(raw) for raw in self.__roots)

    @property
    def count(self) -> int:
        """How many roots the file holds."""
        return len(self.__roots)

    def save(self, path: Path | None = None) -> None:
        """Write the file back as a current-version ``.rehuco``, atomically, under its lock file like a record
        ([[mounts-and-storage#rehuco-scope]], #512).

        The layout is canonical: ``format_version`` first, the rehuco id next, any carried unknown key in the
        order it was read, the roots last.

        :param path: where to write; ``None`` writes back to :attr:`path`, which then becomes ``path``.
        :raises ValueError: the file is read-only (:attr:`lock_reason`), or there is nowhere to write it.
        :raises RecordLockedError: someone else held its lock for longer than a save waits.
        :raises RehucoChangedError: the file on disk is no longer what this machine last read or wrote.
        :raises OSError: the file could not be written.
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
        payload[REHUCO_ROOTS_KEY] = self.__roots
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        with RecordFileLock(target):
            self.__check_unchanged(target)
            atomic_write_text(target, text)
        self.__path = target
        self.__saved_hash = self.__digest(text)

    def add_root(self, location: str, label: str | None = None) -> int:
        """Append a root, under a fresh id.

        :param location: where the root is, as :func:`rehuco_core.root_location.location_of` spells it.
        :param label: the name to show; ``None`` takes the location's last segment. Either way a label already in
            use (case-insensitively) gets a suffix: ``foo``, ``foo (2)``, ``foo (3)``.
        :returns: the new root's row.
        :raises ValueError: the location is already a root. Whether its folder overlaps another is the caller's to
            check over this machine's mapped paths (:meth:`RootOverlap.find`).
        """
        folded = location.casefold()
        if any(raw[ROOT_LOCATION_KEY].casefold() == folded for raw in self.__roots):
            raise ValueError(f"Already a root: {location}")
        base = label if label else self.default_label(location)
        self.__roots.append(
            {ROOT_ID_KEY: str(uuid4()), ROOT_LABEL_KEY: self.__unique_label(base), ROOT_LOCATION_KEY: location}
        )
        return len(self.__roots) - 1

    def remove_root(self, at: int) -> RehucoRoot:
        """Drop a root from the file; its folder and files are not touched.

        :param at: the root's row.
        :returns: the root removed.
        :raises IndexError: no such row.
        """
        self.__check_row(at)
        return self.__parse_root(self.__roots.pop(at))

    def relabel_root(self, at: int, label: str) -> None:
        """Rename a root's label; nothing on disk changes.

        :param at: the root's row.
        :param label: the new label; empty is allowed and kept, and any number of roots may be empty.
        :raises IndexError: no such row.
        :raises ValueError: another root already uses the label (case-insensitively).
        """
        self.__check_row(at)
        folded = label.casefold()
        if label and any(raw[ROOT_LABEL_KEY].casefold() == folded for row, raw in enumerate(self.__roots) if row != at):
            raise ValueError(f"Another root is already labeled {label!r}")
        self.__roots[at][ROOT_LABEL_KEY] = label

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
        return self.__move(at, min(at + 1, len(self.__roots) - 1))

    def move_to_bottom(self, at: int) -> int:
        """Move a root to the last row.

        :param at: the root's row.
        :returns: the row it ends up at.
        :raises IndexError: no such row.
        """
        return self.__move(at, len(self.__roots) - 1)

    def __move(self, at: int, to: int) -> int:
        self.__check_row(at)
        self.__roots.insert(to, self.__roots.pop(at))
        return to

    def __check_row(self, at: int) -> None:
        if not 0 <= at < len(self.__roots):
            raise IndexError(f"No root at row {at}")

    def __parse_root(self, raw: Any) -> RehucoRoot:
        if not isinstance(raw, dict):
            raise self.__error("A root is not an object")
        location = raw.get(ROOT_LOCATION_KEY)
        label = raw.get(ROOT_LABEL_KEY)
        if not isinstance(location, str) or not location:
            raise self.__error(f"A root has no '{ROOT_LOCATION_KEY}'")
        if not isinstance(label, str):
            raise self.__error(f"The root {location!r} has no '{ROOT_LABEL_KEY}'")
        root_id = self.__read_uuid(raw.get(ROOT_ID_KEY), f"the root {location!r}'s id")
        return RehucoRoot(root_id=root_id, label=label, location=location)

    def __read_uuid(self, value: Any, what: str) -> UUID:
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
        try:
            current = self.__digest(target.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError) as error:
            raise RehucoChangedError(f"The .rehuco changed on disk: {target}") from error
        if current != self.__saved_hash:
            raise RehucoChangedError(f"The .rehuco changed on disk: {target}")

    @staticmethod
    def __digest(text: str) -> str:
        """What a save compares the file on disk by.

        :param text: the file's text.
        :returns: its SHA-256, in hex.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def __error(self, message: str) -> RehucoFileError:
        return RehucoFileError(f"{message}: {self.__path}" if self.__path is not None else message)

    def __unique_label(self, base: str) -> str:
        taken = {raw[ROOT_LABEL_KEY].casefold() for raw in self.__roots}
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
