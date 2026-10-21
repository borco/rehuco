"""The window's saves, as jobs on the task queue: one row per record, and what each open document is told about its
own ([[sync#pending-saves]], #497)."""

import logging
from typing import Final, cast
from uuid import UUID

from borco_core.logging import LogScope
from PySide6.QtCore import QEventLoop, QObject
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget
from rehuco_core import (
    SAVE_RECORD_KIND,
    JobState,
    JobStatus,
    RecordConflict,
    RenameCoordinator,
    SavePayload,
    SaveRecordJob,
    TaskQueue,
    rebase_payload,
)
from rehuco_core.access import Records, ResourceKey

from ..dialogs.record_conflict_dialog import ConflictResolution
from ..resource_events import ResourceEvents
from ..settings.identity_settings import shared_identity_settings
from ..tasks import TaskQueueModel
from .document_registry import DocumentRegistry
from .rehu_document_model import UNTITLED_LABEL, RehuDocumentModel
from .save_or_prompt_retry import ask_about_conflict

LOG: Final = logging.getLogger(__name__)

SAVE_PENDING_TEXT: Final = "Save pending"
SAVE_PAUSED_TEXT: Final = "Save paused: it lands once the task is resumed"
"""What a document's banner says while its save waits its turn, or was paused by hand."""

UNFINISHED_SAVE_STATES: Final = frozenset({JobState.QUEUED, JobState.RUNNING})
"""The states a close or a quit waits through (:meth:`PendingSaves.save_and_wait`)."""

SETTLED_SAVE_STATES: Final = frozenset({JobState.DONE, JobState.CANCELLED})
"""The states of a save that is history: landed, or dropped at a shutdown -- in every other one it is still the
record's saved state on this machine ([[sync#unlanded-save]])."""


