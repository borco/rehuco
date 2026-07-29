"""Batch confirmation for a set of dirty documents, shared by every caller that closes several at once (#176)."""

from PySide6.QtWidgets import QDialog, QWidget

from ..dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from .rehu_document_model import RehuDocumentModel
from .save_or_prompt_retry import save_or_prompt_retry


def confirm_and_save_dirty(parent: QWidget, models: list[RehuDocumentModel]) -> bool:
    """Prompt once for ``models``, saving the checked ones, and report whether to proceed (#176).

    The batch counterpart to :func:`~rehuco_agent.documents.save_or_prompt_retry.save_or_prompt_retry`'s
    single save: one :class:`~rehuco_agent.dialogs.unsaved_changes_dialog.UnsavedChangesDialog` listing
    every dirty document with a checkbox, then a guarded save of each checked one. Cancelling either the
    dialog or a failed save's retry prompt reports ``False``.

    Callers keep their own follow-on action -- ignoring a close event
    (:meth:`~rehuco_agent.main_window.MainWindow.closeEvent`) or removing the docks
    (:meth:`~rehuco_agent.documents.documents_dock.DocumentsDock.close_all`) -- but the *ordering* lives
    here: a cancelled retry aborts before the caller closes anything, so no document is closed out from
    under a failed save (#146). Unchecked dirty documents are left unsaved, their edits discarded along
    with whatever close follows.

    :param parent: the widget to parent the dialog (and any failure prompt) to.
    :param models: the dirty document models to confirm. An empty list proceeds silently -- there is
        nothing to confirm, so no dialog is shown.
    :returns: ``True`` if the caller should proceed with its close; ``False`` if the user cancelled,
        in which case nothing further may be closed.
    """
    if not models:
        return True

    dialog = UnsavedChangesDialog(models, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    for model in dialog.selected_models():
        if not save_or_prompt_retry(parent, model):
            return False
    return True
