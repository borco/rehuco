"""Tests for what a browser's *Open in Explorer* reveals (#720): each selected row's key resolved through the catalog to
its resource -- a directory-scoped record's folder, a standalone record's file -- and handed to the file browser.

The browsers run over the mock catalog of ``test_catalog_docks``, with the ``.rehuco`` served.
"""

from typing import Any
from unittest.mock import Mock
from uuid import UUID

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import file_reveals
from rehuco_core import CatalogRecord, CatalogRow, RecordKind

from .test_browsers_copy_paths import KEYS
from .test_catalog_docks import (  # noqa: F401  # pylint: disable=unused-import
    PACKS,
    REHUCO_PATH,
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


@fixture(name="revealed")
def fixture_revealed(
    qtbot: QtBot, dock: CatalogDocks, cached_rows: list[CatalogRow], served: Any, mocker: MockerFixture
) -> Mock:
    """The catalog open over :data:`KEYS`' two rows, shown in the first browser, and the file browser mocked.

    :param qtbot: pytest-qt fixture.
    :param dock: the docks.
    :param cached_rows: the rows the catalog holds.
    :param served: the served ``.rehuco``.
    :param mocker: pytest-mock fixture.
    :returns: the mock standing for the system's file browser.
    """
    del served
    cached_rows.extend(
        [
            catalog_row(1, 0, tutorial_record()),
            catalog_row(2, 1, CatalogRecord("pack.rehu", RecordKind.REHU, title="Pack", type="reference_images")),
        ]
    )
    dock.catalog.open_rehuco(REHUCO_PATH)
    qtbot.waitUntil(lambda: first_browser(dock).model.rowCount() == 2, timeout=WAIT_TIMEOUT_MS)
    return mocker.patch.object(file_reveals, "reveal_in_file_browser")


def test_a_directory_scoped_record_opens_its_folder_and_a_standalone_one_selects_its_file(
    dock: CatalogDocks, revealed: Mock
) -> None:
    """The rows resolve through the catalog to their resources, in the order asked.

    **Test steps:**

    * ask the first browser to reveal both rows
    * verify the folder of the ``info.rehu`` and the standalone ``.rehu`` itself were revealed, in that order
    """
    first_browser(dock).reveal_requested.emit(KEYS)

    assert [call.args[0] for call in revealed.call_args_list] == [TUTORIALS / "python", PACKS / "pack.rehu"]


def test_a_row_whose_root_is_offline_or_not_in_the_catalog_opens_nothing_and_is_logged(
    dock: CatalogDocks, revealed: Mock, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A place this machine does not reach is named in the log, and the others still open.

    **Test steps:**

    * mark the packs root offline and ask for both rows, plus a row of a root the catalog does not list
    * verify only the tutorial was revealed
    * verify each of the other two rows was logged at INFO, the offline one by its full path
    """
    mocker.patch.dict(dock.browsers._BrowsersDock__offline, {KEYS[1][0]: "share off"})  # type: ignore[attr-defined]  # pylint: disable=protected-access
    unknown = (UUID(int=0), "gone.rehu")

    with caplog.at_level("INFO"):
        first_browser(dock).reveal_requested.emit((KEYS[0], KEYS[1], unknown))

    assert [call.args[0] for call in revealed.call_args_list] == [TUTORIALS / "python"]
    assert f"{PACKS / 'pack.rehu'} is not opened in the file browser: its root cannot be reached" in caplog.text
    assert "gone.rehu is not opened in the file browser: its root is not in the catalog" in caplog.text


def test_a_selection_no_root_resolves_opens_nothing(dock: CatalogDocks, revealed: Mock) -> None:
    """A selection no root resolves reveals nothing.

    **Test steps:**

    * ask for a row of a root the catalog does not list
    * verify nothing was revealed
    """
    first_browser(dock).reveal_requested.emit(((UUID(int=0), "gone.rehu"),))

    revealed.assert_not_called()
