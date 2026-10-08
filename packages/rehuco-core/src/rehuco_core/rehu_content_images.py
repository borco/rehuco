"""Content-image enumeration for reference-images resources ([[data-model#resource-scoping]]).

A reference-images resource's *content images* -- as opposed to its screenshots
(`rehuco_core.rehu_screenshots`) -- are every recognized image among its content files (#392): the members
of each ``.zip``/``.cbz`` archive it covers, and every image lying loose in its folders. Which files those
are is :mod:`rehuco_core.rehu_content_files`' answer, the one the checksums and the size scan read, so a
pack never shows an image its checksum does not cover or the other way round. Each archive's members are
listed from its central directory (:meth:`zipfile.ZipFile.infolist`) without extracting or decoding a
single one, so scanning a many-thousand-image archive stays cheap; a loose image costs one ``stat``.
Core-side and GUI-free, like its screenshot counterparts.
"""

import zipfile
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import ClassVar, Final

from borco_core import shared_read_open

from .constants import ARCHIVE_EXTENSIONS, CONTENT_IMAGE_EXTENSIONS, EXCLUDED_FILE_PATTERNS
from .natural_sort import NaturalRun, natural_path_sort_key, natural_sort_key
from .rehu_content_files import enumerate_content_files
from .rename_coordination import RenameCoordinator


@dataclass(frozen=True)
class ContentImageEntry:
    """One content image of a reference-images resource: an archive member, or a loose file (#392)
    ([[data-model#image-meanings]]).

    Carries the image's **tier-0 identity** ([[reference-images#image-identity]]) without reading a byte
    of it: an archive member's uncompressed size and the CRC32 its zip's central directory already
    records; a loose file's size and modification time, the weaker key a folder affords. So a consumer
    can key per-image facts (dimensions, thumbnails) cheaply, and a re-exported image at the same address
    reads as a different one.

    :ivar archive: the archive file this member lives in, or ``None`` for a loose image.
    :ivar name: a member's path within its archive, exactly as stored; a loose image's path relative to
        the ``.rehu``'s directory. ``/``-separated either way, regardless of platform.
    :ivar size: the uncompressed size in bytes.
    :ivar crc: a member's CRC32 as the central directory records it; ``0`` for a loose image.
    :ivar file: a loose image's own path, or ``None`` for an archive member.
    :ivar mtime: a loose image's modification time in nanoseconds; ``0`` for an archive member.
    """

    archive: Path | None
    name: str
    size: int
    crc: int = 0
    file: Path | None = None
    mtime: int = 0

    ZIP_KIND: ClassVar[str] = "zip"
    """The container kind tagging :attr:`key` -- a zip's CRC32 is compared only with another zip's."""

    FILE_KIND: ClassVar[str] = "file"
    """The kind tagging a loose image's :attr:`key`, whose fingerprint is its modification time."""

    @property
    def key(self) -> tuple[str, str, int, int]:
        """The tier-0 key ``(kind, name, size, fingerprint)`` ([[reference-images#image-identity]]).

        A member's fingerprint is its CRC32, never its mtime: a zip stores that at two-second granularity
        and a re-pack resets it. A loose file has no recorded checksum, so its mtime is all there is.
        """
        if self.archive is None:
            return self.FILE_KIND, self.name, self.size, self.mtime
        return self.ZIP_KIND, self.name, self.size, self.crc


MACOSX_DIRNAME: Final = "__MACOSX"
"""The folder macOS's AppleDouble metadata sidecars are zipped into; nothing under it is content."""


def is_content_image(path: PurePosixPath, extensions: tuple[str, ...]) -> bool:
    """Whether an archive member's path, or a loose file's relative one, is a recognized content image, per
    [[data-model#image-meanings]]'s notes.

    Excludes dot-files and anything under a ``__MACOSX`` directory (macOS's AppleDouble metadata sidecar) before
    checking the extension -- the same filter inside an archive and out of one.

    :param path: the path to classify.
    :param extensions: the recognized image extensions, lower-case.
    :returns: whether it counts as a content image.
    """
    if path.name.startswith("."):
        return False
    if MACOSX_DIRNAME in path.parts[:-1]:
        return False
    return path.suffix.lower() in extensions


