"""Tests for the main window asking where this machine finds the roots of a catalog it has no mapping for (#514).

What the wizard shows and what the catalog does with an answer are their own tests' subject: here the catalog's
unmapped roots and the wizard's answer are stand-ins, and the window is shown to hand the answer on.
"""

from pathlib import Path
from typing import NamedTuple
from unittest.mock import MagicMock
from uuid import uuid4

from PySide6.QtWidgets import QMessageBox
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import MainWindow
from rehuco_agent.rehuco import RootCatalog
from rehuco_core import RehucoRoot

from .test_main_window import (  # noqa: F401  # pylint: disable=unused-import
    mock_persistent_settings,
    seed_remembered,
)

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545)."""

TUTORIALS = RehucoRoot(uuid4(), "Tutorials", "//nas/data/Tutorials")
MUSIC = RehucoRoot(uuid4(), "Music", "//nas/data/Music")


class Catalog(NamedTuple):
    """The stand-ins for the parts of the catalog the window asks and tells."""

    unmapped: MagicMock
    skip_roots: MagicMock
    map_root: MagicMock


@fixture(name="catalog")
def fixture_catalog(mocker: MockerFixture) -> Catalog:
    """A catalog that opens, has two unmapped roots, and takes whatever it is told.

    :param mocker: pytest-mock fixture.
    :returns: the stand-ins.
    """
    mocker.patch.object(RootCatalog, "open_rehuco", return_value=True)
    return Catalog(
        mocker.patch.object(RootCatalog, "unmapped_roots", return_value=(TUTORIALS, MUSIC)),
        mocker.patch.object(RootCatalog, "skip_roots", return_value=True),
        mocker.patch.object(RootCatalog, "map_root", return_value=True),
    )


@fixture(name="window")
def fixture_window(qtbot: QtBot) -> MainWindow:
    """A window with no catalog to reopen.

    :param qtbot: pytest-qt fixture.
    :returns: the window.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    return window


def test_an_opened_catalog_asks_about_its_unmapped_roots(
    mocker: MockerFixture, window: MainWindow, catalog: Catalog, tmp_path: Path
) -> None:
    """Opening a catalog with unmapped roots asks the wizard about them and hands the answer to the catalog.

    **Test steps:**

    * make the catalog report two unmapped roots, and the wizard answer a folder for one and a skip for the other
    * open a catalog
    * verify the wizard was asked about both roots, the skip was recorded, and the folder was mapped
    """
    ask = mocker.patch.object(
        window, "ask_root_mappings", return_value=({TUTORIALS.root_id: tmp_path}, [MUSIC.root_id])
    )

    assert window.open_rehuco_path("home.rehuco")

    ask.assert_called_once_with((TUTORIALS, MUSIC))
    catalog.skip_roots.assert_called_once_with([MUSIC.root_id])
    catalog.map_root.assert_called_once_with(TUTORIALS.root_id, tmp_path)


def test_nothing_is_asked_when_every_root_is_mapped(
    mocker: MockerFixture, window: MainWindow, catalog: Catalog
) -> None:
    """A catalog with nothing unmapped opens without a question.

    **Test steps:**

    * make the catalog report no unmapped roots, and spy on the wizard
    * open a catalog
    * verify the wizard was not asked and nothing was recorded
    """
    catalog.unmapped.return_value = ()
    ask = mocker.patch.object(window, "ask_root_mappings")

    assert window.open_rehuco_path("home.rehuco")

    ask.assert_not_called()
    catalog.skip_roots.assert_not_called()
    catalog.map_root.assert_not_called()


def test_a_cancelled_wizard_changes_nothing(mocker: MockerFixture, window: MainWindow, catalog: Catalog) -> None:
    """Cancelling the wizard leaves every root as it was.

    **Test steps:**

    * make the wizard answer ``None``
    * open a catalog
    * verify nothing was skipped or mapped
    """
    mocker.patch.object(window, "ask_root_mappings", return_value=None)

    assert window.open_rehuco_path("home.rehuco")

    catalog.skip_roots.assert_not_called()
    catalog.map_root.assert_not_called()


