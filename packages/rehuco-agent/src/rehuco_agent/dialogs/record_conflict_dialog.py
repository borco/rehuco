"""A save refused as a conflict, shown side by side to choose from ([[nodes#access-seam]], #416)."""

from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QDialog, QLabel, QRadioButton, QWidget
from rehuco_core import ABSENT, FieldPath, MetadataDifference, canonical_json

from .record_conflict_dialog_ui import Ui_RecordConflictDialog

ABSENT_TEXT: Final = "(none)"
"""What a side without the field shows."""

HEADERS: Final = ("Field", "Original", "Mine", "On Disk")
"""The grid's column titles."""

NOTHING_TO_SAVE_TIP: Final = (
    "Nothing to save: every row keeps the value the file already holds. Discard My Edits loads the file as it is."
)
"""Save's tooltip while it would write nothing the file does not already hold."""

VALUE_WIDTH: Final = 280
"""How wide a value is shown, in pixels, before it is elided; its tooltip has all of it."""


def field_label(path: FieldPath) -> str:
    """How a detail is named in the grid: its keys joined by dots, a list item by its index, as in
    ``core.sources[0].title``.

    :param path: where the detail sits.
    :returns: its name.
    """
    return "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in path).lstrip(".")


class ConflictResolution(StrEnum):
    """What the person chose to do with a refused save."""

    SAVE = "save"
    """Save, keeping the chosen side of each detail."""

    DISCARD = "discard"
    """Discard this document's edits and load the file as it is now."""

    CANCEL = "cancel"
    """Do nothing; the edits stay unsaved."""


class ConflictSide(StrEnum):
    """Which of a row's three values is kept."""

    ORIGINAL = "original"
    """The value when the record was opened."""

    MINE = "mine"
    """The edited document's value."""

    THEIRS = "theirs"
    """The file's value now."""


class ConflictRow:
    """One row: a value as it was opened, as edited, and on disk now -- each a radio of one group -- and which is kept.

    A value that differs from the original is in bold, so what each side changed reads at a glance; a value both sides
    changed is bold twice over. The row starts on the side that changed: *On Disk* when only the file did, *Mine*
    otherwise.

    :param difference: the value.
    :param dialog: the dialog the row's radio group belongs to.
    """

    def __init__(self, difference: MetadataDifference, dialog: QWidget) -> None:
        self.difference: Final = difference
        self.field: Final = QLabel(field_label(difference.path))
        self.original: Final = self.__radio(difference.base, changed=False)
        self.mine: Final = self.__radio(difference.mine, changed=difference.mine_changed)
        self.theirs: Final = self.__radio(difference.theirs, changed=difference.theirs_changed)
        self.group: Final = QButtonGroup(dialog)
        for radio in (self.original, self.mine, self.theirs):
            self.group.addButton(radio)
        self.keep(
            ConflictSide.THEIRS if difference.theirs_changed and not difference.mine_changed else ConflictSide.MINE
        )

    def keep(self, side: ConflictSide) -> None:
        """Pick which value is kept.

        :param side: the value's side.
        """
        {ConflictSide.ORIGINAL: self.original, ConflictSide.MINE: self.mine, ConflictSide.THEIRS: self.theirs}[
            side
        ].setChecked(True)

    @property
    def kept(self) -> Any:
        """The value kept, or :data:`~rehuco_core.ABSENT` for one to remove."""
        if self.original.isChecked():
            return self.difference.base
        return self.difference.theirs if self.theirs.isChecked() else self.difference.mine

    @staticmethod
    def __radio(value: Any, *, changed: bool) -> QRadioButton:
        """A radio button keeping a value, elided, all of it in the tooltip.

        :param value: the value, or :data:`~rehuco_core.ABSENT`, shown in italics.
        :param changed: whether it differs from the original, shown in bold.
        :returns: the button.
        """
        if value is ABSENT:
            text = ABSENT_TEXT
        else:
            text = value if isinstance(value, str) else canonical_json(value)
        radio = QRadioButton()
        font = radio.font()
        font.setItalic(value is ABSENT)
        font.setBold(changed)
        radio.setFont(font)
        flat = " ".join(text.split())
        radio.setText(radio.fontMetrics().elidedText(flat, Qt.TextElideMode.ElideRight, VALUE_WIDTH))
        radio.setToolTip(text)
        return radio