def image_order(entry: ContentImageEntry) -> tuple[tuple[tuple[NaturalRun, ...], ...], tuple[NaturalRun, ...]]:
    """An image's place inside its group: by its folder, then by its name, both natural.

    Ordering by folder first is what puts an archive's root images before its folders' and a folder's own images
    before its subfolders', rather than interleaving them by name the way a plain path order would (``a.jpg``,
    ``bar/x.jpg``, ``z.jpg``), which would split the root's images around a folder.

    :param entry: the image.
    :returns: its folder's :func:`~rehuco_core.natural_sort.natural_path_sort_key` (the root's sorting first), then
        its name's :func:`~rehuco_core.natural_sort.natural_sort_key`.
    """
    path = PurePosixPath(entry.name)
    folder = path.parent.as_posix()
    return natural_path_sort_key("" if folder == "." else folder), natural_sort_key(path.name)


def list_archive_images(
    archive: Path, extensions: tuple[str, ...], coordinator: RenameCoordinator | None = None
) -> list[ContentImageEntry]:
    """List one archive's recognized image members, in pack order.

    Sorted by :func:`image_order`, never in the central directory's order ([[reference-images#image-identity]]),
    which is whatever the packer wrote and is not a promise, while a reference pack's folders and names are how its
    author ordered it. Read from the central directory alone, inside the coordinator's hold when one is given, so a
    rename waits for one directory read and no member is inflated.

    :param archive: the archive file to read.
    :param extensions: the recognized image extensions, matched case-insensitively.
    :param coordinator: the rename barrier to read inside, or ``None`` for none.
    :returns: one :class:`ContentImageEntry` per recognized member, or empty when ``archive`` is absent, not a zip,
        truncated, or otherwise unreadable -- reported as empty rather than raised.
    """
    wanted = tuple(extension.lower() for extension in extensions)
    hold = coordinator.holding() if coordinator is not None else nullcontext()
    try:
        with hold, shared_read_open(archive) as file, zipfile.ZipFile(file) as opened:
            infolist = opened.infolist()
    except OSError, zipfile.BadZipFile:
        return []
    entries = [
        ContentImageEntry(archive, info.filename, info.file_size, info.CRC)
        for info in infolist
        if not info.is_dir() and is_content_image(PurePosixPath(info.filename), wanted)
    ]
    return sorted(entries, key=image_order)


