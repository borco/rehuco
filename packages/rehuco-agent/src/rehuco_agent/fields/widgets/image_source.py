"""Where a viewer's pixels come from -- the seam the lightbox and the thumbnail row read through (#221).

A screenshot is a file with a path; a reference pack's content image is a member of an archive and has
none ([[data-model#image-meanings]]). Rather than widen every image widget to know both, they read an
:class:`ImageSource`: a sequence of images that each have a stable key, a name, a description, and can
be decoded -- at full size or downscaled -- from whatever holds them. :class:`PathImageSource` is the
file-backed one; the archive-backed one lives beside the dock that owns the archives
(`rehuco_agent.documents.content_images`). :class:`ScreenshotRowsImageSource` is the screenshots editor's
own (#370): every row of it, each saying whether it is shown, hidden or not yet numbered.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Final, Protocol

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QImageIOHandler, QImageReader


class ImageVisibility(StrEnum):
    """Where one of a resource's screenshots stands in its curation ([[data-model#image-meanings]], #370).

    The value is the word the curating viewer shows for it.
    """

    VISIBLE = "visible"
    """Numbered and shown in the lightbox."""

    HIDDEN = "hidden"
    """Numbered and curated out of the lightbox."""

    UNCONVERTED = "unconverted"
    """Recognized by the name patterns but holding no ``<stem>NN`` slot yet (#270) -- whatever its
    check box last said, since an image with no slot is not curated either way until it has one."""


@dataclass(frozen=True, slots=True)
class ImageDescription:
    """What the lightbox's info overlay says about one image (#221).

    :ivar path_text: where the image is, as a person would name it -- a file's path, or an archive
        member's ``<archive relative to the .rehu>:<member path>``.
    :ivar byte_size: the image's size in bytes as stored, or ``None`` when it cannot be known.
    :ivar visibility: where the image stands in its resource's curation (#370); ``None`` from every
        source but the screenshots editor's, which is the only one that curates.
    """

    path_text: str
    byte_size: int | None
    visibility: ImageVisibility | None = None


class ImageSource(Protocol):
    """A sequence of images a viewer can navigate and decode (#221).

    Every method but :meth:`load` is cheap and GUI-thread; :meth:`load` may run on a worker and must be
    safe to call concurrently for different positions.
    """

    def __len__(self) -> int:  # pyright: ignore[reportReturnType]
        """How many images the source holds."""

    def key(self, index: int) -> Hashable:  # pyright: ignore[reportReturnType]
        """A stable identity for the image at ``index`` -- what survives a re-pointed source, and what
        a thumbnail cache is keyed by. A file's path; an archive member's tier-0 key
        ([[reference-images#image-identity]]).

        :param index: the position.
        :returns: the key.
        """

    def name(self, index: int) -> str:  # pyright: ignore[reportReturnType]
        """The image's short display name -- a window title, a tooltip.

        :param index: the position.
        :returns: the name.
        """

    def describe(self, index: int) -> ImageDescription:  # pyright: ignore[reportReturnType]
        """Where the image is and how big, for the info overlay.

        :param index: the position.
        :returns: the description.
        """

    def pixel_size(self, index: int) -> QSize:  # pyright: ignore[reportReturnType]
        """The image's ``W × H`` read off its header alone -- never a full decode (#321).

        Kept apart from :meth:`describe` on purpose: a header read is an I/O and, for an archive
        member, an inflate under the archive's lock, which the description's callers (a status line
        on every hover, the viewer on every step) must not pay for. Only the thumbnail-hover overlay
        asks, one image at a time, at the pointer's pace.

        :param index: the position.
        :returns: the size, or an invalid one when the header cannot be read.
        """

    def load(self, index: int, max_height: int | None) -> QImage:  # pyright: ignore[reportReturnType]
        """Decode the image at ``index``, at full size or downscaled to ``max_height``.

        :param index: the position.
        :param max_height: the height to scale down to while decoding, or ``None`` for full size; an
            image already shorter is never upscaled.
        :returns: the image, or a null one when it cannot be decoded.
        """


DECODE_OVERSAMPLE: Final = 2
"""How many times the asked-for height a thumbnail is decoded at before the final smooth downscale.
The reader's own scaled decode is cheap but coarse -- JPEG picks a DCT step and finishes with a fast
resample -- so it is asked for roughly twice the target and the last halving is done smoothly here,
which is what keeps edges in a thumbnail from pixelating."""


def decode_image(data: bytes, max_height: int | None) -> QImage:
    """Decode ``data`` with `QImageReader`, downscaled to ``max_height`` when one is asked for.

    Most of the reduction happens in the reader, which is what makes a thumbnail cheap: JPEG's own
    downscaled decode never materializes the full-size pixels. The reader is asked for
    :data:`DECODE_OVERSAMPLE` times the target, and the rest is a smooth scale of that.

    :param data: the encoded image bytes.
    :param max_height: the height to scale down to, or ``None`` for full size.
    :returns: the image, or a null one when the bytes do not decode.
    """
    buffer = reading_buffer(data)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    if max_height is None:
        return reader.read()
    # the cap is on the height *as shown*, while the scaled size is asked for in stored orientation
    # -- the transform is applied after the scale -- so a quarter-turned photo is capped on its stored
    # width and the scaled size handed back transposed
    rotated = bool(reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90)
    shown = reader.size().transposed() if rotated else reader.size()
    coarse_height = min(shown.height(), max_height * DECODE_OVERSAMPLE) if shown.isValid() else 0
    if shown.isValid() and shown.height() > coarse_height:
        coarse = QSize(round(shown.width() * coarse_height / shown.height()), coarse_height)
        reader.setScaledSize(coarse.transposed() if rotated else coarse)
    image = reader.read()
    if image.height() > max_height:
        image = image.scaledToHeight(max_height, Qt.TransformationMode.SmoothTransformation)
    return image


def image_size(data: bytes) -> QSize:
    """The pixel size ``data`` encodes, read off its header alone -- **as it will be shown**.

    :param data: the encoded bytes -- a leading slice is enough for every format whose header comes
        first, which is all of the recognized ones.
    :returns: the size, or an invalid one when the header is not there.
    """
    buffer = reading_buffer(data)
    reader = QImageReader(buffer)
    return reader_image_size(reader)


def image_size_at(path: Path) -> QSize:
    """The pixel size the file at ``path`` encodes, read off its header alone -- **as it will be
    shown**. Cheaper than :func:`image_size` for a file already on disk: `QImageReader` reads only
    the header itself rather than the whole file being read into memory first.

    :param path: the file.
    :returns: the size, or an invalid one when it cannot be read or has no header.
    """
    reader = QImageReader(str(path))
    return reader_image_size(reader)


def reader_image_size(reader: QImageReader) -> QSize:
    """The size ``reader`` reports, swapped for a quarter-turned photo so it matches what
    :func:`decode_image` returns.

    A photo shot with the camera turned is stored landscape with an EXIF orientation tag, and
    `QImageReader.size` reports the stored size while the decode (``autoTransform``) rotates it: a
    portrait would be packed as a landscape and its thumbnail stretched into the cell. The reader's
    own ``transformation`` says whether a quarter turn applies, so the size is swapped to match.

    :param reader: the reader, not yet asked for its size.
    :returns: the size, or an invalid one when the header is not there.
    """
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and reader.transformation() & QImageIOHandler.Transformation.TransformationRotate90:
        return size.transposed()
    return size


def reading_buffer(data: bytes) -> QBuffer:
    """``data`` as an open, readable `QBuffer` that **owns a copy** of the bytes.

    Not ``QBuffer(QByteArray(data))``: that form keeps a bare pointer to the array it was handed, and a
    Python temporary is freed the moment the constructor returns -- a dangling read that corrupts the
    heap under a decode on a worker thread. ``setData`` copies into the buffer's own array instead.

    :param data: the bytes to read.
    :returns: the buffer, open for reading.
    """
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    return buffer


class PathImageSource:
    """An :class:`ImageSource` over image files on disk -- screenshots, a folder's images.

    :param paths: the files, in navigation order.
    :param base: the directory the description names a file relative to -- the ``.rehu``'s, so the
        info overlay reads the same way for a screenshot beside it as for an archive member; a file
        outside it, or any file when there is no base, is named in full.
    """

    def __init__(self, paths: Sequence[Path], base: Path | None = None) -> None:
        self.__paths = list(paths)
        self.__base = base

    def __len__(self) -> int:
        return len(self.__paths)

    def key(self, index: int) -> Path:
        """The file's path."""
        return self.__paths[index]

    def name(self, index: int) -> str:
        """The file's name."""
        return self.__paths[index].name

    def describe(self, index: int) -> ImageDescription:
        """The file's path -- relative to the base when it is under it -- and its size on disk,
        unknown when it cannot be stat'ed."""
        path = self.__paths[index]
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        return ImageDescription(self.__path_text(path), size)

    def pixel_size(self, index: int) -> QSize:
        """The file's pixel size off its header, read straight off disk (#321)."""
        return image_size_at(self.__paths[index])

    def __path_text(self, path: Path) -> str:
        """``path`` as the description names it.

        :param path: the file.
        :returns: the path relative to the base, ``/``-separated like an archive member's; the full
            path when there is no base or the file is not under it.
        """
        if self.__base is None:
            return str(path)
        try:
            return path.relative_to(self.__base).as_posix()
        except ValueError:
            return str(path)

    def load(self, index: int, max_height: int | None) -> QImage:
        """Decode the file; null when it cannot be read or is not an image."""
        try:
            data = self.__paths[index].read_bytes()
        except OSError:
            return QImage()
        return decode_image(data, max_height)


@dataclass(frozen=True, slots=True)
class ScreenshotKey:
    """A screenshot's identity as the file it is, whatever it is named right now (#370).

    A screenshot's name is its position -- moving one renames it and its neighbour, converting one
    renames it into a slot -- so a path is exactly what does **not** identify it across an edit. Two
    things read the key and both need the file: a re-pointed viewer staying on the image it was on
    (`ImageLightbox.set_source`), and a thumbnail cached under it (`thumbnail_cache_key`), which a path
    key would paint under the neighbour's name after a swap. A rename keeps the file's device, inode,
    size and modification time, so those are what compare; the path rides along for whoever needs to
    name the file, and is left out of equality and of the ``repr`` the cache key is built from.

    :ivar path: the file as it is named in this snapshot.
    :ivar identity: what compares -- the file's ``(st_dev, st_ino, st_size, st_mtime_ns)``, or its path
        when it cannot be stat'ed (an offline mount, [[mounts-and-storage#offline-mounts]]), which is
        no worse than the path key every other source has.
    """

    path: Path = field(compare=False, repr=False)
    identity: Hashable

    @classmethod
    def of(cls, path: Path) -> ScreenshotKey:
        """The key of the file at ``path``, read off disk now.

        :param path: the file.
        :returns: its key.
        """
        try:
            stat = path.stat()
        except OSError:
            return cls(path, path)
        return cls(path, (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))


class ScreenshotRowsImageSource:
    """An :class:`ImageSource` over the screenshots editor's rows, every one of them (#370).

    A **snapshot**: the owner builds a fresh one whenever the rows change and re-points its viewer at
    it, so the keys are read once, here, and a viewer comparing the old snapshot's key against the new
    one's is comparing two files rather than two names. Everything but the key and the visibility is
    a `PathImageSource`'s, which this wraps rather than repeats.

    :param rows: every screenshot and where it stands in the curation, in list order.
    :param base: the directory descriptions name a file relative to (see `PathImageSource`).
    """

    def __init__(self, rows: Sequence[tuple[Path, ImageVisibility]], base: Path | None = None) -> None:
        self.__paths: Final = [path for path, _visibility in rows]
        self.__visibilities: Final = [visibility for _path, visibility in rows]
        self.__keys: Final = [ScreenshotKey.of(path) for path in self.__paths]
        self.__files: Final = PathImageSource(self.__paths, base)

    def __len__(self) -> int:
        return len(self.__paths)

    def key(self, index: int) -> ScreenshotKey:
        """The file's identity, which survives a rename (:class:`ScreenshotKey`)."""
        return self.__keys[index]

    def path(self, index: int) -> Path:
        """The file's path as of this snapshot -- what the editor finds its row by.

        :param index: the position.
        :returns: the path.
        """
        return self.__paths[index]

    def name(self, index: int) -> str:
        """The file's name."""
        return self.__files.name(index)

    def describe(self, index: int) -> ImageDescription:
        """What `PathImageSource` says, plus where the image stands in the curation."""
        return replace(self.__files.describe(index), visibility=self.__visibilities[index])

    def pixel_size(self, index: int) -> QSize:
        """The file's pixel size off its header (#321)."""
        return self.__files.pixel_size(index)

    def load(self, index: int, max_height: int | None) -> QImage:
        """Decode the file; null when it cannot be read or is not an image."""
        return self.__files.load(index, max_height)
