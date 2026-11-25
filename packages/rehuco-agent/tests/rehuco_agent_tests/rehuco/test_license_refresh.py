"""Tests for the controller of *Refresh License* (#688, [[assets#licenses]]): that a refresh is a job on the queue, that
the question is asked only when a record holds another text, and that only what is checked is replaced.

A real task queue and the Tasks dock's real model over it, real records under ``tmp_path``, and a stand-in for the
store; the jobs themselves are tested with the scraping tests.
"""

from collections.abc import Generator
from pathlib import Path
from typing import Final
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.license_refresh_dialog import LicenseRefreshDialog
from rehuco_agent.rehuco.license_refresh import LicenseRefresh
from rehuco_agent.scraping.license_refresh_job import RefreshLicenseJob, ReplaceLicenseJob
from rehuco_agent.tasks import TaskQueueModel
from rehuco_core import DEFAULT_RENAME_COORDINATOR, FINISHED_JOB_STATES, JobState, TaskQueue, read_license_terms

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.scraping.test_license_refresh_job import OLD, STORE, URL, asset

pytestmark = mark.usefixtures("real_path_stat")

TIMEOUT: Final = 10_000


class Rig:
    """A queue, its model, a window and the controller over them, as the main window builds them.

    :param delete_at_teardown: what deletes the Qt objects this makes.
    :param qtbot: pytest-qt fixture.
    :param read_text: what stands for the store.
    """

    def __init__(self, delete_at_teardown: DeleteAtTeardown, qtbot: QtBot, read_text: Mock) -> None:
        self.queue: Final = TaskQueue()
        self.rows: Final = delete_at_teardown(TaskQueueModel(self.queue))
        self.rows.attach_to()
        self.window: Final = QWidget()
        qtbot.addWidget(self.window)
        self.read_text: Final = read_text
        self.refresh: Final = LicenseRefresh(self.queue, self.rows, read_text, self.window, DEFAULT_RENAME_COORDINATOR)

    def dialog(self, qtbot: QtBot) -> LicenseRefreshDialog:
        """Wait for the question and give it.

        :param qtbot: pytest-qt fixture.
        :returns: the dialog.
        """
        qtbot.waitUntil(lambda: self.window.findChild(LicenseRefreshDialog) is not None, timeout=TIMEOUT)
        dialog = self.window.findChild(LicenseRefreshDialog)
        assert isinstance(dialog, LicenseRefreshDialog)
        return dialog

    def settle(self, qtbot: QtBot, kind: type[object]) -> None:
        """Wait for every job of a kind to have ended.

        :param qtbot: pytest-qt fixture.
        :param kind: the job class.
        """
        qtbot.waitUntil(
            lambda: (
                any(isinstance(self.queue.job(status.serial), kind) for status in self.queue.jobs())
                and all(status.state in FINISHED_JOB_STATES for status in self.queue.jobs())
            ),
            timeout=TIMEOUT,
        )


