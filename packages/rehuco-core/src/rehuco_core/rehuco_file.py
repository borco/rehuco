"""The ``.rehuco`` file: one set of folder roots browsed together, read and written
([[data-model#local-file-trio]], [[mounts-and-storage#rehuco-scope]], #371).

A ``.rehuco`` is machine-local and opened as a file; a machine may keep several. The shape::

    {
      "format_version": 1,
      "id": "6f1c5e0a-...",
      "roots": [
        { "id": "a41b9c3d-...", "path": "D:/tutorials", "label": "tutorials", "storage": "local" }
      ]
    }

**The file's ``id`` is the rehuco id**: the ``.rehudb`` cache is named by it rather than by the file's path, so
moving or renaming a ``.rehuco`` keeps its cache. **Each root's ``id``** is what the cache keys the root's rows
on, so relabelling it, reordering it or re-pointing its path never orphans them. A root's **label** defaults to
its folder's name, made unique with a suffix on a clash; it is what the browser shows and what a folder filter
addresses (``folder="<label>/<relative path>"``), and changing it touches nothing on disk. **``storage``**
says what the folder lives on -- a local folder, a network share, a removable drive (a USB stick or disk) or a
compact disk -- as the user chose it; nothing here detects it, and changing it touches nothing on disk. Version 1
carried a ``removable`` flag instead, which the migration turns into ``"removable"`` or ``"local"``.

What this build does not understand is carried: an unknown top-level key, and an unknown key on a root, come
back out of a save unchanged (invariant 1 of ``how-it-works.md``). A file stamped newer than this build loads,
but read-only, with the reason stated (invariant 2).
"""

import json
from dataclasses import dataclass
from enum import StrEnum
from os import path as os_path
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid4

from borco_core import atomic_write_text

from .lock_reasons import LockReason, LockReasonKind
from .migrations import CURRENT_REHUCO_VERSION, migrate_rehuco_data
from .rehu_format import FORMAT_VERSION_KEY

REHUCO_ID_KEY: Final = "id"
"""The file's top-level key holding the rehuco id, a UUID string."""

REHUCO_ROOTS_KEY: Final = "roots"
"""The file's top-level key holding its roots, in display order."""

ROOT_ID_KEY: Final = "id"
"""A root's key holding its stable id, a UUID string."""

ROOT_PATH_KEY: Final = "path"
"""A root's key holding its folder, as the user picked it."""

ROOT_LABEL_KEY: Final = "label"
"""A root's key holding the name the browser shows and a folder filter addresses."""

ROOT_STORAGE_KEY: Final = "storage"
"""A root's key saying what its folder lives on, a :class:`RootStorage` value; absent reads as ``local``."""


class RootStorage(StrEnum):
    """What a root's folder lives on, as the user said -- never detected.

    The member values are what the file stores.
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

    Not text, not JSON, not an object, no usable rehuco id, or roots that are not a list of well-formed root
    objects. A file merely stamped *newer* than this build is not one of these: it loads, read-only
    (:attr:`RehucoFile.lock_reason`).
    """


@dataclass(frozen=True, slots=True)
class RehucoRoot:
    """One root of a ``.rehuco``, as parsed -- the view callers reason over, while the raw root object is what
    the file keeps, so a key this build does not know survives a save.

    :param root_id: the root's stable id.
    :param path: the root's folder.
    :param label: the name the browser shows and a folder filter addresses; unique within the file.
    :param storage: what the folder lives on.
    """

    root_id: UUID
    path: Path
    label: str
    storage: RootStorage = RootStorage.LOCAL

    @property
    def removable(self) -> bool:
        """Whether the folder lives on a medium that can be taken away -- a removable drive or a compact disk. What
        the cache's ``removable`` column and the retention rules read."""
        return self.storage in (RootStorage.REMOVABLE, RootStorage.COMPACT_DISK)


