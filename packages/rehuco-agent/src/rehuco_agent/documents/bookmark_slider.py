"""The player's seek slider, with a tick at each bookmark of the video ([[plugins#video-notes-dock]], #573)."""

from typing import Final, override

from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QWidget

TICK_LENGTH: Final = 4
"""How long a tick is, in pixels: one above the groove and one below it, as Qt draws its own."""

TICK_ALPHA: Final = 130
"""How opaque a tick is, of 255: a lighter shade of the text color, so the ticks do not compete with the handle."""

TICK_GAP: Final = 2
"""The space between a tick and the groove, in pixels."""


class BookmarkSlider(QSlider):
    """A slider with a tick at each marked position, above and below the groove as Qt draws its own.

    Qt's ticks come at a regular interval only, so these are drawn here at the marked values.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # the style leaves room for ticks on both sides; it draws none itself, as its tick sub-control is not painted
        self.setTickPosition(QSlider.TickPosition.TicksBothSides)
        self.__marks: tuple[int, ...] = ()

    @property
    def marks(self) -> tuple[int, ...]:
        """The values marked, in the slider's own units."""
        return self.__marks

    def set_marks(self, marks: list[int]) -> None:
        """Mark positions, each drawn as a tick above and below the groove.

        :param marks: the values; one outside the slider's range is not drawn.
        """
        shown = tuple(sorted(set(marks)))
        if shown != self.__marks:
            self.__marks = shown
            self.update()

    def tick_rects(self) -> list[QRect]:
        """Where the ticks are drawn.

        :returns: two rectangles for each mark within the range, the one above the groove then the one below it, left
            to right, in the slider's coordinates.
        """
        if self.maximum() <= self.minimum():
            return []
        option = self.__option()
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self
        )
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self
        )
        span = groove.width() - handle.width()
        rects = []
        for mark in self.__marks:
            if not self.minimum() <= mark <= self.maximum():
                continue
            x = (
                groove.x()
                + handle.width() // 2
                + QStyle.sliderPositionFromValue(self.minimum(), self.maximum(), mark, span)
            )
            rects.append(QRect(x, groove.top() - TICK_GAP - TICK_LENGTH, 1, TICK_LENGTH))
            rects.append(QRect(x, groove.bottom() + 1 + TICK_GAP, 1, TICK_LENGTH))
        return rects

    @override
    def paintEvent(self, ev: QPaintEvent) -> None:  # noqa: N802  (Qt API name)
        """Draw the groove, the ticks, then the handle, so the handle covers a tick it is over."""
        del ev
        painter = QPainter(self)
        option = self.__option()
        option.subControls = QStyle.SubControl.SC_SliderGroove
        self.style().drawComplexControl(QStyle.ComplexControl.CC_Slider, option, painter, self)
        color = self.palette().color(QPalette.ColorRole.WindowText)
        color.setAlpha(TICK_ALPHA)
        # a cosmetic pen is one device pixel wide at any display scaling, where a filled one-pixel rectangle is one
        # or two depending on where it falls
        painter.setPen(QPen(color, 0))
        for rect in self.tick_rects():
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        option.subControls = QStyle.SubControl.SC_SliderHandle
        self.style().drawComplexControl(QStyle.ComplexControl.CC_Slider, option, painter, self)

    def __option(self) -> QStyleOptionSlider:
        """The style option this slider draws with.

        :returns: the option, filled from the slider's state.
        """
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        return option
