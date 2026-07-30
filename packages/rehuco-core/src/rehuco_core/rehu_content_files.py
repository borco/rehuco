"""Which files on disk make up a resource's content ([[data-model#resource-scoping]], #226).

Two features must agree on this and cannot be allowed to disagree: the size-on-disk scan and checksum
generate/verify. A file summed by one and skipped by the other is a bug waiting to happen -- a verify
reporting an *unexpected new file* the size the user was shown already counted -- so the answer is
computed once, here, and both read it.

The counterpart of `rehuco_core.rehu_content_images`, one level out: that module lists the images
*inside* a reference-images resource's archives, this one lists the files the resource *is*. Core-side
and GUI-free; the caller supplies the excluded-name patterns rather than this module reading a setting.
"""

import fnmatch
import os
import re
from pathlib import Path
from typing import Final

from .constants import (
    CHECKSUM_MANIFEST_EXTENSIONS,
    EXCLUDED_FILE_PATTERNS,
    IMAGE_EXTENSIONS,
    INFO_REHU_FILENAME,
    REHU_SUFFIX,
)


class ContentFileScanner:  # pylint: disable=too-few-public-methods
    """Enumerates one resource's content files ([[data-model#resource-scoping]]).

    File-scoped (``rehu_path.name != "info.rehu"``): the same-stem siblings and nothing else -- a
    whitelist named by the ``.rehu`` itself, never a directory walk. An unrelated ``info.rehu``,
    ``bar00.jpg`` or ``bar.zip`` in the same directory belongs to another resource or to none, and is out
    of scope *before* any exclusion is consulted; no pattern can reach it, and emptying the pattern list
    cannot change it.

    Directory-scoped (``info.rehu``): everything under the directory, recursively, minus two tiers of
    exclusion.

    **Structural** -- every ``.rehu`` the walk finds, at any depth, together with the files that belong to
    it: its ``<record>NN`` screenshots and its ``<record>.sfv``/``.md5``/``.sha256`` manifest. Not just
    the scanning resource's own: a nested ``bar/info.rehu`` and a file-scoped ``baz.rehu`` sitting in the
    tree bring their own bookkeeping. [[data-model#checksums]] and [[data-model#image-meanings]] define
    *every* record and its screenshots as editable at any moment, so a measurement that counted them
    would need recomputing each time anyone edited a description or added a screenshot -- and a checksum
    that covered them would report a mismatch for the same. Excluding them is what makes a size and a
    manifest stay valid until the *content* actually changes. The nested resource's real content still
    counts (``baz.zip``, ``bar/video.mp4``): a nested record is not a boundary
    ([[data-model#resource-scoping]]), only its bookkeeping is skipped.

    **A record claims only its own directory.** Screenshots and manifests are a record's siblings by
    definition ([[data-model#resource-scoping]]), so ``baz00.jpg`` is bookkeeping where ``baz.rehu`` sits
    beside it and ordinary content anywhere else -- a root ``info.rehu`` does not reach down and claim a
    ``bar/info00.jpg`` that has no ``bar/info.rehu`` of its own.

    **And the record has to exist.** A name is bookkeeping *because a record claims it*, never because of
    its shape: with no ``xxx.rehu`` beside it, ``xxx00.jpg`` is a normal file, and so is a ``yyy.sfv``
    with no ``yyy.rehu``. Excluding on shape alone would drop a tutorial's own ``lesson01.jpg``, and a
    pack shipping its own checksum file, from the very measurement meant to cover them.

    A screenshot is further ``<record>NN`` plus an
    :data:`~rehuco_core.constants.IMAGE_EXTENSIONS` suffix -- the same predicate
    `rehuco_core.rehu_screenshots` matches -- rather than ``<record>NN.*``, so a tutorial's ``info01.mp4``
    stays content instead of vanishing from the measurement and the manifest alike.

    The structural tier is applied whatever ``excluded_patterns`` says, and is not the user's to remove.
    **Junk** -- ``excluded_patterns`` -- is the caller's, and is the tier a user gets to change.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: filename globs to leave out of the directory-scoped walk, matched
        case-insensitively against the file name.
    """

    __SCREENSHOT_NAME_PATTERN: Final = re.compile(r"^(?P<record>.*)\d{2}$")
    """Splits a candidate screenshot's stem into the record it would belong to and its two-digit index --
    the same ``<record>NN`` shape `rehuco_core.rehu_screenshots` matches, read backwards because the
    record is what has to be looked up. Greedy, so ``info0000`` decomposes to ``info00`` + ``00`` and
    matches only a record actually named ``info00``."""

    def __init__(self, rehu_path: Path, excluded_patterns: tuple[str, ...]) -> None:
        self.__rehu_path: Final = rehu_path
        self.__excluded_patterns: Final = tuple(pattern.lower() for pattern in excluded_patterns)
        self.__slug: Final = rehu_path.stem.lower()

    def scan(self) -> list[Path]:
        """Enumerate :attr:`rehu_path`'s content files.

        :returns: the content file paths; see :func:`enumerate_content_files` for the full order and
            failure-handling contract.
        """
        directory = self.__rehu_path.parent
        if self.__rehu_path.name == INFO_REHU_FILENAME:
            return self.__scan_directory(directory)
        return self.__scan_siblings(directory)

    def __scan_siblings(self, directory: Path) -> list[Path]:
        """List the same-stem siblings a file-scoped resource describes.

        :param directory: the resource's directory.
        :returns: the matching paths sorted by name, or empty when ``directory`` is missing/unreadable
            (e.g. an offline mount, [[mounts-and-storage#offline-mounts]]).
        """
        filenames = self.__read_directory(directory, [])
        records = self.__record_names(filenames) | {self.__slug}
        matches = sorted(
            filename
            for filename in filenames
            if os.path.splitext(filename)[0].lower() == self.__slug and not self.__is_bookkeeping(filename, records)
        )
        return [directory / filename for filename in matches]

    def __scan_directory(self, directory: Path) -> list[Path]:
        """List everything under a directory-scoped resource's directory that both tiers let through.

        One directory at a time, descending: read a directory, take the records *it* holds, keep the
        files none of them claims, then do the same for each subdirectory. Deliberately not a flattened
        ``rglob`` with the records pooled afterwards -- a record's screenshots and manifest are its
        siblings, so the only records that can speak for a file are the ones in its own directory, and a
        pooled set would get that wrong (the root's ``info.rehu`` claiming a ``bar/info00.jpg`` that has
        no record of its own). Reading per directory makes the sibling rule structural rather than a
        filter that has to remember to compare parents, and holds one directory's names at a time
        instead of the whole tree.

        A subdirectory that cannot be read is skipped rather than fatal: an offline branch of a mount
        ([[mounts-and-storage#offline-mounts]]) costs its own contents, not the whole measurement.

        :param directory: the resource's directory.
        :returns: the matching paths sorted by path, or empty when ``directory`` is missing/unreadable.
        """
        matches: list[Path] = []
        pending = [directory]
        while pending:
            current = pending.pop()
            filenames = self.__read_directory(current, pending)
            records = self.__record_names(filenames)
            if current == self.__rehu_path.parent:
                records.add(self.__slug)
            matches.extend(
                current / filename
                for filename in filenames
                if not self.__is_bookkeeping(filename, records) and not self.__is_excluded(filename)
            )
        return sorted(matches, key=str)

    @staticmethod
    def __read_directory(directory: Path, pending: list[Path]) -> list[str]:
        """Read one directory, appending its subdirectories to ``pending`` for later.

        :func:`os.scandir` rather than :meth:`~pathlib.Path.iterdir`: it answers ``is_dir``/``is_file``
        from what reading the directory already returned, where ``iterdir`` would cost a ``stat`` per
        entry to classify -- thousands of round trips on an SMB mount ([[mounts-and-storage#offline-mounts]])
        to learn what the listing knew. Only the filenames are kept, not `Path` objects, since both
        exclusion tiers are filename rules and the survivors are few.

        A symlink to a file counts as that file; a symlink to a directory is skipped entirely rather
        than descended (see the loop-guard comment below), so linked-in trees are never measured.

        :param directory: the directory to read.
        :param pending: the walk's stack of directories still to visit, appended to in place.
        :returns: the directory's filenames, or empty when it cannot be read -- an unreadable branch
            costs its own contents, not the whole measurement.
        """
        filenames: list[str] = []
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    # never descend through a directory symlink: one pointing at an ancestor would loop
                    # the walk forever, and one into a sibling would count that content twice (the
                    # rglob this walk replaced did not follow them either)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(directory / entry.name)
                    elif entry.is_file():
                        filenames.append(entry.name)
        except OSError:
            return []
        return filenames

    @staticmethod
    def __record_names(filenames: list[str]) -> set[str]:
        """Take the record names out of one directory's listing -- the first of the two passes.

        :param filenames: one directory's filenames.
        :returns: the stems of the ``.rehu`` files among them, lower-cased.
        """
        stems = (os.path.splitext(filename) for filename in filenames)
        return {stem.lower() for stem, suffix in stems if suffix.lower() == REHU_SUFFIX}

    def __is_bookkeeping(self, filename: str, records: set[str]) -> bool:
        """Whether ``filename`` is a resource record or one of the files that belong to one.

        Every ``.rehu`` counts, wherever it sits -- the scanning resource's, a nested one's, a
        file-scoped neighbour's. A screenshot or a manifest counts only where a record of that name sits
        beside it, so the same ``info00.jpg`` is bookkeeping next to an ``info.rehu`` and a normal file
        in a directory that has none.

        :param filename: the candidate's file name.
        :param records: the record names found in that file's own directory, from :meth:`__record_names`.
        :returns: whether it is a record, one of a record's screenshots, or a record's checksum manifest.
        """
        stem, suffix = os.path.splitext(filename)
        suffix = suffix.lower()
        if suffix == REHU_SUFFIX:
            return True
        stem = stem.lower()
        if suffix in CHECKSUM_MANIFEST_EXTENSIONS:
            return stem in records
        if suffix in IMAGE_EXTENSIONS:
            screenshot = self.__SCREENSHOT_NAME_PATTERN.match(stem)
            return screenshot is not None and screenshot["record"] in records
        return False

    def __is_excluded(self, filename: str) -> bool:
        """Whether ``filename`` matches one of the caller's junk globs.

        :func:`fnmatch.fnmatchcase` over both sides lower-cased rather than :func:`fnmatch.fnmatch`,
        whose case-folding follows the *host* platform: SMB and macOS both hand back casings Windows
        never wrote, so ``thumbs.db`` must not survive a Linux node's scan by spelling.

        :param filename: the candidate's file name.
        :returns: whether some pattern matches it.
        """
        lowered = filename.lower()
        return any(fnmatch.fnmatchcase(lowered, pattern) for pattern in self.__excluded_patterns)


def enumerate_content_files(rehu_path: Path, excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS) -> list[Path]:
    """Enumerate ``rehu_path``'s content files: what it is a record *of*, never its own bookkeeping.

    :param rehu_path: the resource's ``.rehu`` file.
    :param excluded_patterns: filename globs to leave out of the directory-scoped walk, matched
        case-insensitively against the file name -- injected rather than read from a setting
        (:data:`~rehuco_core.constants.EXCLUDED_FILE_PATTERNS` by default), so the size scan and the
        checksums are handed the same answer instead of each deciding one. Ignored for a file-scoped
        resource, whose content is a whitelist of one.
    :returns: the content file paths, in a stable order (by name for a file-scoped resource, by full path
        for a directory-scoped one). A missing or unreadable directory contributes nothing rather than
        raising -- a document-level condition, not a crash.
    """
    return ContentFileScanner(rehu_path, excluded_patterns).scan()
