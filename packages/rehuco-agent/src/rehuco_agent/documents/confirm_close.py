"""The question closing one dirty document asks."""

from PySide6.QtWidgets import QMessageBox, QWidget

from .pending_saves import PendingSaves
from .rehu_document_model import UNTITLED_LABEL, RehuDocumentModel
from .save_or_prompt_retry import save_or_prompt_retry


def confirm_close(parent: QWidget, model: RehuDocumentModel, pending_saves: PendingSaves | None) -> bool:
    """Prompt Save/Discard/Cancel for a dirty ``model``, saving it if the answer is Save.

    The prompt names the document by :attr:`~RehuDocumentModel.label`, not the bare filename: every folder resource is
    an `info.rehu` ([[data-model#resource-scoping]]), so two of them open at once would otherwise raise two identical
    prompts naming neither (#177).

    Geometry (size/position) is not yet restored across runs -- deferred to #38. Unlike
    :class:`~rehuco_agent.dialogs.unsaved_changes_dialog.UnsavedChangesDialog`, that's simple here: the static
    ``QMessageBox.warning()`` call already blocks until the box closes for any reason (a button, Escape, or the titlebar
    close button), so reading geometry right after it returns would cover every exit path -- no need for a
    `QDialog.done()`-style single hook.

    :param parent: what the prompt is over.
    :param model: the dirty document model about to be closed.
    :param pending_saves: the window's save jobs, as :func:`~.save_or_prompt_retry.save_or_prompt_retry` takes them.
    :returns: ``True`` if the close should proceed (Discard was chosen, or Save was chosen and succeeded), ``False`` if
        it was cancelled -- either at this prompt, or at the retry/cancel dialog a failed save raises (#146), so a
        document whose save fails is never closed out from under its unsaved edits.
    """
    buttons = QMessageBox.StandardButton
    name = model.label or UNTITLED_LABEL
    answer = QMessageBox.warning(
        parent,
        "Unsaved Changes",
        f'"{name}" has unsaved changes. Save them before closing?',
        buttons.Save | buttons.Discard | buttons.Cancel,
        buttons.Save,
    )
    if answer == buttons.Cancel:
        return False
    if answer == buttons.Save:
        return save_or_prompt_retry(parent, model, pending_saves)
    return True