# nine, and each is one thing this owns or keeps: the engine, its rows, the documents, how records are written, the
# announcements, the rename barrier, and per record its newest row, per row its document and its last state
# pylint: disable-next=too-many-instance-attributes
class PendingSaves(QObject):
    """Owns the window's save jobs ([[sync#apply-payload]], #497): hands each Save to the task queue, and each landed
    or failed save back to its document.

    **A save that has not landed is a modified borrowed copy of its record** ([[sync#unlanded-save]]): its data is the
    record's saved state on this machine -- what Revert goes back to and what opening the record shows
    (:meth:`pending_payload`) -- until it lands, or until it is dropped (:meth:`discard`), which returns its document
    to the file.

    **One pending save per record.** A later Save hands the record's save that has not landed the newer data
    (:meth:`~rehuco_core.SaveRecordJob.replace`): in place of what it holds while it waits, or to be written right after
    the write under way. A save that landed is history: the next Save is a job of its own, moved onto what it wrote.
    A row restored from the saved queue is found again by its kind and source, and every row follows its record across
    a rename made in the app.

    Rides :attr:`~rehuco_agent.tasks.TaskQueueModel.snapshot_taken`, on the GUI thread, as the status bar's indicator
    does: the queue's listeners are called on whichever thread a job stopped on.

    :param queue: the app's task queue.
    :param rows: the Tasks dock's model of it.
    :param registry: the open documents.
    :param records: what the records are saved through.
    :param resource_events: the app's change announcements: a root becoming reachable again tries its waiting saves.
    :param coordinator: the rename barrier the saves follow their records through.
    :param parent: optional Qt parent.
    """

    # one thing each: the engine, its rows, the documents, how they are written, and what this keeps per row
    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        queue: TaskQueue,
        rows: TaskQueueModel,
        registry: DocumentRegistry,
        records: Records,
        resource_events: ResourceEvents,
        coordinator: RenameCoordinator | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__rows: Final = rows
        self.__registry: Final = registry
        self.__records: Final = records
        self.__events: Final = resource_events
        self.__coordinator: Final = coordinator
        self.__serials: dict[ResourceKey, int] = self.__newest_rows(queue.jobs())
        """The newest save row of each record, by where the record is now."""
        self.__owners: Final[dict[int, RehuDocumentModel]] = {}
        """The document whose Saves each row holds."""
        self.__seen: Final[dict[int, JobState]] = {}
        """Each save row's state as last handled."""
        self.__attached = True
        """Whether this still follows the queue (:meth:`detach`)."""
        rows.snapshot_taken.connect(self.__on_snapshot)
        registry.model_acquired.connect(self.__on_model_acquired)
        resource_events.root_reachable.connect(self.__on_root_reachable)
        registry.follow_pending_saves(self.pending_payload)
        self.__on_snapshot()

    def detach(self) -> None:
        """Stop following the queue, before it is shut down: its last notifications must reach no document.

        A second call is a no-op, as the queue's own ``remove_listener`` is, so a window closed twice tears down once.
        """
        if not self.__attached:
            return
        self.__attached = False
        self.__rows.snapshot_taken.disconnect(self.__on_snapshot)
        self.__registry.model_acquired.disconnect(self.__on_model_acquired)
        self.__events.root_reachable.disconnect(self.__on_root_reachable)

    def pending_payload(self, key: ResourceKey) -> SavePayload | None:
        """A record's save that has not landed -- its saved state on this machine ([[sync#unlanded-save]]).

        :param key: the record, where it is now.
        :returns: the last Save handed to it, or ``None`` when the record has no save that has not landed.
        """
        serial = self.__serials.get(key)
        status = None if serial is None else self.__status(serial)
        if serial is None or status is None or status.state in SETTLED_SAVE_STATES:
            return None
        job = self.__queue.job(serial)
        return job.handed if isinstance(job, SaveRecordJob) else None

    def save(self, parent: QWidget, model: RehuDocumentModel) -> bool:
        """Hand ``model``'s edits to its record's save, and go back to editing (the Save and Upgrade actions).

        **The differences come first** when the file is known to have changed since the document read it -- a save
        refused as a conflict, or a change heard on disk: the file is read again and the conflict dialog shows what
        differs, before anything is queued. A file found unchanged after all asks nothing. No dialog ever pops out of
        a job's own failure; it waits for this.

        A clean document whose record has a save not landed saves it again: a waiting one is tried now, a failed one
        retried -- which is how a failure is settled from the document ([[sync#unlanded-save]]). Refused, saying
        nothing more than the banner already does, while the document's file or folder is gone.

        :param parent: the widget the conflict dialog is parented to.
        :param model: the document.
        :returns: ``True`` once the edits are with their save, or discarded in the dialog; ``False`` when nothing was
            saved -- the dialog cancelled, or the record gone.
        """
        if model.gone:
            return False
        if (model.conflict is not None or model.changed_on_disk) and not self.__settle_differences(parent, model):
            return False
        key = model.key
        nothing_to_save = not model.dirty and not model.upgradable
        if key is None or (nothing_to_save and self.pending_payload(key) is None):
            # the dialog discarded the edits, or there were none to save
            return True
        self.__enqueue(model)
        return True

    def save_and_wait(self, parent: QWidget, model: RehuDocumentModel) -> bool:
        """Save ``model`` and wait for the write behind a progress dialog -- what a close, a quit and Save All need,
        since what they gate must not go ahead of the edits.

        A conflict shows the differences, and saves again with what was kept. A save that cannot land -- its share
        does not answer, its lock is held, its write failed -- asks: **Try again**, **Leave it pending** (go ahead; the
        row lands later), or **Cancel**.

        :param parent: the widget the dialogs are parented to.
        :param model: the document.
        :returns: ``True`` once saved, discarded, or left pending; ``False`` when the caller must stop -- cancelled, or
            the record gone.
        """
        while True:
            if not self.save(parent, model):
                return False
            key = model.key
            if key is None or key not in self.__serials or not (model.saving or model.dirty):
                return True
            status = self.__wait(parent, model, self.__serials[key])
            if status is None:
                return False
            if status.state is JobState.DONE:
                return True
            if status.state is JobState.FAILED and model.gone:
                return False
            if status.state is JobState.FAILED and model.conflict is not None:
                # the next round shows the differences, and saves what was kept
                continue
            answer = self.__ask_about_pending(parent, model, status)
            if answer is QMessageBox.StandardButton.Retry:
                continue
            return answer is QMessageBox.StandardButton.Ignore

    def key_of(self, serial: int) -> ResourceKey | None:
        """The record a save row is about.

        :param serial: the row.
        :returns: its record, or ``None`` for a row that is no record's newest save.
        """
        return next((key for key, held in self.__serials.items() if held == serial), None)

    def inspect(self, parent: QWidget, serial: int, model: RehuDocumentModel) -> None:
        """Look at a save that has not landed in its document, opened for it -- which shows the save's data, the
        record's saved state -- and, when the file changed since, the differences, before saving it again (the Tasks
        dock's *Inspect*).

        :param parent: the widget the conflict dialog is parented to.
        :param serial: the save row.
        :param model: the row's document, as just opened.
        """
        job = self.__queue.job(serial)
        if not isinstance(job, SaveRecordJob):
            return
        if model.conflict is None and job.conflict is not None:
            model.fail_save(job.conflict, gone=job.gone)
        self.save(parent, model)

    def discard(self, parent: QWidget, serials: list[int]) -> None:
        """Drop saves that have not landed, after asking once -- the borrow's *Drop* ([[sync#unlanded-save]]): an open
        document of each goes back to its file, edits made since its last Save included (the Tasks dock's *Discard*,
        and its Cancel and Clear on a save).

        A save that is writing is left alone: its write cannot be stopped, so dropping its row would only hide a save
        that lands anyway.

        :param parent: the widget the question is parented to.
        :param serials: the save rows.
        """
        rows = {
            serial: key
            for serial in serials
            if (key := self.key_of(serial)) is not None
            and (status := self.__status(serial)) is not None
            and status.state not in (*SETTLED_SAVE_STATES, JobState.RUNNING)
        }
        if not rows:
            return
        count = len(rows)
        answer = QMessageBox.question(
            parent,
            "Discard Saves",
            f"Discard {count} pending save{'' if count == 1 else 's'}? "
            f"The edits {'it holds' if count == 1 else 'they hold'} are lost, and an open document goes back to what "
            "its file holds, edits made since included.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.__queue.remove(*rows)
        for serial in rows:
            self.__forget(serial)

    def __enqueue(self, model: RehuDocumentModel) -> None:
        """Hand a snapshot of ``model`` to its record's save not landed, or to a new one when it has none.

        :param model: the document.
        :raises ValueError: it cannot be saved -- no location, or a lock that refuses saving.
        """
        key = cast(ResourceKey, model.key)
        payload = model.snapshot()
        serial = self.__serials.get(key)
        status = None if serial is None else self.__status(serial)
        job = None if serial is None else self.__queue.job(serial)
        if (
            serial is None
            or status is None
            or status.state in SETTLED_SAVE_STATES
            or not isinstance(job, SaveRecordJob)
        ):
            serial = self.__start(model, self.__onto_landed(payload, job))
        elif not job.replace(payload):
            # it landed between the look and the hand-over: history, so this is a save of its own
            serial = self.__start(model, self.__onto_landed(payload, job))
        elif status.state is JobState.FAILED:
            # nothing landed, so the failed save is still the pending one: back in line, with the newer data already
            # in hand -- handed over first, since a row put back in line may start before this returns
            self.__queue.retry(serial)
        elif status.state in (JobState.WAITING, JobState.PAUSED):
            self.__queue.resume_job(serial)
        self.__owners[serial] = model  # pylint: disable=unsupported-assignment-operation
        model.begin_save()

    @staticmethod
    def __onto_landed(payload: SavePayload, job: object) -> SavePayload:
        """``payload``, moved onto what the record's last save wrote when it was made against the version before it
        -- a Save pressed after that save landed but before its document heard so, which would otherwise be checked
        against the version the landing replaced and refused as a conflict with its own record's save.

        :param payload: the new Save.
        :param job: the record's last save row's job, if it has one.
        :returns: what the new save writes.
        """
        if not isinstance(job, SaveRecordJob):
            return payload
        result, written = job.result, job.payload
        if result is None or written is None or payload.base == result.version:
            return payload
        return rebase_payload(payload, written, result)

    def __start(self, model: RehuDocumentModel, payload: SavePayload) -> int:
        """Queue a new save of ``model``'s record.

        :param model: the document.
        :param payload: what to write.
        :returns: the new row.
        """
        job = SaveRecordJob(payload, records=self.__records, coordinator=self.__coordinator)
        # captured with the job, so its records land in the document's log as well as the Tasks dock's
        with LogScope.open(model.path):
            serial = self.__queue.enqueue(job)
        self.__serials[cast(ResourceKey, model.key)] = serial  # pylint: disable=unsupported-assignment-operation
        return serial

    def __settle_differences(self, parent: QWidget, model: RehuDocumentModel) -> bool:
        """Show what the file and the document disagree on, when the file changed since the document read it, and take
        what the person keeps.

        :param parent: the widget the dialog is parented to.
        :param model: the document.
        :returns: ``True`` to go on -- kept values taken, edits discarded, or the file unchanged after all; ``False``
            when cancelled.
        """
        key = cast(ResourceKey, model.key)
        settings = shared_identity_settings()
        current = self.__records.load(
            key, username=settings.current_username, unknown_username=settings.unknown_username
        )
        base = model.base_version
        if current.version is None or (base is not None and current.version.file_hash == base.file_hash):
            # nothing to compare with -- the save says why -- or nothing changed after all
            model.conflict = None
            model.changed_on_disk = False
            return True
        conflict = RecordConflict(current.document, current.version)
        model.conflict = conflict
        resolution, values = ask_about_conflict(parent, model, conflict)
        if resolution is ConflictResolution.CANCEL:
            return False
        if resolution is ConflictResolution.DISCARD:
            # the borrow's Drop, asked in the dialog: the save goes too, and the document is the file's again
            serial = self.__serials.get(key)
            if serial is not None:
                self.__queue.remove(serial)
                self.__forget(serial)
            else:
                model.revert()
            return True
        model.resolve_conflict(values)
        return True

    def __status(self, serial: int) -> JobStatus | None:
        """One row as the engine has it now.

        :param serial: the row.
        :returns: its status, or ``None`` once it is removed.
        """
        return next((status for status in self.__queue.jobs() if status.serial == serial), None)

    def __wait(self, parent: QWidget, model: RehuDocumentModel, serial: int) -> JobStatus | None:
        """Wait, behind a modal progress dialog, until a save row is no longer queued or writing.

        :param parent: the widget the dialog is parented to.
        :param model: the document.
        :param serial: its row.
        :returns: the row as it ended up; ``None`` when cancelled, the row staying where it is.
        """
        status = self.__status(serial)
        if status is None or status.state not in UNFINISHED_SAVE_STATES:
            return status
        dialog = QProgressDialog(f"Saving {model.label or UNTITLED_LABEL}…", "Cancel", 0, 0, parent)
        dialog.setWindowTitle("Saving")
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        loop = QEventLoop(dialog)
        cancelled = False

        def on_cancel() -> None:
            """Stop waiting; the row stays."""
            nonlocal cancelled
            cancelled = True
            loop.quit()

        def on_snapshot() -> None:
            """Stop waiting once the row has left the states a write passes through."""
            now = self.__status(serial)
            if now is None or now.state not in UNFINISHED_SAVE_STATES:
                loop.quit()

        dialog.canceled.connect(on_cancel)
        self.__rows.snapshot_taken.connect(on_snapshot)
        try:
            dialog.show()
            loop.exec()
        finally:
            self.__rows.snapshot_taken.disconnect(on_snapshot)
            dialog.deleteLater()
        return None if cancelled else self.__status(serial)

    @staticmethod
    def __ask_about_pending(parent: QWidget, model: RehuDocumentModel, status: JobStatus) -> QMessageBox.StandardButton:
        """Ask what to do about a save that could not land.

        :param parent: the widget the question is parented to.
        :param model: the document.
        :param status: its row.
        :returns: ``Retry`` to try again, ``Ignore`` to leave it pending, ``Cancel`` to stop.
        """
        buttons = QMessageBox.StandardButton
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            "Save Not Landed",
            f'Could not save "{model.label or UNTITLED_LABEL}": {status.message or status.state.value}',
            buttons.Retry | buttons.Ignore | buttons.Cancel,
            parent,
        )
        box.button(buttons.Retry).setText("Try Again")
        box.button(buttons.Ignore).setText("Leave It Pending")
        box.setDefaultButton(buttons.Retry)
        try:
            return buttons(box.exec())
        finally:
            box.deleteLater()

    @staticmethod
    def __newest_rows(statuses: tuple[JobStatus, ...]) -> dict[ResourceKey, int]:
        """The newest save row of each record, by where the record is now -- the row made last, which its serial
        says: the queue's order does not, once a row has been moved. Each row's source follows its record across a
        rename.

        :param statuses: the queue's rows.
        :returns: each record's newest save row.
        """
        newest: dict[ResourceKey, int] = {}
        for status in statuses:
            if status.kind == SAVE_RECORD_KIND and status.source is not None:
                key = ResourceKey(status.source)
                newest[key] = max(status.serial, newest.get(key, status.serial))
        return newest

    def __on_snapshot(self) -> None:
        """Tell each document what its save rows did since the last snapshot (GUI thread)."""
        statuses = self.__queue.jobs()
        present = {status.serial for status in statuses}
        for serial in [serial for serial in self.__seen if serial not in present]:
            self.__forget(serial)
            self.__seen.pop(serial, None)
        self.__serials = self.__newest_rows(statuses)
        for status in statuses:
            if status.kind != SAVE_RECORD_KIND or status.source is None:
                continue
            if self.__seen.get(status.serial) is status.state:
                continue
            self.__seen[status.serial] = status.state  # pylint: disable=unsupported-assignment-operation
            self.__on_state(ResourceKey(status.source), status)

    def __on_state(self, key: ResourceKey, status: JobStatus) -> None:
        """Hand one save row's new state to its document.

        :param key: the record.
        :param status: the row.
        """
        model = self.__registry.find(key)
        job = self.__queue.job(status.serial)
        if model is None or not isinstance(job, SaveRecordJob):
            return
        if status.state is JobState.DONE:
            self.__landed(model, status.serial, job)
        if self.__serials.get(key) != status.serial:
            # an earlier save of the record: only its landing is the document's business
            return
        if status.state is JobState.FAILED:
            model.fail_save(job.conflict, gone=job.gone)
        elif status.state is JobState.CANCELLED:
            model.fail_save(None)
        model.pending_save = self.pending_text(status)

    def __landed(self, model: RehuDocumentModel, serial: int, job: SaveRecordJob) -> None:
        """Hand a landed save to its document.

        The document takes it when its Saves are this job's, or -- opened since, after a restart even -- when it is
        based on the version the save was: it then shows the save's data, its saved state. A document based on
        anything else hears what landed as any change on disk.

        :param model: the open document of the record.
        :param serial: the row.
        :param job: the save.
        """
        result, handed = job.result, job.handed
        if result is None or handed is None:
            return
        if self.__owners.get(serial) is model or model.base_version == handed.base:
            model.complete_save(handed, result, latest=self.pending_payload(cast(ResourceKey, model.key)))
        elif result.signature is not None:
            model.note_file_signature(*result.signature)

    def __forget(self, serial: int) -> None:
        """Drop what is kept about a row that left the queue; when it was the record's save not landed, its document
        goes back to the file -- the borrow's Drop ([[sync#unlanded-save]]).

        :param serial: the row.
        """
        self.__owners.pop(serial, None)
        key = self.key_of(serial)
        if key is None:
            return
        del self.__serials[key]  # pylint: disable=unsupported-delete-operation
        model = self.__registry.find(key)
        if model is None:
            return
        model.pending_save = ""
        if self.__seen.get(serial) in SETTLED_SAVE_STATES:
            # a landed save cleared from the dock: history, nothing the document holds goes with it
            return
        model.fail_save(None)
        model.conflict = None
        model.gone = ""
        if model.saved_on_disk:
            model.revert()
        else:
            # a record never written has no file to go back to: what it held stays, unsaved
            model.dirty = True

    def __on_model_acquired(self, model: RehuDocumentModel) -> None:
        """Tell a document just opened about its save that has not landed, if it has one -- its banner, and what a
        failure said.

        :param model: the document.
        """
        key = model.key
        serial = None if key is None else self.__serials.get(key)
        status = None if serial is None else self.__status(serial)
        if serial is None or status is None:
            return
        job = self.__queue.job(serial)
        if status.state is JobState.FAILED and isinstance(job, SaveRecordJob):
            model.fail_save(job.conflict, gone=job.gone)
        model.pending_save = self.pending_text(status)

    def __on_root_reachable(self, root_id: UUID, reachable: bool) -> None:
        """Try every waiting save again when a root answers once more; the engine's own wait covers the rest.

        :param root_id: the root.
        :param reachable: whether it answers now.
        """
        del root_id  # a handful of waiting saves is cheaper to try than to sort by root
        if not reachable:
            return
        for status in self.__queue.jobs():
            if status.kind == SAVE_RECORD_KIND and status.state is JobState.WAITING:
                self.__queue.resume_job(status.serial)

    @staticmethod
    def pending_text(status: JobStatus) -> str:
        """What a document's banner says about its save row.

        :param status: the row.
        :returns: the sentence, or empty when there is nothing to say -- landed, or writing (the banner says *Saving*).
        """
        if status.state is JobState.QUEUED:
            return SAVE_PENDING_TEXT
        if status.state is JobState.WAITING:
            return f"Save waiting: {status.message}" if status.message else "Save waiting"
        if status.state is JobState.PAUSED:
            return SAVE_PAUSED_TEXT
        if status.state is JobState.FAILED:
            return f"Save failed: {status.message}" if status.message else "Save failed"
        return ""
