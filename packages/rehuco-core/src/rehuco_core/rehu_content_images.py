"""Content-image enumeration for reference-images resources ([[data-model#resource-scoping]]).

A reference-images resource's *content* -- as opposed to its screenshots (`rehuco_core.rehu_screenshots`)
-- lives entirely inside archive(s): the single ``.zip``/``.cbz`` a file-scoped ``.rehu`` describes, or
every one found recursively under a directory-scoped ``info.rehu``'s directory. This lists each archive's
image entries from its central directory (:meth:`zipfile.ZipFile.infolist`) without extracting or decoding
a single one, so scanning a many-thousand-image archive stays cheap. Core-side and GUI-free, like its
screenshot counterparts.
"""

import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from .constants import ARCHIVE_EXTENSIONS, CONTENT_IMAGE_EXTENSIONS
from .resource_scoping import is_directory_scoped, is_directory_scoped_name, is_record_name


@dataclass(frozen=True)
class ContentImageEntry:
    """One content image found inside a reference-images resource's archive(s)
    ([[data-model#image-meanings]]).

    :ivar archive: the archive file this entry lives in.
    :ivar name: the entry's path within the archive, exactly as stored (``/``-separated per the zip
        format, regardless of platform).
    """

    archive: Path
    name: str


class ContentImageScanner:  # pylint: disable=too-few-public-methods
    """Enumerates one reference-images resource's content images ([[data-model#resource-scoping]]).

    File-scoped (a named ``foo.rehu``/``foo.tc``): only the sibling archive sharing its stem, ``.zip``
    or ``.cbz`` -- a whitelist of one, never a directory walk. Directory-scoped
    (``info.rehu``/``info.tc``): the sum over every archive found recursively under ``rehu_path``'s
    directory that no other record covers (#254): a subdirectory carrying its own ``info.rehu``/``info.tc``
    is that record's, wholesale, and an archive sitting beside a file-scoped ``foo.rehu`` of its own stem
    is that one's. **A record counts only what it covers**, here for the same reason as in the size scan
    and the checksums -- a count summed over a library has to be the sum of what each record already
    knows, and the overlap this replaced counted a nested pack once for itself and again for every
    ancestor above it.

    Which of the two it is comes from :func:`~rehuco_core.resource_scoping.is_directory_scoped`, the one
    place the rule is stated (#250), so an unconverted ``info.tc`` counts the archives its directory holds
    rather than looking for an ``info.zip`` that was never there.

    :param rehu_path: the resource's ``.rehu`` file.
    :param extensions: the recognized image extensions, matched case-insensitively.
    """

    __MACOSX_DIRNAME: Final = "__MACOSX"

    def __init__(self, rehu_path: Path, extensions: tuple[str, ...]) -> None:
        self.__rehu_path: Final = rehu_path
        self.__extensions: Final = extensions

    def scan(self) -> list[ContentImageEntry]:
        """Enumerate :attr:`rehu_path`'s content images.

        :returns: one :class:`ContentImageEntry` per recognized entry; see :func:`enumerate_content_images`
            for the full order/failure-handling contract.
        """
        directory = self.__rehu_path.parent
        if is_directory_scoped(self.__rehu_path):
            archives = self.__find_archives_under(directory)
        else:
            archives = self.__find_sibling_archives(directory, self.__rehu_path.stem)
        entries = []
        for archive in archives:
            entries.extend(self.__list_archive_images(archive))
        return entries

    def __find_sibling_archives(self, directory: Path, stem: str) -> list[Path]:
        """List ``directory``'s archive siblings sharing ``stem``, case-insensitively.

        :param directory: the file-scoped resource's directory.
        :param stem: the ``.rehu`` file's stem, e.g. ``"foo"`` for ``foo.rehu``.
        :returns: the matching absolute paths, sorted, or empty when ``directory`` is missing/unreadable
            (e.g. an offline mount, [[mounts-and-storage#offline-mounts]]).
        """
        # same offline-mount-tolerant listing as rehu_screenshots.scan_rehu_screenshot_files -- too small
        # a shape (list-or-empty-on-OSError) to be worth a shared helper across two unrelated scanners
        # pylint: disable=duplicate-code
        try:
            siblings = list(directory.iterdir())
        except OSError:
            return []
        matches = [
            sibling
            for sibling in siblings
            if sibling.stem.lower() == stem.lower() and sibling.suffix.lower() in ARCHIVE_EXTENSIONS
        ]
        # pylint: enable=duplicate-code
        return sorted(matches, key=lambda sibling: sibling.name)

    def __find_archives_under(self, directory: Path) -> list[Path]:
        """List the archives under ``directory`` that no other record covers (#254).

        The records are read off the same flattened listing the archives come from, so the coverage
        rule costs no second walk: a directory holding an ``info.rehu``/``info.tc`` takes its whole
        subtree out, and a file-scoped ``foo.rehu`` takes the same-stem archive beside it. What the
        rule is comes from :mod:`rehuco_core.resource_scoping`, the one place it is stated, so this
        walk and `rehuco_core.rehu_content_files`'s cannot answer it differently.

        :param directory: the directory-scoped resource's directory.
        :returns: the matching absolute paths, sorted, or empty when ``directory`` is missing/unreadable.
        """
        try:
            candidates = list(directory.rglob("*"))
        except OSError:
            return []
        covered = {candidate.parent for candidate in candidates if is_directory_scoped_name(candidate.name)}
        covered.discard(directory)
        claimed = {
            (candidate.parent, candidate.stem.lower())
            for candidate in candidates
            if is_record_name(candidate.name) and not is_directory_scoped_name(candidate.name)
        }
        matches = [
            candidate
            for candidate in candidates
            if candidate.suffix.lower() in ARCHIVE_EXTENSIONS
            and (candidate.parent, candidate.stem.lower()) not in claimed
            and not covered.intersection(candidate.parents)
        ]
        return sorted(matches, key=str)

    def __list_archive_images(self, archive: Path) -> list[ContentImageEntry]:
        """List one archive's recognized image entries, in central-directory order.

        :param archive: the archive file to read.
        :returns: one :class:`ContentImageEntry` per recognized entry, or empty when ``archive`` is
            absent, not a zip, truncated, or otherwise unreadable -- reported as empty rather than raised.
        """
        try:
            with zipfile.ZipFile(archive) as opened:
                infolist = opened.infolist()
        except OSError, zipfile.BadZipFile:
            return []
        return [ContentImageEntry(archive, info.filename) for info in infolist if self.__is_content_image(info)]

    def __is_content_image(self, info: zipfile.ZipInfo) -> bool:
        """Whether one zip entry is a recognized content image, per [[data-model#image-meanings]]'s notes.

        Excludes directory entries, dot-files, and anything under a ``__MACOSX/`` directory (macOS's
        AppleDouble metadata sidecar) before checking the extension.

        :param info: the entry to classify.
        :returns: whether ``info`` counts as a content image.
        """
        if info.is_dir():
            return False
        entry_path = PurePosixPath(info.filename)
        if entry_path.name.startswith("."):
            return False
        if self.__MACOSX_DIRNAME in entry_path.parts[:-1]:
            return False
        return entry_path.suffix.lower() in self.__extensions


def enumerate_content_images(
    rehu_path: Path, extensions: tuple[str, ...] = CONTENT_IMAGE_EXTENSIONS
) -> list[ContentImageEntry]:
    """Enumerate ``rehu_path``'s content images: everything its archive(s) hold, never anything loose.

    :param rehu_path: the resource's ``.rehu`` file.
    :param extensions: the recognized image extensions, matched case-insensitively -- injected rather than
        read from a setting (:data:`~rehuco_core.constants.CONTENT_IMAGE_EXTENSIONS` by default), so the
        caller decides, the same inversion `rehuco_agent.fields.image_scanner.ImageScanner` applies.
    :returns: one :class:`ContentImageEntry` per recognized entry, in a stable order (archives sorted by
        path, entries within an archive in central-directory order). An absent, unreadable, or corrupt
        archive contributes no entries rather than raising -- a document-level condition, not a crash.
    """
    return ContentImageScanner(rehu_path, extensions).scan()
