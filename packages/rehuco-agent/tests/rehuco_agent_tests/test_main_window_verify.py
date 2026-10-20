"""Tests for how the main window wires the disk to the open documents: what the feed reports reaches them (#487, #511),
and the folders of those under no root are watched while the window is up."""

from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_registry import DocumentRegistry
from rehuco_agent.documents.held_files_watch import HeldFilesWatch
from rehuco_agent.main_window import MainWindow
from rehuco_agent.rehuco import RootCatalog
from rehuco_core.access import Changed, ResourceKey
from rehuco_core.notify import WatchedFolder

from .test_main_window import (  # noqa: F401  # pylint: disable=unused-import
    mock_persistent_settings,
    serve_tutorials,
)

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545), but
where a test asks for the real ones (``real_settings_pages``, ``real_sub_docks``)."""

RECORD: Final = Path.cwd() / "fake" / "tutorials" / "sculpting" / "info.rehu"


def registry_of(window: MainWindow) -> DocumentRegistry:
    """The window's document registry.

    :param window: the window.
    :returns: its registry.
    """
    return window._MainWindow__document_registry  # type: ignore[attr-defined]  # pylint: disable=protected-access


def catalog_of(window: MainWindow) -> RootCatalog:
    """The window's Root Catalog.

    :param window: the window.
    :returns: its catalog.
    """
    return window._MainWindow__root_catalog  # type: ignore[attr-defined]  # pylint: disable=protected-access


def disk_of(window: MainWindow) -> HeldFilesWatch:
    """The disk side of the window's registry.

    :param window: the window.
    :returns: its watch.
    """
    watch = registry_of(window).findChild(HeldFilesWatch)
    assert isinstance(watch, HeldFilesWatch)
    return watch


@fixture(name="notifiers")
def fixture_notifiers(mocker: MockerFixture) -> MagicMock:
    """Stand in for the file notifier the open documents' folders get.

    :param mocker: pytest-mock fixture.
    :returns: the stand-in class.
    """
    return mocker.patch("rehuco_agent.documents.held_files_watch.FileNotifier")


def test_a_change_on_the_windows_feed_has_the_open_documents_file_read(mocker: MockerFixture, qtbot: QtBot) -> None:
    """What a notifier publishes on the window's feed reaches the registry, which reads the file of the open document
    it touched, for the model to follow or flag (#511).

    **Test steps:**

    * open a document, and stand in for the registry's read
    * publish its file as changed on the window's feed
    * verify the file was read
    """
    serve_tutorials(mocker)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_path(RECORD)
    reads = mocker.patch.object(disk_of(window), "read")

    registry_of(window).resource_events.changes.publish(Changed((ResourceKey(RECORD),)))

    assert list(reads.call_args.args[0]) == [ResourceKey(RECORD)]


def test_the_open_documents_under_no_root_follow_the_roots(
    notifiers: MagicMock, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """The registry asks the window's catalog where the roots are, and asks again whenever the roots change: a document
    under a root is the root's notifier's, and one whose root went gets its folder watched.

    **Test steps:**

    * give the catalog a root holding a document's folder, and open it
    * verify no folder of its own is watched
    * take the root away and say the roots changed
    * verify the document's folder is watched now
    """
    serve_tutorials(mocker)
    window = MainWindow()
    qtbot.addWidget(window)
    roots = {uuid4(): RECORD.parent.parent}
    mocker.patch.object(catalog_of(window), "root_paths", side_effect=lambda: dict(roots))
    window.open_path(RECORD)

    notifiers.assert_not_called()

    roots.clear()
    catalog_of(window).roots_changed.emit()

    notifiers.assert_called_once()
    assert notifiers.call_args.args[0] == WatchedFolder(RECORD.parent, None, True)


def test_closing_the_window_stops_watching_the_open_documents_folders(
    notifiers: MagicMock, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Nothing reaches a window that is going: the open documents' folder notifiers are stopped when it closes.

    **Test steps:**

    * open a document under no root, and verify its folder got a notifier
    * close the window
    * verify the notifier was stopped
    """
    serve_tutorials(mocker)
    window = MainWindow()
    qtbot.addWidget(window)
    mocker.patch.object(catalog_of(window), "root_paths", return_value={})
    window.open_path(RECORD)
    notifiers.return_value.start.assert_called_once_with()

    window.close()

    notifiers.return_value.stop.assert_called_once_with()
