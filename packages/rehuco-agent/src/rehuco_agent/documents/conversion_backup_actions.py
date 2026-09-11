"""Discard Backups, on one open document ([[acquisition-tooling#convert-mechanics]], #193).

The single-resource half of #193, reachable while simply browsing a converted resource rather than only
from the bulk manager -- because the moment someone notices the backups are just taking up space is
usually the moment they are looking at the resource.

**Runs inline, not on the queue.** A discard is a handful of unlinks over one directory, and
:meth:`~rehuco_agent.documents.RehuDocumentModel.convert` -- the operation that created the backups -- is
already inline for the same reason. The bulk dialog queues because it has hundreds of resources to get
through; one resource has no such problem, and putting an instantaneous edit behind a terabyte of hashing
would be worse than doing it.

**The banner says, the toolbar does.** The document's inline strip stays message-only, the rule
`~rehuco_agent.documents.document_widget.DocumentWidget` already states -- every kind's remedy is
already on screen -- so what this class contributes to the strip is one sentence and what it contributes
to the toolbar is the one action that sentence is about.
"""

import logging
from typing import Final

import humanize
from borco_core.logging import LogScope
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMessageBox, QWidget
from rehuco_core import ConversionBackups, conversion_backups, discard_conversion_backups

from .recycle_bin_deleter import configured_deleter
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

DISCARD_ICON_RESOURCE: Final = ":/icons/backup_delete.svg"
"""This action's icon.

Set with a plain ``QIcon`` rather than through
:class:`~borco_pyside.theming.ActionIconThemeHandler`, the same way
:data:`~rehuco_agent.documents.document_widget.CONVERT_DISCARD_ICON_RESOURCE` is: it carries its own red,
which is the point of it, and the handler exists for the icons drawn *without* a color so a theme can give
them one."""

DISCARD_LABEL: Final = "&Discard Backups"
DISCARD_TOOLTIP: Final = "Delete this resource's .orig backups, making the conversion permanent."

NOTICE: Final = "This resource still has its conversion backups — {summary}."
"""What the document's inline strip says while backups are retained."""

DISCARD_TITLE: Final = "Discard Backups"
DISCARD_QUESTION: Final = (
    "Permanently delete this resource's backups, freeing {size}?\n\n"
    "This cannot be undone. Its original .tc and screenshots are gone for good."
)

DISCARD_FAILED_TITLE: Final = "Discard Failed"


