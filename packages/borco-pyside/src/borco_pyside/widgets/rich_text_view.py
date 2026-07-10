"""A read-only rich-text (HTML) view that sizes itself to its content instead of scrolling.

`QTextBrowser` is a scroll area: dropped inside another scroll container it grows its own inner
scrollbars (a scroll-in-scroll). :class:`RichTextView` instead renders the same Qt rich-text subset
but reports its rendered height as its size, so an enclosing scroll area does the scrolling:

* both scrollbars are off -- text wraps to the available width (no horizontal scroll) and the widget
  grows to its full content height (no vertical scroll);
* an image too wide to wrap is simply clipped at the right margin, so it never spills over neighbours;
* no frame, and a selectable/copyable read-only body (``QTextBrowser``'s default interaction);
* the background is either transparent (blends into its parent) or the window's panel colour.
"""

from enum import Enum, auto
from math import ceil
from typing import override

from PySide6.QtCore import QSize, QSizeF, Qt
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextBrowser, QWidget


class RichTextView(QTextBrowser):
    """A `QTextBrowser` that sizes to its rendered content rather than scrolling within itself.

    Both scrollbars are disabled: the document wraps to the widget's width and the widget reports its
    full rendered height as its size hint, so an over-wide image clips at the margin and an enclosing
    scroll area (not the view) handles any overflow. The body stays read-only but selectable/copyable.

    The rendered height is read straight off the live document's ``documentSizeChanged`` signal and
    cached, so the size hints answer from the cache -- the document lays out once per content or width
    change, not once per hint query.

    :param parent: optional Qt parent.
    :param background: whether to paint no background (transparent) or the window panel colour.
    """

    class Background(Enum):
        """How the view fills its background."""

        NONE = auto()
        """Transparent -- the parent shows through, so the view does not stand out."""
        NORMAL = auto()
        """The window's panel colour, matching surrounding chrome."""

    def __init__(self, parent: QWidget | None = None, background: Background = Background.NONE) -> None:
        super().__init__(parent)
        self.__content_height = 0
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.set_background(background)
        # reflow on either a content change or a resize; each reflow lays the document out once and the
        # resulting documentSizeChanged re-caches the height -- so the hints answer from the cache
        self.document().contentsChanged.connect(self.__reflow)
        self.document().documentLayout().documentSizeChanged.connect(self.__on_document_size_changed)

    def set_background(self, background: Background) -> None:
        """Set the view's background fill.

        :param background: :attr:`Background.NONE` for transparent, :attr:`Background.NORMAL` for the
            window panel colour.
        """
        fill = "transparent" if background is RichTextView.Background.NONE else "palette(window)"
        self.setStyleSheet(f"RichTextView {{ background: {fill}; }}")

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt API name)
        super().resizeEvent(event)
        self.__reflow()

    def __reflow(self) -> None:
        """Wrap the live document to the current viewport width, forcing a single layout pass whose
        resulting ``documentSizeChanged`` re-caches the content height."""
        self.document().setTextWidth(self.viewport().width())

    @override
    def hasHeightForWidth(self) -> bool:  # noqa: N802  (Qt API name)
        return True

    @override
    def heightForWidth(self, _width: int) -> int:  # noqa: N802  (Qt API name)
        # width is ignored: the content height is cached from the last reflow, not recomputed here
        return self.__content_height

    @override
    def sizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        return QSize(self.viewport().width(), self.__content_height)

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        # zero minimum width so a long line can never force the view (or its layout) wider -- it wraps
        return QSize(0, self.__content_height)

    def __on_document_size_changed(self, size: QSizeF) -> None:
        """Cache the document's freshly laid-out height and re-advertise geometry only if it changed.

        :param size: the document's new size, as reported by its layout.
        """
        height = ceil(size.height())
        if height != self.__content_height:
            self.__content_height = height
            self.updateGeometry()
