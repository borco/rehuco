"""Tests for the app's announcements of its own file changes (#376)."""

from pathlib import Path
from threading import Thread
from typing import Final

from PySide6.QtCore import QThread
from pytestqt.qtbot import QtBot
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import Relocation

FOLDER: Final = Path.cwd() / "fake" / "library" / "pack"
RELOCATION: Final = Relocation(((FOLDER, FOLDER.with_name("kit")),))
TIMEOUT: Final = 5000


def test_an_announcement_on_the_gui_thread_is_emitted_at_once(qtbot: QtBot) -> None:
    """A rename on the GUI thread is heard before the announcing call returns, so every holder has followed it
    by the time the renaming code goes on.

    **Test steps:**

    * announce each of the three kinds on the GUI thread, with no event loop turn
    * verify each was emitted synchronously with what was announced
    """
    del qtbot
    events = ResourceEvents()
    heard: list[object] = []
    events.moved.connect(heard.append)
    events.changed.connect(heard.append)
    events.folder_changed.connect(heard.append)

    events.announce_moved(RELOCATION)
    events.announce_changed([FOLDER / "info.rehu"])
    events.announce_folder_changed(FOLDER)

    assert heard == [RELOCATION, (FOLDER / "info.rehu",), FOLDER]


def test_an_announcement_off_the_gui_thread_arrives_on_it(qtbot: QtBot) -> None:
    """A rename asked for on another thread still reaches the listeners on the GUI thread.

    **Test steps:**

    * announce a move from a plain worker thread
    * verify the signal arrives, on the GUI thread
    """
    events = ResourceEvents()
    threads: list[QThread] = []
    events.moved.connect(lambda _relocation: threads.append(QThread.currentThread()))

    with qtbot.waitSignal(events.moved, timeout=TIMEOUT) as moved:
        worker = Thread(target=events.announce_moved, args=(RELOCATION,))
        worker.start()
        worker.join()

    assert moved.args == [RELOCATION]
    assert threads == [events.thread()]


def test_an_access_is_announced_with_the_records_opened(qtbot: QtBot) -> None:
    """Opening a record is announced, for the catalog to verify it (#487): nothing was written.

    **Test steps:**

    * announce two records as accessed
    * verify one announcement carries both
    """
    del qtbot
    events = ResourceEvents()
    heard: list[object] = []
    events.accessed.connect(heard.append)

    events.announce_accessed([FOLDER / "info.rehu", FOLDER / "foo.rehu"])

    assert heard == [(FOLDER / "info.rehu", FOLDER / "foo.rehu")]
