"""*Refresh License* on the browser's selection: the two jobs, and the question the user is asked between them
([[assets#licenses]], #688)."""

import logging
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QWidget
from rehuco_core import JobState, RenameCoordinator, TaskQueue

from ..dialogs.license_refresh_dialog import LicenseRefreshDialog
from ..scraping.license_refresh_job import (
    LicenseDifference,
    LicenseTextReader,
    RefreshLicenseJob,
    ReplaceLicenseJob,
)
from ..settings.identity_settings import shared_identity_settings
from ..tasks import TaskQueueModel

LOG: Final = logging.getLogger(__name__)


class LicenseRefresh(QObject):
    """Refreshes the licenses of a selection of records, and replaces the texts the user confirms.

    A refresh is a job on the queue (:class:`~rehuco_agent.scraping.license_refresh_job.RefreshLicenseJob`): it reads
    each distinct license address once and writes the text of every record that has none. **When it ends with records
    holding another text, a dialog asks which licenses to replace** -- not modal, since the job may end while the user
    works elsewhere -- and each one checked is replaced by a second job, only where the record still holds the text that
    was compared. A text is never replaced unasked.

    Follows the queue through the Tasks dock's rows, on the GUI thread, as the saves do.

    :param queue: the app's task queue.
    :param rows: the Tasks dock's model of it.
    :param read_text: what reads the text a ``license_url`` names.
    :param window: the window the question is shown over, which owns this.
    :param coordinator: the rename barrier the jobs read and write the records' files inside.
    """

    def __init__(
        self,
        queue: TaskQueue,
        rows: TaskQueueModel,
        read_text: LicenseTextReader,
        window: QWidget,
        coordinator: RenameCoordinator,
    ) -> None:
        super().__init__(window)
        self.__queue: Final = queue
        self.__read_text: Final = read_text
        self.__window: Final = window
        self.__coordinator: Final = coordinator
        self.__refreshes: Final[dict[int, JobState | None]] = {}
        """Each refresh still in the queue, with its state as last heard: a row retried from the Tasks dock runs again
        under its serial, and is asked about again when it ends."""
        rows.snapshot_taken.connect(self.__on_snapshot)

    def refresh(self, records: object) -> None:
        """Enqueue a refresh of the licenses of ``records``.

        :param records: the ``.rehu`` of each selected record, as the object-typed relay carried them.
        """
        paths = cast(Sequence[Path], records)
        job = RefreshLicenseJob(
            paths,
            self.__read_text,
            username=shared_identity_settings().current_username,
            coordinator=self.__coordinator,
        )
        self.__refreshes[self.__queue.enqueue(job)] = None  # pylint: disable=unsupported-assignment-operation

    def __on_snapshot(self) -> None:
        """Ask about the licenses a refresh that has ended found differing (GUI thread)."""
        statuses = {status.serial: status for status in self.__queue.jobs()}
        for serial, heard in sorted(self.__refreshes.items()):
            status = statuses.get(serial)
            if status is None:
                del self.__refreshes[serial]  # pylint: disable=unsupported-delete-operation
                continue
            self.__refreshes[serial] = status.state  # pylint: disable=unsupported-assignment-operation
            job = self.__queue.job(serial)
            if status.state is JobState.DONE and heard is not JobState.DONE and isinstance(job, RefreshLicenseJob):
                self.__ask(job.differences)

    def __ask(self, differences: Sequence[LicenseDifference]) -> None:
        """Show which licenses read differently, for the user to say which texts to replace.

        :param differences: what the refresh found; none asks nothing.
        """
        if not differences:
            return
        dialog = LicenseRefreshDialog(differences, self.__window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.accepted.connect(partial(self.__replace, dialog))
        dialog.show()

    def __replace(self, dialog: LicenseRefreshDialog) -> None:
        """Enqueue the replacement of what the user checked.

        :param dialog: the dialog they answered.
        """
        chosen = dialog.chosen
        if chosen:
            LOG.info("Replacing the license text of %s license(s) in the records that hold another.", len(chosen))
            self.__queue.enqueue(
                ReplaceLicenseJob(
                    chosen, username=shared_identity_settings().current_username, coordinator=self.__coordinator
                )
            )
