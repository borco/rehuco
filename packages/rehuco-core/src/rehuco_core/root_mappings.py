"""Where this machine finds each root of a ``.rehuco`` -- the per-machine half of a shareable catalog
([[mounts-and-storage#rehuco-scope]], #514).

A ``.rehuco`` names a root by its location, the same on every box; the folder that location is on *this* machine, and
what it lives on, are facts about this machine and are kept here, in a file of the machine's own data folder, never in
the shared ``.rehuco``. The agent and the node of one machine read the same file. A root the user chose not to map is
remembered as skipped, so opening the catalog does not ask again; mapping it later replaces the skip. The shape::

    {
      "format_version": 1,
      "rehucos": {
        "<rehuco id>": {
          "<root id>": { "path": "U:\\\\Tutorials", "storage": "network" },
          "<root id>": { "skipped": true }
        }
      }
    }

One machine writes the file, so it takes no lock; it is replaced atomically. What this build does not understand is
carried: an unknown top-level key, and an unknown key on an entry, come back out of a save unchanged.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from borco_core import atomic_write_text

from .rehuco_file import RehucoFile, RehucoRoot, RootStorage
from .root_location import storage_of

ROOT_MAPPINGS_FILE_NAME: Final = "root-mappings.json"
"""The file, in the machine's data folder, holding every catalog's mappings."""

FORMAT_VERSION: Final = 1
"""The ``format_version`` this build writes and reads."""

FORMAT_VERSION_KEY: Final = "format_version"
REHUCOS_KEY: Final = "rehucos"
PATH_KEY: Final = "path"
STORAGE_KEY: Final = "storage"
SKIPPED_KEY: Final = "skipped"


class RootMappingsError(ValueError):
    """A mappings file this build cannot read: not text, not JSON, not an object, or stamped by a newer build."""


@dataclass(frozen=True, slots=True)
class RootMapping:
    """Where this machine finds one root.

    :param path: the root's folder on this machine.
    :param storage: what that folder lives on, detected when it was mapped.
    """

    path: Path
    storage: RootStorage


@dataclass(frozen=True, slots=True)
class MappedRoot:
    """A root of a ``.rehuco`` this machine reaches: the shared root plus this machine's mapping of it.

    :param root_id: the root's stable id.
    :param label: the name the browser shows and a folder filter addresses.
    :param location: where the root is, spelled the same on every machine.
    :param path: the root's folder on this machine.
    :param storage: what that folder lives on.
    """

    root_id: UUID
    label: str
    location: str
    path: Path
    storage: RootStorage = RootStorage.LOCAL

    @property
    def removable(self) -> bool:
        """Whether the folder lives on a medium that can be taken away -- a removable drive or a compact disk. What
        the cache's ``removable`` column and the retention rules read."""
        return self.storage in (RootStorage.REMOVABLE, RootStorage.COMPACT_DISK)


