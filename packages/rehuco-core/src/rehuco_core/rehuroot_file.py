"""The ``.rehuroot`` file: one root, shared by every catalog that lists it ([[mounts-and-storage#rehuroot]], #577).

A root is a file of its own, beside the ``.rehuco`` files that list it and never inside the root itself. It holds what
is a fact about the root rather than about one catalog or one machine. The shape::

    {
      "format_version": 1,
      "id": "a41b9c3d-...",
      "label": "Tutorials",
      "location": "//nas/data/Tutorials",
      "layouts": { "*": "*" },
      "fallbacks": { "authors": "Unknown" }
    }

**``id``** is minted once, so every catalog listing the file names the root the same way, and a machine maps it once
(:class:`~rehuco_core.root_mappings.RootMappings`). **``label``** and **``location``** are what a ``.rehuco`` root used
to hold inline. **``layouts``** says where a record of each type lives under the root, by the type's main key or ``*``
for any type not named: a path template (:func:`~rehuco_core.root_destination.destination`), or ``*`` for *keep the
record's current name at the root's top*, or *where it is* for a record already under the root (#636).
**``fallbacks``** names what a placeholder renders as when a record leaves it empty.

What this build does not understand is carried: an unknown top-level key comes back out of a save unchanged. A file
stamped newer than this build loads, but read-only, with the reason stated. A save takes the file's lock and writes only
if the file is still what this machine last read or wrote (:class:`RehurootChangedError` otherwise).
"""

import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID, uuid4

from borco_core import atomic_write_text

from .lock_reasons import LockReason, LockReasonKind
from .record_file_lock import RecordFileLock
from .rehu_format import FORMAT_VERSION_KEY
from .shared_file_digest import disk_digest, text_digest

REHUROOT_SUFFIX: Final = ".rehuroot"
"""A root file's extension."""

REHUROOT_FORMAT_VERSION: Final = 1
"""The ``format_version`` this build writes and reads; the first there has been, so nothing older is migrated."""

ROOT_ID_KEY: Final = "id"
"""The key holding the root's id, a UUID string."""

ROOT_LABEL_KEY: Final = "label"
"""The key holding the name the browser shows and a folder filter addresses."""

ROOT_LOCATION_KEY: Final = "location"
"""The key holding the root's machine-independent location (:mod:`rehuco_core.root_location`)."""

LAYOUTS_KEY: Final = "layouts"
"""The key holding the per-type path templates."""

FALLBACKS_KEY: Final = "fallbacks"
"""The key holding what a placeholder renders as when a record leaves it empty."""

ANY_TYPE: Final = "*"
"""The ``layouts`` key a type with no entry of its own falls back to."""

KEEP_NAME: Final = "*"
"""The ``layouts`` value that keeps a record's current folder name, at the root's top; a record already under the root
stays where it is (#636)."""

DEFAULT_LAYOUTS: Final[Mapping[str, str]] = MappingProxyType({ANY_TYPE: KEEP_NAME})
"""What a root made from a folder starts with: any record, under its current name."""


class RehurootFileError(ValueError):
    """A ``.rehuroot`` file this build cannot read: not text, not JSON, not an object, no usable id, label or location,
    layouts or fallbacks that are not an object of strings, or a stamp that is no version at all."""


class RehurootChangedError(RuntimeError):
    """A save found the ``.rehuroot`` changed on disk since this machine last read or wrote it -- or, for a file never
    saved, found one already there. Nothing was written."""


