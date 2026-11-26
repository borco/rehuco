"""Tests for what a browser's *Copy paths* puts on the clipboard (#646): each selected row's key resolved through the
catalog to its resource -- a directory-scoped record's folder, a standalone record's file -- written as plain text.

The browsers run over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served.
"""

import datetime
import threading
from pathlib import Path
from typing import Any, Final
from unittest.mock import Mock
from uuid import UUID

from PySide6.QtGui import QClipboard, QGuiApplication
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.copied_paths import CopiedPath, CopyFormat, json_paths, quoted_paths
from rehuco_core import CatalogRecord, CatalogRow, LicenseTerms, LicenseTermsSet, RecordKind, write_license_terms

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

QUOTED: Final = CopyFormat("Copy paths", quoted_paths)
"""The plain copy, as the browser's menu offers it."""

AS_JSON: Final = CopyFormat("Copy paths as JSON", json_paths, names_licenses=True)
"""The JSON copy, which looks for each asset's license text."""

TERMS: Final = LicenseTermsSet(
    {"fab-standard": LicenseTerms("Standard License", "https://example.com/eula", datetime.date(2026, 11, 18), "Terms")}
)
"""What a record's ``.rehuterms`` holds."""


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
    first_browser(dock).copy_paths_requested.emit(KEYS, QUOTED, frozenset())

    assert board.text() == f'"{TUTORIALS / "python"}"\n"{PACKS / "pack.rehu"}"'
    mime = board.mimeData()
    assert mime is not None and not mime.hasUrls()


def test_copy_paths_as_json_writes_the_same_paths_as_a_list(
    qtbot: QtBot, dock: CatalogDocks, board: QClipboard
) -> None:
    """The format is the one the entry asked for.

    **Test steps:**

    * ask the first browser to copy both rows' paths as JSON
    * verify the clipboard holds the two resources' paths as a JSON list, no asset named so no license looked for
    """
    first_browser(dock).copy_paths_requested.emit(KEYS, AS_JSON, frozenset())

    qtbot.waitUntil(lambda: board.text() != UNTOUCHED, timeout=WAIT_TIMEOUT_MS)
    assert board.text() == json_paths([CopiedPath(TUTORIALS / "python"), CopiedPath(PACKS / "pack.rehu")])


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
    first_browser(dock).copy_paths_requested.emit(KEYS, QUOTED, frozenset())
    assert board.text() == f'"{PACKS / "pack.rehu"}"'

    mocker.patch.object(dock.catalog, "root_paths", return_value={})
    board.setText(UNTOUCHED)
    first_browser(dock).copy_paths_requested.emit(KEYS, QUOTED, frozenset())
    assert board.text() == UNTOUCHED


@mark.usefixtures("real_path_stat")
def test_copy_paths_as_json_names_the_license_text_of_an_asset_that_has_one(
    qtbot: QtBot, mocker: MockerFixture, dock: CatalogDocks, board: QClipboard, tmp_path: Path
) -> None:
    """The text is looked for beside each asset the selection names, off the GUI thread, and the clipboard is set once
    it answers (#688).

    **Test steps:**

    * map both roots into a folder, with a ``.rehuterms`` beside the standalone record only
    * ask for both rows as JSON, both named assets
    * verify the clipboard still holds what it held as the question went out, then the paths, the license named for the
      record that has one and not for the other
    """
    tutorials, packs = tmp_path / "t", tmp_path / "p"
    packs.mkdir()
    write_license_terms(packs / "pack.rehu", TERMS)
    mocker.patch.object(
        dock.catalog, "root_paths", return_value={UUID(ROOT_IDS[0]): tutorials, UUID(ROOT_IDS[1]): packs}
    )

    first_browser(dock).copy_paths_requested.emit(KEYS, AS_JSON, frozenset(KEYS))

    qtbot.waitUntil(lambda: board.text() != UNTOUCHED, timeout=WAIT_TIMEOUT_MS)
    assert (
        json_paths([CopiedPath(tutorials / "python"), CopiedPath(packs / "pack.rehu", packs / "pack.rehuterms")])
        == board.text()
    )


def test_a_license_text_looked_for_that_is_not_there_is_not_named(
    qtbot: QtBot, mocker: MockerFixture, dock: CatalogDocks, board: QClipboard, tmp_path: Path
) -> None:
    """An asset with no ``.rehuterms`` is listed by its path alone, whatever the selection said of it.

    **Test steps:**

    * map the packs root to an empty folder and ask for the standalone record as an asset
    * verify its object has no license key
    """
    mocker.patch.object(dock.catalog, "root_paths", return_value={UUID(ROOT_IDS[1]): tmp_path})

    first_browser(dock).copy_paths_requested.emit(KEYS[1:], AS_JSON, frozenset(KEYS))

    qtbot.waitUntil(lambda: board.text() != UNTOUCHED, timeout=WAIT_TIMEOUT_MS)
    assert board.text() == json_paths([CopiedPath(tmp_path / "pack.rehu")])


