"""Tests for TypeBadge: the type chip's on_type slot, plugin colors, and palette fallback (#83)."""

from PySide6.QtCore import QEvent
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.type_badge import TypeBadge

COLORS: dict[str, tuple[str | None, str | None]] = {
    "tutorial": ("#1E88E5", "#FFFFFF"),
    "audiopack": (None, None),
}


def colors_for(type_key: str) -> tuple[str | None, str | None]:
    """A test type-to-``(background, text)`` resolver, both ``None`` (palette fallback) when unmapped."""
    return COLORS.get(type_key, (None, None))


def label_for(type_key: str) -> str:
    """A test type-to-label resolver: the key title-cased."""
    return type_key.title()


def make_badge(qtbot: QtBot) -> TypeBadge:
    """Build a `TypeBadge` over the test resolvers, registered for teardown."""
    badge = TypeBadge(colors_for, label_for)
    qtbot.addWidget(badge)
    return badge


def test_type_badge_is_a_label_with_a_smaller_font(qtbot: QtBot) -> None:
    """A `TypeBadge` is a ``QLabel`` whose font is smaller than the inherited one (the badge trait).

    **Test steps:**

    * build a badge and compare its font size against a plain label's
    * verify the badge's font is the scaled-down size
    """
    badge = make_badge(qtbot)
    plain = QLabel()
    qtbot.addWidget(plain)

    assert isinstance(badge, QLabel)
    assert badge.font().pointSizeF() == plain.font().pointSizeF() * TypeBadge.FONT_SCALE


def test_on_type_paints_the_plugin_declared_colors(qtbot: QtBot) -> None:
    """``on_type`` shows the type label and paints the chip with the plugin's declared colors.

    **Test steps:**

    * call ``on_type`` with a type whose plugin declares both colors
    * verify the label shows and the stylesheet carries both declared colors
    """
    badge = make_badge(qtbot)

    badge.on_type("tutorial")

    assert badge.text() == "Tutorial"
    style = badge.styleSheet()
    assert "background-color: #1E88E5" in style
    assert "color: #FFFFFF" in style


def test_on_type_falls_back_to_the_palette_selection_colors(qtbot: QtBot) -> None:
    """An undeclared (``None``) color falls back to the theme's selection color -- the palette
    ``Highlight`` background and ``HighlightedText`` text ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * call ``on_type`` for a type whose plugin declares no colors
    * verify the stylesheet uses the palette's highlight and highlighted-text colors
    """
    badge = make_badge(qtbot)

    badge.on_type("audiopack")

    palette = badge.palette()
    style = badge.styleSheet()
    assert f"background-color: {palette.color(QPalette.ColorRole.Highlight).name()}" in style
    assert f"color: {palette.color(QPalette.ColorRole.HighlightedText).name()}" in style


def test_on_type_does_not_show_a_parentless_badge(qtbot: QtBot) -> None:
    """Seeding a still-parentless badge never shows it -- ``on_type`` never touches visibility at all
    (see its own docstring), so a still-parentless badge simply keeps Qt's own default unshown state
    rather than flashing as a momentary top-level window. The badge still takes its label and colors, and
    shows normally once parented and its ancestor window is shown.

    **Test steps:**

    * build a badge (parentless, as the form does before adding it to its row) and seed a real type
    * verify it took the label but stayed unshown -- no momentary top-level window
    """
    badge = make_badge(qtbot)

    badge.on_type("tutorial")

    assert badge.text() == "Tutorial"
    assert badge.isVisible() is False


def test_on_type_blanks_the_badge_for_an_empty_type(qtbot: QtBot) -> None:
    """An empty type shows no badge -- the chip blanks its text and style rather than hiding the widget
    itself ([[plugins#plugin-blocks]], #83).

    Deliberately never touches visibility (see ``on_type``'s own docstring): a widget hidden and later
    re-shown before its top-level window has ever been shown -- exactly a session-restore placeholder's
    own sequence (#66) -- stays invisible forever after, a confirmed Qt/``QToolBarLayout`` quirk. Blanking
    the content instead sidesteps it entirely.

    **Test steps:**

    * paint a badge with a real type, then call ``on_type`` with the empty type
    * verify the label and stylesheet are both cleared
    """
    badge = make_badge(qtbot)
    badge.on_type("tutorial")

    badge.on_type("")

    assert badge.text() == ""
    assert badge.styleSheet() == ""


def test_a_theme_change_restyles_a_palette_fallback_badge_without_recursing(qtbot: QtBot) -> None:
    """A genuine palette (theme) change re-styles a palette-fallback badge, and the guard keeps
    ``setStyleSheet``'s own synchronous ``PaletteChange`` from recursing ([[plugins#plugin-blocks]], #83).

    **Test steps:**

    * show a palette-fallback badge, then deliver a ``PaletteChange`` event to it
    * verify it re-applied a stylesheet (no ``RecursionError``) using the current palette
    """
    badge = make_badge(qtbot)
    badge.on_type("audiopack")

    QApplication.sendEvent(badge, QEvent(QEvent.Type.PaletteChange))

    style = badge.styleSheet()
    assert f"background-color: {badge.palette().color(QPalette.ColorRole.Highlight).name()}" in style
