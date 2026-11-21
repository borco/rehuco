# https://github.com/z3ntu/QtWaitingSpinner
# Copyright (c) 2012-2014 Alexander Turkin
# Copyright (c) 2014 William Hallatt
# Copyright (c) 2015 Jacob Dawid
# Copyright (c) 2016 Luca Weiss
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
# WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
# OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""A ring of lines lit one after another, each fading behind the one lit: something is being waited for, and how long
it will take is not known -- QtWaitingSpinner (https://github.com/z3ntu/QtWaitingSpinner), ported to PySide6."""

import math
from typing import Final, override

from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QShowEvent
from PySide6.QtWidgets import QWidget

DEFAULT_ROUNDNESS: Final = 100.0
"""How round a line's ends are, in percent: 100 is a capsule, 0 a rectangle."""

DEFAULT_MINIMUM_TRAIL_OPACITY: Final = math.pi
"""The opacity, in percent, of the lines past the trail."""

DEFAULT_TRAIL_FADE_PERCENTAGE: Final = 80.0
"""How much of the ring, in percent, the trail fades over behind the line lit."""

DEFAULT_REVOLUTIONS_PER_SECOND: Final = math.pi / 2
"""How many times a second the lit line goes round."""

DEFAULT_NUMBER_OF_LINES: Final = 20
"""How many lines the ring has."""

DEFAULT_LINE_LENGTH: Final = 10
"""A line's length, in pixels."""

DEFAULT_LINE_WIDTH: Final = 2
"""A line's width, in pixels."""

DEFAULT_INNER_RADIUS: Final = 10
"""The radius of the empty circle the lines start from, in pixels."""

MAX_ROUNDNESS: Final = 100.0
"""The roundest a line's ends may be, in percent."""


def line_distance(line: int, lit: int, lines: int) -> int:
    """How many lines a line is behind the lit one, going round.

    :param line: the line's index.
    :param lit: the lit line's index.
    :param lines: how many lines the ring has.
    :returns: 0 for the lit line, up to ``lines - 1``.
    """
    return (lit - line) % lines


def trail_color(color: QColor, distance: int, lines: int, fade_percentage: float, minimum_opacity: float) -> QColor:
    """The color a line is painted in, by how far it is behind the lit one: the lit line in ``color``, the trail fading
    from it, the lines past the trail at the minimum opacity.

    :param color: the lit line's color.
    :param distance: how many lines it is behind the lit one (:func:`line_distance`).
    :param lines: how many lines the ring has.
    :param fade_percentage: how much of the ring the trail covers, in percent.
    :param minimum_opacity: the opacity past the trail, in percent.
    :returns: the line's color.
    """
    faded = QColor(color)
    if distance == 0:
        return faded
    minimum = minimum_opacity / 100.0
    threshold = math.ceil((lines - 1) * fade_percentage / 100.0)
    if distance > threshold:
        faded.setAlphaF(minimum)
        return faded
    step = (faded.alphaF() - minimum) / (threshold + 1)
    faded.setAlphaF(min(1.0, max(0.0, faded.alphaF() - step * distance)))
    return faded


class WaitingSpinner(QWidget):  # pylint: disable=too-many-instance-attributes
    """A ring of lines turning while :attr:`spinning`, hidden while stopped.

    Its shape, its speed and its trail are its properties; it is a fixed square just large enough for its ring.
    **Its color** is the palette's text color unless one is set, so it follows a theme. **Centered on its parent**, it
    stands over the parent's middle and follows its resizes; placed in a layout instead, it is built with
    ``center_on_parent=False``.

    :param parent: optional Qt parent.
    :param center_on_parent: whether it stands over its parent's middle rather than where a layout puts it.
    :param disable_parent_when_spinning: whether its parent is disabled while it spins.
    :param modality: its window modality.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        center_on_parent: bool = True,
        disable_parent_when_spinning: bool = False,
        modality: Qt.WindowModality = Qt.WindowModality.NonModal,
    ) -> None:
        super().__init__(parent)
        self.__center_on_parent: Final = center_on_parent
        self.__disable_parent_when_spinning: Final = disable_parent_when_spinning
        self.__color: QColor | None = None
        self.__roundness = DEFAULT_ROUNDNESS
        self.__minimum_trail_opacity = DEFAULT_MINIMUM_TRAIL_OPACITY
        self.__trail_fade_percentage = DEFAULT_TRAIL_FADE_PERCENTAGE
        self.__revolutions_per_second = DEFAULT_REVOLUTIONS_PER_SECOND
        self.__number_of_lines = DEFAULT_NUMBER_OF_LINES
        self.__line_length = DEFAULT_LINE_LENGTH
        self.__line_width = DEFAULT_LINE_WIDTH
        self.__inner_radius = DEFAULT_INNER_RADIUS
        self.__lit = 0
        """The index of the line lit now."""
        self.__timer: Final = QTimer(self)
        self.__timer.timeout.connect(self.__rotate)
        self.__update_size()
        self.__update_timer()
        self.setWindowModality(modality)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if parent is not None and center_on_parent:
            parent.installEventFilter(self)
        self.hide()

    @property
    def spinning(self) -> bool:
        """Whether the ring is turning."""
        return self.__timer.isActive()

    @property
    def lit(self) -> int:
        """The index of the line lit now."""
        return self.__lit

    @property
    def color(self) -> QColor | None:
        """The lit line's color as set; ``None`` paints in the palette's text color."""
        return None if self.__color is None else QColor(self.__color)

    @color.setter
    def color(self, color: QColor | None) -> None:
        """Set the lit line's color; ``None`` follows the palette's text color again.

        :param color: the color.
        """
        self.__color = None if color is None else QColor(color)
        self.update()

    @property
    def roundness(self) -> float:
        """How round a line's ends are, in percent."""
        return self.__roundness

    @roundness.setter
    def roundness(self, roundness: float) -> None:
        """Set how round a line's ends are, clamped to 0..100.

        :param roundness: the roundness, in percent.
        """
        self.__roundness = max(0.0, min(MAX_ROUNDNESS, roundness))
        self.update()

    @property
    def minimum_trail_opacity(self) -> float:
        """The opacity of the lines past the trail, in percent."""
        return self.__minimum_trail_opacity

    @minimum_trail_opacity.setter
    def minimum_trail_opacity(self, opacity: float) -> None:
        """Set the opacity of the lines past the trail.

        :param opacity: the opacity, in percent.
        """
        self.__minimum_trail_opacity = opacity
        self.update()

    @property
    def trail_fade_percentage(self) -> float:
        """How much of the ring the trail fades over, in percent."""
        return self.__trail_fade_percentage

    @trail_fade_percentage.setter
    def trail_fade_percentage(self, percentage: float) -> None:
        """Set how much of the ring the trail fades over.

        :param percentage: the share of the ring, in percent.
        """
        self.__trail_fade_percentage = percentage
        self.update()

    @property
    def revolutions_per_second(self) -> float:
        """How many times a second the lit line goes round."""
        return self.__revolutions_per_second

    @revolutions_per_second.setter
    def revolutions_per_second(self, revolutions: float) -> None:
        """Set how many times a second the lit line goes round.

        :param revolutions: the speed.
        """
        self.__revolutions_per_second = revolutions
        self.__update_timer()

    @property
    def number_of_lines(self) -> int:
        """How many lines the ring has."""
        return self.__number_of_lines

    @number_of_lines.setter
    def number_of_lines(self, lines: int) -> None:
        """Set how many lines the ring has, lighting the first.

        :param lines: the count.
        """
        self.__number_of_lines = lines
        self.__lit = 0
        self.__update_timer()
        self.update()

    @property
    def line_length(self) -> int:
        """A line's length, in pixels."""
        return self.__line_length

    @line_length.setter
    def line_length(self, length: int) -> None:
        """Set a line's length, which resizes the spinner.

        :param length: the length, in pixels.
        """
        self.__line_length = length
        self.__update_size()

    @property
    def line_width(self) -> int:
        """A line's width, in pixels."""
        return self.__line_width

    @line_width.setter
    def line_width(self, width: int) -> None:
        """Set a line's width.

        :param width: the width, in pixels.
        """
        self.__line_width = width
        self.__update_size()

    @property
    def inner_radius(self) -> int:
        """The radius of the empty circle the lines start from, in pixels."""
        return self.__inner_radius

    @inner_radius.setter
    def inner_radius(self, radius: int) -> None:
        """Set the radius of the empty circle the lines start from, which resizes the spinner.

        :param radius: the radius, in pixels.
        """
        self.__inner_radius = radius
        self.__update_size()

    def start(self) -> None:
        """Show the spinner and start turning, from the first line; a no-op while turning."""
        if self.__timer.isActive():
            return
        self.__center()
        self.show()
        self.__set_parent_enabled(False)
        self.__lit = 0
        self.__timer.start()

    def stop(self) -> None:
        """Stop turning and hide the spinner; a no-op while stopped."""
        if not self.__timer.isActive():
            return
        self.__timer.stop()
        self.__lit = 0
        self.hide()
        self.__set_parent_enabled(True)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """Stand over the parent's middle again as it is resized.

        :param watched: the parent.
        :param event: its event.
        :returns: ``False``: the parent handles its event as ever.
        """
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.__center()
        return super().eventFilter(watched, event)

    @override
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt override)
        """Stand over the parent's middle as it is shown.

        :param event: the Qt show event.
        """
        self.__center()
        super().showEvent(event)

    @override
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 (Qt override)
        """Paint every line, each in its color by how far it is behind the lit one.

        :param event: the Qt paint event.
        """
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        color = self.__color if self.__color is not None else self.palette().windowText().color()
        lines = self.__number_of_lines
        line = QRectF(self.__inner_radius, -self.__line_width / 2, self.__line_length, self.__line_width)
        for index in range(lines):
            painter.save()
            painter.translate(self.width() / 2, self.height() / 2)
            painter.rotate(360 * index / lines)
            distance = line_distance(index, self.__lit, lines)
            painter.setBrush(
                trail_color(color, distance, lines, self.__trail_fade_percentage, self.__minimum_trail_opacity)
            )
            painter.drawRoundedRect(line, self.__roundness, self.__roundness, Qt.SizeMode.RelativeSize)
            painter.restore()
        painter.end()

    def __rotate(self) -> None:
        """Light the next line."""
        self.__lit = (self.__lit + 1) % self.__number_of_lines
        self.update()

    def __update_size(self) -> None:
        """Fit the square to the ring: the inner circle and a line on each side, wide enough for a line across."""
        side = max(2 * (self.__inner_radius + self.__line_length), self.__line_width)
        self.setFixedSize(side, side)
        self.__center()
        self.update()

    def __update_timer(self) -> None:
        """Pace the timer so the lit line goes round at the speed asked."""
        self.__timer.setInterval(max(1, round(1000 / (self.__number_of_lines * self.__revolutions_per_second))))

    def __center(self) -> None:
        """Stand over the parent's middle, when asked to."""
        parent = self.parentWidget()
        if parent is not None and self.__center_on_parent:
            self.move((parent.width() - self.width()) // 2, (parent.height() - self.height()) // 2)

    def __set_parent_enabled(self, enabled: bool) -> None:
        """Enable or disable the parent while spinning, when asked to.

        :param enabled: whether it is enabled.
        """
        parent = self.parentWidget()
        if parent is not None and self.__disable_parent_when_spinning:
            parent.setEnabled(enabled)
