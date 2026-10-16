"""Tests for the local node's heartbeat, log, stop triggers and main loop (#506)."""

import io
import json
import logging
import signal
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_core import AppFolders
from rehuco_node import __version__
from rehuco_node.local_node import (
    HEARTBEAT_FILE_NAME,
    LOG_FILE_NAME,
    NODE_FOLDER_NAME,
    STALE_AFTER_SECONDS,
    LocalNode,
    NodeHeartbeat,
    install_signal_handlers,
    node_folder,
    read_heartbeat,
    setup_logging,
    watch_stdin,
)

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)


def heartbeat(beat: datetime = NOW) -> NodeHeartbeat:
    """A heartbeat written at ``beat``."""
    return NodeHeartbeat(
        pid=42, version="0.0.1", started=NOW.isoformat(timespec="seconds"), beat=beat.isoformat(timespec="seconds")
    )


def test_node_folder_sits_under_the_data_folder(tmp_path: Path) -> None:
    """The node keeps its files in ``node/`` under the shared data folder, and nothing is created by asking.

    **Test steps:**

    * ask for the node folder of app folders rooted at ``tmp_path``
    * verify the path and that it does not exist yet
    """
    folder = node_folder(AppFolders.single(tmp_path))

    assert folder == tmp_path / NODE_FOLDER_NAME
    assert not folder.exists()


def test_heartbeat_round_trips_through_json() -> None:
    """A heartbeat's JSON text parses back to an equal heartbeat.

    **Test steps:**

    * serialize a heartbeat and parse the text
    * verify equality and that the text is a JSON object with the four keys
    """
    original = heartbeat()

    text = original.to_json()

    assert NodeHeartbeat.from_json(text) == original
    assert set(json.loads(text)) == {"pid", "version", "started", "beat"}


def test_heartbeat_rejects_text_that_is_not_one() -> None:
    """Garbage, a JSON list, and an object missing a key each raise ``ValueError``.

    **Test steps:**

    * parse three bad texts
    * verify each raises ``ValueError``
    """
    for text in ("not json", "[1, 2]", '{"pid": 1}', '{"pid": "x", "version": "v", "started": "s", "beat": "b"}'):
        with raises(ValueError):
            NodeHeartbeat.from_json(text)


def test_heartbeat_age_and_freshness() -> None:
    """A heartbeat is fresh while younger than the stale limit, and its age is measured from ``now``.

    **Test steps:**

    * measure a heartbeat written 1 s ago and one written past the stale limit
    * verify the ages and the freshness answers, and that ``now`` defaults to the current time
    """
    recent = heartbeat(NOW - timedelta(seconds=1))
    old = heartbeat(NOW - timedelta(seconds=STALE_AFTER_SECONDS + 1))

    assert recent.age(NOW) == 1
    assert recent.is_fresh(NOW)
    assert old.age(NOW) == STALE_AFTER_SECONDS + 1
    assert not old.is_fresh(NOW)
    assert heartbeat(datetime.now(UTC)).is_fresh()


def test_read_heartbeat_answers_none_for_a_missing_or_unreadable_file(tmp_path: Path) -> None:
    """No file, or a file that is not a heartbeat, both read as ``None``; a good file reads as the heartbeat.

    **Test steps:**

    * read from an empty folder, from a garbage file, and from a real heartbeat
    * verify ``None``, ``None`` and the heartbeat
    """
    assert read_heartbeat(tmp_path) is None
    (tmp_path / HEARTBEAT_FILE_NAME).write_text("garbage", encoding="utf-8")
    assert read_heartbeat(tmp_path) is None
    (tmp_path / HEARTBEAT_FILE_NAME).write_text(heartbeat().to_json(), encoding="utf-8")
    assert read_heartbeat(tmp_path) == heartbeat()


