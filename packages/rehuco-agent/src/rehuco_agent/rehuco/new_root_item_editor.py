"""A folder's row in the Add Roots dialog's list, always open for editing: its label, its root file and the preset
its layouts start from (#578)."""

from collections.abc import Sequence
from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QComboBox, QFileDialog, QLineEdit, QWidget
from rehuco_core import REHUROOT_SUFFIX, RootCandidate, RootPick

from ..fields.colors import WARNING_COLOR
from ..settings.root_catalog_settings import RootLayout
from .new_root_item_editor_ui import Ui_NewRootItemEditor

REMOVE_ICON: Final = ":/icons/items_delete.svg"
"""The list editors' delete glyph, on the button that takes the row out."""

NEW_LAYOUT: Final = "New layout\N{HORIZONTAL ELLIPSIS}"
"""The layout combo's last entry, which adds a preset rather than picking one."""

CHECKING: Final = "Checking\N{HORIZONTAL ELLIPSIS}"
"""What a row says while its plan is out."""


class NewRootItemEditor(QWidget):
    """The editors of one folder to become a root: its label (its folder's name as the placeholder), its root file
    (the planned one as the placeholder, followed while left empty) with a picker, the preset its layouts start from
    -- the combo ending in :data:`NEW_LAYOUT` -- and why it cannot be added, if it cannot. A button takes it out.

    What it shows is the owner's to set (:meth:`show_row`), which leaves a field being typed in alone. What is typed
    is the owner's to read once a field is left (:attr:`edited`).

    :param parent: optional Qt parent.
    """

    edited = Signal()
    """The label or the root file was left after typing."""

    layout_chosen = Signal(object)
    """Emitted with the :class:`~.RootLayout` picked in the combo."""

    new_layout_requested = Signal()
    """:data:`NEW_LAYOUT` was picked; the combo went back to what it showed."""

    remove_requested = Signal()
    """The row is to be taken out."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_NewRootItemEditor()
        self.__ui.setupUi(self)
        self.__presets: tuple[RootLayout, ...] = ()
        self.__shown = 0
        """The combo row of the folder's preset, which picking :data:`NEW_LAYOUT` goes back to."""
        remove = QAction("Remove", self)
        remove.setToolTip(self.__ui.remove_button.toolTip())
        ActionIconThemeHandler(remove, REMOVE_ICON)
        self.__ui.remove_button.setDefaultAction(remove)
        remove.triggered.connect(self.remove_requested)
        self.__ui.label_edit.editingFinished.connect(self.edited)
        self.__ui.root_file_edit.editingFinished.connect(self.edited)
        self.__ui.browse_button.clicked.connect(self.__browse)
        self.__ui.layout_combo.activated.connect(self.__on_layout_activated)
        self.__ui.problem_label.setStyleSheet(f"color: {WARNING_COLOR};")

    @property
    def label_edit(self) -> QLineEdit:
        """The label field."""
        return self.__ui.label_edit

    @property
    def root_file_edit(self) -> QLineEdit:
        """The root file field."""
        return self.__ui.root_file_edit

    @property
    def layout_combo(self) -> QComboBox:
        """The preset combo."""
        return self.__ui.layout_combo

    @property
    def problem(self) -> str:
        """What the row says is wrong, or that it is being checked; empty when nothing is."""
        return self.__ui.problem_label.text()

    def show_row(
        self, pick: RootPick, line: RootCandidate | None, layout: RootLayout, presets: Sequence[RootLayout]
    ) -> None:
        """Show a folder's pick, its plan and its preset; a field that has the keyboard keeps what is typed.

        :param pick: the folder's pick.
        :param line: its plan, or ``None`` while it is being checked.
        :param layout: its preset.
        :param presets: every preset, in the combo's order.
        """
        ui = self.__ui
        ui.path_label.set_text(str(pick.path))
        ui.label_edit.setPlaceholderText(pick.path.name or str(pick.path))
        if not ui.label_edit.hasFocus():
            ui.label_edit.setText(pick.label or "")
        if line is not None and pick.root_file is None:
            ui.root_file_edit.setPlaceholderText(str(line.root_file))
        if not ui.root_file_edit.hasFocus():
            ui.root_file_edit.setText("" if pick.root_file is None else str(pick.root_file))
        self.__show_presets(presets, layout)
        ui.problem_label.setText(CHECKING if line is None else line.problem)
        ui.problem_label.setVisible(bool(ui.problem_label.text()))

    def __show_presets(self, presets: Sequence[RootLayout], layout: RootLayout) -> None:
        """Fill the combo with the presets and :data:`NEW_LAYOUT`, the folder's preset current.

        :param presets: every preset.
        :param layout: the folder's.
        """
        combo = self.__ui.layout_combo
        self.__presets = tuple(presets)
        combo.clear()
        for preset in self.__presets:
            combo.addItem(preset.label)
        combo.addItem(NEW_LAYOUT)
        self.__shown = self.__presets.index(layout) if layout in self.__presets else 0
        combo.setCurrentIndex(self.__shown)

    def __on_layout_activated(self, row: int) -> None:
        """Say which preset was picked, or that a new one is wanted -- the combo then goes back to the one it showed.

        :param row: the combo's row picked.
        """
        if row < len(self.__presets):
            self.__shown = row
            self.layout_chosen.emit(self.__presets[row])
            return
        # setting the row from here is no pick: ``activated`` is a user's alone
        self.__ui.layout_combo.setCurrentIndex(self.__shown)
        self.new_layout_requested.emit()

    def __browse(self) -> None:
        """Pick where the root file goes with the system's save dialog, starting at the one planned."""
        start = self.__ui.root_file_edit.text() or self.__ui.root_file_edit.placeholderText()
        chosen, _ = QFileDialog.getSaveFileName(self, "Root File", start, f"Root files (*{REHUROOT_SUFFIX})")
        if chosen:
            self.__ui.root_file_edit.setText(chosen)
            self.edited.emit()
