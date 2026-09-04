"""Revert Conversion and Discard Backups, on one open document ([[acquisition-tooling#convert-mechanics]], #193).

The single-resource half of #193, reachable while simply browsing a converted resource rather than only
from the bulk manager -- because the moment someone notices a conversion went wrong is usually the moment
they are looking at it.

**Both run inline, not on the queue.** A revert is a handful of renames and unlinks over one directory,
and :meth:`~rehuco_agent.documents.RehuDocumentModel.convert` -- this operation's exact mirror -- is
already inline for the same reason. The bulk dialog queues because it has hundreds of resources to get
through; one resource has no such problem, and putting an instantaneous edit behind a terabyte of hashing
would be worse than doing it.

**The banner says, the toolbar does.** The document's inline strip stays message-only, the rule
`~rehuco_agent.documents.document_widget.DocumentWidget` already states -- every kind's remedy is
already on screen -- so what this class contributes to the strip is one sentence and what it contributes
to the toolbar is the two actions that sentence is about.
"""

import logging
from typing import Final

import humanize
from borco_core.logging import LogScope
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMessageBox, QWidget
from rehuco_core import ConversionBackups, conversion_backups, discard_conversion_backups

from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

REVERT_ICON_RESOURCE: Final = ":/icons/backup_restore.svg"
DISCARD_ICON_RESOURCE: Final = ":/icons/backup_delete.svg"
"""The two actions' icons.

Set with a plain ``QIcon`` rather than through
:class:`~borco_pyside.theming.ActionIconThemeHandler`, the same way
:data:`~rehuco_agent.documents.document_widget.CONVERT_DISCARD_ICON_RESOURCE` is: both carry their own
red, which is the point of them, and the handler exists for the icons drawn *without* a color so a theme
can give them one."""

REVERT_LABEL: Final = "Revert &Conversion"
DISCARD_LABEL: Final = "&Discard Backups"

REVERT_TOOLTIP: Final = "Restore this resource's original .tc and screenshots, deleting the converted .rehu."
DISCARD_TOOLTIP: Final = "Delete this resource's .orig backups, making the conversion permanent."

NOTICE: Final = "This resource still has its conversion backups — {summary}."
EDITED_NOTICE: Final = (
    "This resource still has its conversion backups — {summary}. It has been saved since it was converted, "
    "so reverting now would discard those edits."
)
"""What the document's inline strip says while backups are retained.

**Two wordings, because the second is a different fact.** Once the ``.rehu`` has been saved again, a
revert stops being free and starts costing real work ([[field-schema#record-timestamps]] is how that is
known) -- and a reader deciding whether to keep the backups around deserves to learn that while looking
at the resource, not inside the confirmation they are already halfway through."""

REVERT_TITLE: Final = "Revert Conversion"
REVERT_QUESTION: Final = (
    "Revert this conversion?\n\n"
    "{summary} are restored to their original names, and the .rehu the conversion wrote is deleted."
)
REVERT_EDITED_WARNING: Final = "\n\nThis resource has been saved since it was converted. Those edits are discarded."
REVERT_DIRTY_WARNING: Final = "\n\nThis document has unsaved changes. They are discarded too."

DISCARD_TITLE: Final = "Discard Backups"
DISCARD_QUESTION: Final = (
    "Permanently delete this resource's backups, freeing {size}?\n\n"
    "This cannot be undone. The conversion can no longer be reverted."
)

REFUSED_TITLE: Final = "Cannot Revert"
NO_LEGACY_REFUSAL: Final = "There is no backed-up .tc file beside this resource, so this is not a conversion to undo."
OBSTRUCTED_REFUSAL: Final = "{name} is already there, and a revert will not overwrite it."
FAILED_TITLE: Final = "Revert Failed"
DISCARD_FAILED_TITLE: Final = "Discard Failed"


