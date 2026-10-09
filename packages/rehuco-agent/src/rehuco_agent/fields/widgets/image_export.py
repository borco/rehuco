"""Taking an image out of the app -- a drag or Ctrl+C from the Content Images grid or a lightbox (#395).

Another app gets two things at once, and takes whichever it understands: the **file** -- a byte-identical copy staged
under a name that says where it came from (:mod:`rehuco_core.staged_images`), which Explorer, Finder, PureRef, GIMP,
Krita and Blender pick up by name -- and the decoded **pixels**, for a target that takes a bitmap only (a browser, a
chat app, Blender's image-editor paste). One :class:`ImageExporter` builds both for a drag and for the clipboard, so
the two can never hand over different things.

The bytes are read on the GUI thread when the drag starts or the copy is asked for: one image, read through the same
source the viewer decodes from -- an archive member through its `ArchiveCache`, whose handle discipline (#347) holds.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Final

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl
from PySide6.QtGui import QDrag, QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QWidget
from rehuco_core import stage_image, staged_name

from .image_source import ImageSource

LOG: Final = logging.getLogger(__name__)

DRAG_PIXMAP_SIZE: Final = 256
"""The most a dragged image's picture under the pointer measures either way, in pixels: big enough to recognize,
small enough to leave the drop target visible."""


def image_mime(path: Path, data: bytes) -> QMimeData:
    """What a drop or a paste receives: the staged file's URL, and the pixels when they decode.

    :param path: the staged file.
    :param data: its bytes, decoded here for the bitmap.
    :returns: the mime data, the URL always set.
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    image = QImage.fromData(data)
    if not image.isNull():
        mime.setImageData(image)
    return mime


class ImageExporter:
    """Stages images of one resource -- or one Roots folder -- and hands them over by drag or clipboard (#395).

    :param folder: the staging folder.
    :param origin: what the staged names say the images came from (:func:`rehuco_core.staging_origin`); asked at
        every export, so a document saved for the first time since, or renamed, is named as it is now.
    """

    def __init__(self, folder: Path, origin: Callable[[], str]) -> None:
        self.__folder: Final = folder
        self.__origin: Final = origin

    @property
    def folder(self) -> Path:
        """The staging folder."""
        return self.__folder

    def mime_data(self, source: ImageSource, index: int) -> QMimeData | None:
        """Stage one image and describe it for a drop or a paste.

        The staged name carries the image's path as the source describes it -- relative to its record. A file the
        source names in full, being outside the record's folder, is named by its file name alone.

        :param source: the images.
        :param index: the one to stage.
        :returns: the mime data; ``None`` when the image could not be read or staged, which is logged.
        """
        data = source.read(index)
        path_text = source.describe(index).path_text
        if data is None:
            LOG.warning("Could not read %s to copy it out", path_text)
            return None
        relative = Path(path_text).name if Path(path_text).is_absolute() else path_text
        staged = stage_image(self.__folder, staged_name(self.__origin(), relative), data)
        return image_mime(staged, data) if staged is not None else None

    def copy(self, source: ImageSource, index: int) -> bool:
        """Put one image on the clipboard, as a file and as pixels.

        :param source: the images.
        :param index: the one to copy.
        :returns: whether it was copied.
        """
        mime = self.mime_data(source, index)
        if mime is None:
            return False
        QGuiApplication.clipboard().setMimeData(mime)
        return True

    def drag(self, widget: QWidget, source: ImageSource, index: int, picture: QPixmap) -> bool:
        """Drag one image out, as a file and as pixels; returns once it is dropped or abandoned.

        A copy and nothing else: a file manager offered a move would take the staged file away from under a later
        paste.

        :param widget: the widget the drag starts from.
        :param source: the images.
        :param index: the one to drag.
        :param picture: what to show under the pointer, shrunk to :data:`DRAG_PIXMAP_SIZE`; none when null.
        :returns: whether a drag was started.
        """
        mime = self.mime_data(source, index)
        if mime is None:
            return False
        drag = QDrag(widget)
        drag.setMimeData(mime)
        if not picture.isNull():
            bound = QSize(DRAG_PIXMAP_SIZE, DRAG_PIXMAP_SIZE)
            if picture.width() > bound.width() or picture.height() > bound.height():
                picture = picture.scaled(
                    bound, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
                )
            drag.setPixmap(picture)
            drag.setHotSpot(QPoint(picture.width() // 2, picture.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)
        return True
