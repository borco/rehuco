"""Tests for the player maximized over the document, the main window or the screen, its clicks and its info panel
(#574).

What a click means is ``test_player_clicks``'s; the overlay's focus discipline is the lightbox's tests', on the base
both share.
"""

from dataclasses import dataclass
from typing import Final

import cbor2
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QSplitter, QToolButton, QVBoxLayout, QWidget
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.player_overlay import PlayerOverlay
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode
from rehuco_agent.settings.videos_settings import shared_videos_settings
from rehuco_core import VideoFacts

from rehuco_agent_tests.qt_waits import wait_destroyed

from .player_view_support import (  # pylint: disable=unused-import
    Media,
    action_of,
    fixture_coordinator,  # noqa: F401
    fixture_listing,  # noqa: F401
    fixture_media,  # noqa: F401
    fixture_model,  # noqa: F401
    fixture_progress,  # noqa: F401
    fixture_recorder,  # noqa: F401
    load_paused,
    make_view,
    shown_of,
    start_playing,
)

CLICK_MS: Final = 50
"""How long a click waits for a second one in these tests."""

PAST_CLICK_MS: Final = 3 * CLICK_MS

SETTLE_MS: Final = 10
"""Long enough for the event loop to turn at least once, as it does many times between a user's clicks."""


@dataclass(frozen=True)
class Host:
    """A main window whose client area holds a document holding the player."""

    window: QMainWindow
    document: QWidget
    view: PlayerView