class RootMappings:
    """This machine's mappings of every catalog's roots, in memory; :meth:`save` writes them back.

    :param data: the parsed JSON object.
    :param path: the file it was read from and is saved to.
    :raises RootMappingsError: the object is stamped by a newer build.
    """

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        stamp = data.get(FORMAT_VERSION_KEY, FORMAT_VERSION)
        if isinstance(stamp, int) and not isinstance(stamp, bool) and stamp > FORMAT_VERSION:
            raise RootMappingsError(f"{path} was written by a newer build (format_version {stamp})")
        self.__data: Final = data
        self.__path: Final = path

    @classmethod
    def load(cls, path: Path) -> RootMappings:
        """Read the file; a file that does not exist yet is an empty one.

        :param path: the file.
        :returns: the mappings.
        :raises OSError: the file exists and cannot be read.
        :raises RootMappingsError: the file is not a mappings file this build can read.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return cls({}, path)
        except UnicodeDecodeError as error:
            raise RootMappingsError(f"Not a text file: {path}") from error
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise RootMappingsError(f"Not JSON: {path}") from error
        if not isinstance(data, dict):
            raise RootMappingsError(f"Not a JSON object: {path}")
        return cls(data, path)

    def mapping(self, rehuco_id: UUID, root_id: UUID) -> RootMapping | None:
        """Where this machine finds a root.

        :param rehuco_id: the catalog.
        :param root_id: the root.
        :returns: the mapping, or ``None`` when the root is unmapped, skipped, or its entry is malformed.
        """
        entry = self.__entry(rehuco_id, root_id)
        path = entry.get(PATH_KEY)
        storage = entry.get(STORAGE_KEY)
        if not isinstance(path, str) or not path or storage not in {member.value for member in RootStorage}:
            return None
        return RootMapping(Path(path), RootStorage(storage))

    def skipped(self, rehuco_id: UUID, root_id: UUID) -> bool:
        """Whether the user chose not to map a root on this machine.

        :param rehuco_id: the catalog.
        :param root_id: the root.
        :returns: whether the root is remembered as skipped.
        """
        return self.__entry(rehuco_id, root_id).get(SKIPPED_KEY) is True

    def map(self, rehuco_id: UUID, root_id: UUID, path: Path) -> RootMapping:
        """Say where this machine finds a root; a skip is replaced.

        :param rehuco_id: the catalog.
        :param root_id: the root.
        :param path: the root's folder on this machine; its storage is detected from this machine's tables.
        :returns: the mapping now recorded.
        """
        mapping = RootMapping(path, storage_of(path))
        entry = self.__entry(rehuco_id, root_id)
        entry.pop(SKIPPED_KEY, None)
        entry[PATH_KEY] = str(mapping.path)
        entry[STORAGE_KEY] = mapping.storage.value
        self.__catalog(rehuco_id)[str(root_id)] = entry
        return mapping

    def skip(self, rehuco_id: UUID, root_id: UUID) -> None:
        """Remember that the user chose not to map a root on this machine; an earlier mapping is dropped.

        :param rehuco_id: the catalog.
        :param root_id: the root.
        """
        entry = self.__entry(rehuco_id, root_id)
        entry.pop(PATH_KEY, None)
        entry.pop(STORAGE_KEY, None)
        entry[SKIPPED_KEY] = True
        self.__catalog(rehuco_id)[str(root_id)] = entry

    def forget(self, rehuco_id: UUID, root_id: UUID) -> None:
        """Drop everything remembered about a root -- it was removed from the catalog.

        :param rehuco_id: the catalog.
        :param root_id: the root.
        """
        self.__catalog(rehuco_id).pop(str(root_id), None)

    def mapped(self, file: RehucoFile) -> tuple[MappedRoot, ...]:
        """The roots of a catalog this machine reaches, in display order.

        :param file: the catalog.
        :returns: its roots that have a mapping here.
        """
        mapped: list[MappedRoot] = []
        for root in file.roots:
            mapping = self.mapping(file.rehuco_id, root.root_id)
            if mapping is not None:
                mapped.append(MappedRoot(root.root_id, root.label, root.location, mapping.path, mapping.storage))
        return tuple(mapped)

    def unmapped(self, file: RehucoFile) -> tuple[RehucoRoot, ...]:
        """The roots of a catalog this machine does not reach -- skipped ones too.

        :param file: the catalog.
        :returns: its roots that have no mapping here, in display order.
        """
        return tuple(root for root in file.roots if self.mapping(file.rehuco_id, root.root_id) is None)

    def save(self) -> None:
        """Write the mappings back atomically, creating the file's folder.

        :raises OSError: the file could not be written.
        """
        payload: dict[str, Any] = {FORMAT_VERSION_KEY: FORMAT_VERSION}
        payload.update({key: value for key, value in self.__data.items() if key != FORMAT_VERSION_KEY})
        self.__path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.__path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    def __catalog(self, rehuco_id: UUID) -> dict[str, Any]:
        """One catalog's entries, created on demand; a malformed one is replaced.

        :param rehuco_id: the catalog.
        :returns: its entries, by root id, held in the data so a change to them is saved.
        """
        rehucos = self.__data.get(REHUCOS_KEY)
        if not isinstance(rehucos, dict):
            rehucos = self.__data[REHUCOS_KEY] = {}
        catalog = rehucos.get(str(rehuco_id))
        if not isinstance(catalog, dict):
            catalog = rehucos[str(rehuco_id)] = {}
        return catalog

    def __entry(self, rehuco_id: UUID, root_id: UUID) -> dict[str, Any]:
        """One root's entry, a copy-free read; a missing or malformed one reads as empty (and is not stored).

        :param rehuco_id: the catalog.
        :param root_id: the root.
        :returns: the entry.
        """
        rehucos = self.__data.get(REHUCOS_KEY)
        catalog = rehucos.get(str(rehuco_id)) if isinstance(rehucos, dict) else None
        entry = catalog.get(str(root_id)) if isinstance(catalog, dict) else None
        return entry if isinstance(entry, dict) else {}
