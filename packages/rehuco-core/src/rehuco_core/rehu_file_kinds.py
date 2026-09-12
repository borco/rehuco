"""What one directory holds, named from a resource's point of view ([[plugins#files-subdock]], #266).

:mod:`rehuco_core.rehu_content_files` answers *is this content* over a whole resource, recursively, and
answers it as a boolean because that is all a size sum and a checksum baseline need. A file browser
needs the other half of the same rule: **what is this file, to this resource** -- the record itself, one
of its screenshots, its checksum record, a retained conversion backup, another resource's record, one of
*that* record's siblings, or ordinary content. So this module asks
:class:`~rehuco_core.rehu_content_files.ContentFileScanner`'s question one directory at a time and
answers it with a name.

**The rules are that walk's, not a second set.** The record suffixes come from
:mod:`rehuco_core.resource_scoping` (#250), the sibling rule is applied per listing exactly as the walk
applies it -- a record claims only its own directory, and only where the record actually exists -- the
``<record>NN`` shape is :mod:`rehuco_core.rehu_screenshots`', the pattern-matched legacy names are the
caller's (#287, #289), and a ``.orig`` is :func:`~rehuco_core.tc_conversion_backups.is_conversion_backup`'s
call. What is deliberately **not** shared is the recursion: this never descends, because a browser shows
one directory and lets the reader walk.

**Coverage is exclusive here too** (#254). A file a *file-scoped* record in this directory claims is
:data:`FileKind.FOREIGN_SIDECAR`'s neighbour rather than this resource's content -- reported as
:data:`FileKind.FOREIGN_CONTENT`, which is the one kind the boolean walk has no name for: those bytes are
somebody's content, just not this record's, so a surface reporting on *this* record has nothing to say
about them.

**And whether the reader may descend is a property of the listing, not of a row.** A directory holding a
directory-scoped record that is not this resource's own is another resource wholesale, and so are the
subdirectories beside it -- :attr:`DirectoryListing.foreign_directory_record` is what says so, once per
listing, rather than each row guessing.

Core-side and GUI-free: the caller supplies the junk globs and the screenshot patterns, as it does for
the content walk, and gets back names, kinds and the ``stat`` fields a listing already knew.
"""

import fnmatch
import os
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from .constants import (
    ARCHIVE_EXTENSIONS,
    AUDIO_EXTENSIONS,
    CHECKSUM_MANIFEST_EXTENSIONS,
    EXCLUDED_FILE_PATTERNS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)
from .resource_scoping import is_directory_scoped, is_directory_scoped_name, is_record_name
from .tc_conversion_backups import is_conversion_backup
from .tc_screenshots import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern, compiled_screenshot_name_patterns

SCREENSHOT_STEM_PATTERN: Final = re.compile(r"^(?P<record>.*)\d{2}$")
"""Splits a candidate screenshot's stem into the record it would belong to and its two-digit index.

The same ``<record>NN`` shape :mod:`rehuco_core.rehu_screenshots` matches, read backwards because the
record is what has to be looked up -- and the same expression
:class:`~rehuco_core.rehu_content_files.ContentFileScanner` reads it with. Greedy, so ``info0000``
decomposes to ``info00`` + ``00`` and matches only a record actually named ``info00``."""


