"""Tests for what a browser's *Copy paths* puts on the clipboard (#646): each selected row's key resolved through the
catalog to its resource -- a directory-scoped record's folder, a standalone record's file -- written as plain text.

The browsers run over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served.
"""

from typing import Any, Final
from uuid import UUID

from PySide6.QtGui import QClipboard, QGuiApplication
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.copied_paths import json_paths, quoted_paths
from rehuco_core import CatalogRecord, CatalogRow, RecordKind

from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    PACKS,
    REHUCO_PATH,
    ROOT_IDS,
    TUTORIALS,
    WAIT_TIMEOUT_MS,
    CatalogDocks,
    catalog_row,
    first_browser,
    fixture_cache,
    fixture_cached_rows,
    fixture_catalog,
    fixture_dock,
    fixture_held,
    fixture_machine,
    fixture_no_open_scan,
    fixture_on_disk,
    fixture_queue,
    fixture_saves,
    fixture_served,
    tutorial_record,
)

KEYS: Final = ((UUID(ROOT_IDS[0]), "python/info.rehu"), (UUID(ROOT_IDS[1]), "pack.rehu"))
"""A directory-scoped record under the tutorials root and a standalone one under the packs root, as a browser names
them."""

UNTOUCHED: Final = "untouched"
"""What the clipboard holds before a test copies."""


@fixture(name="board")
def fixture_board(
    qtbot: QtBot, dock: CatalogDocks, cached_rows: list[CatalogRow], served: Any, clipboard: None
) -> QClipboard:
    """The catalog open over :data:`KEYS`' two rows, shown in the first browser, and the clipboard holding
    :data:`UNTOUCHED`.

    :param qtbot: pytest-qt fixture.
    :param dock: the docks.
    :param cached_rows: the rows the catalog holds.
    :param served: the served ``.rehuco``.
    :param clipboard: the shared fixture, which puts back what the developer had on the clipboard (#485).
    :returns: the application's clipboard.
    """
    del served, clipboard
    cached_rows.extend(
        [
            catalog_row(1, 0, tutorial_record()),
            catalog_row(2, 1, CatalogRecord("pack.rehu", RecordKind.REHU, title="Pack", type="reference_images")),
        ]
    )
    dock.catalog.open_rehuco(REHUCO_PATH)
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 2, timeout=WAIT_TIMEOUT_MS)
    board = QGuiApplication.clipboard()
    board.setText(UNTOUCHED)
    return board


def test_copy_paths_puts_the_folder_of_a_directory_scoped_record_and_a_standalone_file_as_plain_text(
    dock: CatalogDocks, board: QClipboard
) -> None:
    """The rows resolve through the catalog to their resources, in the order asked, and only text is copied, so a
    paste into Explorer copies no folders.

    **Test steps:**

    * ask the first browser to copy both rows' paths, quoted
    * verify the folder of the ``info.rehu`` and the standalone ``.rehu`` itself, one quoted per line
    * verify the clipboard holds no file list
    """
    first_browser(dock).copy_paths_requested.emit(KEYS, quoted_paths)

    assert board.text() == f'"{TUTORIALS / "python"}"\n"{PACKS / "pack.rehu"}"'
    mime = board.mimeData()
    assert mime is not None and not mime.hasUrls()


def test_copy_paths_as_json_writes_the_same_paths_as_a_list(dock: CatalogDocks, board: QClipboard) -> None:
    """The format is the one the entry asked for.

    **Test steps:**

    * ask the first browser to copy both rows' paths as JSON
    * verify the clipboard holds the two resources' paths as a JSON list
    """
    first_browser(dock).copy_paths_requested.emit(KEYS, json_paths)

    assert board.text() == json_paths([TUTORIALS / "python", PACKS / "pack.rehu"])


def test_a_row_whose_root_is_gone_is_left_out_and_none_left_copies_nothing(
    mocker: MockerFixture, dock: CatalogDocks, board: QClipboard
) -> None:
    """A row the catalog no longer resolves has no path to copy; with no row left, the clipboard is left as it was.

    **Test steps:**

    * have the catalog map only the packs root, and copy both rows
    * verify only the pack's path was copied
    * have it map no root, reset the clipboard and copy both rows again
    * verify the clipboard is untouched
    """
    mocker.patch.object(dock.catalog, "root_paths", return_value={UUID(ROOT_IDS[1]): PACKS})
    first_browser(dock).copy_paths_requested.emit(KEYS, quoted_paths)
    assert board.text() == f'"{PACKS / "pack.rehu"}"'

    mocker.patch.object(dock.catalog, "root_paths", return_value={})
    board.setText(UNTOUCHED)
    first_browser(dock).copy_paths_requested.emit(KEYS, quoted_paths)
    assert board.text() == UNTOUCHED
