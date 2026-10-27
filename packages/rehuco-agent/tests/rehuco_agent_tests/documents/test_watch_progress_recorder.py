"""Tests for the recorder that paces a player's positions into a document's progress (#316)."""

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.watch_progress_recorder import WRITE_INTERVAL_MS, WatchProgressRecorder

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

SHORT_MS = 10
"""An interval short enough to wait out in a test."""


@fixture(name="model")
def fixture_model(mocker: MockerFixture) -> RehuDocumentModel:
    """A stand-in for the model the recorder writes to, whose own write is tested with the model.

    :param mocker: pytest-mock fixture.
    :returns: the autospecced model.
    """
    return mocker.create_autospec(RehuDocumentModel, instance=True)


def test_the_default_pace_is_about_five_seconds() -> None:
    """The cadence the issue names: a debounced write every ~5 s.

    **Test steps:**

    * read the interval
    * verify it is five seconds
    """
    assert WRITE_INTERVAL_MS == 5000


def test_positions_are_written_once_per_interval_and_the_latest_wins(
    qtbot: QtBot, model: RehuDocumentModel, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A player reporting every tick costs one write, of its newest position.

    **Test steps:**

    * report three positions of one video inside one interval
    * wait for the interval
    * verify one write, of the last position
    """
    recorder = delete_at_teardown(WatchProgressRecorder(model, interval_ms=SHORT_MS))
    recorder.position("a.mp4", 1.0, 100.0)
    recorder.position("a.mp4", 2.0, 100.0)
    recorder.position("a.mp4", 3.0, 100.0)

    qtbot.waitUntil(lambda: model.record_progress.call_count == 1)  # type: ignore[attr-defined]
    qtbot.wait(4 * SHORT_MS)

    model.record_progress.assert_called_once_with("a.mp4", 3.0, 100.0)  # type: ignore[attr-defined]


def test_a_flush_writes_at_once_and_leaves_nothing_for_the_timer(
    qtbot: QtBot, model: RehuDocumentModel, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Pause, seek, stop and close do not wait for the interval, and are not written twice.

    **Test steps:**

    * report a position, flush, and wait out the interval
    * verify the position was written once, at the flush
    """
    recorder = delete_at_teardown(WatchProgressRecorder(model, interval_ms=SHORT_MS))
    recorder.position("a.mp4", 7.0, None)

    recorder.flush()

    model.record_progress.assert_called_once_with("a.mp4", 7.0, None)  # type: ignore[attr-defined]
    qtbot.wait(4 * SHORT_MS)
    model.record_progress.assert_called_once()  # type: ignore[attr-defined]


def test_a_flush_with_nothing_waiting_writes_nothing(
    model: RehuDocumentModel, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Closing a player that never played costs no write.

    **Test steps:**

    * flush a recorder that was told nothing
    * verify no write
    """
    del qtbot
    recorder = delete_at_teardown(WatchProgressRecorder(model))

    recorder.flush()

    model.record_progress.assert_not_called()  # type: ignore[attr-defined]


def test_switching_video_writes_the_one_left_behind(
    model: RehuDocumentModel, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A position for another video never overwrites the last position of the previous one.

    **Test steps:**

    * report a position on one video and then on another
    * verify the first was written at once, and the second still waits; flushing writes it
    """
    del qtbot
    recorder = delete_at_teardown(WatchProgressRecorder(model))
    recorder.position("a.mp4", 9.0, 10.0)

    recorder.position("b.mp4", 1.0, 20.0)

    model.record_progress.assert_called_once_with("a.mp4", 9.0, 10.0)  # type: ignore[attr-defined]
    recorder.flush()
    assert model.record_progress.call_args.args == ("b.mp4", 1.0, 20.0)  # type: ignore[attr-defined]