@fixture(name="host")
def fixture_host(qtbot: QtBot, model: RehuDocumentModel, recorder: WatchProgressRecorder) -> Host:
    """A shown, active main window with a document holding a player, the player focused.

    :param qtbot: pytest-qt fixture.
    :param model: the document's model.
    :param recorder: the recorder.
    :returns: the parts.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    central = QWidget()
    window.setCentralWidget(central)
    document = QWidget(central)
    QVBoxLayout(central).addWidget(document)
    view = make_view(qtbot, model, recorder, document=document, click_ms=CLICK_MS)
    QVBoxLayout(document).addWidget(view)
    window.resize(800, 600)
    window.show()
    window.activateWindow()
    qtbot.waitUntil(window.isActiveWindow)
    view.setFocus()
    qtbot.wait(SETTLE_MS)
    return Host(window, document, view)


def stage_of(view: PlayerView) -> QSplitter:
    """The player's stage: the picture and the panels beside it.

    :param view: the view.
    :returns: the stage, wherever it is.
    """
    return view.findChild(QSplitter, "stage_splitter") or overlay_stage()


def overlay_stage() -> QSplitter:
    """The stage of the player maximized now -- it is not the view's child while it is.

    :returns: the stage.
    """
    stage = only_overlay().findChild(QSplitter, "stage_splitter")
    assert isinstance(stage, QSplitter)
    return stage


def only_overlay() -> PlayerOverlay:
    """The one overlay a player is maximized in.

    :returns: the overlay.
    """
    overlays = [widget for widget in QApplication.allWidgets() if isinstance(widget, PlayerOverlay)]
    assert len(overlays) == 1
    return overlays[0]


def click_picture(
    qtbot: QtBot, picture: QWidget, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
) -> None:
    """Click the picture as a user does, through the window.

    :param qtbot: pytest-qt fixture.
    :param picture: the surface shown.
    :param modifiers: the keys held.
    """
    qtbot.mousePress(picture, Qt.MouseButton.LeftButton, modifiers, QPoint(5, 5))
    qtbot.mouseRelease(picture, Qt.MouseButton.LeftButton, modifiers, QPoint(5, 5))


def double_click_picture(
    qtbot: QtBot, picture: QWidget, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
) -> None:
    """Double-click the picture: two clicks within the interval, and the interval let pass, so a click after this is a
    run of its own.

    :param qtbot: pytest-qt fixture.
    :param picture: the surface shown.
    :param modifiers: the keys held at the second click.
    """
    click_picture(qtbot, picture)
    click_picture(qtbot, picture, modifiers)
    qtbot.wait(PAST_CLICK_MS)


def test_a_double_click_maximizes_a_playing_video_over_the_document_and_back(
    host: Host, media: Media, qtbot: QtBot
) -> None:
    """**Test steps:**

    * play a video, double-click its picture
    * verify the stage and the bar went into an overlay covering the document, the mode reads as the document's and
      the player was neither reopened nor paused
    * double-click again
    * verify the overlay is gone, the stage and the bar are back under the title and nothing was reopened or paused
    """
    start_playing(host.view, "01.mp4")
    picture = shown_of(host.view)
    for call in (media.set_source, media.play, media.pause, media.stop):
        call.reset_mock()

    double_click_picture(qtbot, picture)

    overlay = only_overlay()
    assert overlay.parentWidget() is host.document
    assert overlay.geometry() == host.document.rect()
    assert overlay_stage().parentWidget() is overlay
    assert host.view.maximized_mode is OverlayMode.DOCUMENT_OVERLAY

    with wait_destroyed(qtbot, overlay):
        double_click_picture(qtbot, picture)

    layout = host.view.layout()
    stage = host.view.findChild(QSplitter, "stage_splitter")
    controls = host.view.findChild(QWidget, "controls_bar")
    assert layout is not None and stage is not None and controls is not None
    assert (layout.indexOf(stage), layout.indexOf(controls)) == (layout.count() - 2, layout.count() - 1)
    assert host.view.maximized_mode is None
    for call in (media.set_source, media.play, media.pause, media.stop):
        call.assert_not_called()
    assert action_of(host.view, "play_pause_action").text() == "Pause"


@mark.parametrize("mode", list(OverlayMode))
def test_the_videos_page_names_the_surface(
    host: Host, model: RehuDocumentModel, mode: OverlayMode, qtbot: QtBot
) -> None:
    """**Test steps:**

    * set the Videos page's surface, load a video, double-click its picture
    * verify the overlay covers the document, the main window's client area, or the whole screen as a window
    """
    shared_videos_settings().maximize_mode = mode
    load_paused(host.view, model, "02.mp4")

    double_click_picture(qtbot, shown_of(host.view))

    overlay = only_overlay()
    assert host.view.maximized_mode is mode
    match mode:
        case OverlayMode.DOCUMENT_OVERLAY:
            assert overlay.parentWidget() is host.document
        case OverlayMode.APP_WINDOW_OVERLAY:
            assert overlay.parentWidget() is host.window.centralWidget()
        case OverlayMode.FULL_SCREEN:
            assert overlay.isWindow()
    overlay.close()


def test_a_key_held_at_the_double_click_picks_the_surface_over_the_setting(
    host: Host, model: RehuDocumentModel, qtbot: QtBot
) -> None:
    """**Test steps:**

    * with the document named on the Videos page, double-click the picture holding Ctrl
    * verify the player is maximized over the main window
    """
    load_paused(host.view, model, "02.mp4")

    double_click_picture(qtbot, shown_of(host.view), Qt.KeyboardModifier.ControlModifier)

    assert host.view.maximized_mode is OverlayMode.APP_WINDOW_OVERLAY
    assert only_overlay().parentWidget() is host.window.centralWidget()
    only_overlay().close()


def test_escape_and_the_restore_button_put_the_player_back(host: Host, model: RehuDocumentModel, qtbot: QtBot) -> None:
    """**Test steps:**

    * verify the restore button is hidden while the player is in its dock
    * maximize, verify the button shows, press Esc and verify the player is back and the button hidden
    * maximize again, click the restore button and verify the player is back
    """
    load_paused(host.view, model, "02.mp4")
    button = host.view.findChild(QToolButton, "restore_button")
    assert isinstance(button, QToolButton)
    assert button.isHidden()

    double_click_picture(qtbot, shown_of(host.view))
    assert not button.isHidden()
    with wait_destroyed(qtbot, only_overlay()):
        qtbot.keyClick(only_overlay(), Qt.Key.Key_Escape)
    assert host.view.maximized_mode is None
    assert button.isHidden()

    double_click_picture(qtbot, shown_of(host.view))
    with wait_destroyed(qtbot, only_overlay()):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)
    assert host.view.maximized_mode is None


def test_the_players_keys_work_while_it_is_maximized(host: Host, media: Media, qtbot: QtBot) -> None:
    """**Test steps:**

    * play a video and maximize it
    * verify the keyboard is in the overlay, and press Space where it is
    * verify the video paused
    """
    start_playing(host.view, "01.mp4")
    double_click_picture(qtbot, shown_of(host.view))
    overlay = only_overlay()
    focused = QApplication.focusWidget()
    # the video widget's native child may hold it: anywhere in the overlay arms the player's keys
    assert focused is not None and (focused is overlay or overlay.isAncestorOf(focused))

    qtbot.keyClick(focused, Qt.Key.Key_Space)

    assert action_of(host.view, "play_pause_action").text() == "Play"
    media.stop.assert_called()
    overlay.close()


def test_stopping_puts_a_maximized_player_back(host: Host, model: RehuDocumentModel, qtbot: QtBot) -> None:
    """Closing the dock or the document stops the player, which must not leave its stage on an overlay.

    **Test steps:**

    * maximize a loaded video and stop the player
    * verify the overlay is gone and the stage is back in the view
    """
    load_paused(host.view, model, "02.mp4")
    double_click_picture(qtbot, shown_of(host.view))

    with wait_destroyed(qtbot, only_overlay()):
        host.view.stop()

    assert host.view.maximized_mode is None
    assert host.view.findChild(QSplitter, "stage_splitter") is not None


def test_a_click_on_the_picture_pauses_and_plays_and_reports_the_press(host: Host, qtbot: QtBot) -> None:
    """**Test steps:**

    * play a video, click its picture once
    * verify the press was reported, and the video paused once the double-click interval passed
    """
    start_playing(host.view, "01.mp4")
    play_pause = action_of(host.view, "play_pause_action")

    with qtbot.waitSignal(host.view.surface_clicked):
        click_picture(qtbot, shown_of(host.view))

    assert play_pause.text() == "Pause"
    qtbot.waitUntil(lambda: play_pause.text() == "Play", timeout=PAST_CLICK_MS)


def test_a_click_that_brings_the_focus_to_the_player_also_pauses_it(host: Host, qtbot: QtBot) -> None:
    """The picture has nothing a stray click could harm: the click that focuses the player counts (owner).

    **Test steps:**

    * play a video, move the focus away from the player
    * click its picture once
    * verify the player took the focus, and the video paused once the interval passed
    """
    start_playing(host.view, "01.mp4")
    host.window.centralWidget().setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    host.window.centralWidget().setFocus()
    qtbot.wait(SETTLE_MS)

    click_picture(qtbot, shown_of(host.view))

    assert host.view.hasFocus()
    play_pause = action_of(host.view, "play_pause_action")
    qtbot.waitUntil(lambda: play_pause.text() == "Play", timeout=PAST_CLICK_MS)


def test_a_note_added_while_maximized_leaves_the_player_playing_and_maximized(
    host: Host, media: Media, qtbot: QtBot
) -> None:
    """*Add note at* works as it does docked: it asks for the line and changes nothing else (#574, owner).

    **Test steps:**

    * play a video at 42 seconds and maximize it
    * trigger *Add note at*
    * verify the note was asked for at 42 seconds, the video was not paused and the player is still maximized
    """
    start_playing(host.view, "01.mp4")
    double_click_picture(qtbot, shown_of(host.view))
    media.position.return_value = 42_000
    media.pause.reset_mock()
    media.stop.reset_mock()

    with qtbot.waitSignal(host.view.note_requested) as requested:
        action_of(host.view, "add_note_at_action").trigger()

    assert requested.args == ["01.mp4", 42.0]
    media.pause.assert_not_called()
    media.stop.assert_not_called()
    assert host.view.maximized_mode is OverlayMode.DOCUMENT_OVERLAY
    only_overlay().close()


def info_panel_of(view: PlayerView) -> QLabel:
    """The player's info panel.

    :param view: the view.
    :returns: the panel.
    """
    panel = view.findChild(QLabel, "info_panel")
    assert isinstance(panel, QLabel)
    return panel


def test_i_shows_the_videos_info_beside_the_picture(host: Host, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * have a Measure record the second video's size, load it paused and move it to 25 seconds
    * verify the info panel is hidden, then toggle the info action
    * verify the panel shows the video, its size, length, position with progress, and its place in the playlist
    * toggle it again and verify it is hidden
    """
    model.measured_videos.return_value = {"02.mp4": VideoFacts(100.0, 1920, 1080)}  # type: ignore[attr-defined]
    load_paused(host.view, model, "02.mp4")
    host.view.seek("02.mp4", 25.0)
    panel = info_panel_of(host.view)
    assert not panel.isVisibleTo(host.view)

    action_of(host.view, "info_action").trigger()

    assert panel.isVisibleTo(host.view)
    assert panel.text() == "02.mp4\n1920 × 1080 px\n1:40\n0:25 (25 %)\n[2/3]"
    action_of(host.view, "info_action").trigger()
    assert not panel.isVisibleTo(host.view)


def test_the_info_follows_the_position_while_it_is_shown(host: Host, model: RehuDocumentModel) -> None:
    """**Test steps:**

    * show the info, load a video paused
    * seek it to 50 seconds
    * verify the panel names the new position
    """
    action_of(host.view, "info_action").trigger()
    load_paused(host.view, model, "01.mp4")

    host.view.seek("01.mp4", 50.0)

    assert "0:50 (50 %)" in info_panel_of(host.view).text()


def test_the_stage_split_is_saved_and_restored(host: Host) -> None:
    """**Test steps:**

    * show the info, split the stage 500 to 200, and save the state
    * split it otherwise, then restore the saved state
    * verify the split is the saved one, and that a blob that cannot be read, or holds no split, changes nothing
    """
    action_of(host.view, "info_action").trigger()
    stage = stage_of(host.view)
    stage.setSizes([500, 200])
    saved_sizes = stage.sizes()
    state = host.view.save_state()

    stage.setSizes([300, 400])
    host.view.restore_state(state)
    # the panel's width is what was saved; the picture takes what the layout leaves, a few pixels either way
    assert stage.sizes()[1] == saved_sizes[1]

    host.view.restore_state(b"not cbor")
    host.view.restore_state(b"\x01")
    host.view.restore_state(cbor2.dumps({"another": b""}))
    assert stage.sizes()[1] == saved_sizes[1]


def test_a_click_with_no_video_loaded_plays_nothing(host: Host, media: Media, qtbot: QtBot) -> None:
    """**Test steps:**

    * with nothing loaded, click the picture
    * verify nothing was told to play once the interval passed
    """
    click_picture(qtbot, shown_of(host.view))
    qtbot.wait(PAST_CLICK_MS)

    media.play.assert_not_called()
    assert action_of(host.view, "play_pause_action").text() == "Play"


def test_the_info_reads_the_measured_size_once_per_video(host: Host, model: RehuDocumentModel) -> None:
    """The record's ``videos`` map is parsed whole at each read, and the panel follows every position.

    **Test steps:**

    * play a video, then show the info, which reads the measured videos once
    * have the player report three positions and verify nothing was read again
    """
    player = start_playing(host.view, "01.mp4")
    model.measured_videos.reset_mock()  # type: ignore[attr-defined]
    action_of(host.view, "info_action").trigger()
    assert model.measured_videos.call_count == 1  # type: ignore[attr-defined]

    for position_ms in (1_000, 2_000, 3_000):
        player.positionChanged.emit(position_ms)

    assert model.measured_videos.call_count == 1  # type: ignore[attr-defined]


def test_a_state_that_is_no_map_leaves_the_split_as_it_is(host: Host) -> None:
    """**Test steps:**

    * show the info and split the stage
    * restore a state that decodes to a list, and verify the split is unchanged
    """
    action_of(host.view, "info_action").trigger()
    stage = stage_of(host.view)
    stage.setSizes([500, 200])
    sizes = stage.sizes()

    host.view.restore_state(cbor2.dumps([1, 2]))

    assert stage.sizes() == sizes


def test_a_double_click_with_no_video_loaded_maximizes_nothing(host: Host, qtbot: QtBot) -> None:
    """**Test steps:**

    * with nothing loaded, double-click the picture
    * verify no overlay came up and the player is in its dock
    """
    double_click_picture(qtbot, shown_of(host.view))

    assert host.view.maximized_mode is None
    assert not [widget for widget in QApplication.allWidgets() if isinstance(widget, PlayerOverlay)]


def test_the_edit_notes_key_does_nothing_where_the_document_has_put_no_panels_in(host: Host) -> None:
    """**Test steps:**

    * select a video on a player the document has not given panels, and trigger its edit-notes action
    * verify nothing shows and nothing fails
    """
    host.view.load_last()

    action_of(host.view, "edit_notes_action").trigger()

    assert info_panel_of(host.view).isHidden()


def test_the_tree_and_notes_keys_do_nothing_where_the_document_has_put_no_panels_in(host: Host) -> None:
    """**Test steps:**

    * toggle the player's tree and notes on a player the document has not given panels
    * verify nothing shows and nothing fails
    """
    assert not host.view.panels.attached

    action_of(host.view, "tree_action").trigger()
    action_of(host.view, "notes_action").trigger()

    assert info_panel_of(host.view).isHidden()