def test_a_root_that_cannot_be_mapped_is_reported_and_the_others_go_on(
    mocker: MockerFixture, window: MainWindow, catalog: Catalog, tmp_path: Path
) -> None:
    """A mapping the catalog refuses is shown with its reason; the other roots are still mapped.

    **Test steps:**

    * make the wizard answer a folder for both roots, the catalog refuse the first, and spy on the warning box
    * open a catalog
    * verify the box showed the catalog's reason once, and both roots were tried
    """
    folders = {TUTORIALS.root_id: tmp_path / "tutorials", MUSIC.root_id: tmp_path / "music"}
    mocker.patch.object(window, "ask_root_mappings", return_value=(folders, []))
    catalog.map_root.side_effect = [False, True]
    mocker.patch.object(RootCatalog, "save_error", new_callable=mocker.PropertyMock, return_value="Roots overlap.")
    warning = mocker.patch.object(QMessageBox, "warning")

    assert window.open_rehuco_path("home.rehuco")

    warning.assert_called_once_with(window, "Map Roots", "Roots overlap.")
    assert catalog.map_root.call_count == 2


def test_a_question_is_not_asked_while_another_is_open(
    mocker: MockerFixture, window: MainWindow, catalog: Catalog
) -> None:
    """A catalog opened while the wizard is up does not raise a second wizard.

    **Test steps:**

    * make the wizard open another catalog from inside its own question
    * open a catalog
    * verify the wizard was asked once
    """
    asked: list[object] = []

    def nested(roots: object) -> None:
        asked.append(roots)
        window.open_rehuco_path("other.rehuco")

    mocker.patch.object(window, "ask_root_mappings", side_effect=nested)

    assert window.open_rehuco_path("home.rehuco")

    assert len(asked) == 1
    catalog.skip_roots.assert_not_called()


def test_the_catalog_reopened_at_start_is_asked_about_once_the_loop_runs(
    mocker: MockerFixture, qtbot: QtBot, catalog: Catalog, tmp_path: Path
) -> None:
    """A restored catalog's question waits for the event loop; the start does not block on it.

    **Test steps:**

    * seed a ``.rehuco`` file as the one to reopen, and make the wizard answer a skip for one root
    * construct the window, and verify the wizard has not been asked yet
    * wait for it
    * verify the wizard was asked about the roots and the skip was recorded
    """
    rehuco_file = tmp_path / "home.rehuco"
    rehuco_file.touch()
    seed_remembered(mocker, rehuco_current=rehuco_file)
    ask = mocker.patch.object(MainWindow, "ask_root_mappings", return_value=({}, [MUSIC.root_id]))

    window = MainWindow()
    qtbot.addWidget(window)
    ask.assert_not_called()
    qtbot.waitUntil(lambda: ask.called, timeout=2000)

    ask.assert_called_once_with((TUTORIALS, MUSIC))
    catalog.skip_roots.assert_called_once_with([MUSIC.root_id])


def test_a_catalog_that_arrives_late_is_asked_about_once_the_loop_runs(
    mocker: MockerFixture, window: MainWindow, qtbot: QtBot, catalog: Catalog
) -> None:
    """A catalog opened because its share answered is asked about from the event loop too.

    **Test steps:**

    * make the wizard answer a skip, and deliver the arrival of a catalog
    * verify the wizard has not been asked yet
    * wait for it
    * verify the wizard was asked about the roots and the skip was recorded
    """
    ask = mocker.patch.object(window, "ask_root_mappings", return_value=({}, [MUSIC.root_id]))
    mocker.patch.object(RootCatalog, "rehuco_path", new_callable=mocker.PropertyMock, return_value=None)

    window._MainWindow__on_rehuco_arrived(Path("home.rehuco"))  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ask.assert_not_called()
    qtbot.waitUntil(lambda: ask.called, timeout=2000)

    ask.assert_called_once_with((TUTORIALS, MUSIC))
    catalog.skip_roots.assert_called_once_with([MUSIC.root_id])


def test_the_wizard_answers_with_what_the_dialog_collected(
    mocker: MockerFixture, window: MainWindow, tmp_path: Path
) -> None:
    """``ask_root_mappings`` runs the dialog and returns its mapped and skipped roots, or ``None`` when cancelled.

    **Test steps:**

    * replace the dialog class so it runs as accepted with a known answer
    * verify the question returns that answer
    * make it run as cancelled
    * verify the question returns ``None``
    """
    dialog = mocker.patch("rehuco_agent.main_window.MapRootsDialog")
    dialog.DialogCode.Accepted = 1
    instance = dialog.return_value
    instance.mapped = {TUTORIALS.root_id: tmp_path}
    instance.skipped = [MUSIC.root_id]

    instance.exec.return_value = 1
    assert window.ask_root_mappings((TUTORIALS, MUSIC)) == ({TUTORIALS.root_id: tmp_path}, [MUSIC.root_id])

    instance.exec.return_value = 0
    assert window.ask_root_mappings((TUTORIALS, MUSIC)) is None