class RehucoFile:
    """A ``.rehuco`` in memory: its rehuco id and its ordered, labeled roots.

    The parsed JSON object is the source of truth; every root operation edits it in place, and
    :meth:`save` writes it back atomically. The ordering operations speak the vocabulary of
    ``borco_pyside``'s ``ItemOrderingEditor`` -- each takes a row and returns the row the root ends up at --
    so a toolbar can drive them directly.

    :param data: the parsed JSON object; migrated in place to the current layout.
    :param path: the file it was read from, or ``None`` for one not yet saved.
    :raises RehucoFileError: the object does not have a ``.rehuco``'s shape.
    """

    def __init__(self, data: dict[str, Any], path: Path | None = None) -> None:
        self.__path = path
        migrate_rehuco_data(data)
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
        return cls(data, path)

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
        """Write the file back as a current-version ``.rehuco``, atomically.

        The layout is canonical: ``format_version`` first, the rehuco id next, any carried unknown key in the
        order it was read, the roots last.

        :param path: where to write; ``None`` writes back to :attr:`path`, which then becomes ``path``.
        :raises ValueError: the file is read-only (:attr:`lock_reason`), or there is nowhere to write it.
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
        atomic_write_text(target, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        self.__path = target

    def add_root(self, path: Path | str, label: str | None = None, *, storage: RootStorage = RootStorage.LOCAL) -> int:
        """Append a root, under a fresh id.

        :param path: the root's folder.
        :param label: the name to show; ``None`` takes the folder's name. Either way a label already in use
            (case-insensitively) gets a suffix: ``foo``, ``foo (2)``, ``foo (3)``.
        :param storage: what the folder lives on.
        :returns: the new root's row.
        :raises ValueError: the folder is already a root -- compared normalized, and case-folded where the
            platform's paths are.
        """
        key = self.__path_key(path)
        if any(self.__path_key(raw[ROOT_PATH_KEY]) == key for raw in self.__roots):
            raise ValueError(f"Already a root: {path}")
        base = label if label else self.__default_label(path)
        self.__roots.append(
            {
                ROOT_ID_KEY: str(uuid4()),
                ROOT_PATH_KEY: str(path),
                ROOT_LABEL_KEY: self.__unique_label(base),
                ROOT_STORAGE_KEY: RootStorage(storage).value,
            }
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
        :param label: the new label.
        :raises IndexError: no such row.
        :raises ValueError: the label is empty, or another root already uses it (case-insensitively).
        """
        self.__check_row(at)
        if not label:
            raise ValueError("A root label cannot be empty")
        folded = label.casefold()
        if any(raw[ROOT_LABEL_KEY].casefold() == folded for row, raw in enumerate(self.__roots) if row != at):
            raise ValueError(f"Another root is already labeled {label!r}")
        self.__roots[at][ROOT_LABEL_KEY] = label

    def set_storage(self, at: int, storage: RootStorage) -> None:
        """Say what a root's folder lives on; nothing on disk changes.

        :param at: the root's row.
        :param storage: the new storage.
        :raises IndexError: no such row.
        """
        self.__check_row(at)
        self.__roots[at][ROOT_STORAGE_KEY] = RootStorage(storage).value

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
        path = raw.get(ROOT_PATH_KEY)
        label = raw.get(ROOT_LABEL_KEY)
        storage = raw.get(ROOT_STORAGE_KEY, RootStorage.LOCAL.value)
        if not isinstance(path, str) or not path:
            raise self.__error(f"A root has no '{ROOT_PATH_KEY}'")
        if not isinstance(label, str) or not label:
            raise self.__error(f"The root {path!r} has no '{ROOT_LABEL_KEY}'")
        if not isinstance(storage, str) or storage not in {member.value for member in RootStorage}:
            raise self.__error(f"The root {path!r} has an unknown '{ROOT_STORAGE_KEY}': {storage!r}")
        root_id = self.__read_uuid(raw.get(ROOT_ID_KEY), f"the root {path!r}'s id")
        return RehucoRoot(root_id=root_id, path=Path(path), label=label, storage=RootStorage(storage))

    def __read_uuid(self, value: Any, what: str) -> UUID:
        if not isinstance(value, str):
            raise self.__error(f"Missing {what}")
        try:
            return UUID(value)
        except ValueError as error:
            raise self.__error(f"Not a UUID: {what}") from error

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
    def __default_label(path: Path | str) -> str:
        # split on both separators rather than through `Path`, so a Windows path labels the same on every platform
        spelled = str(path)
        return spelled.rstrip("/\\").replace("\\", "/").rsplit("/", 1)[-1] or spelled

    @staticmethod
    def __path_key(path: Path | str) -> str:
        return os_path.normcase(os_path.normpath(str(path)))
