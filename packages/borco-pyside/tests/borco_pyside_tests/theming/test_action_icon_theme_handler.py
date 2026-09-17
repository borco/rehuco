"""Tests for ActionIconThemeHandler."""

from collections.abc import Callable
from typing import Any

import pytest
from borco_pyside.theming.action_icon_theme_handler import ActionIconThemeHandler
from borco_pyside.theming.checked_chrome import CheckedToolButtonChrome
from borco_pyside.theming.contrast import perceived_brightness
from PySide6.QtCore import QObject, QSize
from PySide6.QtGui import QAction, QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication
from pytest_mock import MockerFixture

SVG: bytes = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<rect width="10" height="10" style="fill:rgb(0,0,0)"/></svg>'
)


def test_read_file_raises_when_the_file_cannot_be_opened(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """A path that fails to open raises, instead of silently building an icon from nothing.

    **Test steps:**

    * mock QFile.open to fail
    * construct an ActionIconThemeHandler for that path
    * verify RuntimeError is raised, naming the path
    """
    mock_qfile(SVG, open_ok=False)

    with pytest.raises(RuntimeError, match="missing.svg"):
        ActionIconThemeHandler(make_action, "missing.svg")


def test_construction_raises_without_a_running_qapplication(
    make_action: QAction, mock_qfile: Callable[..., Any], mocker: MockerFixture
) -> None:
    """Construction requires a running QApplication, to have somewhere to install the event filter.

    **Test steps:**

    * mock QFile and QApplication.instance() to return None
    * construct an ActionIconThemeHandler
    * verify RuntimeError is raised
    """
    mock_qfile(SVG)
    mocker.patch("borco_pyside.theming.themed_icons.QApplication.instance", return_value=None)

    with pytest.raises(RuntimeError, match="QApplication"):
        ActionIconThemeHandler(make_action, "icon.svg")


def test_construction_builds_the_unchecked_icon_from_button_text_color(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """A freshly-constructed handler immediately sets an icon colored for the unchecked state.

    **Test steps:**

    * mock QFile to return a real recolorable SVG
    * construct an ActionIconThemeHandler for a non-checkable action
    * verify the action's icon renders in the app palette's ButtonText color
    """
    mock_qfile(SVG)

    ActionIconThemeHandler(make_action, "icon.svg")

    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText)
    pixmap = make_action.icon().pixmap(10, 10)
    assert pixmap.toImage().pixelColor(5, 5).name() == expected.name()


def test_the_single_icon_carries_both_state_variants(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """One ``QIcon`` holds both variants: unchecked (ButtonText) as ``Off``, checked as ``On``.

    Qt itself picks the variant from the action's checked state, so a state change that never emits
    ``toggled`` (a dock closed via its tab's ``[x]``, or ``CDockManager.restoreState()``) still
    shows the right colour -- this is the fix for the icon going white on such changes.

    **Test steps:**

    * construct a handler, then read the built icon's ``Off`` and ``On`` state pixmaps
    * verify ``Off`` renders in ButtonText and ``On`` in the color measured for the checked chrome
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg")

    icon = make_action.icon()
    off = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.Off)
    on = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.On)
    palette = QApplication.palette()
    assert off.toImage().pixelColor(5, 5).name() == palette.color(QPalette.ColorRole.ButtonText).name()
    expected_on = CheckedToolButtonChrome.glyph_color(palette, enabled=True)
    assert on.toImage().pixelColor(5, 5).name() == expected_on.name()


def test_the_checked_variant_contrasts_with_the_chrome_the_style_paints(
    make_action: QAction, mock_qfile: Callable[..., Any], drive_palette: Callable[..., QPalette]
) -> None:
    """The checked glyph is dark over a light checked button and light over a dark one.

    Hard-coding ``HighlightedText`` here was the second half of #304, and it is wrong in both
    directions: the Windows 11 dark palette fills a checked tool button with ``#4cc2ff`` and leaves
    ``HighlightedText`` at ``#ffffff`` (Qt's own style draws that button's text *black*), while
    `Fusion` fills a light one with ``#dcdcdc`` and takes ``ButtonText``. Driving the palette rather
    than the color scheme, because a theme switch cannot be observed under the offscreen platform.

    **Test steps:**

    * construct a handler, then drive the palette dark and read the checked corner
    * drive the palette light and read it again
    * verify the two corners land on opposite sides of the chrome each time
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg")

    def checked_glyph() -> float:
        pixmap = make_action.icon().pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.On)
        return perceived_brightness(pixmap.toImage().pixelColor(5, 5))

    dark_chrome = CheckedToolButtonChrome.glyph_color(drive_palette("#3c3c3c", "#1e1e1e"), enabled=True)
    assert checked_glyph() > 0.5, "a dark checked button needs a light glyph"
    assert perceived_brightness(dark_chrome) > 0.5

    light_chrome = CheckedToolButtonChrome.glyph_color(drive_palette("#ffffff", "#f3f3f3"), enabled=True)
    assert checked_glyph() <= 0.5, "a light checked button needs a dark glyph"
    assert perceived_brightness(light_chrome) <= 0.5


def test_companion_action_icon_has_no_checked_variant(
    make_action: QAction, make_companion_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """The ``companion`` action's icon keeps ``ButtonText`` for both the ``Off`` and ``On`` states,
    unlike the main action's own ``HighlightedText`` checked variant -- built for a plain menu row,
    where that recolor would render near-invisible against the menu's own background.

    **Test steps:**

    * construct a handler with a companion action
    * verify the companion's ``Off`` and ``On`` state pixmaps both render in ``ButtonText``
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg", companion=make_companion_action)

    icon = make_companion_action.icon()
    off = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.Off)
    on = icon.pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.On)
    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText).name()
    assert off.toImage().pixelColor(5, 5).name() == expected
    assert on.toImage().pixelColor(5, 5).name() == expected


def test_companion_action_starts_matching_the_main_actions_checked_state(
    make_action: QAction, make_companion_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """The companion action's checked state is synced from the main action immediately at
    construction, not just from then on.

    **Test steps:**

    * make the main action checkable and checked before constructing the handler
    * verify the companion starts out checked too
    """
    mock_qfile(SVG)
    make_action.setCheckable(True)
    make_action.setChecked(True)
    make_companion_action.setCheckable(True)

    ActionIconThemeHandler(make_action, "icon.svg", companion=make_companion_action)

    assert make_companion_action.isChecked() is True


def test_companion_action_checked_state_tracks_the_main_action(
    make_action: QAction, make_companion_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """The companion action's checkmark keeps tracking the main action's checked state after
    construction too -- e.g. when the main action's state changes some other way than through the
    companion itself.

    **Test steps:**

    * construct a handler with a companion action, both checkable
    * check the main action directly
    * verify the companion picked up the change
    """
    mock_qfile(SVG)
    make_action.setCheckable(True)
    make_companion_action.setCheckable(True)
    ActionIconThemeHandler(make_action, "icon.svg", companion=make_companion_action)

    make_action.setChecked(True)

    assert make_companion_action.isChecked() is True


def test_triggering_the_companion_action_triggers_the_main_action(
    make_action: QAction, make_companion_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """Triggering the companion action forwards to the main action, so clicking it in a menu
    actually performs the real toggle.

    **Test steps:**

    * construct a handler with a companion action, both checkable
    * trigger the companion action
    * verify the main action's checked state flipped
    """
    mock_qfile(SVG)
    make_action.setCheckable(True)
    make_companion_action.setCheckable(True)
    ActionIconThemeHandler(make_action, "icon.svg", companion=make_companion_action)

    make_companion_action.trigger()

    assert make_action.isChecked() is True


def test_resync_companion_checked_state_corrects_a_stale_companion(
    make_action: QAction, make_companion_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """``resync_companion_checked_state`` force-corrects the companion to match the main action's
    *current* checked state -- the fix for ``toggled``-based mirroring's known gap (some ways the
    main action's checked state changes, e.g. `QtAds`' ``DockableDialog.toggleView()``, don't emit
    ``toggled`` at all, leaving the companion silently stale, confirmed empirically).

    **Test steps:**

    * construct a handler with a companion, both checkable
    * check the main action, then force the companion back out of sync directly (standing in for a
      real desync path ``toggled`` can't observe, without needing a real `QtAds` dock to reproduce)
    * call ``resync_companion_checked_state``
    * verify the companion is checked again, matching the main action
    """
    mock_qfile(SVG)
    make_action.setCheckable(True)
    make_companion_action.setCheckable(True)
    handler = ActionIconThemeHandler(make_action, "icon.svg", companion=make_companion_action)
    make_action.setChecked(True)
    make_companion_action.setChecked(False)

    handler.resync_companion_checked_state()

    assert make_companion_action.isChecked() is True


def test_resync_companion_checked_state_is_a_noop_without_a_companion(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """Calling ``resync_companion_checked_state`` with no companion configured does nothing, and
    doesn't raise.

    **Test steps:**

    * construct a handler with no companion
    * call ``resync_companion_checked_state``
    * verify it doesn't raise
    """
    mock_qfile(SVG)
    handler = ActionIconThemeHandler(make_action, "icon.svg")

    handler.resync_companion_checked_state()


def test_the_single_icon_carries_a_disabled_variant_too(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """The built icon's ``Mode.Disabled`` variant is colored from the palette's own disabled group.

    A custom icon engine gets no automatic disabled-greying from Qt -- without this, a disabled
    action's icon would render identically to its enabled one (the actual bug this closes).

    **Test steps:**

    * construct a handler, then read the built icon's ``Disabled`` pixmap
    * verify it renders in the palette's ``ColorGroup.Disabled`` ``ButtonText``, not the enabled one
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg")

    icon = make_action.icon()
    disabled = icon.pixmap(QSize(10, 10), QIcon.Mode.Disabled, QIcon.State.Off)
    expected = QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    assert disabled.toImage().pixelColor(5, 5).name() == expected.name()


def test_the_single_icon_carries_a_disabled_checked_variant_too(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """The built icon's disabled+checked corner is measured against the *disabled* checked chrome.

    Distinct from plain ``Mode.Disabled`` (``State.Off``) -- a disabled *checkable* action (e.g. one
    mirroring a model flag the user can't toggle directly) still needs to show checked-ness while
    disabled, not collapse to one flat disabled look. Several styles fill a disabled checked button
    with a neutral shade rather than the accent they use when it is enabled, so the two corners are
    measured separately rather than sharing one answer.

    **Test steps:**

    * construct a handler, then read the built icon's disabled+checked pixmap
    * verify it renders in the color measured for a *disabled* checked button
    """
    mock_qfile(SVG)
    ActionIconThemeHandler(make_action, "icon.svg")

    icon = make_action.icon()
    disabled_checked = icon.pixmap(QSize(10, 10), QIcon.Mode.Disabled, QIcon.State.On)
    expected = CheckedToolButtonChrome.glyph_color(QApplication.palette(), enabled=False)
    assert disabled_checked.toImage().pixelColor(5, 5).name() == expected.name()


def test_set_icon_switches_the_source_svg_and_keeps_it_themed(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """set_icon swaps the source SVG, rebuilding the icon in the current theme's color.

    **Test steps:**

    * mock QFile to return one SVG, then a second, differently-shaped one
    * construct a handler, then call set_icon with a new path
    * verify the new icon still renders in the app palette's ButtonText color
    """
    mock_qfile(SVG)
    handler = ActionIconThemeHandler(make_action, "icon.svg")

    other_svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        b'<circle cx="5" cy="5" r="5" style="fill:rgb(0,0,0)"/></svg>'
    )
    mock_qfile(other_svg)

    handler.set_icon("other.svg")

    expected = QApplication.palette().color(QPalette.ColorRole.ButtonText)
    pixmap = make_action.icon().pixmap(10, 10)
    assert pixmap.toImage().pixelColor(5, 5).name() == expected.name()


def test_toggling_the_action_never_swaps_the_icon(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """Toggling the action never swaps the icon -- Qt picks the state variant from the one icon.

    **Test steps:**

    * construct a checkable handler and note the icon it assigned
    * check and uncheck the action
    * verify the action still holds the very same icon
    """
    mock_qfile(SVG)
    make_action.setCheckable(True)
    ActionIconThemeHandler(make_action, "icon.svg")
    original = make_action.icon().cacheKey()

    make_action.setChecked(True)
    make_action.setChecked(False)

    assert make_action.icon().cacheKey() == original


def test_the_icon_follows_a_palette_change_with_nothing_told_to_rebuild(
    make_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """The icon recolors itself on a palette change, with no rebuild and no signal reaching it.

    This is #304 stated exactly. The icon used to be rebuilt from a ``palette_changed``
    subscription, which made a glyph's correctness depend on that signal arriving at every one of the
    many handlers an app creates -- and with several documents restored from the session, a theme
    switch recolored only the one that happened to be focused. Nothing here is notified: the handler
    is destroyed outright before the palette changes, and the icon still comes out right, because the
    color is resolved as it paints.

    **Test steps:**

    * construct a handler, then delete it so nothing is left subscribed to anything
    * change the app's palette for real (ButtonText to a new color)
    * verify the unchecked variant renders in the new color anyway
    """
    mock_qfile(SVG)
    handler = ActionIconThemeHandler(make_action, "icon.svg")
    handler.setParent(None)
    del handler

    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original_palette = app.palette()
    try:
        palette = QPalette(original_palette)
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("lime"))
        app.setPalette(palette)

        pixmap = make_action.icon().pixmap(QSize(10, 10), QIcon.Mode.Normal, QIcon.State.Off)
        assert pixmap.toImage().pixelColor(5, 5).name() == "#00ff00"
    finally:
        app.setPalette(original_palette)


def test_two_actions_from_one_source_share_a_single_icon(
    make_action: QAction, make_companion_action: QAction, mock_qfile: Callable[..., Any]
) -> None:
    """Two actions themed from the same SVG are given the very same ``QIcon``.

    Sharing is what makes it impossible *in principle* for two windows -- or two restored documents --
    to disagree about one action's glyph, which is the shape #304 took.

    **Test steps:**

    * construct two independent handlers over the same source path
    * verify both actions ended up holding the same icon
    """
    mock_qfile(SVG)

    ActionIconThemeHandler(make_action, "icon.svg")
    ActionIconThemeHandler(make_companion_action, "icon.svg")

    assert make_action.icon().cacheKey() == make_companion_action.icon().cacheKey()


def test_defaults_to_being_parented_to_the_action(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """With no explicit parent, the handler is parented to the action it manages.

    **Test steps:**

    * mock QFile
    * construct a handler with no `parent` argument
    * verify its Qt parent is the action
    """
    mock_qfile(SVG)

    handler = ActionIconThemeHandler(make_action, "icon.svg")

    assert handler.parent() is make_action


def test_accepts_an_explicit_parent(make_action: QAction, mock_qfile: Callable[..., Any]) -> None:
    """An explicit `parent` argument overrides the default of parenting to the action.

    **Test steps:**

    * mock QFile
    * construct a handler with an explicit parent
    * verify its Qt parent is that object, not the action
    """
    mock_qfile(SVG)
    parent = QObject()

    handler = ActionIconThemeHandler(make_action, "icon.svg", parent)

    assert handler.parent() is parent
