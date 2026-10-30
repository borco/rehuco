"""Tests for a tutorial's player dock in its document's sub-docks: where it sits, what a double-clicked video does to
it, and what closing it or the document does to what plays (#317)."""

from unittest.mock import Mock, call

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.theming import themed_svg_icon
from PySide6.QtWidgets import QToolBar
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_fields import VIEWER_DESCRIPTION_TAB
from rehuco_agent.documents.document_sub_docks import (
    PLAYER_DOCK_MIN_HEIGHT,
    PLAYER_DOCK_NAME,
    PLAYER_DOCK_TITLE,
    PLAYER_ICON_RESOURCE,
)
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.player_view import PlayerView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WatchProgressRecorder
from rehuco_core import RehuDocument

from .test_document_widget import layout_dock_entries


@fixture(name="model")
def fixture_model() -> RehuDocumentModel:
    """A view-model over a tutorial.

    :returns: the model.
    """
    return RehuDocumentModel(RehuDocument({"type": "Tutorial", "sources": [{"title": "Foo", "primary": True}]}))


@fixture(name="widget")
def fixture_widget(qtbot: QtBot, model: RehuDocumentModel) -> DocumentWidget:
    """A tutorial's document widget.

    :param qtbot: pytest-qt fixture.
    :param model: the document.
    :returns: the widget.
    """
    widget = DocumentWidget(model)
    qtbot.addWidget(widget)
    return widget


