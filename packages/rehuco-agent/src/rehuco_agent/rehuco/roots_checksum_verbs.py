"""The checksum verbs of the Roots view's menu and buttons (#457, #469).

What the verbs are, which row gets which, and the jobs they queue: the panel owns the actions and the row it acts on,
and asks this for the group a row's menu or buttons end with.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Final

from borco_core.logging import LogScope
from PySide6.QtCore import QModelIndex
from PySide6.QtGui import QAction
from rehuco_core import (
    ChecksumJob,
    GenerateChecksumsJob,
    RenameCoordinator,
    TaskQueue,
    VerifyChecksumsJob,
    resource_name,
)

from ..documents.files_rows import FileChecksumState
from ..settings.checksum_settings import shared_checksum_settings
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..tasks.already_queued import job_already_queued
from ..tasks.job_end_watcher import JobEndWatcher
from .rehuco_roots_panel_ui import Ui_RehucoRootsPanel
from .roots_folder_model import RootsFolderModel
from .roots_management import ManagingRecord, managing_record

LOG: Final = logging.getLogger(__name__)


class RootsChecksumVerbs:
    """Verify and generate checksums from the Roots view.

    **A record that manages a row** (:func:`~rehuco_agent.rehuco.roots_management.managing_record`) gives it one bulk
    verb -- *Verify* when the record has its checksum file, *Generate* when it has none yet -- and a file with a stored
    result gets verbs for itself alone. A checksum file keeps its own two (*Verify old checksums*, *Verify checksums*).
    Every run is a job on the queue, and the end of one announces the record it may have rewritten, so every view of it
    follows.

    :param model: the Roots model.
    :param ui: the panel's actions.
    :param queue: the task queue the jobs go on.
    :param coordinator: what a job reads through, so it never blocks a rename.
    :param watcher: tells when a queued job has ended.
    :param announce: told the resource whose checksum record a finished job may have rewritten.
    :param acting: the row the actions act on.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        model: RootsFolderModel,
        ui: Ui_RehucoRootsPanel,
        queue: TaskQueue,
        coordinator: RenameCoordinator,
        watcher: JobEndWatcher,
        announce: Callable[[Path], None],
        acting: Callable[[], QModelIndex],
    ) -> None:
        self.__model: Final = model
        self.__ui: Final = ui
        self.__queue: Final = queue
        self.__coordinator: Final = coordinator
        self.__watcher: Final = watcher
        self.__announce: Final = announce
        self.__acting: Final = acting
        ui.verify_checksums_action.triggered.connect(lambda: self.__on_verify_checksums(old=False))
        ui.verify_old_checksums_action.triggered.connect(lambda: self.__on_verify_checksums(old=True))
        ui.verify_record_action.triggered.connect(lambda: self.__on_record(VerifyChecksumsJob))
        ui.generate_record_action.triggered.connect(lambda: self.__on_record(GenerateChecksumsJob))
        ui.verify_file_action.triggered.connect(lambda: self.__on_file(VerifyChecksumsJob))
        ui.add_file_checksum_action.triggered.connect(lambda: self.__on_file(GenerateChecksumsJob))
        ui.update_file_checksum_action.triggered.connect(lambda: self.__on_file(GenerateChecksumsJob))

    def group(self, index: QModelIndex, *, file_verbs: bool = False, buttons: bool = False) -> list[QAction]:
        """The verbs for a folder or file, from the record that manages it, with the separator that sets them apart.

        For a file with a stored result: *Verify this file now* for a result there is; *Add* for a file with no
        checksum and *Update* for one that no longer matches, which are for the menu only, as they hash a file at once.

        :param index: the folder or file.
        :param file_verbs: whether to add the file's own verbs.
        :param buttons: whether the group is for the details pane, which gets *Verify this file now* alone.
        :returns: the separator and the actions; empty when nothing manages the row, or what manages it is a legacy
            ``.tc``.
        """
        managing = managing_record(self.__model, index)
        if managing is None or not managing.can_checksum:
            return []
        ui = self.__ui
        if managing.has_checksum:
            bulk = ui.verify_record_action
            bulk.setText(f"Verify {managing.scope_words}")
        else:
            bulk = ui.generate_record_action
            bulk.setText(f"Generate checksums for {managing.scope_words}")
        return [bulk, *(self.__file_verbs(index, managing, buttons=buttons) if file_verbs else [])]

    def __file_verbs(self, index: QModelIndex, managing: ManagingRecord, *, buttons: bool) -> list[QAction]:
        """The verbs for one file of a record that has its checksum file.

        :param index: the file.
        :param managing: the record that manages it.
        :param buttons: whether only the harmless verb is wanted.
        :returns: the verbs its state calls for; none for a file the record does not checksum.
        """
        checksum = index.data(RootsFolderModel.CHECKSUM_ROLE)
        if checksum is None or not managing.has_checksum:
            return []
        ui = self.__ui
        state = checksum.state
        if state is FileChecksumState.MISSING:
            return [] if buttons else [ui.add_file_checksum_action]
        if state is FileChecksumState.MALFORMED:
            return [] if buttons else [ui.update_file_checksum_action]
        if state in (FileChecksumState.BAD, FileChecksumState.OLD_BAD) and not buttons:
            return [ui.verify_file_action, ui.update_file_checksum_action]
        return [ui.verify_file_action]

    def verify_actions(self, index: QModelIndex) -> list[QAction]:
        """The two Verify actions for a checksum file, on only while the resource it belongs to is there to be checked.

        **Verify old checksums** is the file's default: it leaves a check that is still valid alone, checks the files
        whose check has expired and records the ones with no checksum. **Verify checksums** checks every file, whatever
        its last check was, and dates it anew.

        :param index: the checksum file.
        :returns: the two actions, enabled or not, with tooltips saying which.
        """
        ui = self.__ui
        resource = self.verify_resource(index)
        days = shared_checksum_settings().stale_days
        for action, reason in (
            (
                ui.verify_old_checksums_action,
                f"Check the files whose last check is more than {days} days old, and record the ones with no checksum "
                "yet; a check that is still valid is left alone.",
            ),
            (
                ui.verify_checksums_action,
                "Check every file of the resource this checksum record belongs to, whatever its last check was.",
            ),
        ):
            action.setEnabled(resource is not None)
            action.setToolTip(reason if resource is not None else "There is no .rehu with this name beside it.")
        return [ui.verify_old_checksums_action, ui.verify_checksums_action]

    def verify_resource(self, index: QModelIndex) -> Path | None:
        """The resource a checksum file records: the ``.rehu`` that shares its name.

        :param index: the checksum file.
        :returns: the ``.rehu``'s path when it is there, else ``None``. Answered from the listing, which a file's
            neighbours always have.
        """
        path = self.__model.path_of(index)
        names = self.__model.child_names(index.parent())
        if path is None or names is None:
            return None
        resource = path.with_suffix(".rehu")
        return resource if os.path.normcase(resource.name) in {os.path.normcase(name) for name in names} else None

    def __on_verify_checksums(self, *, old: bool) -> None:
        """Queue a verification of the resource the current checksum file belongs to.

        The Checksums dock's two verbs: *Verify Old* (``old``) skips what was checked within the settings' window and
        records what is new, and *Verify All* checks every file. They derive the same label, so a verify already
        waiting for this resource, asked from either place, is not asked again.

        :param old: whether to leave a check that is still valid alone.
        """
        resource = self.verify_resource(self.__acting())
        if resource is not None:
            self.__enqueue(VerifyChecksumsJob, resource, stale=old)

    def __on_record(self, job_class: type[ChecksumJob]) -> None:
        """Queue a verify or a generate over everything the current row's record manages.

        A verify leaves a check that is still valid alone, as the checksum file's *Verify old checksums* does -- and
        derives the same label, so one already waiting is not asked again.

        :param job_class: :class:`~rehuco_core.VerifyChecksumsJob` or :class:`~rehuco_core.GenerateChecksumsJob`.
        """
        managing = managing_record(self.__model, self.__acting())
        if managing is not None and managing.can_checksum:
            self.__enqueue(job_class, managing.record, stale=job_class is VerifyChecksumsJob)

    def __on_file(self, job_class: type[ChecksumJob]) -> None:
        """Queue a verify or a re-baseline of the current file alone: hashed now, whatever its last check was.

        :param job_class: :class:`~rehuco_core.VerifyChecksumsJob` or :class:`~rehuco_core.GenerateChecksumsJob`.
        """
        managing = managing_record(self.__model, self.__acting())
        if managing is not None and managing.can_checksum:
            self.__enqueue(job_class, managing.record, only=(managing.relative,))

    def __enqueue(
        self,
        job_class: type[ChecksumJob],
        resource: Path,
        *,
        only: tuple[str, ...] | None = None,
        stale: bool = False,
    ) -> None:
        """Build one checksum job from the settings and queue it, unless the same work is already waiting.

        A run over a selection is never refused as a duplicate: its label carries a count, not an identity, so
        label-matching cannot tell one file from another (#244).

        :param job_class: which run.
        :param resource: the ``.rehu`` it works over.
        :param only: the record-relative names to work on, or ``None`` for the whole resource.
        :param stale: whether a check within the settings' window is left alone (a verify only).
        """
        checksums = shared_checksum_settings()
        job = job_class(
            resource,
            coordinator=self.__coordinator,
            algorithm=checksums.algorithm,
            only=only,
            excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            create_if_missing=True if checksums.create_missing_on_verify else None,
            migrate_to=checksums.migrate_target,
            stale_after=checksums.stale_after if stale else None,
            label=None if only is None else f"{job_class.verb} checksums (1 file) - {resource_name(resource)}",
        )
        if only is None and job_already_queued(self.__queue, label=job.label, source=job.source):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        with LogScope.open(resource):
            serial = self.__queue.enqueue(job)
        self.__watcher.watch(serial, lambda: self.__announce(resource))
