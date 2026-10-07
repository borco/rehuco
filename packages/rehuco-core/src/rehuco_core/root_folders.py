"""Listing one folder under a ``.rehuco``'s root, by ``(root id, relative path)`` (#378).

The Roots view reads every folder through :meth:`RootFolderLister.list`, and nothing else in it touches the
disk. That one function is the seam Release 0.4.0 swaps for the access seam's file listing
([[nodes#access-seam]]), so a root another node serves browses the same way: the question is asked by root id
and relative path, never by an absolute path the caller built.

**It also reads the checksum record that covers a listed file** (#457): the same small JSON read the Files dock makes,
once per record per listed folder, inside the same hold, so the Roots view can say what each file's record last found
without ever reading on the GUI thread.

Core-side and GUI-free: the roots, the rename coordinator, the trust store and the junk globs are all parameters.
"""

import os
from collections.abc import Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from .checksum_record import (
    TRUST_NOT_TRACKED,
    ChecksumRecordError,
    checksum_entry_name,
    checksum_record_path,
    load_checksum_record,
    parse_checksum_entry,
)
from .checksum_trust import ChecksumTrust
from .constants import EXCLUDED_FILE_PATTERNS
from .rehu_file_kinds import CoveredFile, DirectoryClassifier, DirectoryListing, FileKind
from .rehuco_file import RehucoRoot
from .rename_coordination import RenameCoordinator
from .resource_scoping import is_directory_scoped_name, is_record_name

BROWSING_RECORD: Final = Path("browsing.rehu")
"""The record path a listing is classified from. It names no resource: its parent is ``.``, which no directory a
root lists ever equals, so no folder is ever "a resource's own directory" -- the classifier answers for entries
as they would be to a stranger, which is all the Roots view reads (whether an entry is a folder, and its
:class:`~rehuco_core.rehu_file_kinds.FileType`)."""


