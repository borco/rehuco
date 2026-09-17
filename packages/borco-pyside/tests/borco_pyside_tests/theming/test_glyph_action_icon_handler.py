"""Tests for GlyphActionIconThemeHandler."""

from borco_pyside.theming.glyph_action_icon_handler import GlyphActionIconThemeHandler
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QColor, QPalette
from PySide6.QtWidgets import QApplication
from pytest import raises
from pytest_mock import MockerFixture

STAR_GLYPH = "\ue46a"
"""Phosphor's "star" glyph -- a real, solid icon shape guaranteed present in the loaded test font."""


def test_construction_raises_without_a_running_qapplication(make_action: QAction, mocker: MockerFixture) -> None:
    """Construction requires a running QApplication, to have somewhere to install the event filter.

    **Test steps:**

    * mock QApplication.instance() to return None
    * construct a GlyphActionIconThemeHandler
    * verify RuntimeError is raised
    """
    mocker.patch("borco_pyside.theming.glyph_action_icon_handler.QApplication.instance", return_value=None)

    with raises(RuntimeError, match="QApplication"):
        GlyphActionIconThemeHandler(make_action, STAR_GLYPH, "Arial")


def test_construction_builds_the_icon_from_the_given_palette_role(make_action: QAction, real_font_family: str) -> None:
    """A freshly-constructed handler immediately sets an icon colored from the given palette role.

    **Test steps:**

    * construct a handler for a non-default palette role
    * verify the action's icon renders in that role's color
    """
    GlyphActionIconThemeHandler(make_action, STAR_GLYPH, real_font_family, QPalette.ColorRole.ButtonText)

    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText)
    pixmap = make_action.icon().pixmap(16, 16)
    assert pixmap.toImage().pixelColor(8, 8).name() == expected.name()


def test_the_icon_follows_a_palette_change_with_nothing_told_to_rebuild(
    make_action: QAction, real_font_family: str
) -> None:
    """The glyph recolors itself on a palette change, with no rebuild and no signal reaching it.

    The glyph half of #304: this handler carried the same exposure as the SVG one, holding an icon
    that was only correct as long as a ``palette_changed`` subscription kept arriving. Nothing here
    is notified -- the handler is destroyed outright before the palette changes.

    **Test steps:**

    * construct a handler, then delete it so nothing is left subscribed to anything
    * change the app's palette for real (Text to a new color)
    * verify the icon renders in the new color anyway
    """
    handler = GlyphActionIconThemeHandler(make_action, STAR_GLYPH, real_font_family)
    handler.setParent(None)
    del handler

    # pylint: disable=duplicate-code
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_palette = app.palette()
    try:
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.Text, QColor("lime"))
        app.setPalette(palette)
        # pylint: enable=duplicate-code

        pixmap = make_action.icon().pixmap(16, 16)
        assert pixmap.toImage().pixelColor(8, 8).name() == "#00ff00"
    finally:
        app.setPalette(original_palette)


def test_defaults_to_being_parented_to_the_action(make_action: QAction) -> None:
    """With no explicit parent, the handler is parented to the action it manages.

    **Test steps:**

    * construct a handler with no `parent` argument
    * verify its Qt parent is the action
    """
    handler = GlyphActionIconThemeHandler(make_action, STAR_GLYPH, "Arial")

    assert handler.parent() is make_action


def test_accepts_an_explicit_parent(make_action: QAction) -> None:
    """An explicit `parent` argument overrides the default of parenting to the action.

    **Test steps:**

    * construct a handler with an explicit parent
    * verify its Qt parent is that object, not the action
    """
    parent = QObject()

    handler = GlyphActionIconThemeHandler(make_action, STAR_GLYPH, "Arial", parent=parent)

    assert handler.parent() is parent
