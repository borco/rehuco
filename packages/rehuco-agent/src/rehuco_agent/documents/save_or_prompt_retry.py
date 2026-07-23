"""Save a document, surfacing an I/O failure as a retry/cancel dialog rather than a bare traceback (#146)."""

from typing import Final

from PySide6.QtWidgets import QMessageBox, QWidget

from .rehu_document_model import RehuDocumentModel

SAVE_FAILED_TITLE: Final = "Save Failed"
"""Title of the dialog shown when a save raises ``OSError`` (#146)."""


def save_or_prompt_retry(parent: QWidget, model: RehuDocumentModel) -> bool:
    """Save ``model``, prompting **Retry/Cancel** on an I/O failure instead of letting it escape (#146).

    :meth:`~RehuDocumentModel.save` does real file I/O and can raise ``OSError`` -- an offline SMB mount
    is an explicitly supported scenario ([[mounts-and-storage#offline-mounts]]) where a save fails
    *transiently*, so the failure is offered as a retry loop rather than lost edits and a stderr
    traceback. This is the one seam every save call site funnels through -- the Save and Upgrade actions,
    Save All, the per-tab and batch close guards, and the whole-app close -- so how a failed save is
    surfaced (and the choice to abort whatever the save was gating) lives in exactly one place, the same
    way :meth:`~rehuco_agent.documents.document_widget.DocumentWidget.__on_convert_triggered` already
    guards the convert actions.

    Only ``OSError`` is caught: a save-blocking lock raises ``ValueError`` from
    :meth:`~rehuco_core.RehuDocument.save`, but editing is disabled while a document is locked, so a
    lock never reaches a save call site here ([[data-model#write-integrity]]) -- only the file I/O can
    actually fail.

    :param parent: the widget to parent the error dialog to.
    :param model: the document model to save.
    :returns: ``True`` once the document is saved; ``False`` if the user cancelled after a failure --
        nothing was written, and the caller should abort whatever the save was gating (e.g. a close).
    """
    buttons = QMessageBox.StandardButton
    while True:
        try:
            model.save()
            return True
        except OSError as exc:
            label = model.label or "Untitled"
            answer = QMessageBox.critical(
                parent,
                SAVE_FAILED_TITLE,
                f'Could not save "{label}":\n\n{exc}',
                buttons.Retry | buttons.Cancel,
                buttons.Retry,
            )
            if answer != buttons.Retry:
                return False