class ContentImageScanner:  # pylint: disable=too-few-public-methods
    """Enumerates one reference-images resource's content images ([[data-model#resource-scoping]]).

    **Which files are the resource's is asked, not decided here** (#392). The content walk
    (:func:`~rehuco_core.rehu_content_files.enumerate_content_files`) already states what a record covers:
    a file-scoped ``foo.rehu`` owns its ``foo.*`` siblings, a directory-scoped ``info.rehu`` everything under
    its directory that no other record covers (#254), and no record owns its ``<record>NN`` screenshots
    as content. The images are the archives and the loose images among those files. A second walk with
    its own claims would be one the checksums could disagree with.

    **A folder's own images first, then what it holds** -- at every level, on disk and inside an archive.
    Every archive is a group, and so is every folder holding loose images -- the root's group is the
    ``.rehu``'s own directory. The groups come in natural order of their paths relative to the ``.rehu``'s
    directory, case-insensitively, folders and archives together, so the root comes first: ``/``,
    ``Bar.zip``, ``foo``, ``xxx/xyz.zip``. Inside an archive, its root's images come before its folders',
    each folder's before its subfolders', folders in natural order and images in natural order of their
    names -- so each folder's images are contiguous, and a banner per folder appears once (#392).

    Each archive is read inside its own :meth:`~rehuco_core.RenameCoordinator.holding` when a coordinator
    is given (#347), through :func:`~borco_core.shared_read_open`: one hold per archive rather than one
    for the walk, so a rename arriving mid-scan waits for one central-directory read, not for a whole
    library over a NAS. A loose image's ``stat`` takes a hold of its own the same way. An archive or a
    file the rename moved before its turn reads as empty -- the caller that renamed re-enumerates anyway.

    :param rehu_path: the resource's ``.rehu`` file.
    :param extensions: the recognized image extensions, matched case-insensitively.
    :param coordinator: the rename barrier to read inside, or ``None`` for none.
    :param excluded_patterns: the junk globs the content walk leaves out (#226), the caller's -- the same
        set the checksums are handed, so an image a user's glob excludes is shown by neither.
    """

    def __init__(
        self,
        rehu_path: Path,
        extensions: tuple[str, ...],
        coordinator: RenameCoordinator | None = None,
        excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
    ) -> None:
        self.__rehu_path: Final = rehu_path
        self.__extensions: Final = tuple(extension.lower() for extension in extensions)
        self.__coordinator: Final = coordinator
        self.__excluded_patterns: Final = excluded_patterns

    def scan(self) -> list[ContentImageEntry]:
        """Enumerate :attr:`rehu_path`'s content images.

        :returns: one :class:`ContentImageEntry` per recognized image; see :func:`enumerate_content_images`
            for the full order/failure-handling contract.
        """
        directory = self.__rehu_path.parent
        groups: dict[str, list[ContentImageEntry]] = {}
        for path in enumerate_content_files(self.__rehu_path, self.__excluded_patterns).files:
            relative = PurePosixPath(path.relative_to(directory).as_posix())
            if path.suffix.lower() in ARCHIVE_EXTENSIONS:
                groups[relative.as_posix()] = list_archive_images(path, self.__extensions, self.__coordinator)
            elif is_content_image(relative, self.__extensions):
                loose = self.__loose_image(path, relative)
                if loose is not None:
                    folder = relative.parent.as_posix()
                    groups.setdefault("" if folder == "." else folder, []).append(loose)
        entries: list[ContentImageEntry] = []
        for group in sorted(groups, key=self.__group_order):
            entries.extend(sorted(groups[group], key=image_order))
        return entries

    @staticmethod
    def __group_order(group: str) -> tuple[tuple[NaturalRun, ...], ...]:
        """A group's place among the others: natural and case-insensitive, component by component, so
        ``pack2.zip`` precedes ``pack10.zip``, ``Bar.zip`` precedes ``foo``, and the root (``""``) comes
        first.

        :param group: the group's path relative to the ``.rehu``'s directory -- an archive's own, or the
            folder its loose images sit in.
        :returns: its :func:`~rehuco_core.natural_sort.natural_path_sort_key`.
        """
        return natural_path_sort_key(group)

    def __loose_image(self, path: Path, relative: PurePosixPath) -> ContentImageEntry | None:
        """One loose image, keyed by its ``stat`` ([[reference-images#image-identity]]).

        :param path: the image file.
        :param relative: its path relative to the ``.rehu``'s directory.
        :returns: the entry, or ``None`` when the file cannot be measured -- deleted since the walk, or on
            a share that went away -- reported as absent rather than raised.
        """
        try:
            with self.__holding():
                stat = path.stat()
        except OSError:
            return None
        return ContentImageEntry(None, relative.as_posix(), stat.st_size, file=path, mtime=stat.st_mtime_ns)

    def __holding(self) -> AbstractContextManager[None]:
        """The coordinator's hold, or nothing to hold when there is no coordinator."""
        return self.__coordinator.holding() if self.__coordinator is not None else nullcontext()


def enumerate_content_images(
    rehu_path: Path,
    extensions: tuple[str, ...] = CONTENT_IMAGE_EXTENSIONS,
    coordinator: RenameCoordinator | None = None,
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS,
) -> list[ContentImageEntry]:
    """Enumerate ``rehu_path``'s content images: every archive member and every loose image among its
    content files (#392).

    :param rehu_path: the resource's ``.rehu`` file.
    :param extensions: the recognized image extensions, matched case-insensitively -- injected rather than
        read from a setting (:data:`~rehuco_core.constants.CONTENT_IMAGE_EXTENSIONS` by default), so the
        caller decides, the same inversion `rehuco_agent.fields.image_scanner.ImageScanner` applies.
    :param coordinator: the rename barrier each archive and loose image is read inside (#347), or ``None``
        for none.
    :param excluded_patterns: the junk globs the content walk leaves out (#226), injected like
        ``extensions`` and from the same settings the checksums read, so the two never disagree about a
        file.
    :returns: one :class:`ContentImageEntry` per recognized image, in a stable order: groups -- each archive,
        and each folder holding loose images -- in natural, case-insensitive order of their paths relative
        to the ``.rehu``'s directory (the root folder first), and inside an archive each folder's images
        before its subfolders', in natural order (:func:`~rehuco_core.natural_sort.natural_path_sort_key`)
        -- never an archive's central-directory order, which is whatever the packer wrote. An absent,
        unreadable, or corrupt archive, an unreadable folder, and a file that cannot be measured all
        contribute nothing rather than raising -- a document-level condition, not a crash.
    """
    return ContentImageScanner(rehu_path, extensions, coordinator, excluded_patterns).scan()