class ConversionBackupActions(QObject):
    """One document's Discard Backups action, and the sentence about it (#193).

    Offered exactly while the resource still holds retained backups, the same
    visible-while-the-condition-holds shape the two Convert actions already have for ``legacy_tc``. A
    document that was never converted, or whose backups have already been discarded, shows nothing and
    says nothing.

    **The inventory is re-read at the file-touching seams**, the set
    :data:`~rehuco_agent.documents.source_views.ON_DISK_REFRESH_FIELDS` already names: a path change, a
    save (``dirty`` clearing), a lock-reason change, and
    :attr:`~rehuco_agent.documents.RehuDocumentModel.reloaded`.

    **A save never discards the backups**, and nothing here does it as a side effect: discarding is the
    one irreversible step in the whole import flow ([[acquisition-tooling#convert-mechanics]]), and the
    ``.orig`` set is also the only copy of the original ``.tc``.

    :param model: the document these actions are about.
    :param parent: optional Qt parent, and the widget confirmations are shown over.
    """

    changed = Signal()
    """Fires when :attr:`notice` may have changed -- what the document's banner rebuilds on."""

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__parent: Final = parent
        self.__backups: ConversionBackups | None = None

        self.__discard_action: Final = QAction(DISCARD_LABEL, self)
        self.__discard_action.setToolTip(DISCARD_TOOLTIP)
        self.__discard_action.setIcon(QIcon(DISCARD_ICON_RESOURCE))
        self.__discard_action.triggered.connect(self.discard)

        model.path_changed.connect(self.refresh)  # type: ignore[attr-defined]
        model.dirty_changed.connect(self.refresh)  # type: ignore[attr-defined]
        model.lock_reasons_changed.connect(self.refresh)  # type: ignore[attr-defined]
        model.reloaded.connect(self.refresh)
        self.refresh()

    # region What the document shows

    @property
    def discard_action(self) -> QAction:
        """Deletes this resource's retained backups, making the conversion permanent."""
        return self.__discard_action

    @property
    def retained(self) -> bool:
        """Whether this resource still holds conversion backups -- what decides whether Discard is
        offered, and whether the banner has anything to say."""
        return self.__retained_backups() is not None

    @property
    def notice(self) -> str:
        """What the document's inline strip says about these backups, or an empty string when there are
        none.

        Names the size, because the reason to act on retained backups at all is usually that they
        occupy space.
        """
        backups = self.__retained_backups()
        if backups is None:
            return ""
        return NOTICE.format(summary=self.__summary(backups))

    def refresh(self) -> None:
        """Re-read the inventory and re-offer the action, at a seam where the files may have moved.

        Cheap enough to run at every such seam: one directory listing over the one resource on screen.

        A :attr:`~RehuDocumentModel.pending` session-restore placeholder is treated like a document with
        no path: its file is deliberately unread (#66), and this inventory would otherwise be the very
        read the deferral exists to avoid. The deferred load emits ``reloaded``, which is already wired
        here, so the inventory catches up the moment the document is real.
        """
        path = self.__model.path if not self.__model.pending else None
        self.__backups = conversion_backups(path) if path is not None else None
        self.__discard_action.setVisible(self.retained)
        self.changed.emit()

    # endregion

    # region Acting

    def discard(self) -> None:
        """Delete this resource's retained backups, after confirming that it cannot be undone.

        The document itself is untouched: a discard removes only the ``.orig`` siblings, so there is
        nothing to reseed and no path to follow -- only a banner row that stops being true.

        Re-read at the click for the same reason a fresh confirmation needs to be: the byte total the
        confirmation names must be the one the delete would actually free.
        """
        self.refresh()
        backups = self.__retained_backups()
        if backups is None:
            return
        if not self.__confirm(DISCARD_TITLE, DISCARD_QUESTION.format(size=self.__size(backups))):
            return
        with LogScope.open(backups.rehu_path):
            try:
                discarded = discard_conversion_backups(backups.rehu_path, deleter=configured_deleter())
            except OSError as error:
                LOG.error("Could not discard the backups beside %s: %s", backups.rehu_path, error)
                self.__report(DISCARD_FAILED_TITLE, str(error))
                self.refresh()
                return
            LOG.info("Discarded %d backup(s) beside %s.", len(discarded), backups.rehu_path)
        self.refresh()

    @staticmethod
    def __summary(backups: ConversionBackups) -> str:
        """This resource's backups as prose, e.g. ``"6 files, 14.0 MB"``."""
        count = len(backups.backups)
        return f"{count} file{'' if count == 1 else 's'}, {ConversionBackupActions.__size(backups)}"

    @staticmethod
    def __size(backups: ConversionBackups) -> str:
        """What this resource's backups occupy, in the long form the bulk manager also uses."""
        return humanize.naturalsize(backups.total_bytes)

    def __retained_backups(self) -> ConversionBackups | None:
        """This resource's inventory while it still holds backups, else ``None``.

        The one place *is there anything to act on* is decided, so every surface reads the same answer,
        and gets the inventory narrowed in the same breath rather than checking a flag and then reaching
        for a value that could still be absent.

        :returns: the inventory, or ``None`` when this document has no path, was never converted, or has
            had its backups discarded.
        """
        backups = self.__backups
        return backups if backups is not None and backups.backups else None

    def __confirm(self, title: str, question: str) -> bool:
        """Put one destructive question, defaulting to No.

        :param title: the dialog's title.
        :param question: what is being asked.
        :returns: whether the answer was Yes.
        """
        answer = QMessageBox.warning(
            self.__parent,
            title,
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def __report(self, title: str, message: str) -> None:
        """Say why nothing happened.

        :param title: the dialog's title.
        :param message: the reason.
        """
        QMessageBox.warning(self.__parent, title, message)

    # endregion
