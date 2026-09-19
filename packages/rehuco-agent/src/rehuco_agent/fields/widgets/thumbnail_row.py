"""The lightbox's thumbnail row: a lazy, single-row `QListView` over an :class:`ImageSource` (#221).

Replaces the synchronous `ImageStrip` the viewer used to carry: that one decodes every thumbnail as it is
built, which is fine for a dozen screenshots and hopeless for a reference pack of thousands. A list view
virtualizes its paint, so only the thumbnails in the viewport are ever asked of the
:class:`ThumbnailLoader`, and `QPixmapCache`'s cap is what expunges the ones scrolled far away.
"""

from typing import Any, Final, override

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPixmap, QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QFrame, QListView, QStyledItemDelegate, QStyleOptionViewItem, QWidget

from .image_source import ImageSource
from .image_strip import THUMBNAIL_BORDER
from .thumbnail_loader import ThumbnailLoader

type ModelIndex = QModelIndex | QPersistentModelIndex

PLACEHOLDER_ALPHA: Final = 40
"""How faint the pending-thumbnail placeholder is: a hint of the palette's text colour over the backdrop,
enough to say "something is coming here" without competing with the thumbnails already up."""


class ImageSourceModel(QAbstractListModel):
    """A list model over an :class:`ImageSource` -- one row per image, its name as the display text.

    The thumbnails themselves are not data: the delegate reads them straight from the loader's cache,
    keyed by the source's own keys, so nothing is copied into the model.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__source: ImageSource | None = None

    @property
    def source(self) -> ImageSource | None:
        """The images this model lists, or ``None`` while it lists nothing."""
        return self.__source

    def set_source(self, source: ImageSource | None) -> None:
        """Replace the listed images wholesale.

        :param source: the new source, or ``None`` to list nothing.
        """
        self.beginResetModel()
        self.__source = source
        self.endResetModel()

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:
        """See ``QAbstractListModel``: a flat list has rows only at the root."""
        if parent.isValid() or self.__source is None:
            return 0
        return len(self.__source)

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """The image's name as display text; nothing for any other role -- no tooltip, since the
        viewer names the hovered thumbnail in its own info box (:attr:`ThumbnailRow.hovered_index`)."""
        if not index.isValid() or self.__source is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self.__source.name(index.row())
        return None


class ThumbnailDelegate(QStyledItemDelegate):
    """Paints one row item: the cached thumbnail, a placeholder while it decodes, and the current ring.

    :param row: the row this delegate paints for -- where the source, loader and height are read.
    """

    def __init__(self, row: ThumbnailRow) -> None:
        super().__init__(row)
        self.__row: Final = row

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:
        """The thumbnail's own size once decoded; a square of the row height until then.

        Reads the cache and **never requests**: the list view asks every item's hint when it lays the
        row out, and a request here would decode a whole pack the moment the row was built. Only a
        paint asks for what is actually in view; the width settles as the thumbnail lands.

        :param option: the style option; unused.
        :param index: the item.
        :returns: the size.
        """
        del option
        height = self.__row.row_height
        pixmap = self.__row.cached_thumbnail(index.row())
        return QSize(pixmap.deviceIndependentSize().toSize().width() if pixmap is not None else height, height)

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        """Paint the thumbnail or its placeholder, then the ring when it is the current image.

        The ring is the same odd-even-filled band `ImageStrip.ThumbnailLabel` paints, for the same
        reasons: no centring and no joins, so every side is exactly :data:`THUMBNAIL_BORDER`.

        :param painter: the painter.
        :param option: the style option -- its rect is the item's.
        :param index: the item.
        """
        rect = option.rect
        pixmap = self.__row.thumbnail(index.row())
        if pixmap is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(rect.topLeft(), pixmap)
        else:
            colour = option.palette.color(QPalette.ColorRole.Text)
            colour.setAlpha(PLACEHOLDER_ALPHA)
            painter.fillRect(rect, colour)
        if index.row() == self.__row.current_index:
            border = THUMBNAIL_BORDER
            ring = QPainterPath()
            ring.addRect(QRectF(rect))
            ring.addRect(QRectF(rect.adjusted(border, border, -border, -border)))
            painter.fillPath(ring, option.palette.color(QPalette.ColorRole.Highlight))


class ThumbnailRow(QListView):
    """A fixed-height, horizontally flowing row of lazily decoded thumbnails (#221).

    Frameless and transparent so nothing but the thumbnails is drawn on whatever hosts it; takes no
    focus, so a click on a thumbnail leaves the keyboard where the arrow keys are handled; and never
    shows a scrollbar -- overflow is reached by the wheel, either axis, and the current thumbnail is
    scrolled into view programmatically.

    :param loader: the shared decode pool the thumbnails come from.
    :param parent: optional Qt parent.
    :param height: the row's fixed pixel height.
    """

    activated_index = Signal(int)
    """Fires with the position of the thumbnail the user clicked."""

    hovered_index = Signal(int)
    """Fires with the position of the thumbnail under the pointer as it changes, and ``-1`` once the
    pointer is over none -- a gap, or outside the row. Immediate, unlike a tooltip."""

    def __init__(self, loader: ThumbnailLoader, parent: QWidget | None = None, height: int = 96) -> None:
        super().__init__(parent)
        self.__loader: Final = loader
        self.__height = height
        self.__current = -1
        self.__model: Final = ImageSourceModel(self)
        self.setModel(self.__model)
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setSpacing(0)
        self.setUniformItemSizes(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # scoped to the view: a selector-less rule reaches every descendant, and Qt paints a tooltip
        # through the stylesheet of the widget it belongs to -- a transparent tooltip over the
        # thumbnails came out as black boxes
        self.setStyleSheet("QListView { background: transparent; }")
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(height)
        self.clicked.connect(lambda index: self.activated_index.emit(index.row()))
        # tracking on the viewport (the widget the pointer is actually over) is what makes the view
        # report the item under a moving pointer (``entered``); ``viewportEntered`` is the pointer
        # over the row but over no item
        self.viewport().setMouseTracking(True)
        self.__hovered = -1
        self.entered.connect(lambda index: self.__set_hovered(index.row()))
        self.viewportEntered.connect(lambda: self.__set_hovered(-1))
        loader.ready.connect(self.__on_thumbnail_ready)

    @property
    def row_height(self) -> int:
        """The row's fixed pixel height, which is also every thumbnail's."""
        return self.__height

    @property
    def current_index(self) -> int:
        """The position framed as current, or ``-1`` for none."""
        return self.__current

    def set_source(self, source: ImageSource | None) -> None:
        """Replace the thumbnails wholesale.

        :param source: the images to show, or ``None`` for none.
        """
        self.__current = -1
        # a position hovered in the old source names nothing in the new one
        self.__set_hovered(-1)
        self.__model.set_source(source)

    def set_current(self, index: int) -> None:
        """Frame ``index``'s thumbnail as the current image and scroll it into view.

        :param index: the position, or ``-1`` for none.
        """
        self.__current = index
        if 0 <= index < self.__model.rowCount():
            self.scrollTo(self.__model.index(index), QAbstractItemView.ScrollHint.EnsureVisible)
        self.viewport().update()

    def set_height(self, height: int) -> None:
        """Resize the row; every thumbnail is re-requested at the new height on its next paint.

        :param height: the new fixed pixel height.
        """
        if height == self.__height:
            return
        self.__height = height
        self.setFixedHeight(height)
        self.scheduleDelayedItemsLayout()

    def set_requested_visible(self, visible: bool) -> None:
        """Show or hide the row.

        :param visible: whether the row should be shown.
        """
        self.setVisible(visible)

    def thumbnail(self, index: int) -> QPixmap | None:
        """The cached thumbnail for ``index``, requesting a decode when there is none yet -- what a
        paint asks for.

        :param index: the position.
        :returns: the pixmap, or ``None`` while it is pending or after it failed.
        """
        source = self.__model.source
        if source is None:
            return None
        return self.__loader.request(self, source, index, self.__height, self.devicePixelRatio())

    def cached_thumbnail(self, index: int) -> QPixmap | None:
        """The thumbnail for ``index`` if it is already decoded, requesting nothing -- what a size hint
        asks for.

        :param index: the position.
        :returns: the pixmap, or ``None``.
        """
        source = self.__model.source
        if source is None:
            return None
        return self.__loader.cached(source.key(index), self.__height, self.devicePixelRatio())

    @override
    def wheelEvent(self, event: QWheelEvent) -> None:
        """Scroll the row sideways on either wheel axis.

        A vertical wheel is the natural gesture over a horizontal row that has no vertical extent to
        scroll, so it is translated rather than left to bubble up to the lightbox, which would step.

        :param event: the Qt wheel event.
        """
        delta = event.angleDelta().x() or event.angleDelta().y()
        scrollbar = self.horizontalScrollBar()
        scrollbar.setValue(scrollbar.value() - delta)
        event.accept()

    @override
    def leaveEvent(self, event: QEvent) -> None:
        """Nothing is hovered once the pointer leaves the row.

        :param event: the Qt leave event, forwarded to the base class.
        """
        super().leaveEvent(event)
        self.__set_hovered(-1)

    def __set_hovered(self, index: int) -> None:
        """Announce the hovered position when it changes.

        :param index: the position, or ``-1`` for none.
        """
        if index == self.__hovered:
            return
        self.__hovered = index
        self.hovered_index.emit(index)

    def __on_thumbnail_ready(self, cache_key: str) -> None:
        """Repaint and re-lay out as a thumbnail lands -- its width is only known now.

        Coarse on purpose: the loader announces every thumbnail it decodes, for every surface, and
        telling which of them this row shows would cost a walk over the source per announcement. A
        delayed layout coalesces a burst into one pass.

        :param cache_key: the thumbnail's cache key; unused.
        """
        del cache_key
        self.scheduleDelayedItemsLayout()
        self.viewport().update()
