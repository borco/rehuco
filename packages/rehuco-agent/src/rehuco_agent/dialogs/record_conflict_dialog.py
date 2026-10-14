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


class ConflictRow:
    """One detail's row: its value when opened, on each side, and which side is kept.

    :param difference: the detail.
    :param dialog: the dialog the row's radio group belongs to.
    """

    def __init__(self, difference: MetadataDifference, dialog: QWidget) -> None:
        self.difference: Final = difference
        self.field: Final = QLabel(field_label(difference.path))
        if difference.mine_changed and difference.theirs_changed:
            font = self.field.font()
            font.setBold(True)
            self.field.setFont(font)
            self.field.setToolTip("Changed both here and on disk.")
        self.original: Final = QLabel()
        self.mine: Final = QRadioButton()
        self.theirs: Final = QRadioButton()
        for widget, value in (
            (self.original, difference.base),
            (self.mine, difference.mine),
            (self.theirs, difference.theirs),
        ):
            self.__show(widget, value)
        self.group: Final = QButtonGroup(dialog)
        self.group.addButton(self.mine)
        self.group.addButton(self.theirs)
        self.keep_theirs(difference.theirs_changed and not difference.mine_changed)

    def keep_theirs(self, theirs: bool) -> None:
        """Pick which side's value is kept.

        :param theirs: keep the file's value; the edited document's otherwise.
        """
        (self.theirs if theirs else self.mine).setChecked(True)

    @property
    def keeps_theirs(self) -> bool:
        """Whether the file's value is kept."""
        return self.theirs.isChecked()

    @staticmethod
    def __show(widget: QLabel | QRadioButton, value: Any) -> None:
        """Show a value on a label or a radio button, elided, all of it in the tooltip.

        :param widget: where.
        :param value: the value, or :data:`~rehuco_core.ABSENT`.
        """
        if value is ABSENT:
            text = ABSENT_TEXT
        else:
            text = value if isinstance(value, str) else canonical_json(value)
        flat = " ".join(text.split())
        widget.setText(widget.fontMetrics().elidedText(flat, Qt.TextElideMode.ElideRight, VALUE_WIDTH))
        widget.setToolTip(text)
        if value is ABSENT:
            font = widget.font()
            font.setItalic(True)
            widget.setFont(font)


class RecordConflictDialog(QDialog):
    """Every detail an edited document and its file on disk disagree on, with its original value, and which side to
    keep for each -- a merge tool for one record.

    A row starts on the side that changed since the document was opened, so a detail edited on one side only is
    already merged; a detail edited on both starts on *Mine* and its name is in bold. **All Mine** and **All On Disk**
    pick a side for every row. **Save** saves the picks, **Discard My Edits** loads the file as it is, **Cancel**
    leaves the edits unsaved.

    :param label: the document's name, for the message.
    :param differences: what the two disagree on (:func:`~rehuco_core.metadata_differences`).
    :param parent: optional Qt parent.
    """

    def __init__(self, label: str, differences: Sequence[MetadataDifference], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__resolution = ConflictResolution.CANCEL
        self.__ui: Final = Ui_RecordConflictDialog()
        self.__ui.setupUi(self)
        if differences:
            message = f'"{label}" was changed on disk since you opened it. Pick the value to keep for each detail.'
        else:
            message = (
                f'"{label}" was changed on disk since you opened it, but both now carry the same details: '
                "<i>Save</i> keeps them, with your own per-user changes."
            )
        self.__ui.message_label.setText(message)
        self.__rows: Final = [ConflictRow(difference, self) for difference in differences]
        self.__fill()
        self.__ui.all_mine_button.clicked.connect(lambda: self.__keep_all(theirs=False))
        self.__ui.all_on_disk_button.clicked.connect(lambda: self.__keep_all(theirs=True))
        self.__ui.all_mine_button.setEnabled(bool(self.__rows))
        self.__ui.all_on_disk_button.setEnabled(bool(self.__rows))
        self.__ui.save_button.clicked.connect(lambda: self.__choose(ConflictResolution.SAVE))
        self.__ui.discard_button.clicked.connect(lambda: self.__choose(ConflictResolution.DISCARD))

    @property
    def resolution(self) -> ConflictResolution:
        """What was chosen; :attr:`ConflictResolution.CANCEL` until Save or Discard My Edits is pressed."""
        return self.__resolution

    def chosen(self) -> dict[FieldPath, Any]:
        """The file's value for every detail it is kept for.

        :returns: each value by its path -- :data:`~rehuco_core.ABSENT` to remove the detail -- for
            ``RehuDocumentModel.resolve_conflict``.
        """
        return {row.difference.path: row.difference.theirs for row in self.__rows if row.keeps_theirs}

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

    def __keep_all(self, *, theirs: bool) -> None:
        """Keep one side's value for every detail.

        :param theirs: keep the file's values; the edited document's otherwise.
        """
        for row in self.__rows:
            row.keep_theirs(theirs)

    def __choose(self, resolution: ConflictResolution) -> None:
        """Close the dialog with ``resolution``.

        :param resolution: what was chosen.
        """
        self.__resolution = resolution
        self.accept()
