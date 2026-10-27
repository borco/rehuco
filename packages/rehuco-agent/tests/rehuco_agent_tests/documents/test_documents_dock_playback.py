"""Tests for what the Documents dock does about the players of its documents: stopping them as the app quits, and as the
preview moves on to another record (#317)."""

from unittest.mock import Mock, call

from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

from .test_documents_dock import FAKE_KEY, FAKE_PATH, OTHER_KEY, load_document


def test_stopping_playback_stops_every_documents_player_and_then_waits_for_the_writes(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """What quitting does: every player is stopped first, so each records where it stopped, and only then are the
    writes waited for, each within what is left of the one time allowed.

    **Test steps:**

    * open two documents, one in the preview, and spy on each one's stop and on each model's wait for its writes
    * stop playback, allowing two seconds
    * verify both players were stopped before either model was waited for, and each wait was given no more than the time
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    dock.open_document(FAKE_KEY)
    dock.show_in_preview(OTHER_KEY)
    calls = Mock()
    calls.attach_mock(mocker.patch.object(DocumentWidget, "stop_playback"), "stop")
    calls.attach_mock(mocker.patch.object(RehuDocumentModel, "wait_for_progress_writes", return_value=True), "wait")

    dock.stop_playback(2.0)

    assert [step[0] for step in calls.mock_calls] == ["stop", "stop", "wait", "wait"]
    assert all(0.0 <= step.args[0] <= 2.0 for step in calls.mock_calls[2:])


def test_a_spent_wait_gives_the_remaining_documents_no_time(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The wait is one budget shared by every document, so a share gone silent cannot hold up quitting once per
    document.

    **Test steps:**

    * open two documents and stop playback allowing no time at all
    * verify each model's wait was asked for nothing rather than a time of its own
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    dock.open_document(FAKE_KEY)
    dock.open_document(OTHER_KEY)
    mocker.patch.object(DocumentWidget, "stop_playback")
    wait = mocker.patch.object(RehuDocumentModel, "wait_for_progress_writes", return_value=False)

    dock.stop_playback(0.0)

    assert wait.call_args_list == [call(0.0), call(0.0)]


def test_a_preview_moving_on_stops_its_player_before_the_record_changes(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A player still going would record the old record's video under the new record: it is stopped while the preview
    still shows the one it was playing.

    **Test steps:**

    * show a document in the preview and spy on its stop, noting which record the preview shows when it runs
    * show another document in the preview
    * verify the player was stopped once, and the preview still showed the first record when it was
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    preview = dock.show_in_preview(FAKE_KEY)
    shown_when_stopped: list[object] = []
    stop = mocker.patch.object(
        DocumentWidget, "stop_playback", side_effect=lambda: shown_when_stopped.append(preview.model.path)
    )

    dock.show_in_preview(OTHER_KEY)

    stop.assert_called_once_with()
    assert shown_when_stopped == [FAKE_PATH]
