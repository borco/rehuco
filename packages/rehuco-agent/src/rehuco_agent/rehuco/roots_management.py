"""Which record manages a row of the Roots view (#469).

A file or folder is *managed* when a record's content walk takes it: a file-scoped ``foo.rehu`` manages ``foo.*`` and
screenshots, the nearest ``info.rehu`` at or above a folder manages everything under it that no record of its own takes.
The answer is the content walk's own -- :class:`~rehuco_core.DirectoryClassifier` over the listings the model already
holds -- so the menu, the buttons and the checksum verbs cannot disagree with the Files dock, and no disk is read but
for a folder never opened, whose own record is asked of the disk as its Open button already is.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QModelIndex
from rehuco_core import (
    DIRECTORY_SCOPED_FILENAMES,
    INFO_REHU_FILENAME,
    SCREENSHOT_STEM_PATTERN,
    DirectoryClassifier,
    DirectoryEntry,
    DirectoryListing,
    FileKind,
    FileType,
    checksum_record_path,
    is_directory_scoped_name,
    is_record_name,
)

from .roots_folder_model import RootsFolderModel, RootsNodeKind

MANAGED_KINDS: Final = frozenset(
    {FileKind.CONTENT, FileKind.OWN_RECORD, FileKind.OWN_SCREENSHOT, FileKind.OWN_MANIFEST, FileKind.DIRECTORY}
)
"""What a record takes as its own, seen from one of its folders: content, its own bookkeeping, and folders (a folder
with a record of its own is its own resource, and is asked as one)."""


@dataclass(frozen=True, slots=True)
class ManagingRecord:
    """The record that manages a row.

    :param record: the record's path.
    :param file_scoped: whether it is a ``foo.rehu`` (its stem's files) rather than an ``info.rehu`` (its folder).
    :param here: whether the row is in the record's own folder, or is that folder.
    :param relative: the row's name under the record's folder, ``/`` separated -- how the record's entries are named.
    :param has_checksum: whether a checksum file of the record is beside it.
    """

    record: Path
    file_scoped: bool
    here: bool
    relative: str
    has_checksum: bool

    @property
    def can_checksum(self) -> bool:
        """Whether the checksum jobs can run over it: a ``.rehu`` record (a legacy ``.tc`` is managed, not hashed)."""
        return self.record.suffix.lower() == ".rehu"

    @property
    def scope_words(self) -> str:
        """What the record's bulk verb covers, as the menu words it: ``all foo.* files``, ``all files in the folder`` or
        ``all files of the parent resource``."""
        if self.file_scoped:
            return f"all {self.record.stem}.* files"
        return "all files in the folder" if self.here else "all files of the parent resource"


def _entry(model: RootsFolderModel, child: QModelIndex) -> DirectoryEntry:
    """One folder or file row, as the classifier reads it.

    :param model: the Roots model.
    :param child: the row.
    :returns: its entry.
    """
    name = str(model.data(child))
    if model.node_kind(child) is RootsNodeKind.FOLDER:
        return DirectoryEntry(name, FileKind.DIRECTORY, FileType.DIRECTORY)
    return DirectoryEntry(name, FileKind.CONTENT, model.file_type_of(child) or FileType.GENERIC)


def _listing(model: RootsFolderModel, holder: QModelIndex) -> DirectoryListing:
    """A root or folder that has rows as a listing -- its placeholder rows left out.

    Every caller asks about a row, whose folders and root were all listed for it to be there.

    :param model: the Roots model.
    :param holder: the root or folder.
    :returns: the listing.
    """
    children = (model.index(row, 0, holder) for row in range(model.rowCount(holder)))
    entries = tuple(
        _entry(model, child)
        for child in children
        if model.node_kind(child) in (RootsNodeKind.FOLDER, RootsNodeKind.FILE)
    )
    return DirectoryListing(cast(Path, model.path_of(holder)), entries=entries)


def _record_in(names: tuple[str, ...]) -> str | None:
    """The directory-scoped record a folder holds: ``info.rehu`` before ``info.tc``.

    :param names: the folder's names.
    :returns: its name, or ``None``.
    """
    return next((name for name in DIRECTORY_SCOPED_FILENAMES if name in names), None)


def _file_scoped_records(names: tuple[str, ...]) -> list[str]:
    """The file-scoped records a folder holds, ``.rehu`` before ``.tc``.

    :param names: the folder's names.
    :returns: their names, in the order they are asked.
    """
    records = (name for name in names if is_record_name(name) and not is_directory_scoped_name(name))
    return sorted(records, key=lambda name: (name.lower().endswith(".tc"), name.lower()))


def _manages(listing: DirectoryListing, record: Path, name: str) -> bool:
    """Whether ``record`` takes the entry called ``name`` of ``listing`` as its own.

    :param listing: a folder, anywhere in or under the record's.
    :param record: the record.
    :param name: the entry.
    :returns: whether the content walk counts it.
    """
    named = DirectoryClassifier(record).reclassify(listing)
    return any(entry.name == name and entry.kind in MANAGED_KINDS for entry in named.entries)


def _has_checksum(listing: DirectoryListing, record: Path) -> bool:
    """Whether a checksum file of ``record`` is in its folder.

    :param listing: the record's own folder.
    :param record: the record.
    :returns: whether one is.
    """
    named = DirectoryClassifier(record).reclassify(listing)
    return any(entry.kind is FileKind.OWN_MANIFEST for entry in named.entries)


def managing_record(model: RootsFolderModel, index: QModelIndex) -> ManagingRecord | None:
    """The record that manages a folder or file row.

    A file-scoped record in the row's folder is asked first, as in the content walk; then the nearest ``info.rehu``
    in the row's folder or above it. A folder with a record of its own is that record's; a folder under an
    ``info.rehu`` is the parent's.

    :param model: the Roots model.
    :param index: the row.
    :returns: the record; ``None`` for a root, a placeholder, a row nothing manages, or folders not yet listed.
    """
    kind = model.node_kind(index)
    path = model.path_of(index)
    if path is None or kind not in (RootsNodeKind.FOLDER, RootsNodeKind.FILE):
        return None
    listing = _listing(model, index.parent())
    if kind is RootsNodeKind.FOLDER:
        # a folder with a record of its own is its own resource -- asked of the listing when it has one and of the
        # disk otherwise, as its Open button is, so the two never disagree on a folder never opened
        record = companion_found(model, index)
        if record is not None:
            has_checksum = (
                checksum_record_path(record).exists()
                if model.child_names(index) is None
                else _has_checksum(_listing(model, index), record)
            )
            return ManagingRecord(record, False, True, "", has_checksum)
    else:
        for file_name in _file_scoped_records(tuple(entry.name for entry in listing.entries)):
            record = listing.directory / file_name
            if _manages(listing, record, path.name):
                return ManagingRecord(record, True, True, path.name, _has_checksum(listing, record))
    return _above(model, index, path)


def _above(model: RootsFolderModel, index: QModelIndex, path: Path) -> ManagingRecord | None:
    """The nearest ``info.rehu`` in a row's folder or above it, if it takes the row.

    :param model: the Roots model.
    :param index: the folder or file row.
    :param path: its path.
    :returns: the record; ``None`` when there is none, or it does not take the row.
    """
    row_listing = _listing(model, index.parent())
    holder = index.parent()
    while holder.isValid():
        listing = _listing(model, holder)
        found = _record_in(tuple(entry.name for entry in listing.entries if not entry.is_directory))
        if found is not None:
            record = listing.directory / found
            if not _manages(row_listing, record, path.name):
                return None
            relative = Path(os.path.relpath(path, record.parent)).as_posix()
            return ManagingRecord(record, False, path.parent == record.parent, relative, _has_checksum(listing, record))
        holder = holder.parent()
    return None


def companion_record(model: RootsFolderModel, index: QModelIndex) -> Path | None:
    """Where the ``.rehu`` of a folder or file is, or would be.

    :param model: the Roots model.
    :param index: the folder or file.
    :returns: its ``info.rehu`` for a folder, its same-name ``.rehu`` for a file; ``None`` for any other row.
    """
    path = model.path_of(index)
    if path is None:
        return None
    if model.node_kind(index) is RootsNodeKind.FOLDER:
        return path / INFO_REHU_FILENAME
    if index.data(RootsFolderModel.BOOKKEEPING_ROLE) and model.file_type_of(index) is FileType.IMAGE:
        # a screenshot belongs to the record it is numbered after: ``info00.jpg`` to ``info.rehu``, and it is
        # never the start of a record of its own (a listing calls an image a sidecar only when it is numbered)
        return path.with_name(f"{SCREENSHOT_STEM_PATTERN.sub(r'\g<record>', path.stem)}.rehu")
    return path.with_suffix(".rehu")


def companion_found(model: RootsFolderModel, index: QModelIndex) -> Path | None:
    """The rehu a folder or file already has: its ``.rehu``, else its legacy ``.tc``.

    Answered from the listing when it has one -- a file's neighbours are always listed, a folder's only once it
    has been opened -- and from the disk otherwise.

    :param model: the Roots model.
    :param index: the folder or file.
    :returns: its path, or ``None`` when it has none (or the row is neither a folder nor a file).
    """
    record = companion_record(model, index)
    if record is None:
        return None
    holder = index if model.node_kind(index) is RootsNodeKind.FOLDER else index.parent()
    candidates = (record, record.with_suffix(".tc"))
    names = model.child_names(holder)
    if names is None:
        return next((candidate for candidate in candidates if candidate.exists()), None)
    listed = {os.path.normcase(name) for name in names}
    return next((candidate for candidate in candidates if os.path.normcase(candidate.name) in listed), None)