def test_a_copy_that_fails_leaves_the_clipboard_as_it_was(
    qtbot: QtBot, dock: CatalogDocks, board: QClipboard, caplog: LogCaptureFixture
) -> None:
    """A worker's failure is logged and nothing is put down.

    **Test steps:**

    * make the format raise, and copy as JSON
    * verify the failure was logged and the clipboard is untouched
    """
    broken = CopyFormat("Copy paths as JSON", Mock(side_effect=OSError("disk gone")), names_licenses=True)

    with caplog.at_level("ERROR"):
        first_browser(dock).copy_paths_requested.emit(KEYS, broken, frozenset())
        qtbot.waitUntil(lambda: "disk gone" in caplog.text, timeout=WAIT_TIMEOUT_MS)

    assert board.text() == UNTOUCHED


def test_refresh_license_hands_the_records_of_the_selected_rows_on(
    mocker: MockerFixture, dock: CatalogDocks, board: QClipboard, tmp_path: Path
) -> None:
    """The catalog resolves each row to its ``.rehu``, in the order asked; a row whose root is gone is left out, and
    with none left nothing is asked for (#688).

    **Test steps:**

    * map both roots and ask to refresh both rows
    * verify the records of both were handed on
    * map one root and verify only its record was, then map none and verify nothing was
    """
    del board
    mocker.patch.object(
        dock.catalog, "root_paths", return_value={UUID(ROOT_IDS[0]): tmp_path / "t", UUID(ROOT_IDS[1]): tmp_path / "p"}
    )
    handed = mocker.Mock()
    dock.browsers.refresh_license_requested.connect(handed)

    first_browser(dock).refresh_license_requested.emit(KEYS)
    mocker.patch.object(dock.catalog, "root_paths", return_value={UUID(ROOT_IDS[1]): tmp_path / "p"})
    first_browser(dock).refresh_license_requested.emit(KEYS)
    mocker.patch.object(dock.catalog, "root_paths", return_value={})
    first_browser(dock).refresh_license_requested.emit(KEYS)

    assert [call.args[0] for call in handed.call_args_list] == [
        (tmp_path / "t" / "python" / "info.rehu", tmp_path / "p" / "pack.rehu"),
        (tmp_path / "p" / "pack.rehu",),
    ]


@mark.usefixtures("real_path_stat")
def test_an_asset_under_a_root_that_cannot_be_reached_is_not_asked_about_its_license(
    qtbot: QtBot, mocker: MockerFixture, dock: CatalogDocks, board: QClipboard, tmp_path: Path
) -> None:
    """Every question to a share that does not answer waits for it to time out, so none is asked: the asset is listed by
    its path alone, though its text is there.

    **Test steps:**

    * map the packs root to a folder holding the record's text, and mark the root unreachable
    * ask for the record as JSON, as an asset
    * verify its object has no license key
    """
    write_license_terms(tmp_path / "pack.rehu", TERMS)
    mocker.patch.object(dock.catalog, "root_paths", return_value={UUID(ROOT_IDS[1]): tmp_path})
    mocker.patch.dict(dock.browsers._BrowsersDock__offline, {UUID(ROOT_IDS[1]): "offline"})  # type: ignore[attr-defined]  # pylint: disable=protected-access

    first_browser(dock).copy_paths_requested.emit(KEYS[1:], AS_JSON, frozenset(KEYS))

    qtbot.waitUntil(lambda: board.text() != UNTOUCHED, timeout=WAIT_TIMEOUT_MS)
    assert board.text() == json_paths([CopiedPath(tmp_path / "pack.rehu")])


def test_a_plain_copy_outdates_a_json_copy_still_being_written(
    qtbot: QtBot, dock: CatalogDocks, board: QClipboard
) -> None:
    """The clipboard holds the last copy asked for: a JSON copy whose worker answers after a plain copy was made is
    dropped.

    **Test steps:**

    * hold the JSON copy's worker, ask for it, then make a plain copy and let the worker go
    * verify the clipboard holds the plain copy, and still does once the events are run
    """
    gate = threading.Event()
    held = CopyFormat("Copy paths as JSON", lambda paths: (gate.wait(5), json_paths(paths))[1], names_licenses=True)

    first_browser(dock).copy_paths_requested.emit(KEYS, held, frozenset())
    first_browser(dock).copy_paths_requested.emit(KEYS, QUOTED, frozenset())
    plain = board.text()
    gate.set()
    qtbot.wait(300)

    assert plain.startswith('"')
    assert board.text() == plain
