"""Tests for the Roots view's folder loader: every request answered, an answer for a deleted loader reaching nobody
(#378, #529)."""

import threading
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.root_folder_loader import RootFolderLoader
from rehuco_core import DirectoryListing, RootFolderLister

from rehuco_agent_tests.rehuco.test_roots_folder_model import WAIT_TIMEOUT_MS, make_root


def test_the_loader_answers_once_per_request_even_for_an_unreadable_folder(qtbot: QtBot, tmp_path: Path) -> None:
    """Every request is answered, an unreadable folder included, so a row can never wait for ever.

    **Test steps:**

    * ask the loader for a folder that does not exist
    * verify one answer, carrying the serial and an unreachable listing
    """
    root = make_root(tmp_path / "missing")
    loader = RootFolderLoader()

    with qtbot.waitSignal(loader.listed, timeout=WAIT_TIMEOUT_MS) as blocker:
        loader.start(7, RootFolderLister([root]), root.root_id, ())

    assert blocker.args is not None
    serial, listing = blocker.args
    assert serial == 7
    assert not listing.reachable


def test_a_loader_deleted_while_its_read_is_out_answers_nobody(qtbot: QtBot) -> None:
    """A loader deleted while a folder is still being read -- its model gone -- leaves the worker an answer for
    nobody; the emit on the deleted loader is swallowed on the pool thread rather than raised there (#529).

    **Test steps:**

    * start a read that waits, and delete the loader while it does
    * let the read finish and the pool settle
    * verify the pool settled
    """
    del qtbot
    release = threading.Event()

    class WaitingLister:  # pylint: disable=missing-class-docstring,too-few-public-methods
        def list(self, root_id: object, relative: object) -> DirectoryListing:  # pylint: disable=missing-function-docstring
            del root_id, relative
            release.wait(2)
            return DirectoryListing(Path(), reachable=False)

    loader = RootFolderLoader()
    loader.start(7, WaitingLister(), uuid4(), ())  # type: ignore[arg-type]
    loader.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    release.set()

    assert QThreadPool.globalInstance().waitForDone(2000)
