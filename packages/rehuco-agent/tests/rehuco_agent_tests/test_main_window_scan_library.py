"""Tests for the main window's ``Tools`` > ``Scan Library...``: the dialog that starts a store's library scan into a
root of the open catalog, and the scan it enqueues (#685).

What the dialog shows is its own test's subject: here the catalog, the wizards and the answer are stand-ins, and the
window is shown to ask the dialog about the open catalog and to queue what it answers.
"""

from pathlib import Path
from threading import Event
from typing import Final, override
from unittest.mock import Mock, PropertyMock
from uuid import uuid4

from PySide6.QtWidgets import QComboBox
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.library_wizard_dialog import LibraryWizardDialog
from rehuco_agent.main_window import MainWindow
from rehuco_agent.rehuco import RootCatalog
from rehuco_agent.scraping.library_scan_job import LibraryScanTarget
from rehuco_agent.scraping.scraper_wizard import ScraperWizard
from rehuco_agent.settings.library_wizard_settings import LibraryWizardSettings
from rehuco_core import JobControl, MappedRoot, TaskJobBase

from .test_main_window import mock_persistent_settings  # noqa: F401  # pylint: disable=unused-import

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545)."""

GATE_TIMEOUT: Final = 120.0
"""How long a held scan waits before giving up, in seconds -- a deadlock detector, not a measurement."""


class HeldJob(TaskJobBase):
    """The scan a wizard stand-in makes: it occupies the worker until released, so a second ask finds it queued.

    :param label: the label its row reads.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.label = label
        self.release: Final = Event()

    def run(self, control: JobControl) -> None:
        """Wait until released."""
        del control
        self.release.wait(GATE_TIMEOUT)


def ask(window: MainWindow) -> object:
    """Ask the window the question of ``Tools`` > ``Scan Library...``.

    :param window: the window.
    :returns: what it answers.
    """
    return window.ask_library_scan()


@fixture(name="window")
def fixture_window(qtbot: QtBot) -> MainWindow:
    """A window with no catalog open.

    :param qtbot: pytest-qt fixture.
    :returns: the window.
    """
    window = MainWindow()
    qtbot.addWidget(window)
    return window


@fixture(name="root")
def fixture_root(tmp_path: Path) -> MappedRoot:
    """A root of the catalog, which takes an asset.

    :param tmp_path: pytest fixture.
    :returns: the root.
    """
    return MappedRoot(uuid4(), "Assets", "//nas/assets", tmp_path / "assets", file=tmp_path / "assets.rehuroot")


@fixture(name="wizard")
def fixture_wizard() -> Mock:
    """A scraper wizard whose scans hold the worker.

    :returns: the stand-in.
    """
    wizard = Mock(spec=ScraperWizard)
    wizard.key = "fab"
    wizard.label = "Fab"
    return wizard


@fixture(name="catalog")
def fixture_catalog(mocker: MockerFixture, root: MappedRoot, tmp_path: Path, wizard: Mock) -> Path:
    """An open catalog: one root, a cache and the one wizard, the remembered roots as none.

    :param mocker: pytest-mock fixture.
    :param root: the catalog's root.
    :param tmp_path: pytest fixture.
    :param wizard: the installed wizard.
    :returns: the cache's path.
    """
    cache = tmp_path / "cache.rehudb"
    mocker.patch.object(RootCatalog, "cache_path", new_callable=PropertyMock, return_value=cache)
    mocker.patch.object(RootCatalog, "mapped_roots", return_value=(root,))
    mocker.patch.object(RootCatalog, "root_paths", return_value={root.root_id: root.path})
    mocker.patch("rehuco_agent.main_window.shared_scraper_wizard_registry", return_value=Mock(wizards=(wizard,)))
    mocker.patch("rehuco_agent.main_window.shared_library_wizard_settings", return_value=LibraryWizardSettings())
    return cache


class AnsweringDialog(LibraryWizardDialog):
    """The dialog with the user's answer built in: it chooses the first root, then presses Start or Cancel."""

    accepts = True
    """Whether the user presses Start rather than Cancel."""

    @override
    def exec(self) -> int:
        """Choose the first root and answer, in place of showing the dialog."""
        combo = self.findChild(QComboBox, "root_combo")
        assert combo is not None
        combo.setCurrentIndex(0)
        return self.DialogCode.Accepted if self.accepts else self.DialogCode.Rejected


class CancelingDialog(AnsweringDialog):
    """The dialog the user cancels."""

    accepts = False


class HastyDialog(LibraryWizardDialog):
    """A dialog accepted with nothing chosen."""

    @override
    def exec(self) -> int:
        """Answer accepted at once."""
        return self.DialogCode.Accepted


def test_scan_library_is_on_only_while_a_catalog_is_open(window: MainWindow, tmp_path: Path) -> None:
    """The action's roots are the catalog's, so it is there to use only while one is open.

    **Test steps:**

    * verify the action is off in a window with no catalog
    * tell the window a catalog was opened
    * verify the action is on
    * tell the window the catalog was closed
    * verify the action is off again
    """
    action = window._MainWindow__ui.scan_library_action  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    catalog = window._MainWindow__root_catalog  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert not action.isEnabled()

    catalog.rehuco_path_changed.emit(tmp_path / "home.rehuco")
    assert action.isEnabled()

    catalog.rehuco_path_changed.emit(None)
    assert not action.isEnabled()