class FileKind(StrEnum):
    """What one entry of a directory is *to* the resource whose listing this is (#266).

    Roles, not file types: an ``info00.jpg`` and a ``lesson.jpg`` are both images and only one of them
    is bookkeeping, which is the distinction a reader of the folder needs and the one a suffix cannot
    make. :class:`FileType` is the other axis.
    """

    OWN_RECORD = "own_record"
    """This resource's own ``.rehu``/``.tc``. Never content, and never an invitation to open a second
    view of the document already showing it."""

    OWN_SCREENSHOT = "own_screenshot"
    """One of this record's screenshots -- ``<record>NN`` or a pattern-matched legacy name
    ([[data-model#image-meanings]]). App-managed presentation metadata, not content, and not
    checksummed."""

    OWN_MANIFEST = "own_manifest"
    """This record's ``.checksum``, or a legacy manifest suffix an external checker left beside it
    ([[data-model#checksums]])."""

    FOREIGN_RECORD = "foreign_record"
    """Another resource's record sharing this directory -- a nested ``info.rehu``, or a file-scoped
    ``foo.rehu`` beside this one ([[data-model#resource-scoping]]'s tolerated coexistence). A resource
    of its own, so it is somewhere to *go* rather than something to read here."""

    FOREIGN_SIDECAR = "foreign_sidecar"
    """A screenshot or manifest belonging to a foreign record. Bookkeeping, and not this resource's."""

    FOREIGN_CONTENT = "foreign_content"
    """A file a foreign *file-scoped* record covers -- its same-stem sibling (#254). Content, but not
    this record's, which is why it is neither :data:`CONTENT` nor any flavour of bookkeeping."""

    CONVERSION_BACKUP = "conversion_backup"
    """A retained ``.orig`` a conversion left behind (#253). Excluded on its name alone, because a
    backup belongs to the directory it sits in rather than to a stem."""

    EXCLUDED = "excluded"
    """A file the caller's junk globs take out of content -- ``Thumbs.db`` and its kin (#226). Shown,
    because it is genuinely in the folder, and named, because that is the honest reason it is not being
    counted."""

    CONTENT = "content"
    """This resource's own content: what its size measures and its checksums cover."""

    DIRECTORY = "directory"
    """A subdirectory. Whether it may be entered is the *listing*'s answer
    (:attr:`DirectoryListing.foreign_directory_record`), not this row's."""


class FileType(StrEnum):
    """What one entry *is*, by shape rather than by role (#266).

    The axis a glyph is chosen on, where :class:`FileKind` is the axis a row's meaning and its
    interactivity come from. Deliberately coarse: it exists so a reader can pick a video out of a
    listing of two hundred files, not to classify formats.
    """

    DIRECTORY = "directory"
    RECORD = "record"
    MANIFEST = "manifest"
    BACKUP = "backup"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    GENERIC = "generic"


@dataclass(frozen=True, slots=True)
class DirectoryEntry:
    """One row of a directory listing, classified (#266).

    :param name: the entry's file name, as the listing handed it back.
    :param kind: what it is to the resource.
    :param file_type: what it is by shape.
    :param size: its size in bytes, or ``None`` for a directory and for anything that refused to
        ``stat`` -- a listed entry whose metadata is away is still an entry worth showing.
    :param modified: its modification time as a POSIX timestamp, or ``None`` for the same reasons.
    """

    name: str
    kind: FileKind
    file_type: FileType
    size: int | None = None
    modified: float | None = None

    @property
    def is_directory(self) -> bool:
        """Whether this entry is a subdirectory."""
        return self.kind is FileKind.DIRECTORY


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    """One classified directory, and what the listing itself establishes (#266).

    :param directory: the directory that was read.
    :param entries: its entries, unsorted -- a view sorts, and a read that imposed an order would only
        fight it (the same division :class:`~rehuco_agent.documents.checksum_rows.ChecksumRows` keeps).
    :param reachable: whether the directory listed at all. **Empty and away are not the same answer**
        (#245): a browser that drew an empty table over an offline mount
        ([[mounts-and-storage#offline-mounts]]) would say the resource has no files, which is the one
        thing it must not say.
    :param foreign_directory_record: the name of the directory-scoped record found here that is *not*
        this resource's own, or ``None``. Whatever sits in a directory that has one belongs to that
        record wholesale (#254), subdirectories included -- so this is what decides whether the reader
        may descend, asked once per listing.
    """

    directory: Path
    entries: tuple[DirectoryEntry, ...] = ()
    reachable: bool = True
    foreign_directory_record: str | None = None