def test_setup_logging_writes_the_node_log_in_the_folder(tmp_path: Path) -> None:
    """The handler creates the folder, rotates as the only writer, and records what is logged.

    **Test steps:**

    * set up logging in a folder that does not exist yet and log one line
    * verify the folder and the log file exist and hold the line
    * detach and close the handler
    """
    folder = tmp_path / "node"
    handler = setup_logging(folder)
    try:
        logging.getLogger("rehuco_node_tests.probe").info("hello from the test")
        handler.flush()
        assert handler.rotates is True
        assert "hello from the test" in (folder / LOG_FILE_NAME).read_text(encoding="utf-8")
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def test_watch_stdin_sets_stop_at_eof() -> None:
    """The watcher reads the stream to its end and then sets the stop event.

    **Test steps:**

    * watch a stream holding a few bytes
    * verify the stop event is set once the thread finishes
    """
    stop = threading.Event()

    thread = watch_stdin(stop, io.BytesIO(b"abc"))
    thread.join(5)

    assert stop.is_set()
    assert not thread.is_alive()


def test_watch_stdin_sets_stop_when_the_stream_breaks() -> None:
    """A stream that raises (a broken pipe, a closed file) counts as the host being gone.

    **Test steps:**

    * watch a closed ``BytesIO``, whose read raises ``ValueError``
    * verify the stop event is set
    """
    stop = threading.Event()
    stream = io.BytesIO(b"x")
    stream.close()

    watch_stdin(stop, stream).join(5)

    assert stop.is_set()


def test_signal_handlers_set_stop(mocker: MockerFixture) -> None:
    """SIGINT and SIGTERM are routed to a handler that sets the stop event.

    **Test steps:**

    * install the handlers with ``signal.signal`` patched to record them
    * call the recorded handler
    * verify both signals were registered and the event is set
    """
    recorded: dict[int, object] = {}
    mocker.patch.object(signal, "signal", side_effect=lambda signum, handler: recorded.update({signum: handler}))
    stop = threading.Event()

    install_signal_handlers(stop)
    recorded[signal.SIGTERM](signal.SIGTERM, None)  # type: ignore[operator]

    assert set(recorded) == {signal.SIGINT, signal.SIGTERM}
    assert stop.is_set()


def test_run_writes_the_heartbeat_and_removes_it_when_stopped(tmp_path: Path, mocker: MockerFixture) -> None:
    """The loop writes a heartbeat with this process's pid and version at once, beats again while running, and
    removes the file on the way out.

    **Test steps:**

    * run the node with a tiny heartbeat period on a thread, wait for two beats, stop it
    * verify the heartbeat was a fresh one with the pid and version while running, and is gone after
    """
    mocker.patch("rehuco_node.local_node.os.getpid", return_value=4242)
    node = LocalNode(AppFolders.single(tmp_path), heartbeat_seconds=0.05)
    stop = threading.Event()
    seen: list[NodeHeartbeat] = []

    def watch() -> None:
        """Collect distinct heartbeats until two were seen, then stop the node."""
        while len(seen) < 2 and not stop.is_set():
            current = read_heartbeat(node.folder)
            if current is not None and (not seen or current.beat != seen[-1].beat or current == seen[-1]):
                if not seen or current != seen[-1]:
                    seen.append(current)
            threading.Event().wait(0.02)
        stop.set()

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    node.run(stop)
    watcher.join(5)

    assert seen
    assert seen[0].pid == 4242
    assert seen[0].version == __version__
    assert seen[0].is_fresh()
    assert not (node.folder / HEARTBEAT_FILE_NAME).exists()


def test_run_logs_and_goes_on_when_a_beat_or_the_removal_fails(tmp_path: Path, mocker: MockerFixture, caplog) -> None:
    """A beat that cannot be written is a warning, not the end of the node; so is a removal that fails.

    **Test steps:**

    * patch the atomic write and the unlink to raise ``OSError``
    * run with the stop event already set, so the loop beats once and leaves
    * verify both warnings were logged
    """
    mocker.patch("rehuco_node.local_node.atomic_write_text", side_effect=OSError("disk full"))
    mocker.patch.object(Path, "unlink", side_effect=OSError("busy"))
    stop = threading.Event()
    stop.set()

    with caplog.at_level(logging.WARNING, logger="rehuco_node.local_node"):
        LocalNode(AppFolders.single(tmp_path)).run(stop)

    assert "could not write the heartbeat" in caplog.text
    assert "could not remove the heartbeat" in caplog.text
