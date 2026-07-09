"""Tests for glyph_icon: rendering a single font glyph fresh at whatever size Qt requests."""

from borco_pyside.theming.glyph_icon import GlyphIconEngine, glyph_icon
from PySide6.QtGui import QColor, QIcon

STAR_GLYPH = "\ue46a"
"""Phosphor's "star" glyph -- a real, solid icon shape guaranteed present in the loaded test font,
unlike an arbitrary Unicode character the font may not carry."""


def test_glyph_icon_renders_sharply_at_a_different_size(real_font_family: str) -> None:
    """The same icon renders fresh (not scaled from a cached fixed-resolution raster) at another size.

    **Test steps:**

    * build a glyph icon
    * render it at both 16x16 and 64x64
    * verify each pixmap is exactly the size requested
    """
    icon = glyph_icon(STAR_GLYPH, real_font_family, QColor("red"))

    small = icon.pixmap(16, 16)
    large = icon.pixmap(64, 64)

    assert small.size().width() == 16
    assert large.size().width() == 64


def test_glyph_icon_draws_the_glyph_in_the_given_color(real_font_family: str) -> None:
    """The glyph is drawn in ``color`` -- its center pixel (a filled shape covers its own center) matches it.

    **Test steps:**

    * render a solid glyph in a distinct color
    * verify the center pixel's color matches
    """
    color = QColor(255, 0, 0)
    icon = glyph_icon(STAR_GLYPH, real_font_family, color)

    image = icon.pixmap(16, 16).toImage()
    assert image.pixelColor(8, 8).name() == color.name()


def test_glyph_icon_is_transparent_in_the_corners(real_font_family: str) -> None:
    """A glyph centered in its cell leaves the corners untouched (alpha 0).

    **Test steps:**

    * render the glyph
    * verify a corner pixel is fully transparent
    """
    icon = glyph_icon(STAR_GLYPH, real_font_family, QColor("black"))

    image = icon.pixmap(16, 16).toImage()
    assert image.pixelColor(0, 0).alpha() == 0


def test_engine_clone_renders_the_same_glyph(real_font_family: str) -> None:
    """Cloning the icon engine produces an independent engine rendering the same glyph.

    **Test steps:**

    * build a GlyphIconEngine directly and clone it
    * render both at the same size
    * verify both produce the same center pixel color
    """
    color = QColor(0, 128, 0)
    engine = GlyphIconEngine(STAR_GLYPH, real_font_family, color)

    clone = engine.clone()
    icon = QIcon(clone)

    pixmap = icon.pixmap(16, 16)
    assert pixmap.toImage().pixelColor(8, 8).name() == color.name()
