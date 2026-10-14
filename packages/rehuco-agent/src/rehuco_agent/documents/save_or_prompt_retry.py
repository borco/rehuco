"""Save a document, surfacing an I/O failure as a retry/cancel dialog rather than a bare traceback (#146), and a
conflict as a side-by-side choice (#416)."""

from collections.abc import Callable
from functools import partial
from typing import Any, Final

from PySide6.QtWidgets import QMessageBox, QWidget
from rehuco_core import FieldPath, RecordConflict, metadata_differences

from ..dialogs.record_conflict_dialog import ConflictResolution, RecordConflictDialog
from .rehu_document_model import UNTITLED_LABEL, RehuDocumentModel

SAVE_FAILED_TITLE: Final = "Save Failed"
"""Title of the dialog shown when a save raises ``OSError`` (#146)."""


def save_or_prompt_retry(parent: QWidget, model: RehuDocumentModel) -> bool:
    """Save ``model``, prompting **Retry/Cancel** on an I/O failure and the conflict dialog on a conflict, instead of
    letting either escape (#146, #416).

    :meth:`~RehuDocumentModel.save` does real file I/O and can raise ``OSError`` -- an offline SMB mount
    is an explicitly supported scenario ([[mounts-and-storage#offline-mounts]]) where a save fails
    *transiently*, so the failure is offered as a retry loop rather than lost edits and a stderr
    traceback. This is the one seam every save call site funnels through -- the Save and Upgrade actions,
    Save All, the per-tab and batch close guards, and the whole-app close -- so how a failed save is
    surfaced (and the choice to abort whatever the save was gating) lives in exactly one place, the same
    way :meth:`~rehuco_agent.documents.document_sub_docks.DocumentSubDocks.__on_convert_triggered` already
    guards the convert actions.

    A save refused because the record's details changed on disk since it was read (:class:`~rehuco_core.RecordConflict`)
    opens :class:`~rehuco_agent.dialogs.record_conflict_dialog.RecordConflictDialog`: the two side by side, saved with
    the value kept for each detail, or the edits discarded -- either leaves nothing unsaved, so the gated action goes
    on -- or cancelled, which aborts it like a cancelled retry.

    A save-blocking lock raises ``ValueError`` from :meth:`~rehuco_core.RehuDocument.save`, but editing is disabled
    while a document is locked, so a lock never reaches a save call site here ([[data-model#write-integrity]]).

    :param parent: the widget to parent the dialogs to.
    :param model: the document model to save.
    :returns: ``True`` once the document is saved or reverted; ``False`` if the user cancelled -- nothing was
        written, and the caller should abort whatever the save was gating (e.g. a close).
    """
    buttons = QMessageBox.StandardButton
    action: Callable[[], None] = model.save
    while True:
        try:
            action()
            return True
        except RecordConflict as conflict:
            resolution, values = ask_about_conflict(parent, model, conflict)
            if resolution is ConflictResolution.CANCEL:
                return False
            if resolution is ConflictResolution.DISCARD:
                model.revert()
                return True
            action = partial(model.resolve_conflict, values)
        except OSError as exc:
            label = model.label or UNTITLED_LABEL
            answer = QMessageBox.critical(
                parent,
                SAVE_FAILED_TITLE,
                f'Could not save "{label}":\n\n{exc}',
                buttons.Retry | buttons.Cancel,
                buttons.Retry,
            )
            if answer != buttons.Retry:
                return False


def ask_about_conflict(
    parent: QWidget, model: RehuDocumentModel, conflict: RecordConflict
) -> tuple[ConflictResolution, dict[FieldPath, Any]]:
    """Show the conflict dialog for ``model`` and say what was chosen.

    :param parent: the widget to parent the dialog to.
    :param model: the document whose save was refused.
    :param conflict: the refusal, carrying the file as it is now.
    :returns: the choice, and the value kept for each detail not kept as the document has it.
    """
    differences = metadata_differences(model.base_metadata(), model.document.data, conflict.theirs.data)
    dialog = RecordConflictDialog(model.label or UNTITLED_LABEL, differences, parent)
    try:
        dialog.exec()
        return dialog.resolution, dialog.chosen() if dialog.resolution is ConflictResolution.SAVE else {}
    finally:
        dialog.deleteLater()
