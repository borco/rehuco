"""The one permanent-delete confirmation, carrying the matching *without asking* box (#313).

Every user-facing delete in the app answers to `DeletionSettings` (#312), and this is where that
policy is put to the user: :func:`confirm_delete` is the whole up-front gate -- nothing is asked while
the delete is bound for the Recycle Bin or the kind's box is already ticked, and otherwise the question
is :func:`ask_permanent_delete`'s, a `QMessageBox` whose checkbox **is** the Files page's own *without
asking* box, worded verbatim so the user knows which box unticks it. `AskingDeleter` puts the same
question, through the same function, at the one other point a delete turns permanent: the Recycle Bin
refusing a file.

Top-level rather than under ``documents`` or ``settings``: the images dock (``fields/widgets``) is one
of its callers, and the field toolkit may import neither ``documents`` nor ``settings``
([[plugins#field-toolkit]]) -- the same arrangement `asking_deleter` has. `DeletionKind` is
re-exported here for that caller, so the toolkit names its kind through the one module it may import.
"""

from PySide6.QtWidgets import QCheckBox, QMessageBox, QWidget

from .settings.deletion_settings import (
    WITHOUT_ASKING_BOXES,
    DeletionKind,
    remember_without_asking,
    shared_deletion_settings,
)

__all__ = ["DeletionKind", "ask_permanent_delete", "confirm_delete"]


def confirm_delete(parent: QWidget | None, kind: DeletionKind, title: str, text: str) -> bool:
    """Whether a delete of ``kind`` may go ahead -- asking only when it is permanent and not yet
    silenced (#312, #313).

    Returns ``True`` without showing anything while **Move deleted files to the Recycle Bin, if
    possible** is on (the delete is not permanent; if the bin then proves unreachable,
    `AskingDeleter` asks at that point instead) or while the kind's *without asking* box is ticked.
    Otherwise the question is :func:`ask_permanent_delete`'s.

    :param parent: the widget the question is shown over.
    :param kind: what kind of file is being deleted -- which box the question carries.
    :param title: the dialog's title.
    :param text: the dialog's body, naming what is deleted and what cannot be undone.
    :returns: whether to go ahead.
    """
    settings = shared_deletion_settings()
    if settings.use_recycle_bin or settings.without_asking(kind):
        return True
    return ask_permanent_delete(parent, kind, title, text)


def ask_permanent_delete(parent: QWidget | None, kind: DeletionKind, title: str, text: str) -> bool:
    """Put the permanent-delete question, with ``kind``'s *without asking* box on it (#313).

    Always shown -- the gating is :func:`confirm_delete`'s and `AskingDeleter`'s, each of which knows
    why the delete is permanent. A constructed box rather than the static ``warning()``, because only a
    constructed one takes a checkbox. Defaults to No.

    **The box is applied only on Yes.** Ticked and answered No, nothing is written and the question
    is asked next time: a No with "don't ask" would mean *never delete*, which the flag cannot express.

    :param parent: the widget the question is shown over.
    :param kind: what kind of file is being deleted -- which box the question carries.
    :param title: the dialog's title.
    :param text: the dialog's body.
    :returns: whether the answer was Yes.
    """
    box = QMessageBox(
        QMessageBox.Icon.Warning,
        title,
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        parent,
    )
    box.setDefaultButton(QMessageBox.StandardButton.No)
    check_box = QCheckBox(WITHOUT_ASKING_BOXES[kind].label)
    box.setCheckBox(check_box)
    answered_yes = QMessageBox.StandardButton(box.exec()) == QMessageBox.StandardButton.Yes
    if answered_yes and check_box.isChecked():
        remember_without_asking(kind)
    return answered_yes