class RecordConflictDialog(QDialog):
    """Every value an edited document and its file on disk disagree on -- its details and its own per-user fields
    (:func:`~rehuco_core.record_differences`) -- with the original value, and which side to keep for each: a merge
    tool for one record.

    Each row keeps one of its three values (:class:`ConflictRow`): *Original*, *Mine* or *On Disk*, a value that
    differs from the original in bold. A row starts on the side that changed, so a value edited on one side only is
    already merged. **All Mine** and **All On Disk** pick a side for every row. **Save** saves the picks, **Discard My
    Edits** loads the file as it is, **Cancel** leaves the edits unsaved.

    **Save is disabled while every row keeps the file's value** -- an empty dialog included: such a save would write
    the file back as it is, which is what Discard My Edits does.

    :param label: the document's name, for the message.
    :param differences: what the two disagree on (:func:`~rehuco_core.record_differences`).
    :param parent: optional Qt parent.
    """

    def __init__(self, label: str, differences: Sequence[MetadataDifference], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__resolution = ConflictResolution.CANCEL
        self.__ui: Final = Ui_RecordConflictDialog()
        self.__ui.setupUi(self)
        if differences:
            message = f'"{label}" was changed on disk since you opened it. Pick the value to keep for each row.'
        else:
            message = (
                f'"{label}" was changed on disk since you opened it, and both now hold the same values: there is '
                "nothing of yours to save. <i>Discard My Edits</i> loads the file as it is."
            )
        self.__ui.message_label.setText(message)
        self.__rows: Final = [ConflictRow(difference, self) for difference in differences]
        self.__fill()
        self.__ui.all_mine_button.clicked.connect(lambda: self.__keep_all(ConflictSide.MINE))
        self.__ui.all_on_disk_button.clicked.connect(lambda: self.__keep_all(ConflictSide.THEIRS))
        self.__ui.all_mine_button.setEnabled(bool(self.__rows))
        self.__ui.all_on_disk_button.setEnabled(bool(self.__rows))
        self.__ui.save_button.clicked.connect(lambda: self.__choose(ConflictResolution.SAVE))
        self.__ui.discard_button.clicked.connect(lambda: self.__choose(ConflictResolution.DISCARD))
        self.__save_tip: Final = self.__ui.save_button.toolTip()
        for row in self.__rows:
            row.group.buttonToggled.connect(lambda _button, _checked: self.__update_save())
        self.__update_save()

    @property
    def resolution(self) -> ConflictResolution:
        """What was chosen; :attr:`ConflictResolution.CANCEL` until Save or Discard My Edits is pressed."""
        return self.__resolution

    def chosen(self) -> dict[FieldPath, Any]:
        """The value kept for every row, whichever side it comes from.

        :returns: each value by its path -- :data:`~rehuco_core.ABSENT` to remove it -- for
            ``RehuDocumentModel.resolve_conflict``.
        """
        return {row.difference.path: row.kept for row in self.__rows}

    def __fill(self) -> None:
        """Lay out the column titles and one row per difference."""
        grid = self.__ui.rows_layout
        for column, title in enumerate(HEADERS):
            grid.addWidget(QLabel(f"<b>{title}</b>"), 0, column)
        for index, row in enumerate(self.__rows, start=1):
            for column, widget in enumerate((row.field, row.original, row.mine, row.theirs)):
                grid.addWidget(widget, index, column, Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnStretch(len(HEADERS) - 1, 1)
        grid.setRowStretch(len(self.__rows) + 1, 1)

    def __keep_all(self, side: ConflictSide) -> None:
        """Keep one side's value for every row.

        :param side: the side.
        """
        for row in self.__rows:
            row.keep(side)

    def __update_save(self) -> None:
        """Enable Save only while a row keeps a value other than the file's: otherwise it would write the file back as
        it is -- which keeping *Original* where the file still holds the original does too."""
        useful = any(row.kept != row.difference.theirs for row in self.__rows)
        button = self.__ui.save_button
        button.setEnabled(useful)
        button.setToolTip(self.__save_tip if useful else NOTHING_TO_SAVE_TIP)

    def __choose(self, resolution: ConflictResolution) -> None:
        """Close the dialog with ``resolution``.

        :param resolution: what was chosen.
        """
        self.__resolution = resolution
        self.accept()
