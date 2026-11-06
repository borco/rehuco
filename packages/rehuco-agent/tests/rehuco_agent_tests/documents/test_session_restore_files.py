"""Tests for what the Files and Checksums tables remember across a restart ([[plugins#session-restore]], #576): the
folder
browsed and the sort. Their columns stay auto-sized, so a sort is all there is to keep (owner)."""

# the tables are reached through their name-mangled members, as these views' own tests do
# pylint: disable=protected-access

from typing import Any

import cbor2
from PySide6.QtCore import Qt
from pytest import mark
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.checksum_view import ChecksumView
from rehuco_agent.documents.files_view import FilesView
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import DirectoryListing, RehuDocument

from .test_checksum_view import fixture_model as fixture_checksum_model  # noqa: F401  # pylint: disable=unused-import
from .test_checksum_view import (  # noqa: F401  # pylint: disable=unused-import
    fixture_queue,
    fixture_rows,
    fixture_runs,
)
from .test_checksum_view import fixture_view as fixture_checksum_view  # noqa: F401  # pylint: disable=unused-import
from .test_files_view import (  # noqa: F401  # pylint: disable=unused-import
    DIRECTORY,
    INFO_PATH,
    SUB,
    TIMEOUT,
    fixture_listing,
    fixture_record,
    settle,
)


def files_view(qtbot: QtBot, state: bytes | None = None) -> FilesView:
    """A shown browser over the resource, its first read landed.

    :param qtbot: pytest-qt fixture.
    :param state: a state to restore before it is shown.
    :returns: the view.
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH))
    view = FilesView(model)
    qtbot.addWidget(view)
    if state is not None:
        view.restore_state(state)
    view.show()
    settle(qtbot, view)
    return view


def test_the_folder_browsed_comes_back(qtbot: QtBot) -> None:
    """A browser in a subfolder goes back there, reading that folder and not the top first.

    **Test steps:**

    * restore a state naming the subfolder, then show the browser
    * verify it is in the subfolder, and its state says so
    """
    view = files_view(qtbot, cbor2.dumps({"folder": "sub"}))

    assert view.directory == SUB
    assert cbor2.loads(view.save_state())["folder"] == "sub"


def test_the_top_is_saved_as_the_top(qtbot: QtBot) -> None:
    """**Test steps:**

    * save the state of a browser at the resource's own folder
    * verify it names no subfolder
    """
    assert cbor2.loads(files_view(qtbot).save_state())["folder"] == "."


@mark.parametrize("folder", ["../elsewhere", "sub/../..", "C:/elsewhere", "/elsewhere", ".." + chr(92) + "x", 3, None])
def test_a_folder_that_would_leave_the_resource_is_not_gone_to(qtbot: QtBot, folder: Any) -> None:
    """A hand-damaged state stays inside the resource's folder, as the browser itself does.

    **Test steps:**

    * restore a state naming it, then show the browser
    * verify it is at the top
    """
    view = files_view(qtbot, cbor2.dumps({"folder": folder}))

    assert view.directory == DIRECTORY


def test_a_folder_no_longer_there_goes_back_to_the_top(qtbot: QtBot, listing: Any) -> None:
    """A subfolder gone since says so by its read, and the browser goes back to the top rather than saying *away*.

    **Test steps:**

    * make the subfolder's listing unreachable, and restore a state naming it
    * show the browser, and verify it ends up at the top
    """
    answer = listing.side_effect

    def classify(self: object, directory: Any) -> DirectoryListing:
        """Answer the subfolder as gone, and the rest as the module's listing does.

        :param self: the classifier.
        :param directory: the folder asked for.
        :returns: the listing.
        """
        return DirectoryListing(directory, reachable=False) if directory == SUB else answer(self, directory)

    listing.side_effect = classify
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, INFO_PATH))
    view = FilesView(model)
    qtbot.addWidget(view)
    view.restore_state(cbor2.dumps({"folder": "sub"}))

    view.show()

    qtbot.waitUntil(lambda: view.directory == DIRECTORY, timeout=TIMEOUT)


@mark.parametrize("state", [b"", b"not cbor", cbor2.dumps(["a list"])])
def test_a_state_it_cannot_read_changes_nothing(qtbot: QtBot, state: bytes) -> None:
    """**Test steps:**

    * restore it, and show the browser
    * verify it is at the top
    """
    assert files_view(qtbot, state).directory == DIRECTORY


def test_the_files_tables_sort_comes_back(qtbot: QtBot) -> None:
    """The sort is applied, not only drawn on the header.

    **Test steps:**

    * sort a browser's table by a column, descending, and save the state
    * restore it into another, and verify the header and the proxy sort alike
    """
    view = files_view(qtbot)
    table = view._FilesView__ui.file_view  # type: ignore[attr-defined]
    table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    state = view.save_state()

    restored = files_view(qtbot, state)

    header = restored._FilesView__ui.file_view.horizontalHeader()  # type: ignore[attr-defined]
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (1, Qt.SortOrder.DescendingOrder)
    assert (restored.proxy.sortColumn(), restored.proxy.sortOrder()) == (1, Qt.SortOrder.DescendingOrder)


def test_the_checksums_tables_sort_comes_back(view: ChecksumView) -> None:
    """**Test steps:**

    * sort the table by a column, descending, and save the state
    * sort it another way, and restore the state
    * verify the header and the proxy are back
    """
    table = view._ChecksumView__ui.file_view  # type: ignore[attr-defined]
    table.sortByColumn(1, Qt.SortOrder.DescendingOrder)
    state = view.save_state()
    table.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    view.restore_state(state)

    assert (view.proxy.sortColumn(), view.proxy.sortOrder()) == (1, Qt.SortOrder.DescendingOrder)


def test_a_header_state_qt_refuses_leaves_the_checksums_sort_alone(view: ChecksumView) -> None:
    """**Test steps:**

    * sort the table, and restore a state Qt does not recognise
    * verify the sort stays
    """
    view._ChecksumView__ui.file_view.sortByColumn(1, Qt.SortOrder.DescendingOrder)  # type: ignore[attr-defined]

    view.restore_state(b"not a header")

    assert (view.proxy.sortColumn(), view.proxy.sortOrder()) == (1, Qt.SortOrder.DescendingOrder)