# one public method is the whole of it -- classify a directory -- and everything else is the rules that
# answer it; a second public entry point would only be a different way to ask the same question
# pylint: disable-next=too-few-public-methods
class DirectoryClassifier:
    """Classifies the entries of **one** directory from ``record_path``'s point of view (#266).

    The naming half of :class:`~rehuco_core.rehu_content_files.ContentFileScanner`'s rules, over one
    listing: see the module docstring for which rules are shared and why the recursion is not. Built
    once per browser and asked per directory, so the caller's screenshot patterns are compiled once
    rather than per listing.

    :param record_path: the asking resource's own record, ``.rehu`` or ``.tc``. Its directory is the
        resource's, which is what makes a record found *here* this resource's own rather than a
        neighbour's.
    :param excluded_patterns: filename globs that take a file out of content, matched
        case-insensitively against the name -- the caller's, the same set the content walk is handed.
    :param screenshot_name_patterns: the naming rules a legacy screenshot is recognized by, the caller's
        for the same reason (#287): what this names a screenshot must be what a conversion would rename.
    """

    def __init__(
        self,
        record_path: Path,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
        screenshot_name_patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS,
    ) -> None:
        self.__record_path: Final = record_path
        self.__excluded_patterns: Final = tuple(pattern.lower() for pattern in excluded_patterns)
        self.__screenshot_name_patterns: Final = compiled_screenshot_name_patterns(screenshot_name_patterns)
        self.__slug: Final = record_path.stem.lower()
        self.__file_scoped: Final = not is_directory_scoped(record_path)
        """Whether this resource's content is a whitelist of one stem rather than a directory
        ([[data-model#resource-scoping]], #250) -- asked through the one predicate every scope-dependent
        answer reads, never by comparing the filename here."""

    def classify(self, directory: Path) -> DirectoryListing:
        """Read ``directory`` and name every entry in it.

        One :func:`os.scandir`, and the ``stat`` fields come from what the listing already returned --
        the same reason the content walk scandirs rather than iterdirs: a per-entry ``stat`` is a
        round trip each on an SMB share ([[packaging-deployment#ts230-as-nas]]).

        :param directory: the directory to read; need not be the resource's own, and need not exist.
        :returns: the classified listing; an unreadable directory comes back empty and **not
            reachable**, never raising (#245).
        """
        try:
            with os.scandir(directory) as scan:
                scanned = [(entry.name, entry.is_dir(follow_symlinks=False), self.__stat(entry)) for entry in scan]
        except OSError:
            return DirectoryListing(directory, reachable=False)

        filenames = [name for name, is_directory, _ in scanned if not is_directory]
        own_directory = directory == self.__record_path.parent
        records = self.__record_names(filenames)
        if own_directory:
            records.add(self.__slug)
        claimed = self.__file_scoped_stems(filenames) - ({self.__slug} if own_directory else set())
        foreign_directory = self.__foreign_directory_record(filenames, own_directory)
        entries = tuple(
            DirectoryEntry(
                name=name,
                kind=FileKind.DIRECTORY
                if is_directory
                else self.__kind(
                    name, records, claimed, own_directory=own_directory, foreign_directory=foreign_directory is not None
                ),
                file_type=FileType.DIRECTORY if is_directory else self.__file_type(name),
                size=None if is_directory else (None if stat is None else stat[0]),
                modified=None if stat is None else stat[1],
            )
            for name, is_directory, stat in scanned
        )
        return DirectoryListing(directory, entries=entries, foreign_directory_record=foreign_directory)

    @staticmethod
    def __stat(entry: os.DirEntry[str]) -> tuple[int, float] | None:
        """One entry's size and modification time, from the listing's own cached ``stat``.

        :param entry: the scanned entry.
        :returns: its ``(size, mtime)``, or ``None`` when it refuses to ``stat`` -- a file deleted
            between the listing and the question, or one on a share that answered the listing and then
            went away. The entry is still shown; only these two cells are blank.
        """
        try:
            status = entry.stat(follow_symlinks=False)
        except OSError:
            return None
        return status.st_size, status.st_mtime

    # a dispatch chain: one return per rule, in the order the rules override one another, which is what
    # the docstring below is about -- collapsing them into fewer exits would only hide the precedence
    # pylint: disable-next=too-many-return-statements
    def __kind(
        self, filename: str, records: set[str], claimed: set[str], *, own_directory: bool, foreign_directory: bool
    ) -> FileKind:
        """Name one file, in the order the rules override one another.

        A backup first, because it is the one thing excluded on its name alone and against no record
        (#253). Then a record -- this resource's own or a neighbour's. Then the sibling rules, which
        need to know *which* record claims the name, since ``foo00.jpg`` is this record's screenshot
        beside ``foo.rehu`` and a foreign one beside ``bar.rehu``. Then coverage (#254), in the three
        shapes that take content out of this record's: a **file-scoped** record's content is its
        same-stem siblings and nothing else, a neighbouring file-scoped record takes its own stem, and a
        directory belonging to a foreign directory-scoped record is that record's wholesale. Then the
        junk globs, and whatever survives is content.

        :param filename: the entry's name.
        :param records: the record stems found in this directory, this resource's own included where
            this *is* its directory.
        :param claimed: the stems *other* file-scoped records here claim.
        :param own_directory: whether this is the resource's own directory.
        :param foreign_directory: whether a foreign directory-scoped record sits in this directory.
        :returns: the kind.
        """
        if is_conversion_backup(filename):
            return FileKind.CONVERSION_BACKUP
        if is_record_name(filename):
            return FileKind.OWN_RECORD if self.__is_own(filename, own_directory) else FileKind.FOREIGN_RECORD
        stem, suffix = os.path.splitext(filename)
        stem, suffix = stem.lower(), suffix.lower()
        sidecar_of = self.__sidecar_owner(stem, suffix, records, own_directory=own_directory)
        if sidecar_of is not None:
            own = own_directory and sidecar_of == self.__slug
            if suffix in CHECKSUM_MANIFEST_EXTENSIONS:
                return FileKind.OWN_MANIFEST if own else FileKind.FOREIGN_SIDECAR
            return FileKind.OWN_SCREENSHOT if own else FileKind.FOREIGN_SIDECAR
        if self.__file_scoped:
            # a whitelist of one stem, which no junk glob reaches and no directory descends into
            return FileKind.CONTENT if own_directory and stem == self.__slug else FileKind.FOREIGN_CONTENT
        if stem in claimed or foreign_directory:
            return FileKind.FOREIGN_CONTENT
        if self.__is_excluded(filename):
            return FileKind.EXCLUDED
        return FileKind.CONTENT

    def __sidecar_owner(self, stem: str, suffix: str, records: set[str], *, own_directory: bool) -> str | None:
        """Which record in this directory claims ``stem`` as a screenshot or a manifest.

        **The record has to exist**, which is the content walk's own rule: a name is bookkeeping because
        a record claims it, never because of its shape, so ``xxx00.jpg`` with no ``xxx.rehu`` beside it
        is an ordinary file and so is a ``yyy.sfv`` with no ``yyy.rehu``.

        A pattern-matched legacy screenshot is the exception the walk also makes (#289): tc4 wrote
        ``01.jpg``/``cover.jpg``/``sample-01.jpg``, none of which carries a record's name, so the
        ``<record>NN`` rule cannot see it and it is a screenshot beside any record, or none. Attributed
        to *this* resource only in its own directory, which is the only place the images dock scans and
        so the only place the offer to convert one is real; deeper down it is still bookkeeping -- the
        walk skips it either way -- but it is nobody's to act on from here.

        :param stem: the entry's lower-cased stem.
        :param suffix: its lower-cased suffix.
        :param records: the record stems found in this directory.
        :param own_directory: whether this is the resource's own directory.
        :returns: the owning record's stem, or ``None`` when nothing here claims the name.
        """
        if suffix in CHECKSUM_MANIFEST_EXTENSIONS:
            return stem if stem in records else None
        if suffix not in IMAGE_EXTENSIONS:
            return None
        if self.__screenshot_name_patterns.recognizes(stem):
            return self.__slug if own_directory else ""
        numbered = SCREENSHOT_STEM_PATTERN.match(stem)
        if numbered is not None and numbered["record"] in records:
            return numbered["record"]
        return None

    def __is_own(self, filename: str, own_directory: bool) -> bool:
        """Whether ``filename`` is this resource's own record.

        **The directory is half the question.** Every directory-scoped resource's record is called
        ``info.rehu`` ([[data-model#resource-scoping]]), so a name comparison alone would call a nested
        resource's record this one's -- and then offer no way to open the resource a reader has just
        browsed into.

        The name is matched exactly, as :mod:`rehuco_core.resource_scoping` matches a record filename: a
        case-folded comparison would make ``Info.rehu`` and ``info.rehu`` two spellings of one resource
        on a share that hands back either.

        :param filename: the entry's name.
        :param own_directory: whether the directory being classified is the resource's own.
        :returns: whether it is the record this classifier speaks for.
        """
        return own_directory and filename == self.__record_path.name

    def __foreign_directory_record(self, filenames: list[str], own_directory: bool) -> str | None:
        """The directory-scoped record here that is not this resource's own, if there is one (#254).

        **A directory-scoped resource covers its own directory, whatever else sits in it.** Asked about
        its own directory, this answers ``None`` without looking: the subdirectories there are its
        content ([[data-model#resource-scoping]]), and nothing beside it can take them -- a file-scoped
        ``foo.rehu`` claims only its same-stem siblings, and a legacy ``info.tc`` a conversion left
        behind *is* this same resource under its old name rather than a neighbour. Comparing filenames
        instead would have an ``info.rehu`` refuse to browse its own folders the moment a conversion
        left its ``info.tc`` beside it.

        Everywhere else the question is simply *is a directory-scoped record here*: a **file-scoped**
        resource sharing a folder with an ``info.rehu`` does not cover that ground, and neither does any
        resource browsing into a subdirectory that holds a record of its own (#254).

        :param filenames: this directory's file names.
        :param own_directory: whether this is the resource's own directory.
        :returns: the covering record's filename, or ``None`` when this resource covers the ground.
        """
        if own_directory and not self.__file_scoped:
            return None
        for filename in filenames:
            if is_directory_scoped_name(filename):
                return filename
        return None

    @staticmethod
    def __record_names(filenames: list[str]) -> set[str]:
        """The record stems among one directory's file names -- who can claim a sidecar here.

        :param filenames: the directory's file names.
        :returns: their stems, lower-cased; ``.rehu`` and legacy ``.tc`` alike (#250).
        """
        return {os.path.splitext(name)[0].lower() for name in filenames if is_record_name(name)}

    @staticmethod
    def __file_scoped_stems(filenames: list[str]) -> set[str]:
        """The *named* record stems among one directory's file names -- who claims same-stem content.

        :param filenames: the directory's file names.
        :returns: the stems of the file-scoped records, lower-cased; a directory-scoped ``info.rehu``
            claims its directory rather than the ``info.*`` siblings sitting in it, so it is not one.
        """
        return {
            os.path.splitext(name)[0].lower()
            for name in filenames
            if is_record_name(name) and not is_directory_scoped_name(name)
        }

    def __is_excluded(self, filename: str) -> bool:
        """Whether ``filename`` matches one of the caller's junk globs.

        :func:`fnmatch.fnmatchcase` over both sides lower-cased rather than :func:`fnmatch.fnmatch`,
        whose case-folding follows the *host* platform -- the content walk's own reasoning: SMB and
        macOS both hand back casings Windows never wrote.

        :param filename: the entry's name.
        :returns: whether some pattern matches it.
        """
        lowered = filename.lower()
        return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in self.__excluded_patterns)

    @staticmethod
    # one return per recognized shape, same as :meth:`__kind` -- a mapping would need the two
    # predicate-answered kinds (a record, a backup) grafted onto it anyway
    # pylint: disable-next=too-many-return-statements
    def __file_type(filename: str) -> FileType:
        """Name one file by shape, for the glyph a listing draws it with.

        A record and a backup are answered by the same predicates :meth:`__kind` uses rather than by a
        suffix, so the two axes cannot disagree about what a ``.rehu`` or an ``.orig`` is.

        :param filename: the entry's name.
        :returns: its type; anything unrecognized is :data:`FileType.GENERIC`, which is a great deal of
            what a catalog holds and not a failure.
        """
        if is_conversion_backup(filename):
            return FileType.BACKUP
        if is_record_name(filename):
            return FileType.RECORD
        suffix = os.path.splitext(filename)[1].lower()
        if suffix in CHECKSUM_MANIFEST_EXTENSIONS:
            return FileType.MANIFEST
        if suffix in IMAGE_EXTENSIONS:
            return FileType.IMAGE
        if suffix in VIDEO_EXTENSIONS:
            return FileType.VIDEO
        if suffix in AUDIO_EXTENSIONS:
            return FileType.AUDIO
        if suffix in ARCHIVE_EXTENSIONS:
            return FileType.ARCHIVE
        return FileType.GENERIC


def classify_directory(
    record_path: Path,
    directory: Path,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    screenshot_name_patterns: tuple[ScreenshotNamePattern, ...] = SCREENSHOT_NAME_PATTERNS,
) -> DirectoryListing:
    """Read one directory and name every entry from ``record_path``'s point of view (#266).

    The one-shot form of :class:`DirectoryClassifier`, for a caller listing a single directory; a
    browser walking several holds the classifier instead, so the screenshot patterns compile once.

    :param record_path: the asking resource's record, ``.rehu`` or ``.tc``.
    :param directory: the directory to read -- the resource's own, or one under it.
    :param excluded_patterns: the caller's junk globs, the same set the content walk is handed.
    :param screenshot_name_patterns: the naming rules a legacy screenshot is recognized by, likewise.
    :returns: the classified listing; unreadable comes back empty and not reachable, never raising.
    """
    return DirectoryClassifier(record_path, excluded_patterns, screenshot_name_patterns).classify(directory)