# one method is the whole of it -- list a folder -- and it is the seam the access seam replaces
# pylint: disable-next=too-few-public-methods
class RootFolderLister:
    """Lists one folder of one root, under the rename coordinator's hold.

    **Never blocks a rename** ([[mounts-and-storage#out-of-band]]): each call is one ``scandir``, plus one small read
    per checksum record that covers a file of the folder (#457), inside :meth:`~rehuco_core.RenameCoordinator.holding`,
    closed before it returns, so no handle is held between two calls and a rename waits for at most one directory
    read.

    Built over a snapshot of the roots, which is immutable, so one instance may be called from any thread.

    :param roots: the ``.rehuco``'s roots.
    :param coordinator: what each read is held under; ``None`` holds nothing, for a caller with no renames to yield
        to.
    :param excluded_patterns: filename globs that take a file out of content.
    :param trust: what says when this machine began trusting a record where it is, for the states of the files it
        covers; ``None`` tracks no trust, so every stamp counts.
    """

    def __init__(
        self,
        roots: Iterable[RehucoRoot],
        *,
        coordinator: RenameCoordinator | None = None,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        trust: ChecksumTrust | None = None,
    ) -> None:
        self.__paths: Final = {root.root_id: root.path for root in roots}
        self.__coordinator: Final = coordinator
        self.__excluded_patterns: Final = excluded_patterns
        self.__trust: Final = trust
        self.__classifier: Final = DirectoryClassifier(BROWSING_RECORD, excluded_patterns)

    def list(
        self, root_id: UUID, relative: tuple[str, ...] = (), *, covering: tuple[str, ...] | None = None
    ) -> DirectoryListing:
        """Read one folder, and what the checksum records that cover its files say about them.

        :param root_id: the root.
        :param relative: the folder's path under the root, one name per step; empty for the root's own folder.
        :param covering: the directory-scoped record above this folder whose ``info.checksum`` covers it -- its
            ``info.rehu`` or ``info.tc``, as a path under the root -- when the caller knows one: the caller has the
            listings above this folder, which this read does not repeat. ``None`` when no folder above is a resource.
        :returns: the classified listing, unsorted. An unknown root, or a folder that cannot be read, comes back
            empty and **not reachable**, never raising (#245): "the folder is gone" and "the folder is empty" are
            different answers.
        """
        root = self.__paths.get(root_id)
        if root is None:
            return DirectoryListing(Path(), reachable=False)
        holding: AbstractContextManager[None] = (
            nullcontext() if self.__coordinator is None else self.__coordinator.holding()
        )
        with holding:
            listing = self.__classifier.classify(root.joinpath(*relative))
            if not listing.reachable:
                return listing
            covered = self.__cover(root, relative, listing, covering)
            return replace(listing, covered=covered) if covered else listing

    def __cover(
        self, root: Path, relative: tuple[str, ...], listing: DirectoryListing, covering: tuple[str, ...] | None
    ) -> dict[str, CoveredFile]:
        """What each record that covers a file of this folder says about it.

        The records are a file-scoped ``foo.rehu`` with its ``foo.checksum`` here, an ``info.rehu`` with its
        ``info.checksum`` here, or -- when this folder holds no record of its own -- the one ``covering`` names above
        it. Which listed files each covers is the record's own classifier's answer, so the rule is the content walk's.

        :param root: the root's folder.
        :param relative: the listed folder's path under the root.
        :param listing: the folder, classified as a stranger sees it.
        :param covering: the directory-scoped record above, as a path under the root, if the caller knows one.
        :returns: the covered files by name; empty when no record covers anything here.
        """
        directory = listing.directory
        files = {entry.name.lower(): entry.name for entry in listing.entries if not entry.is_directory}
        claims: list[tuple[Path, str]] = []
        for name in files.values():
            if is_record_name(name) and not is_directory_scoped_name(name):
                stem = os.path.splitext(name)[0]
                if f"{stem}.checksum".lower() in files:
                    claims.append((directory / name, ""))
        own = next((name for name in files.values() if is_directory_scoped_name(name)), None)
        if own is not None:
            if "info.checksum" in files:
                claims.append((directory / own, ""))
        elif covering is not None:
            prefix = "/".join(relative[len(covering) - 1 :])
            claims.append((root.joinpath(*covering), f"{prefix}/" if prefix else ""))
        covered: dict[str, CoveredFile] = {}
        for record_path, prefix in claims:
            covered.update(self.__read_claim(record_path, prefix, listing))
        return covered

    def __read_claim(self, record_path: Path, prefix: str, listing: DirectoryListing) -> dict[str, CoveredFile]:
        """Read one record, and say what it holds for the content files of this listing.

        :param record_path: the covering resource's ``.rehu`` (its name sets the scope).
        :param prefix: where this folder is under the record's own, as ``sub/`` or ``""``.
        :param listing: the folder, classified as a stranger sees it.
        :returns: the content files it covers; empty for a record that is unreadable or that does not parse, as the
            Files dock reads one.
        """
        try:
            record = load_checksum_record(checksum_record_path(record_path))
        except OSError, ChecksumRecordError:
            return {}
        raw_entries: dict[str, Any] = {}
        for raw in record["files"]:
            name = checksum_entry_name(raw)
            if name is not None:
                raw_entries[name] = raw
        trusted = TRUST_NOT_TRACKED if self.__trust is None else self.__trust.trusted_since(record_path)
        named = DirectoryClassifier(record_path, self.__excluded_patterns).reclassify(listing)
        covered: dict[str, CoveredFile] = {}
        for entry in named.entries:
            if entry.kind is not FileKind.CONTENT:
                continue
            raw = raw_entries.get(f"{prefix}{entry.name}")
            if raw is None:
                covered[entry.name] = CoveredFile(None, trusted)
                continue
            parsed = parse_checksum_entry(raw)
            covered[entry.name] = CoveredFile(parsed, trusted, malformed=parsed is None)
        return covered