def test_scan_library_is_the_first_entry_of_tools(window: MainWindow) -> None:
    """The scan joins the maintenance operations in ``Tools``, ahead of them.

    **Test steps:**

    * verify the action is the first of the Tools menu
    """
    ui = window._MainWindow__ui  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert ui.tools_menu.actions()[0] is ui.scan_library_action


def test_nothing_is_asked_with_no_catalog_open(mocker: MockerFixture, window: MainWindow) -> None:
    """With no catalog there is no cache to scan into and no root to scan into it.

    **Test steps:**

    * ask the open-catalog question of a window with no catalog open
    * verify nothing was answered and no dialog was built
    """
    built = mocker.patch("rehuco_agent.main_window.LibraryWizardDialog")

    assert ask(window) is None
    built.assert_not_called()


def test_the_dialog_is_built_over_the_open_catalog(
    mocker: MockerFixture, window: MainWindow, catalog: Path, root: MappedRoot, wizard: Mock
) -> None:
    """The answer is the wizard the user chose and the target over the root they chose, in the catalog's cache.

    **Test steps:**

    * open a catalog with one root and one wizard, and let the user choose the root and press Start
    * ask the question
    * verify the answer is the wizard and a target of that root in the catalog's cache
    """
    mocker.patch("rehuco_agent.main_window.LibraryWizardDialog", AnsweringDialog)

    answer = ask(window)

    assert answer == (
        wizard,
        LibraryScanTarget("fab", root.root_id, "Assets", root.file, catalog),  # type: ignore[arg-type]
    )


def test_a_canceled_dialog_answers_nothing(
    mocker: MockerFixture,
    window: MainWindow,
    catalog: Path,  # pylint: disable=unused-argument
) -> None:
    """Cancel starts nothing, however far the user got.

    **Test steps:**

    * let the user choose the root and press Cancel
    * verify nothing was answered
    """
    mocker.patch("rehuco_agent.main_window.LibraryWizardDialog", CancelingDialog)

    assert ask(window) is None


def test_a_dialog_accepted_with_nothing_chosen_answers_nothing(
    mocker: MockerFixture,
    window: MainWindow,
    catalog: Path,  # pylint: disable=unused-argument
) -> None:
    """A dialog accepted with no root chosen has no target, so nothing is answered.

    **Test steps:**

    * accept the dialog without choosing a root
    * verify nothing was answered
    """
    mocker.patch("rehuco_agent.main_window.LibraryWizardDialog", HastyDialog)

    assert ask(window) is None


def test_the_action_queues_the_scan_the_wizard_makes_in_the_roots_log_scope(
    mocker: MockerFixture, window: MainWindow, root: MappedRoot, wizard: Mock, tmp_path: Path
) -> None:
    """Start puts the wizard's scan on the task queue, its log lines filed under the root's folder.

    **Test steps:**

    * answer the question with the wizard and a target of the root
    * trigger the action
    * verify the wizard was asked for the scan of that target
    * verify one row was queued, under the root's log scope
    """
    target = LibraryScanTarget("fab", root.root_id, "Assets", tmp_path / "assets.rehuroot", tmp_path / "cache.rehudb")
    job = HeldJob("Scan the Fab library into Assets")
    wizard.create_job.return_value = job
    mocker.patch.object(window, "ask_library_scan", return_value=(wizard, target))
    mocker.patch.object(RootCatalog, "root_paths", return_value={root.root_id: root.path})
    scope = mocker.patch("rehuco_agent.main_window.LogScope.open")

    window._MainWindow__ui.scan_library_action.setEnabled(True)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    try:
        window._MainWindow__ui.scan_library_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    finally:
        job.release.set()

    wizard.create_job.assert_called_once_with(target)
    scope.assert_called_once_with(root.path)
    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert [status.label for status in queue.jobs()] == ["Scan the Fab library into Assets"]


def test_a_scan_already_queued_is_not_queued_again(
    mocker: MockerFixture, window: MainWindow, root: MappedRoot, wizard: Mock, tmp_path: Path
) -> None:
    """Asking twice for the same scan is not asking again.

    **Test steps:**

    * answer the question with the same wizard and target twice, each time making a scan with one label
    * trigger the action twice
    * verify one row was queued
    """
    target = LibraryScanTarget("fab", root.root_id, "Assets", tmp_path / "assets.rehuroot", tmp_path / "cache.rehudb")
    jobs = [HeldJob("Scan the Fab library into Assets"), HeldJob("Scan the Fab library into Assets")]
    wizard.create_job.side_effect = jobs
    mocker.patch.object(window, "ask_library_scan", return_value=(wizard, target))
    mocker.patch.object(RootCatalog, "root_paths", return_value={root.root_id: root.path})

    window._MainWindow__ui.scan_library_action.setEnabled(True)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    try:
        window._MainWindow__ui.scan_library_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
        window._MainWindow__ui.scan_library_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    finally:
        for job in jobs:
            job.release.set()

    queue = window._MainWindow__task_queue  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    assert len(queue.jobs()) == 1


def test_a_canceled_question_queues_nothing(mocker: MockerFixture, window: MainWindow, wizard: Mock) -> None:
    """Cancel leaves the queue as it was and asks the wizard for nothing.

    **Test steps:**

    * answer the question with nothing
    * trigger the action
    * verify no scan was made and the queue is empty
    """
    window._MainWindow__ui.scan_library_action.setEnabled(True)  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    mocker.patch.object(window, "ask_library_scan", return_value=None)

    window._MainWindow__ui.scan_library_action.trigger()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    wizard.create_job.assert_not_called()
    assert window._MainWindow__task_queue.jobs() == ()  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
