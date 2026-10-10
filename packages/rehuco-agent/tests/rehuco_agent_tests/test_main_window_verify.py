"""Tests for how the main window wires verify-on-access between the catalog and the open documents (#487)."""

from pathlib import Path
from typing import Final

from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import MainWindow

from .test_main_window import (  # noqa: F401  # pylint: disable=unused-import
    mock_persistent_settings,
    serve_tutorials,
)

RECORD: Final = Path.cwd() / "fake" / "tutorials" / "sculpting" / "info.rehu"


def test_a_refreshed_catalog_has_the_open_documents_files_looked_at(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A scan's end refreshes the catalog, and says nothing of which records it read: the files the open documents
    stand for are looked at, so each can follow or flag what changed (#487).

    **Test steps:**

    * open a document, then say the catalog refreshed
    * verify the catalog was asked to read that document's file
    """
    serve_tutorials(mocker)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_path(RECORD)
    catalog = window._MainWindow__root_catalog  # type: ignore[attr-defined]  # pylint: disable=protected-access
    read = mocker.patch.object(catalog, "read_signatures")

    catalog.refreshed.emit()

    (paths,), _ = read.call_args
    assert list(paths) == [RECORD]


def test_what_the_catalog_saw_on_disk_reaches_the_open_documents(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The catalog's report of a file goes to the model that stands for it (#487).

    **Test steps:**

    * open a document, and report its file as the catalog would
    * verify its model heard
    """
    serve_tutorials(mocker)
    window = MainWindow()
    qtbot.addWidget(window)
    window.open_path(RECORD)
    registry = window._MainWindow__document_registry  # type: ignore[attr-defined]  # pylint: disable=protected-access
    model = registry.find(RECORD)
    noted = mocker.patch.object(model, "note_file_signature")
    catalog = window._MainWindow__root_catalog  # type: ignore[attr-defined]  # pylint: disable=protected-access

    catalog.files_seen.emit({RECORD: (7, 3)})

    noted.assert_called_once_with(7, 3)