class ConversionBackupActions(QObject):
    """One document's Revert Conversion and Discard Backups actions, and the sentence about them (#193).

    Both actions are offered exactly while the resource still holds retained backups, the same
    visible-while-the-condition-holds shape the two Convert actions already have for ``legacy_tc``. A
    document that was never converted, or whose backups have been discarded, shows neither and says
    nothing.

    **The inventory is re-read at the file-touching seams**, the set
    :data:`~rehuco_agent.documents.source_views.ON_DISK_REFRESH_FIELDS` already names: a path change, a
    save (``dirty`` clearing), a lock-reason change, and
    :attr:`~rehuco_agent.documents.RehuDocumentModel.reloaded`. A save is in there deliberately -- it is
    what makes *edited since* become true, and the strip has to start saying so at that moment rather
    than at the next time the document happens to be reopened.

    **A save never discards the backups**, and nothing here does it as a side effect: discarding is the
    one irreversible step in the whole import flow ([[acquisition-tooling#convert-mechanics]]), the
    ``.orig`` set is also the only copy of the original ``.tc`` and of the tie-break losers, and someone
    may edit a resource and only then conclude the conversion was wrong.

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

        self.__revert_action: Final = QAction(REVERT_LABEL, self)
        self.__revert_action.setToolTip(REVERT_TOOLTIP)
        self.__revert_action.setIcon(QIcon(REVERT_ICON_RESOURCE))
        self.__revert_action.triggered.connect(self.revert)

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
    def revert_action(self) -> QAction:
        """Undoes this resource's conversion from its retained backups, in place."""
        return self.__revert_action

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
    def undoable(self) -> bool:
        """Whether a backed-up ``.tc`` is here, so there is a conversion to undo at all -- what decides
        whether Revert is offered (#246).

        **Not the same question as :attr:`retained`**, and offering Revert on that one was the defect:
        backups are any ``.orig`` sibling, deliberately unscoped
        ([[acquisition-tooling#convert-mechanics]]), so a directory holding only a retired checksum
        manifest (an ``info.sfv.orig``, [[data-model#checksums]]) reads as *has backups* while there is
        nothing to revert to. A convert-discarding-originals run leaves exactly that shape, and the
        button it offered could only ever answer :data:`NO_LEGACY_REFUSAL`.

        Deliberately weaker than :attr:`~rehuco_core.ConversionBackups.revertible`, which also wants the
        restore targets free: an occupied target is a conversion that *can* be undone once the file in
        the way is moved, so Revert stays offered and :meth:`revert` names what is blocking it. Hiding
        it there would leave the reader nothing to act on and no reason given.
        """
        backups = self.__retained_backups()
        return backups is not None and backups.legacy_restored is not None

    @property
    def edited_since(self) -> bool:
        """Whether the ``.rehu`` has been saved again since the conversion, so reverting now costs real
        work -- what turns the banner's row from information into a warning.

        ``False`` for a resource with no retained backups, and for one with nothing to revert *to*
        (the same condition :attr:`undoable` reads, #246) -- in both the question does not arise, and
        an edit costs nothing by being unrevertable when no revert was on offer.
        """
        backups = self.__retained_backups()
        return backups is not None and backups.legacy_restored is not None and backups.edited_since

    @property
    def notice(self) -> str:
        """What the document's inline strip says about these backups, or an empty string when there are
        none.

        Names the size, because the reason to act on retained backups at all is usually that they
        occupy space -- and says when a revert would now cost edits, since that is the fact that
        changes what the right action is.
        """
        backups = self.__retained_backups()
        if backups is None:
            return ""
        template = EDITED_NOTICE if self.edited_since else NOTICE
        return template.format(summary=self.__summary(backups))

    def refresh(self) -> None:
        """Re-read the inventory and re-offer the actions, at a seam where the files may have moved.

        Cheap enough to run at every such seam: one directory listing plus the one read of the ``.rehu``
        that :attr:`~rehuco_core.ConversionBackups.edited_since` needs, over the one resource on screen.

        A :attr:`~RehuDocumentModel.pending` session-restore placeholder is treated like a document with
        no path: its file is deliberately unread (#66), and this inventory would otherwise be the very
        read the deferral exists to avoid -- it loads the whole ``.rehu`` for the timestamps. The
        deferred load emits ``reloaded``, which is already wired here, so the inventory catches up the
        moment the document is real.
        """
        path = self.__model.path if not self.__model.pending else None
        self.__backups = conversion_backups(path) if path is not None else None
        self.__revert_action.setVisible(self.undoable)
        self.__discard_action.setVisible(self.retained)
        self.changed.emit()

    # endregion

    # region Acting

    def revert(self) -> None:
        """Undo this resource's conversion, after confirming what it costs.

        Refuses up front where the inventory already knows it cannot run -- an occupied restore target,
        naming the file in the way and changing nothing, rather than letting the operation raise the same
        answer out of a confirmed action. That is the refusal this surface exists to put: the *other*
        one, no backed-up ``.tc`` at all, is not offered in the first place (:attr:`undoable`, #246) and
        so only a click racing an out-of-band change can still reach it.

        The inventory is re-read **at the click**, not taken from the last seam's cache: the model's
        signals cover this app's own writes, but an out-of-band edit -- or the bulk manager acting on
        the same directory -- moves the files without one, and a confirmation must describe the files
        as they are when it is put.
        """
        self.refresh()
        backups = self.__retained_backups()
        if backups is None:
            return
        if not backups.revertible:
            self.__report(REFUSED_TITLE, self.__refusal(backups))
            return
        if not self.__confirm(REVERT_TITLE, self.__revert_question(backups)):
            return
        try:
            self.__model.revert_conversion()
        except OSError as error:
            # a refusal that only the operation itself can see -- the directory changed between the
            # inventory above and the rename below, which is exactly the race the plan-then-replace
            # sequence refuses rather than half-reverts through
            LOG.error("Could not revert the conversion of %s: %s", backups.rehu_path, error)
            self.__report(FAILED_TITLE, str(error))
            self.refresh()

    def discard(self) -> None:
        """Delete this resource's retained backups, after confirming that it cannot be undone.

        The document itself is untouched: a discard removes only the ``.orig`` siblings, so there is
        nothing to reseed and no path to follow -- only a banner row that stops being true.

        Re-read at the click for the same reason :meth:`revert` is: the byte total the confirmation
        names must be the one the delete would actually free.
        """
        self.refresh()
        backups = self.__retained_backups()
        if backups is None:
            return
        if not self.__confirm(DISCARD_TITLE, DISCARD_QUESTION.format(size=self.__size(backups))):
            return
        with LogScope.open(backups.rehu_path):
            try:
                discarded = discard_conversion_backups(backups.rehu_path)
            except OSError as error:
                LOG.error("Could not discard the backups beside %s: %s", backups.rehu_path, error)
                self.__report(DISCARD_FAILED_TITLE, str(error))
                self.refresh()
                return
            LOG.info("Discarded %d backup(s) beside %s.", len(discarded), backups.rehu_path)
        self.refresh()

    def __revert_question(self, backups: ConversionBackups) -> str:
        """What the revert confirmation asks, naming every kind of work it would discard.

        :param backups: this resource's inventory.
        :returns: the question.
        """
        question = REVERT_QUESTION.format(summary=self.__summary(backups))
        if backups.edited_since:
            question += REVERT_EDITED_WARNING
        if self.__model.dirty:
            question += REVERT_DIRTY_WARNING
        return question

    @staticmethod
    def __refusal(backups: ConversionBackups) -> str:
        """Why this resource's conversion cannot be reverted.

        :param backups: this resource's inventory, which already knows.
        :returns: the reason, in the vocabulary :func:`~rehuco_core.revert_conversion` refuses in.
        """
        if backups.legacy_restored is None:
            return NO_LEGACY_REFUSAL
        # pylint's astroid mis-infers a tuple element of `obstructions` (a `Path`) as a PySide6 signal
        # descriptor in this module -- this is an ordinary attribute read
        return OBSTRUCTED_REFUSAL.format(name=backups.obstructions[0].name)  # pylint: disable=no-member

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

        The one place *is there anything to act on* is decided, so every surface and both actions read
        the same answer -- and each gets the inventory narrowed in the same breath, rather than checking
        a flag and then reaching for a value that could still be absent.

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
