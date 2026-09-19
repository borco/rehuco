"""Where a viewer's pixels come from -- the seam the lightbox and the thumbnail row read through (#221).

A screenshot is a file with a path; a reference pack's content image is a member of an archive and has
none ([[data-model#image-meanings]]). Rather than widen every image widget to know both, they read an
:class:`ImageSource`: a sequence of images that each have a stable key, a name, a description, and can
be decoded -- at full size or downscaled -- from whatever holds them. :class:`PathImageSource` is the
file-backed one; the archive-backed one lives beside the dock that owns the archives
(`rehuco_agent.documents.content_images`).
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QBuffer, QIODevice, QSize
from PySide6.QtGui import QImage, QImageReader


@dataclass(frozen=True, slots=True)
class ImageDescription:
    """What the lightbox's info overlay says about one image (#221).

    :ivar path_text: where the image is, as a person would name it -- a file's path, or an archive
        member's ``<archive relative to the .rehu>:<member path>``.
    :ivar byte_size: the image's size in bytes as stored, or ``None`` when it cannot be known.
    """

    path_text: str
    byte_size: int | None


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

    def load(self, index: int, max_height: int | None) -> QImage:  # pyright: ignore[reportReturnType]
        """Decode the image at ``index``, at full size or downscaled to ``max_height``.

        :param index: the position.
        :param max_height: the height to scale down to while decoding, or ``None`` for full size; an
            image already shorter is never upscaled.
        :returns: the image, or a null one when it cannot be decoded.
        """


def decode_image(data: bytes, max_height: int | None) -> QImage:
    """Decode ``data`` with `QImageReader`, downscaled during the decode when a height is asked for.

    Scaling through the reader rather than after it is what makes a thumbnail cheap: JPEG's own
    downscaled decode never materializes the full-size pixels.

    :param data: the encoded image bytes.
    :param max_height: the height to scale down to, or ``None`` for full size.
    :returns: the image, or a null one when the bytes do not decode.
    """
    buffer = reading_buffer(data)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    if max_height is not None:
        size = reader.size()
        if size.isValid() and size.height() > max_height:
            reader.setScaledSize(QSize(round(size.width() * max_height / size.height()), max_height))
    return reader.read()


def image_size(data: bytes) -> QSize:
    """The pixel size ``data`` encodes, read off its header alone.

    :param data: the encoded bytes -- a leading slice is enough for every format whose header comes
        first, which is all of the recognized ones.
    :returns: the size, or an invalid one when the header is not there.
    """
    buffer = reading_buffer(data)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    return reader.size()


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
    """

    def __init__(self, paths: Sequence[Path]) -> None:
        self.__paths = list(paths)

    def __len__(self) -> int:
        return len(self.__paths)

    def key(self, index: int) -> Path:
        """The file's path."""
        return self.__paths[index]

    def name(self, index: int) -> str:
        """The file's name."""
        return self.__paths[index].name

    def describe(self, index: int) -> ImageDescription:
        """The file's path and its size on disk, unknown when it cannot be stat'ed."""
        path = self.__paths[index]
        try:
            size = path.stat().st_size
        except OSError:
            size = None
        return ImageDescription(str(path), size)

    def load(self, index: int, max_height: int | None) -> QImage:
        """Decode the file; null when it cannot be read or is not an image."""
        try:
            data = self.__paths[index].read_bytes()
        except OSError:
            return QImage()
        return decode_image(data, max_height)