class RehurootFile:
    """A ``.rehuroot`` in memory.

    The parsed JSON object is the source of truth; :attr:`label`, :attr:`layouts` and :attr:`fallbacks` edit it in
    place and mark the file :attr:`dirty` until :meth:`save` writes it back.

    :param data: the parsed JSON object.
    :param path: the file it was read from, or is to be saved to.
    :param loaded_text: the text ``data`` was parsed from, which a save compares the file on disk with; ``None`` for a
        file not read from disk, which a save writes only where no file is.
    :raises RehurootFileError: the object does not have a ``.rehuroot``'s shape.
    """

    def __init__(self, data: dict[str, Any], path: Path, *, loaded_text: str | None = None) -> None:
        self.__path: Final = path
        self.__saved_hash = None if loaded_text is None else text_digest(loaded_text)
        self.__dirty = loaded_text is None
        stamp = data.get(FORMAT_VERSION_KEY)
        if not isinstance(stamp, int) or isinstance(stamp, bool) or stamp < REHUROOT_FORMAT_VERSION:
            raise self.__error(f"'{FORMAT_VERSION_KEY}' is not a version")
        self.__data: Final = data
        self.__root_id: Final = self.__read_uuid(data.get(ROOT_ID_KEY))
        location = data.get(ROOT_LOCATION_KEY)
        if not isinstance(location, str) or not location:
            raise self.__error(f"No '{ROOT_LOCATION_KEY}'")
        if not isinstance(data.get(ROOT_LABEL_KEY), str):
            raise self.__error(f"No '{ROOT_LABEL_KEY}'")
        self.__read_strings(data.setdefault(LAYOUTS_KEY, dict(DEFAULT_LAYOUTS)), LAYOUTS_KEY)
        self.__read_strings(data.setdefault(FALLBACKS_KEY, {}), FALLBACKS_KEY)

    @classmethod
    def new(
        cls,
        path: Path,
        location: str,
        label: str,
        *,
        layouts: Mapping[str, str] = DEFAULT_LAYOUTS,
        fallbacks: Mapping[str, str] | None = None,
    ) -> RehurootFile:
        """A root file never saved, under a fresh id.

        :param path: where it is to be saved.
        :param location: where the root is, as :func:`rehuco_core.root_location.location_of` spells it.
        :param label: the name to show.
        :param layouts: where a record of each type lives under the root; the default keeps any record's name.
        :param fallbacks: what a placeholder renders as when a record leaves it empty; none when ``None``.
        :returns: the file, :attr:`dirty` until its first :meth:`save`.
        :raises RehurootFileError: the layouts or fallbacks are not strings.
        """
        data: dict[str, Any] = {
            FORMAT_VERSION_KEY: REHUROOT_FORMAT_VERSION,
            ROOT_ID_KEY: str(uuid4()),
            ROOT_LABEL_KEY: label,
            ROOT_LOCATION_KEY: location,
            LAYOUTS_KEY: dict(layouts),
            FALLBACKS_KEY: dict(fallbacks or {}),
        }
        return cls(data, path)

    @classmethod
    def load(cls, path: Path) -> RehurootFile:
        """Read a ``.rehuroot`` file whole.

        :param path: the file.
        :returns: the file; read-only (:attr:`lock_reason`) when it is stamped newer than this build.
        :raises FileNotFoundError: no such file.
        :raises OSError: the file exists and cannot be read.
        :raises RehurootFileError: the file is not a ``.rehuroot`` this build can read.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise RehurootFileError(f"Not a text file: {path}") from error
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise RehurootFileError(f"Not JSON: {path}") from error
        if not isinstance(data, dict):
            raise RehurootFileError(f"Not a JSON object: {path}")
        return cls(data, path, loaded_text=text)

    @property
    def path(self) -> Path:
        """The file."""
        return self.__path

    @property
    def root_id(self) -> UUID:
        """The root's id, the same in every catalog listing this file."""
        return self.__root_id

    @property
    def location(self) -> str:
        """Where the root is, spelled the same on every machine."""
        return self.__data[ROOT_LOCATION_KEY]

    @property
    def label(self) -> str:
        """The name the browser shows and a folder filter addresses; may be empty."""
        return self.__data[ROOT_LABEL_KEY]

    @label.setter
    def label(self, value: str) -> None:
        reason = self.lock_reason
        if reason is not None:
            raise ValueError(f"Refusing to relabel a read-only .rehuroot: {reason.message}")
        if value != self.label:
            self.__data[ROOT_LABEL_KEY] = value
            self.__dirty = True

    @property
    def layouts(self) -> Mapping[str, str]:
        """The path template of each type's main key, ``*`` for any type not named."""
        return MappingProxyType(self.__data[LAYOUTS_KEY])

    @layouts.setter
    def layouts(self, value: Mapping[str, str]) -> None:
        self.__replace(LAYOUTS_KEY, value)

    @property
    def fallbacks(self) -> Mapping[str, str]:
        """What each placeholder renders as when a record leaves it empty."""
        return MappingProxyType(self.__data[FALLBACKS_KEY])

    @fallbacks.setter
    def fallbacks(self, value: Mapping[str, str]) -> None:
        self.__replace(FALLBACKS_KEY, value)

    def __replace(self, key: str, value: Mapping[str, str]) -> None:
        """Replace one of the maps, marking the file dirty only when it changes.

        :param key: :data:`LAYOUTS_KEY` or :data:`FALLBACKS_KEY`.
        :param value: the new map, copied.
        :raises ValueError: the file is read-only (:attr:`lock_reason`).
        """
        reason = self.lock_reason
        if reason is not None:
            raise ValueError(f"Refusing to edit a read-only .rehuroot: {reason.message}")
        copied = dict(value)
        if copied != self.__data[key]:
            self.__data[key] = copied
            self.__dirty = True

    @property
    def dirty(self) -> bool:
        """Whether there is something :meth:`save` would write: a change, or a file never saved."""
        return self.__dirty

    @property
    def format_version(self) -> int:
        """The version the file is stamped with -- above :data:`REHUROOT_FORMAT_VERSION` only for a file newer than
        this build."""
        return self.__data[FORMAT_VERSION_KEY]

    @property
    def lock_reason(self) -> LockReason | None:
        """Why this file is read-only, or ``None`` when it can be saved: only a file newer than this build is."""
        if self.format_version > REHUROOT_FORMAT_VERSION:
            return LockReason(
                LockReasonKind.NEWER_FORMAT,
                f"format_version {self.format_version} is newer than this build understands "
                f"({REHUROOT_FORMAT_VERSION}).",
            )
        return None

    def save(self) -> None:
        """Write the file, atomically, under its lock file like a record.

        The layout is canonical: ``format_version``, the id, the label, the location, the layouts, the fallbacks, then
        any carried unknown key in the order it was read.

        :raises ValueError: the file is read-only (:attr:`lock_reason`).
        :raises RecordLockedError: someone else held its lock for longer than a save waits.
        :raises RehurootChangedError: the file on disk is no longer what this machine last read or wrote, or a file
            never saved found one already there.
        :raises OSError: the file could not be written.
        """
        reason = self.lock_reason
        if reason is not None:
            raise ValueError(f"Refusing to save a read-only .rehuroot: {reason.message}")
        ordered = (FORMAT_VERSION_KEY, ROOT_ID_KEY, ROOT_LABEL_KEY, ROOT_LOCATION_KEY, LAYOUTS_KEY, FALLBACKS_KEY)
        payload: dict[str, Any] = {key: self.__data[key] for key in ordered}
        payload[FORMAT_VERSION_KEY] = REHUROOT_FORMAT_VERSION
        payload.update({key: value for key, value in self.__data.items() if key not in ordered})
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        with RecordFileLock(self.__path):
            self.__check_unchanged()
            atomic_write_text(self.__path, text)
        self.__saved_hash = text_digest(text)
        self.__dirty = False

    def __check_unchanged(self) -> None:
        """Refuse to write over a file someone else changed since this one last read or wrote it, or, for a file never
        saved, over one someone made meanwhile.

        :raises RehurootChangedError: the file differs, or is there when it should not be.
        :raises OSError: the file could not be read.
        """
        if self.__saved_hash is None:
            if self.__path.exists():
                raise RehurootChangedError(f"A .rehuroot is already there: {self.__path}")
            return
        if disk_digest(self.__path) != self.__saved_hash:
            raise RehurootChangedError(f"The .rehuroot changed on disk: {self.__path}")

    def __read_uuid(self, value: Any) -> UUID:
        """The root's id, read.

        :param value: what the file holds under the id's key.
        :returns: the id.
        :raises RehurootFileError: it is no UUID string.
        """
        if not isinstance(value, str):
            raise self.__error(f"No '{ROOT_ID_KEY}'")
        try:
            return UUID(value)
        except ValueError as error:
            raise self.__error(f"Not a UUID: '{ROOT_ID_KEY}'") from error

    def __read_strings(self, value: Any, key: str) -> None:
        """Check an object of strings.

        :param value: what the file holds under ``key``.
        :param key: the key, for the message.
        :raises RehurootFileError: it is not an object whose keys and values are all strings.
        """
        if not isinstance(value, dict) or not all(isinstance(item, str) for item in value.values()):
            raise self.__error(f"'{key}' is not an object of strings")

    def __error(self, message: str) -> RehurootFileError:
        """An error naming this file.

        :param message: what is wrong.
        :returns: the error.
        """
        return RehurootFileError(f"{message}: {self.__path}")
