"""Tests for the host the app lends a record's move (#339): its roots read from this machine's mappings, its saves
asked of the save owner, and its steps run on the GUI thread while the worker waits, still stoppable.

Real threads: the subject is a worker handing a step to the GUI thread and what each does meanwhile.
"""

import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import UUID

from PySide6.QtCore import QCoreApplication, QThread
from pytest import LogCaptureFixture, raises
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.main_thread_move_host import MainThreadMoveHost
from rehuco_core import JobPaused, ResourceKey
from rehuco_core.root_mappings import FORMAT_VERSION, FORMAT_VERSION_KEY, PATH_KEY, ROOTS_KEY, STORAGE_KEY

ROOT_ID: Final = UUID("00000000-0000-0000-0000-000000000001")
WAIT_MS: Final = 5000
"""How long a test waits for a worker, in milliseconds -- generous, since it expires only when something is wrong."""


def on_worker(qtbot: QtBot, work: Callable[[], None]) -> list[BaseException]:
    """Run ``work`` on a worker thread while the GUI thread keeps dispatching, and wait for it.

    :param qtbot: pytest-qt fixture.
    :param work: what the worker does.
    :returns: what it raised, if anything.
    """
    raised: list[BaseException] = []

    def run() -> None:
        try:
            work()
        except BaseException as error:  # pylint: disable=broad-exception-caught  # handed back to the test
            raised.append(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    qtbot.waitUntil(lambda: not worker.is_alive(), timeout=WAIT_MS)
    return raised


# region roots and saves
def test_a_root_is_found_from_this_machines_mappings(tmp_path: Path) -> None:
    """A mapped root's folder is read from the mappings file when asked; an unmapped one has none.

    **Test steps:**

    * write a mappings file mapping a root, and build a host over it
    * check the root's folder is found, and another root's is not
    """
    mappings_path = tmp_path / "root-mappings.json"
    entry = {PATH_KEY: str(tmp_path / "Tutorials"), STORAGE_KEY: "local"}
    mappings_path.write_text(json.dumps({FORMAT_VERSION_KEY: FORMAT_VERSION, ROOTS_KEY: {str(ROOT_ID): entry}}))
    host = MainThreadMoveHost(mappings_path)

    assert host.root_folder(ROOT_ID) == tmp_path / "Tutorials"
    assert host.root_folder(UUID(int=2)) is None


def test_an_unreadable_mappings_file_maps_nothing(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """A mappings file that cannot be read maps no root, and says why in the log.

    **Test steps:**

    * write a mappings file that is not JSON, and ask for a root
    * check none is found and the failure was logged
    """
    mappings_path = tmp_path / "root-mappings.json"
    mappings_path.write_text("not json")

    with caplog.at_level(logging.ERROR):
        assert MainThreadMoveHost(mappings_path).root_folder(ROOT_ID) is None

    assert "Could not read the root mappings" in caplog.text


def test_a_save_is_pending_only_as_the_save_owner_says(tmp_path: Path) -> None:
    """Until the save owner is followed no save is pending; then a record's is when the owner holds one for it.

    **Test steps:**

    * ask a host with no save owner, then follow one holding a save for one record only
    * check the answers
    """
    record = tmp_path / "info.rehu"
    host = MainThreadMoveHost(tmp_path / "root-mappings.json")
    assert not host.save_pending(record)

    host.follow_pending_saves(lambda key: MagicMock() if key == ResourceKey(record) else None)

    assert host.save_pending(record)
    assert not host.save_pending(tmp_path / "other.rehu")


# endregion


# region steps
def test_a_step_asked_on_the_gui_thread_runs_there_at_once(tmp_path: Path) -> None:
    """Asked from the thread it lives on, a host runs the step at once, after the checkpoint.

    **Test steps:**

    * run a step from the GUI thread
    * check the checkpoint ran, then the step
    """
    calls: list[str] = []

    MainThreadMoveHost(tmp_path / "m.json").run_step(lambda: calls.append("step"), lambda: calls.append("checkpoint"))

    assert calls == ["checkpoint", "step"]


def test_a_workers_step_runs_on_the_gui_thread_and_its_error_comes_back(tmp_path: Path, qtbot: QtBot) -> None:
    """A worker's step runs on the GUI thread, the worker waiting for it; what the step raises, the worker raises.

    **Test steps:**

    * from a worker, run a step noting its thread, then one that raises
    * check the first ran on the GUI thread, and the second's error reached the worker
    """
    host = MainThreadMoveHost(tmp_path / "m.json")
    threads: list[QThread] = []

    def failing() -> None:
        raise PermissionError("denied")

    assert not on_worker(qtbot, lambda: host.run_step(lambda: threads.append(QThread.currentThread()), lambda: None))
    raised = on_worker(qtbot, lambda: host.run_step(failing, lambda: None))

    assert threads == [host.thread()]
    assert len(raised) == 1 and isinstance(raised[0], PermissionError)


def test_a_stop_before_the_step_starts_abandons_it(tmp_path: Path) -> None:
    """A pause asked while the step waits for the GUI thread abandons it: it never runs, and the pause comes out.

    **Test steps:**

    * from a worker, with the GUI thread not dispatching, run a step whose checkpoint raises a pause
    * let the GUI thread dispatch afterwards
    * check the worker raised the pause and the step never ran
    """
    host = MainThreadMoveHost(tmp_path / "m.json")
    ran: list[bool] = []
    raised: list[BaseException] = []

    def checkpoint() -> None:
        raise JobPaused("move")

    def work() -> None:
        try:
            host.run_step(lambda: ran.append(True), checkpoint)
        except JobPaused as error:
            raised.append(error)

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(WAIT_MS / 1000)
    QCoreApplication.processEvents()

    assert len(raised) == 1
    assert not ran


def test_a_stop_once_the_step_runs_is_waited_out(tmp_path: Path, qtbot: QtBot) -> None:
    """A pause asked while the step already runs cannot abandon it: the worker waits for it to finish, and returns.

    **Test steps:**

    * from a worker, run a step that asks for the pause and waits until the worker's checkpoint has raised it
    * check the step ran to its end and the worker returned without raising
    """
    host = MainThreadMoveHost(tmp_path / "m.json")
    stop = threading.Event()
    stopped = threading.Event()
    finished: list[bool] = []

    def checkpoint() -> None:
        if stop.is_set():
            stopped.set()
            raise JobPaused("move")

    def step() -> None:
        stop.set()
        stopped.wait(WAIT_MS / 1000)
        finished.append(True)

    raised = on_worker(qtbot, lambda: host.run_step(step, checkpoint))

    assert finished == [True]
    assert not raised
    with raises(JobPaused):
        checkpoint()


# endregion
