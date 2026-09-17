"""Measure what the active style paints behind a checked toolbar button's glyph."""

from typing import ClassVar, Final

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionToolButton

from .contrast import readable_color_on

PROBE_SIZE: Final = QSize(16, 16)
"""Big enough that the style paints its real fill rather than degenerating, small enough to be free."""


class CheckedToolButtonChrome:  # pylint: disable=too-few-public-methods
    """What a checked toolbar button is actually filled with, and what reads against it.

    Measured, never assumed. Assuming it was the whole of #304's second defect: the checked glyph was
    colored from ``HighlightedText`` on the theory that the chrome paints a ``Highlight``-colored
    backdrop, and no style measured here does. `windows11` fills with ``Accent`` -- ``#0067c0`` in the
    light theme but ``#4cc2ff``, a *pale* blue, in the dark one -- and `Fusion` fills with a neutral
    shade of ``Button`` (``#dcdcdc`` / ``#414141``) and no accent at all. Reading the fill and choosing
    for contrast reproduces, in all four of those cases, the color each style draws its own button
    *text* in.

    Same technique, and the same reasoning, as the menu-row measurement in ``RehuDocumentMenuEntry``:
    render a probe, sample its center, decide from that.
    """

    colors: ClassVar[dict[tuple[str, int, bool], QColor]] = {}
    """Memo of the chosen glyph color, keyed by style, palette and enabled-ness.

    ``objectName()``, not the class name: PySide reports several distinct Qt styles as the same wrapper
    class (``QCommonStyle``), so keying on the class silently serves one style's measurement to
    another. ``QStyleFactory`` stamps the object name with the real style key.
    """

    @classmethod
    def glyph_color(cls, palette: QPalette, *, enabled: bool) -> QColor:
        """The color to draw a checked toolbar button's glyph in, under ``palette``.

        :param palette: the palette the button will be painted with.
        :param enabled: whether the button is enabled, which several styles fill differently.
        :returns: a color that contrasts with the fill this style actually paints.
        """
        style = QApplication.style()
        key = (style.objectName() or type(style).__name__, palette.cacheKey(), enabled)
        cached = cls.colors.get(key)
        if cached is not None:
            return cached
        group = QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled
        color = readable_color_on(cls.__backdrop(palette, enabled=enabled), palette, group)
        # a palette change is a new cacheKey, so entries for any other palette are already dead: drop
        # them here rather than letting every theme toggle of a long session leave two behind
        for stale in [k for k in cls.colors if k[1] != palette.cacheKey()]:
            del cls.colors[stale]  # pylint: disable=unsupported-delete-operation
        cls.colors[key] = color  # pylint: disable=unsupported-assignment-operation
        return color

    @classmethod
    def __backdrop(cls, palette: QPalette, *, enabled: bool) -> QColor:
        image = QImage(PROBE_SIZE, QImage.Format.Format_ARGB32)
        # the toolbar's own background, so a style that paints no checked fill at all reports what the
        # glyph would really sit on rather than an uninitialized pixel
        image.fill(palette.color(QPalette.ColorRole.Window))
        painter = QPainter(image)
        QApplication.style().drawComplexControl(
            QStyle.ComplexControl.CC_ToolButton, cls.__option(palette, enabled=enabled), painter, None
        )
        painter.end()
        # sampled at the center: several styles fill with a vertical gradient, so a pixel near an edge
        # reports an extreme rather than what the glyph will actually sit on
        return image.pixelColor(PROBE_SIZE.width() // 2, PROBE_SIZE.height() // 2)

    @classmethod
    def __option(cls, palette: QPalette, *, enabled: bool) -> QStyleOptionToolButton:
        option = QStyleOptionToolButton()
        option.rect = QRect(0, 0, PROBE_SIZE.width(), PROBE_SIZE.height())
        option.palette = palette
        # AutoRaise because that is what a QToolBar gives its buttons, and it is precisely the flag
        # that decides whether a style paints a filled chrome or none at all
        option.state = QStyle.StateFlag.State_On | QStyle.StateFlag.State_AutoRaise
        if enabled:
            option.state |= QStyle.StateFlag.State_Enabled
        option.subControls = QStyle.SubControl.SC_ToolButton
        option.features = QStyleOptionToolButton.ToolButtonFeature.None_
        return option
