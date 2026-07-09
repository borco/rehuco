"""Render a single icon-font glyph fresh at whatever exact size Qt requests.

Unlike rasterizing once at a fixed size, this keeps the glyph as a real, infinitely-scalable icon --
exactly as crisp at any requested size as an SVG-backed ``QIcon``, since nothing is ever cached at a
fixed resolution (mirrors :mod:`~borco_pyside.theming.svg_recolor`'s approach for the same reason: a
single baked pixmap renders blurry once Qt requests it at any other size, e.g. a HiDPI screen's
actual device pixel size).
"""

from typing import Final, override

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QIconEngine, QPainter, QPixmap

from borco_pyside.theming.utils import painted_pixmap


def glyph_icon(glyph: str, family: str, color: QColor) -> QIcon:
    """Build a scalable ``QIcon`` that renders ``glyph`` in ``color``, at any size, on demand.

    :param glyph: the character to draw (typically one codepoint from an icon font).
    :param family: the font family ``glyph`` resolves in; must already be loaded
        (``QFontDatabase.addApplicationFont``) or the glyph renders as tofu.
    :param color: the color to draw the glyph with.
    :returns: a scalable ``QIcon`` backed by a :class:`GlyphIconEngine`.
    """
    return QIcon(GlyphIconEngine(glyph, family, color))


class GlyphIconEngine(QIconEngine):
    """Renders one font glyph fresh at whatever exact size/mode/state Qt requests.

    A single glyph/family/color, unlike :class:`~borco_pyside.theming.RecoloredSvgIconEngine`'s
    mode/state corners -- none of this toolkit's glyph icons (a line edit's clear/calendar trailing
    actions) are checkable, so there is no On/Off or enabled/disabled variant to carry.

    :param glyph: the character to draw.
    :param family: the font family ``glyph`` resolves in.
    :param color: the color to draw the glyph with.
    """

    FILL_FACTOR: Final = 0.7
    """Fraction of the requested rect the glyph's font size fills. An SVG icon's own source already
    bakes in margin around its drawn shape (its viewBox is deliberately larger than the artwork), so
    :class:`~borco_pyside.theming.RecoloredSvgIconEngine` can render edge-to-edge; a font glyph has no
    such built-in canvas margin, so filling the *whole* rect at ``1.0`` reads as cramped -- confirmed
    empirically against the actual `QLineEdit` trailing-action size (#24)."""

    def __init__(self, glyph: str, family: str, color: QColor) -> None:
        super().__init__()
        self.__glyph: Final = glyph
        self.__family: Final = family
        self.__color: Final = color

    @override
    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        del mode, state  # no mode/state variants -- see class docstring
        font = QFont(self.__family)
        font.setPixelSize(round(min(rect.width(), rect.height()) * self.FILL_FACTOR))
        painter.setFont(font)
        painter.setPen(self.__color)
        painter.drawText(QRectF(rect), Qt.AlignmentFlag.AlignCenter, self.__glyph)

    @override
    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return painted_pixmap(self, size, mode, state)

    @override
    def clone(self) -> QIconEngine:
        return GlyphIconEngine(self.__glyph, self.__family, self.__color)