@fixture(name="pack")
def fixture_pack(qtbot: QtBot) -> DocumentWidget:
    """A reference pack's document widget -- a type with a dock of its own, but not the player.

    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    widget = DocumentWidget(
        RehuDocumentModel(
            RehuDocument({"type": "ReferenceImages", "sources": [{"title": "Pack", "primary": True}]}),
        )
    )
    qtbot.addWidget(widget)
    return widget


def player_dock(widget: DocumentWidget) -> QtAds.CDockWidget:
    """A document's player dock.

    :param widget: the document's widget.
    :returns: the dock.
    """
    dock = widget.sub_docks._DocumentSubDocks__player_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert dock is not None
    return dock


def files_view_of(widget: DocumentWidget) -> QtAds.CDockWidget:
    """A document's Files dock.

    :param widget: the document's widget.
    :returns: the dock.
    """
    return widget.sub_docks._DocumentSubDocks__files_dock  # type: ignore[attr-defined]  # pylint: disable=protected-access


def toolbar_of(widget: DocumentWidget) -> QToolBar:
    """A document's toolbar.

    :param widget: the document's widget.
    :returns: the toolbar.
    """
    return widget.findChildren(QToolBar)[0]


def test_a_tutorial_has_a_player_dock_that_starts_hidden(widget: DocumentWidget) -> None:
    """**Test steps:**

    * build a tutorial's widget
    * verify the dock hosts a `PlayerView`, is named and titled, and its toggle is unchecked
    """
    dock = player_dock(widget)

    assert isinstance(dock.widget(), PlayerView)
    assert dock.objectName() == PLAYER_DOCK_NAME
    assert dock.windowTitle() == PLAYER_DOCK_TITLE
    assert dock.toggleViewAction().isChecked() is False


def test_the_player_toggle_is_on_the_toolbar_with_its_own_icon(widget: DocumentWidget) -> None:
    """The type's own toggles close the common run, ahead of the layout button.

    **Test steps:**

    * verify the toolbar carries the player's toggle right after the Files one
    * verify the toggle's icon was built from the tutorial icon
    """
    action = player_dock(widget).toggleViewAction()
    actions = toolbar_of(widget).actions()

    assert actions.index(action) == actions.index(files_view_of(widget).toggleViewAction()) + 1
    assert action.icon().cacheKey() == themed_svg_icon(PLAYER_ICON_RESOURCE).cacheKey()


def test_the_player_dock_hosts_its_view_directly_with_a_floor(widget: DocumentWidget) -> None:
    """The player lays out its own surface and bar, so no scroll area wraps it, and a splitter cannot squeeze the dock
    under its floor.

    **Test steps:**

    * verify the view is parented directly on the dock and the dock's minimum height is the floor
    """
    dock = player_dock(widget)

    assert dock.widget().parentWidget() is dock
    assert dock.minimumSizeHint().height() == PLAYER_DOCK_MIN_HEIGHT


def test_a_reference_pack_has_no_player(widget: DocumentWidget, pack: DocumentWidget) -> None:
    """**Test steps:**

    * build a tutorial's and a reference pack's widgets
    * verify only the tutorial built a player, and the pack's toolbar carries no toggle titled for it
    """
    assert isinstance(player_dock(widget).widget(), PlayerView)
    assert pack.sub_docks._DocumentSubDocks__player_dock is None  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert PLAYER_DOCK_TITLE not in [action.text() for action in toolbar_of(pack).actions()]


def test_a_layout_that_never_names_the_player_puts_it_back_hidden(widget: DocumentWidget) -> None:
    """Adding a dock to a type resets nobody's layout: a layout saved before the player existed restores, and the
    player comes back hidden beside the Description View, where construction stacks it.

    **Test steps:**

    * save the widget's state with the player open, then drop its entry from the layout
    * restore it
    * verify it restored, the player is hidden, and it sits in the Description View's area
    """
    player_dock(widget).toggleView(True)
    payload = cbor2.loads(widget.save_state())
    for entry in layout_dock_entries(payload["dock_manager"]):
        if entry["name"] == PLAYER_DOCK_NAME:
            entry["name"] = "no such dock"

    assert widget.restore_state(cbor2.dumps(payload)) is True

    description = widget.sub_docks._DocumentSubDocks__viewer_docks[VIEWER_DESCRIPTION_TAB]  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert player_dock(widget).toggleViewAction().isChecked() is False
    assert player_dock(widget).dockAreaWidget() is description.dockAreaWidget()  # pylint: disable=no-member


def test_a_video_double_clicked_in_the_files_dock_is_jumped_to_in_the_player_and_shown(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * have the Files dock report a video activated
    * verify the player dock was shown and made current
    * verify the player was told to jump to the video, and the dock's showing loaded nothing over it
    """
    jump = mocker.patch.object(PlayerView, "jump")
    load_last = mocker.patch.object(PlayerView, "load_last")
    dock = player_dock(widget)

    files_view_of(widget).widget().video_activated.emit("02.mp4")  # type: ignore[union-attr]

    assert dock.toggleViewAction().isChecked() is True
    assert dock.isCurrentTab() is True  # type: ignore[attr-defined]
    jump.assert_called_once_with("02.mp4", None)
    # the jump comes first, so a dock shown by it finds the player already asked
    assert load_last.call_count == 1


