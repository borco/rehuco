"""Tests for recolor_svg/recolored_svg_icon and their backing RecoloredSvgIconEngine."""

from borco_pyside.theming.svg_recolor import RecoloredSvgIconEngine, recolor_svg, recolored_svg_icon
from PySide6.QtCore import QSize
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


def test_recolored_svg_icon_with_on_color_renders_a_distinct_checked_variant(qtbot: QtBot) -> None:
    """Passing ``on_color`` gives ``State.On`` its own color, while ``State.Off`` keeps ``color``.

    **Test steps:**

    * build a recolored icon with ``color`` red and ``on_color`` blue
    * render the ``Off`` and ``On`` state pixmaps
    * verify ``Off`` is red and ``On`` is blue
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"), QColor("blue"))

    off = icon.pixmap(QSize(24, 24), QIcon.Mode.Normal, QIcon.State.Off)
    on = icon.pixmap(QSize(24, 24), QIcon.Mode.Normal, QIcon.State.On)

    assert off.toImage().pixelColor(12, 12).name() == "#ff0000"
    assert on.toImage().pixelColor(12, 12).name() == "#0000ff"


def test_recolored_svg_icon_with_disabled_color_renders_a_distinct_disabled_variant(qtbot: QtBot) -> None:
    """Passing ``disabled_color`` gives ``Mode.Disabled`` its own color.

    A custom icon engine gets no automatic disabled-greying from Qt (that fallback only applies to
    the default pixmap-based engine), so without this the disabled variant would render identically
    to the enabled one -- confirmed as the actual bug behind an always-enabled-looking toolbar button.

    **Test steps:**

    * build a recolored icon with ``color`` red and ``disabled_color`` grey
    * render the ``Normal``/``Off`` and ``Disabled``/``Off`` pixmaps
    * verify ``Normal`` is red and ``Disabled`` is grey
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"), disabled_color=QColor("grey"))

    normal = icon.pixmap(QSize(24, 24), QIcon.Mode.Normal, QIcon.State.Off)
    disabled = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.Off)

    assert normal.toImage().pixelColor(12, 12).name() == "#ff0000"
    assert disabled.toImage().pixelColor(12, 12).name() == QColor("grey").name()


def test_recolored_svg_icon_disabled_wins_over_checked_when_both_apply(qtbot: QtBot) -> None:
    """A disabled *and* checked icon renders the disabled variant, not the checked one.

    **Test steps:**

    * build a recolored icon with distinct ``color``/``on_color``/``disabled_color``
    * render ``Mode.Disabled`` + ``State.On`` together
    * verify it's the disabled color, not the checked one
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"), QColor("blue"), QColor("grey"))

    disabled_and_checked = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.On)

    assert disabled_and_checked.toImage().pixelColor(12, 12).name() == QColor("grey").name()


def test_recolored_svg_icon_with_on_disabled_color_renders_a_distinct_disabled_checked_variant(qtbot: QtBot) -> None:
    """Passing ``on_disabled_color`` gives disabled+checked its own look, distinct from disabled+unchecked.

    A disabled *toggle* that mirrors a model flag (e.g. a "dirty" indicator the user can't click) still
    needs to visually show checked-ness while disabled -- without this, it would look identical whether
    checked or not.

    **Test steps:**

    * build a recolored icon with distinct ``color``/``on_color``/``disabled_color``/``on_disabled_color``
    * render ``Mode.Disabled`` for both ``State.Off`` and ``State.On``
    * verify each renders its own color, not collapsed to one flat disabled look
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"), QColor("blue"), QColor("grey"), QColor("purple"))

    disabled_off = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.Off)
    disabled_on = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.On)

    assert disabled_off.toImage().pixelColor(12, 12).name() == QColor("grey").name()
    assert disabled_on.toImage().pixelColor(12, 12).name() == QColor("purple").name()


def test_recolored_svg_icon_disabled_checked_falls_back_to_disabled_color(qtbot: QtBot) -> None:
    """Without ``on_disabled_color``, disabled+checked falls back to the plain ``disabled_color``.

    **Test steps:**

    * build a recolored icon with ``disabled_color`` but no ``on_disabled_color``
    * render ``Mode.Disabled`` + ``State.On``
    * verify it renders ``disabled_color``, not ``on_color``
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"), on_color=QColor("blue"), disabled_color=QColor("grey"))

    disabled_on = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.On)

    assert disabled_on.toImage().pixelColor(12, 12).name() == QColor("grey").name()


def test_recolored_svg_icon_disabled_checked_falls_back_to_on_color_with_no_disabled_variant(qtbot: QtBot) -> None:
    """With neither ``disabled_color`` nor ``on_disabled_color``, disabled+checked falls back to ``on_color``.

    **Test steps:**

    * build a recolored icon with only ``on_color`` set
    * render ``Mode.Disabled`` + ``State.On``
    * verify it renders ``on_color`` (no disabled-specific variant exists at all)
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"), on_color=QColor("blue"))

    disabled_on = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.On)

    assert disabled_on.toImage().pixelColor(12, 12).name() == QColor("blue").name()


def test_recolored_svg_icon_without_disabled_color_falls_back_to_color(qtbot: QtBot) -> None:
    """Omitting ``disabled_color`` leaves ``Mode.Disabled`` rendering in ``color`` (prior behavior).

    **Test steps:**

    * build a recolored icon with no ``disabled_color``
    * render ``Mode.Disabled``
    * verify it matches ``color``, unchanged from the enabled look
    """
    del qtbot
    icon = recolored_svg_icon(SVG_WITH_RGB_FILL, QColor("red"))

    disabled = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.Off)

    assert disabled.toImage().pixelColor(12, 12).name() == "#ff0000"


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


def test_engine_clone_preserves_the_disabled_variant(qtbot: QtBot) -> None:
    """Cloning an engine that carries a disabled variant preserves it.

    **Test steps:**

    * build a RecoloredSvgIconEngine with a disabled variant and clone it
    * render the clone's disabled pixmap
    * verify it still renders the disabled color, not the base one
    """
    del qtbot
    engine = RecoloredSvgIconEngine(
        recolor_svg(SVG_WITH_RGB_FILL, QColor("green")), disabled_svg=recolor_svg(SVG_WITH_RGB_FILL, QColor("grey"))
    )

    clone = engine.clone()
    icon = QIcon(clone)

    pixmap = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.Off)
    assert pixmap.toImage().pixelColor(12, 12).name() == QColor("grey").name()


def test_engine_clone_preserves_the_on_disabled_variant(qtbot: QtBot) -> None:
    """Cloning an engine that carries a disabled+checked variant preserves it.

    **Test steps:**

    * build a RecoloredSvgIconEngine with an on-disabled variant and clone it
    * render the clone's disabled+checked pixmap
    * verify it still renders the on-disabled color
    """
    del qtbot
    engine = RecoloredSvgIconEngine(
        recolor_svg(SVG_WITH_RGB_FILL, QColor("green")),
        on_disabled_svg=recolor_svg(SVG_WITH_RGB_FILL, QColor("purple")),
    )

    clone = engine.clone()
    icon = QIcon(clone)

    pixmap = icon.pixmap(QSize(24, 24), QIcon.Mode.Disabled, QIcon.State.On)
    assert pixmap.toImage().pixelColor(12, 12).name() == QColor("purple").name()


# endregion
