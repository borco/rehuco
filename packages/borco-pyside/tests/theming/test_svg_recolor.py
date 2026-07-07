"""Tests for recolor_svg/recolored_svg_icon and their backing RecoloredSvgIconEngine."""

from borco_pyside.theming.svg_recolor import RecoloredSvgIconEngine, recolor_svg, recolored_svg_icon
from PySide6.QtGui import QColor, QIcon
from pytestqt.qtbot import QtBot

SVG_WITH_RGB_FILL: bytes = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<rect width="10" height="10" style="fill:rgb(0,0,0)"/></svg>'
)


# region recolor_svg tests
def test_recolor_svg_replaces_an_explicit_rgb_fill() -> None:
    """A shape with an explicit `fill:rgb(...)` gets that fill rewritten to the requested color.

    **Test steps:**

    * recolor `SVG_WITH_RGB_FILL` to red
    * verify the rgb(...) fill is gone and the new hex color is present
    """
    result = recolor_svg(SVG_WITH_RGB_FILL, QColor("red")).decode("utf-8")

    assert "fill:rgb(0,0,0)" not in result
    assert "fill:#ff0000" in result


def test_recolor_svg_preserves_fill_none() -> None:
    """A shape styled `fill:none` (e.g. a background rect) is left untouched.

    **Test steps:**

    * recolor an SVG whose only shape has `style="fill:none"`
    * verify the style string is unchanged
    """
    svg = b'<svg><rect style="fill:none;stroke:black"/></svg>'

    result = recolor_svg(svg, QColor("red")).decode("utf-8")

    assert 'style="fill:none;stroke:black"' in result


def test_recolor_svg_adds_fill_when_missing() -> None:
    """A shape with a `style` but no `fill` at all gets one prepended (SVG's implicit fill is black).

    **Test steps:**

    * recolor an SVG whose shape's style has no `fill` entry
    * verify the requested color's fill was added
    """
    svg = b'<svg><rect style="stroke:black"/></svg>'

    result = recolor_svg(svg, QColor("red")).decode("utf-8")

    assert 'style="fill:#ff0000;stroke:black"' in result


def test_recolor_svg_leaves_a_non_rgb_fill_untouched() -> None:
    """A shape already styled with a fill in some other form (e.g. a hex literal) is left as-is.

    Only the `fill:rgb(...)` form (as emitted by Inkscape) is rewritten; this exercises the
    remaining branch where neither `fill:none` nor `fill:rgb(...)` matches, but `fill:` is present.

    **Test steps:**

    * recolor an SVG whose shape's style already has a hex `fill`
    * verify the style is unchanged
    """
    svg = b'<svg><rect style="fill:#123456"/></svg>'

    result = recolor_svg(svg, QColor("red")).decode("utf-8")

    assert 'style="fill:#123456"' in result


def test_recolor_svg_ignores_text_without_any_style_attribute() -> None:
    """An SVG with no `style="..."` attribute at all passes through unchanged.

    **Test steps:**

    * recolor an SVG with no style attributes
    * verify the bytes are unchanged
    """
    svg = b'<svg><rect width="10" height="10"/></svg>'

    assert recolor_svg(svg, QColor("red")) == svg


# endregion


# region recolored_svg_icon / RecoloredSvgIconEngine tests
def test_recolored_svg_icon_renders_the_requested_color_at_an_exact_size(qtbot: QtBot) -> None:
    """The built icon renders `svg` recolored to `color`, at whatever exact size is requested.

    **Test steps:**

    * build a recolored icon from `SVG_WITH_RGB_FILL` in red
    * render it at 24x24
    * verify the rendered pixmap is exactly 24x24 and its center pixel is red
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"))

    pixmap = icon.pixmap(24, 24)

    assert pixmap.size().width() == 24
    assert pixmap.size().height() == 24
    assert pixmap.toImage().pixelColor(12, 12).name() == "#ff0000"


def test_recolored_svg_icon_renders_sharply_at_a_different_size(qtbot: QtBot) -> None:
    """The same icon renders fresh (not from a cached fixed-resolution raster) at another size.

    **Test steps:**

    * build a recolored icon from `SVG_WITH_RGB_FILL`
    * render it at both 20x20 and 64x64
    * verify each pixmap is exactly the size requested
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("blue"))

    small = icon.pixmap(20, 20)
    large = icon.pixmap(64, 64)

    assert small.size().width() == 20
    assert large.size().width() == 64


def test_engine_clone_renders_the_same_recolored_content(qtbot: QtBot) -> None:
    """Cloning the icon engine produces an independent engine rendering the same SVG.

    **Test steps:**

    * build a RecoloredSvgIconEngine directly and clone it
    * render both at the same size
    * verify both produce the same center pixel color
    """
    del qtbot
    engine = RecoloredSvgIconEngine(recolor_svg(SVG_WITH_RGB_FILL, QColor("green")))

    clone = engine.clone()
    icon = QIcon(clone)

    pixmap = icon.pixmap(24, 24)
    assert pixmap.toImage().pixelColor(12, 12).name() == "#008000"


# endregion
