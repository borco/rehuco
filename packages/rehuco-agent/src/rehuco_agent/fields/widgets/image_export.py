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
from typing import Final, override

from PySide6.QtCore import QEvent, QMimeData, QObject, QPoint, QSize, Qt, QUrl
from PySide6.QtGui import QDrag, QGuiApplication, QImage, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from rehuco_core import stage_image, staged_name

from .image_source import ImageSource, PathImageSource, ScreenshotKey

LOG: Final = logging.getLogger(__name__)

DRAG_PIXMAP_SIZE: Final = 256
"""The most a dragged image's picture under the pointer measures either way, in pixels: big enough to recognize,
small enough to leave the drop target visible."""


ORIGINAL_FILE_MIME: Final = "application/x-rehuco-original-file"
"""Carried by what leaves the app when the image **is a file on disk** (#395): that file's own path, UTF-8. The staged
copy's URL says nothing of where the image came from, so a drop target in this app that must tell *its own screenshots*
from anything else -- the Images dock, which would otherwise acquire a screenshot as a duplicate of itself -- reads
this instead. Another app ignores it."""


def image_mime(path: Path, data: bytes, original: Path | None = None) -> QMimeData:
    """What a drop or a paste receives: the staged file's URL, and the pixels when they decode.

    :param path: the staged file.
    :param data: its bytes, decoded here for the bitmap.
    :param original: the file the image really is, when it is one (:data:`ORIGINAL_FILE_MIME`).
    :returns: the mime data, the URL always set.
    """
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    if original is not None:
        mime.setData(ORIGINAL_FILE_MIME, str(original).encode())
    image = QImage.fromData(data)
    if not image.isNull():
        mime.setImageData(image)
    return mime


def source_file(source: ImageSource, index: int) -> Path | None:
    """The file an image of a source really is, for a source whose images are files.

    :param source: the images.
    :param index: the one asked about.
    :returns: its path; ``None`` for an image with no file of its own (an archive member).
    """
    key = source.key(index)
    if isinstance(key, ScreenshotKey):
        return key.path
    return key if isinstance(key, Path) else None


class PressTracker:
    """Remembers where a left press landed on something draggable, and says when the pointer has moved far enough
    from it to start dragging (#395) -- the platform's drag distance, the way every list does.

    One of these per widget that drags: the widget feeds it the press, the moves and the release, and starts the drag
    itself when :meth:`moved` answers.
    """

    def __init__(self) -> None:
        self.__pressed: tuple[QPoint, object] | None = None

    def press(self, event: QMouseEvent, token: object | None) -> None:
        """Remember a left press on ``token``, or forget any when it is on nothing draggable.

        :param event: the press.
        :param token: what is under it; ``None`` for nothing draggable.
        """
        left = event.button() == Qt.MouseButton.LeftButton
        self.__pressed = (event.position().toPoint(), token) if left and token is not None else None

    def moved(self, event: QMouseEvent) -> object | None:
        """What the pointer has been dragged away from, once it has gone far enough with the left button held.

        :param event: the move.
        :returns: the pressed token, once, after which the press is forgotten; ``None`` until then.
        """
        pressed = self.__pressed
        if pressed is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return None
        start, token = pressed
        if (event.position().toPoint() - start).manhattanLength() < QApplication.startDragDistance():
            return None
        self.__pressed = None
        return token

    def release(self) -> None:
        """Forget the press."""
        self.__pressed = None


class PressDragFilter(QObject):
    """Starts a drag from a widget that is not ours to subclass, by watching its mouse events (#395).

    It only observes -- every event goes on to the widget unchanged, so its selection, clicks and double-clicks
    behave as they always did -- and tells its owner when a press on a draggable thing has moved far enough.

    :param widget: the widget to watch; a view's *viewport*, for a view.
    :param token_at: what is draggable at a point of the widget, or ``None``; asked at the press.
    :param started: told the token once the pointer has moved the drag distance from the press.
    """

    def __init__(
        self, widget: QWidget, token_at: Callable[[QPoint], object | None], started: Callable[[object], None]
    ) -> None:
        super().__init__(widget)
        self.__token_at: Final = token_at
        self.__started: Final = started
        self.__press: Final = PressTracker()
        widget.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """See :meth:`QObject.eventFilter`; never consumes an event.

        :param watched: the widget.
        :param event: the event.
        :returns: ``False`` always.
        """
        del watched
        if isinstance(event, QMouseEvent):
            match event.type():
                case QEvent.Type.MouseButtonPress:
                    self.__press.press(event, self.__token_at(event.position().toPoint()))
                case QEvent.Type.MouseMove:
                    token = self.__press.moved(event)
                    if token is not None:
                        self.__started(token)
                case QEvent.Type.MouseButtonRelease:
                    self.__press.release()
                case _:
                    pass
        return False


class ImageExporter:
    """Stages images of one resource -- or one Roots folder -- and hands them over by drag or clipboard (#395).

    :param folder: the staging folder.
    :param origin: what the staged names say the images came from (:func:`rehuco_core.staging_origin`); asked at
        every export, so a document saved for the first time since, or renamed, is named as it is now.
    :param base: the folder an image *file*'s name is taken relative to when it is exported by path
        (:meth:`drag_path`) -- the record's, as in a document; asked at every export; ``None``, the default, names a
        file by its own name.
    """

    def __init__(self, folder: Path, origin: Callable[[], str], base: Callable[[], Path | None] | None = None) -> None:
        self.__folder: Final = folder
        self.__origin: Final = origin
        self.__base: Final = base

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
        return image_mime(staged, data, source_file(source, index)) if staged is not None else None

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

    def source_of(self, path: Path) -> ImageSource:
        """A one-image source over an image file, named as the record's own files are.

        :param path: the file.
        :returns: the source, with the one image at position ``0``.
        """
        return PathImageSource([path], self.__base() if self.__base is not None else None)

    def drag_path(self, widget: QWidget, path: Path, picture: QPixmap) -> bool:
        """Drag one image *file* out -- for a widget that holds paths rather than a source.

        :param widget: the widget the drag starts from.
        :param path: the file.
        :param picture: what to show under the pointer.
        :returns: whether a drag was started.
        """
        return self.drag(widget, self.source_of(path), 0, picture)

    def copy_path(self, path: Path) -> bool:
        """Put one image *file* on the clipboard.

        :param path: the file.
        :returns: whether it was copied.
        """
        return self.copy(self.source_of(path), 0)

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