def test_a_second_double_click_points_the_same_player_at_the_other_video(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """One player per document: a second video does not make a second player.

    **Test steps:**

    * have the Files dock report a video, then another
    * verify both reached the document's one player, and no other was built
    """
    jump = mocker.patch.object(PlayerView, "jump")

    files_view_of(widget).widget().video_activated.emit("01.mp4")  # type: ignore[union-attr]
    files_view_of(widget).widget().video_activated.emit("02.mp4")  # type: ignore[attr-defined]

    assert jump.call_args_list == [call("01.mp4", None), call("02.mp4", None)]
    assert len(widget.findChildren(PlayerView)) == 1


def test_a_document_with_no_player_ignores_a_video_activation(pack: DocumentWidget, mocker: MockerFixture) -> None:
    """A type without a player has nothing to play with, whatever its Files dock reports.

    **Test steps:**

    * have a reference pack's Files dock report a video
    * verify nothing was jumped to and nothing raised
    """
    jump = mocker.patch.object(PlayerView, "jump")

    files_view_of(pack).widget().video_activated.emit("01.mp4")  # type: ignore[union-attr]

    jump.assert_not_called()


def test_showing_the_dock_loads_the_last_video_and_closing_it_stops_the_player(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """A video must not play on out of sight behind a closed dock, and its file is let go -- the OS refuses to rename a
    folder with a video open in it; showing the dock loads the video watched last, paused.

    **Test steps:**

    * show the player's dock
    * verify the last video was loaded and the player not stopped
    * close it
    * verify the player was stopped once, by the close
    """
    stop = mocker.patch.object(PlayerView, "stop")
    load_last = mocker.patch.object(PlayerView, "load_last")
    dock = player_dock(widget)

    dock.toggleView(True)
    load_last.assert_called_once_with()
    stop.assert_not_called()
    dock.toggleView(False)

    stop.assert_called_once_with()
    load_last.assert_called_once_with()


def test_a_record_loaded_into_a_shown_player_dock_loads_its_last_video(
    widget: DocumentWidget, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """The dock stays shown as a preview moves to another record, so no toggle tells the player: the load does.

    **Test steps:**

    * with the player dock hidden, finish a load and verify nothing was loaded
    * show the dock, then finish another load
    * verify the player was told to load the last video again
    """
    load_last = mocker.patch.object(PlayerView, "load_last")

    model.reloaded.emit()
    load_last.assert_not_called()
    player_dock(widget).toggleView(True)
    load_last.reset_mock()
    model.reloaded.emit()

    load_last.assert_called_once_with()


def test_closing_the_document_stops_the_player_before_the_recorder_is_flushed(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """The player records where it stopped, and only then is what waits written: the other way round, the last seconds
    would be left for a timer no one is left to wait for.

    **Test steps:**

    * detach the document's sub-docks, as closing the document does
    * verify the player was stopped, then the recorder flushed
    """
    calls = Mock()
    calls.attach_mock(mocker.patch.object(PlayerView, "stop"), "stop")
    calls.attach_mock(mocker.patch.object(WatchProgressRecorder, "flush"), "flush")

    widget.sub_docks.detach()

    assert calls.mock_calls == [call.stop(), call.flush()]


def test_stopping_playback_stops_the_player_then_flushes_the_recorder(
    widget: DocumentWidget, mocker: MockerFixture
) -> None:
    """What a document does before the record it shows is swapped, and before the app quits, as well as before it
    closes.

    **Test steps:**

    * stop the playback of a document's widget
    * verify the player was stopped, then the recorder flushed
    """
    calls = Mock()
    calls.attach_mock(mocker.patch.object(PlayerView, "stop"), "stop")
    calls.attach_mock(mocker.patch.object(WatchProgressRecorder, "flush"), "flush")

    widget.stop_playback()

    assert calls.mock_calls == [call.stop(), call.flush()]


def test_stopping_the_playback_of_a_document_with_no_player_only_flushes(
    pack: DocumentWidget, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * stop the playback of a reference pack's widget
    * verify the recorder was flushed, and nothing raised
    """
    flush = mocker.patch.object(WatchProgressRecorder, "flush")

    pack.stop_playback()

    flush.assert_called_once_with()


def test_a_type_switch_away_stops_the_player_and_takes_its_dock_with_it(
    widget: DocumentWidget, model: RehuDocumentModel, mocker: MockerFixture
) -> None:
    """A tutorial turned into another type is not left playing in a dock that is going.

    **Test steps:**

    * switch the tutorial to a reference pack
    * verify the player was stopped, and its dock and toggle are gone
    * switch back to a tutorial
    * verify a new player was built, hidden
    """
    stop = mocker.patch.object(PlayerView, "stop")
    toggle = player_dock(widget).toggleViewAction()

    model.resource_type = "reference_images"

    stop.assert_called_once_with()
    assert widget.sub_docks._DocumentSubDocks__player_dock is None  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert toggle not in toolbar_of(widget).actions()

    model.resource_type = "tutorial"

    assert player_dock(widget).toggleViewAction().isChecked() is False
    assert isinstance(player_dock(widget).widget(), PlayerView)
