"""What a Roots folder's listing says beyond its rows: the records it bears on, the names it holds, the folders that
appeared in it since the listing before (#487, #645), and the directory-scoped record above it.

Read from the nodes the model already holds, so none of it costs a disk read
(:class:`~rehuco_agent.rehuco.roots_folder_model.RootsFolderModel`).
"""

import os
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from rehuco_core import DIRECTORY_SCOPED_FILENAMES, DirectoryEntry, Relocation

from .roots_node import RootsNode, RootsNodeKind

CHECKSUM_FILENAME: Final = "info.checksum"
"""The checksum file a directory-scoped record keeps beside it, matched case-folded."""


@dataclass(frozen=True, slots=True)
class ListedFolder:
    """A folder just listed, reachable, and what that tells the cache (#487, #645).

    :param folder: the folder's absolute path.
    :param records: the records it holds and the directory-scoped one above that manages it, absolute.
    :param folders: the names of the folders it holds.
    :param files: the names of the files it holds.
    :param appeared: the folders this listing shows and the previous one did not, absolute. A first listing has no
        previous one, so nothing appeared in it.
    """

    folder: Path
    records: tuple[Path, ...]
    folders: tuple[str, ...] = ()
    files: tuple[str, ...] = ()
    appeared: tuple[Path, ...] = ()

    def unlisted(self, records: Iterable[Path]) -> list[Path]:
        """The records beneath the folder that the listing no longer shows a way to (#645): one directly in it whose
        file is not listed, or one deeper whose first folder down is not -- what the cache still holds of something
        deleted or moved away, whenever that happened. Names compare as the file system compares them.

        :param records: records the cache holds at or beneath the folder, absolute; one not beneath it is passed over.
        :returns: those the listing does not account for, in order.
        """
        folder = Relocation.path_parts(self.folder)
        folders = {os.path.normcase(name) for name in self.folders}
        files = {os.path.normcase(name) for name in self.files}
        unlisted: list[Path] = []
        for record in records:
            parts = Relocation.path_parts(record)
            if len(parts) <= len(folder) or parts[: len(folder)] != folder:
                continue
            first, *deeper = parts[len(folder) :]
            if first not in (folders if deeper else files):
                unlisted.append(record)
        return unlisted


@dataclass(frozen=True, slots=True)
class ScopedRecord:
    """The directory-scoped record nearest above a row.

    :param folder: the ancestor row that holds it.
    :param name: its file name.
    :param checksummed: whether an ``info.checksum`` sits beside it.
    """

    folder: RootsNode
    name: str
    checksummed: bool


def scoped_record_above(node: RootsNode, top: RootsNode) -> ScopedRecord | None:
    """The directory-scoped record above ``node``, from the listings already held: the nearest ancestor with one
    decides, and an ``info.rehu`` is preferred over an ``info.tc`` a conversion left beside it.

    :param node: a root or a row under one.
    :param top: the model's invisible top, where the walk stops.
    :returns: the record; ``None`` when no loaded ancestor holds one.
    """
    ancestor = node.parent
    while ancestor is not None and ancestor is not top:
        names = {child.name for child in ancestor.children if child.kind is RootsNodeKind.FILE}
        record = next((name for name in DIRECTORY_SCOPED_FILENAMES if name in names), None)
        if record is not None:
            return ScopedRecord(ancestor, record, CHECKSUM_FILENAME in {name.lower() for name in names})
        ancestor = ancestor.parent
    return None


def appeared_folders(before: Collection[str] | None, entries: Iterable[DirectoryEntry]) -> list[str]:
    """The folders a listing shows that the folder's listing before did not (#645).

    :param before: the names of the folders the listing before showed; ``None`` when there was no listing before that
        could read the folder.
    :param entries: what this listing shows.
    :returns: the names; none when ``before`` is ``None``.
    """
    if before is None:
        return []
    return [entry.name for entry in entries if entry.is_directory and entry.name not in before]
