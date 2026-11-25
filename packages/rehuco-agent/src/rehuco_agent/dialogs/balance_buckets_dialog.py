"""The dialog that starts a balance of the open catalog's buckets
([[mounts-and-storage#bucket-rebalance]], #681).
"""

from collections.abc import Sequence
from typing import Final, override
from uuid import UUID

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidgetItem, QPushButton, QWidget
from rehuco_core import MappedRoot, has_bucketed_layout

from ..settings.balance_buckets_dialog_settings import BalanceBucketsDialogSettings
from ..settings.move_settings import MoveSettings
from ..settings.persistent_settings import persistent_settings
from .balance_buckets_dialog_ui import Ui_BalanceBucketsDialog

START_TEXT: Final = "Start"
"""What the OK button says: it enqueues the balance."""

NO_RULE_NOTE: Final = "no rule has {buckets}: any buckets left are joined"
"""What a root whose layouts have no buckets reads besides its name."""


class BalanceBucketsDialog(QDialog):
    """Asks which roots to balance and with which limits; **Start** saves the limits and accepts, Cancel saves neither.

    Opened from the menu it checks the roots checked on the last run accepted from there, and for a catalog with none of
    those every root whose layouts have buckets. Opened for one root it checks that root alone, and what the menu checks
    next time stays as it was. Start needs one root checked. Geometry is restored on construction and saved in
    :meth:`done`, which every exit path funnels through.

    :param roots: the roots of the open catalog this machine maps.
    :param moves: the limits, which Start updates.
    :param only: the root the dialog is opened for; ``None`` from the menu.
    :param parent: optional Qt parent.
    """

    def __init__(
        self, roots: Sequence[MappedRoot], moves: MoveSettings, only: UUID | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_BalanceBucketsDialog()
        self.__ui.setupUi(self)
        self.__moves: Final = moves
        self.__only: Final = only
        self.__settings: Final = BalanceBucketsDialogSettings()
        self.__settings.load(persistent_settings())
        if self.__settings.geometry:
            self.restoreGeometry(QByteArray(self.__settings.geometry))
        self.start_button.setText(START_TEXT)
        self.__ui.limits_editor.limits = (moves.split_limit, moves.join_limit)

        self.__roots: Final = tuple(roots)
        checked = self.__preselected()
        for root in self.__roots:
            self.__ui.roots_list.addItem(self.__item_of(root, root.root_id in checked))
        self.__ui.roots_list.setVisible(bool(self.__roots))
        self.__ui.no_roots_label.setVisible(not self.__roots)
        self.__ui.roots_list.itemChanged.connect(self.__update_start)
        self.__update_start()

    @property
    def start_button(self) -> QPushButton:
        """The Start button, for tests."""
        return self.__ui.button_box.button(QDialogButtonBox.StandardButton.Ok)

    @property
    def limits(self) -> tuple[int, int]:
        """The split limit and the join limit, as entered."""
        return self.__ui.limits_editor.limits

    @property
    def root_ids(self) -> tuple[UUID, ...]:
        """The roots checked, in the order listed."""
        return tuple(
            root.root_id
            for row, root in enumerate(self.__roots)
            if self.__ui.roots_list.item(row).checkState() is Qt.CheckState.Checked
        )

    @override
    def accept(self) -> None:
        """Save the limits, and the roots checked unless the dialog was opened for one, then close accepted."""
        self.__moves.split_limit, self.__moves.join_limit = self.limits
        self.__moves.save(persistent_settings())
        if self.__only is None:
            listed = {root.root_id for root in self.__roots}
            self.__settings.roots = (self.__settings.roots - listed) | frozenset(self.root_ids)
        super().accept()

    @override
    def done(self, result: int) -> None:
        """Persist the dialog's geometry before closing, on every exit path.

        :param result: the dialog's result code, passed straight through to :meth:`QDialog.done`.
        """
        self.__settings.geometry = bytes(self.saveGeometry().data())
        self.__settings.save(persistent_settings())
        super().done(result)

    def __preselected(self) -> frozenset[UUID]:
        """The roots checked as the dialog opens.

        :returns: their ids.
        """
        if self.__only is not None:
            return frozenset((self.__only,))
        remembered = self.__settings.roots & {root.root_id for root in self.__roots}
        return remembered or frozenset(root.root_id for root in self.__roots if has_bucketed_layout(root.layouts))

    @staticmethod
    def __item_of(root: MappedRoot, checked: bool) -> QListWidgetItem:
        """A root's row.

        :param root: the root.
        :param checked: whether it is checked.
        :returns: the row.
        """
        name = root.label or root.location
        item = QListWidgetItem(name if has_bucketed_layout(root.layouts) else f"{name} ({NO_RULE_NOTE})")
        item.setToolTip(str(root.path))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def __update_start(self) -> None:
        """Offer Start while a root is checked."""
        self.start_button.setEnabled(bool(self.root_ids))