@fixture(name="rig")
def fixture_rig(qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> Generator[Rig]:
    """The rig over a store that answers :data:`STORE` for :data:`URL`.

    :param qtbot: pytest-qt fixture.
    :param delete_at_teardown: what deletes the Qt objects the rig makes.
    :yields: the rig.
    """
    rig = Rig(delete_at_teardown, qtbot, Mock(return_value=STORE))
    yield rig
    rig.queue.shutdown()


def test_a_refresh_is_a_job_on_the_queue_that_writes_the_missing_texts_and_asks_nothing_when_nothing_differs(
    qtbot: QtBot, rig: Rig, tmp_path: Path
) -> None:
    """**Test steps:**

    * refresh a record with no saved text
    * verify the job ran on the queue, the store was asked for its address, the text was written, and no question was
      asked
    """
    record = asset(tmp_path, "a")

    rig.refresh.refresh((record,))
    rig.settle(qtbot, RefreshLicenseJob)
    qtbot.wait(100)

    rig.read_text.assert_called_once_with(URL)
    assert read_license_terms(record) == STORE
    assert rig.window.findChild(LicenseRefreshDialog) is None


def test_a_record_holding_another_text_is_asked_about_and_replaced_only_when_checked(
    qtbot: QtBot, rig: Rig, tmp_path: Path
) -> None:
    """A text is replaced only on a yes: the question comes with nothing checked, and what is checked is replaced by a
    second job.

    **Test steps:**

    * refresh a record holding an older text and one with none
    * verify a dialog asks about the one license and the older text is still there
    * check it and press the replace button
    * verify a second job ran and the record holds the store's text
    """
    older, empty = asset(tmp_path, "a", terms=OLD), asset(tmp_path, "b")

    rig.refresh.refresh((older, empty))
    dialog = rig.dialog(qtbot)

    assert dialog.chosen == ()
    assert read_license_terms(older) == OLD
    assert read_license_terms(empty) == STORE
    dialog._LicenseRefreshDialog__ui.licenses_list.item(0).setCheckState(Qt.CheckState.Checked)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    dialog.replace_button.click()
    rig.settle(qtbot, ReplaceLicenseJob)
    qtbot.waitUntil(lambda: read_license_terms(older) == STORE, timeout=TIMEOUT)

    assert any(isinstance(rig.queue.job(status.serial), ReplaceLicenseJob) for status in rig.queue.jobs())


def test_keeping_every_text_replaces_nothing_and_enqueues_nothing(qtbot: QtBot, rig: Rig, tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a record holding an older text and answer the question with *Keep All*
    * verify the text is as it was and the queue holds the refresh alone
    """
    older = asset(tmp_path, "a", terms=OLD)

    rig.refresh.refresh((older,))
    dialog = rig.dialog(qtbot)
    dialog.reject()
    qtbot.wait(100)

    assert read_license_terms(older) == OLD
    assert [type(rig.queue.job(status.serial)) for status in rig.queue.jobs()] == [RefreshLicenseJob]


def test_closing_the_question_with_nothing_checked_replaces_nothing(qtbot: QtBot, rig: Rig, tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a record holding an older text and accept the dialog with nothing checked
    * verify nothing was enqueued
    """
    older = asset(tmp_path, "a", terms=OLD)

    rig.refresh.refresh((older,))
    dialog = rig.dialog(qtbot)
    dialog.accept()
    qtbot.wait(100)

    assert [type(rig.queue.job(status.serial)) for status in rig.queue.jobs()] == [RefreshLicenseJob]


def test_a_refresh_that_failed_asks_nothing(qtbot: QtBot, rig: Rig, tmp_path: Path) -> None:
    """**Test steps:**

    * refresh with a store that fails unexpectedly
    * verify the job failed and no question was asked
    """
    rig.read_text.side_effect = RuntimeError("boom")
    record = asset(tmp_path, "a")

    rig.refresh.refresh((record,))
    qtbot.waitUntil(lambda: any(status.state is JobState.FAILED for status in rig.queue.jobs()), timeout=TIMEOUT)
    qtbot.wait(100)

    assert rig.window.findChild(LicenseRefreshDialog) is None


def test_a_refresh_retried_from_the_tasks_dock_is_asked_about_when_it_ends(
    qtbot: QtBot, rig: Rig, tmp_path: Path
) -> None:
    """A row that failed and is retried runs again under its serial, and its differences are asked about then.

    **Test steps:**

    * refresh a record holding an older text with a store that fails, and wait for the failure
    * let the store answer and retry the row
    * verify the question is asked
    """
    older = asset(tmp_path, "a", terms=OLD)
    rig.read_text.side_effect = RuntimeError("boom")
    rig.refresh.refresh((older,))
    qtbot.waitUntil(lambda: any(status.state is JobState.FAILED for status in rig.queue.jobs()), timeout=TIMEOUT)
    qtbot.wait(100)

    rig.read_text.side_effect = None
    rig.queue.retry(rig.queue.jobs()[0].serial)

    assert rig.dialog(qtbot).chosen == ()


def test_a_refresh_removed_from_the_queue_is_forgotten(qtbot: QtBot, rig: Rig, tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a record holding an older text, answer the question, and remove the row from the queue
    * verify the controller follows no refresh any more
    """
    older = asset(tmp_path, "a", terms=OLD)
    rig.refresh.refresh((older,))
    rig.dialog(qtbot).reject()

    rig.queue.remove(rig.queue.jobs()[0].serial)
    qtbot.waitUntil(lambda: not rig.refresh._LicenseRefresh__refreshes, timeout=TIMEOUT)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert rig.queue.jobs() == ()
