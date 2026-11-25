"""The dialog that asks which licenses' saved texts to replace with the store's ([[assets#licenses]], #688)."""

from collections.abc import Sequence
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidgetItem, QPushButton, QWidget

from ..scraping.license_refresh_job import LicenseDifference
from .license_refresh_dialog_ui import Ui_LicenseRefreshDialog

REPLACE_TEXT: Final = "Replace Checked"
"""What the OK button says: it replaces the checked licenses' texts."""

KEEP_TEXT: Final = "Keep All"
"""What the Cancel button says: every saved text is kept as it is."""

TOOLTIP_RECORDS: Final = 20
"""How many records a row's tooltip names before it says how many more hold the text."""


class LicenseRefreshDialog(QDialog):
    """One row per license whose text the store gives differently from some records' saved text -- the license, how many
    records hold another and the days those were read, and the day the store's was -- each unchecked: **a saved text is
    replaced only on a yes**, and Cancel, or closing the dialog, keeps every one.

    :param differences: what the refresh found.
    :param parent: optional Qt parent.
    """

    def __init__(self, differences: Sequence[LicenseDifference], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_LicenseRefreshDialog()
        self.__ui.setupUi(self)
        self.__differences: Final = tuple(differences)
        self.replace_button.setText(REPLACE_TEXT)
        self.__ui.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(KEEP_TEXT)
        for difference in self.__differences:
            self.__ui.licenses_list.addItem(self.__item_of(difference))
        self.__ui.licenses_list.itemChanged.connect(self.__update_replace)
        self.__update_replace()

    @property
    def replace_button(self) -> QPushButton:
        """The button that replaces the checked texts, for tests."""
        return self.__ui.button_box.button(QDialogButtonBox.StandardButton.Ok)

    @property
    def chosen(self) -> tuple[LicenseDifference, ...]:
        """The licenses checked, in the order listed."""
        return tuple(
            difference
            for row, difference in enumerate(self.__differences)
            if self.__ui.licenses_list.item(row).checkState() is Qt.CheckState.Checked
        )

    @staticmethod
    def describe(difference: LicenseDifference) -> str:
        """What a license's row says.

        :param difference: the license.
        :returns: its title and address, how many records hold another text and when they read it, and when the store's
            was read.
        """
        days = sorted({holder.terms.read for holder in difference.holders})
        span = days[0].isoformat() if len(days) == 1 else f"{days[0].isoformat()} to {days[-1].isoformat()}"
        count = len(difference.holders)
        noun = "record holds" if count == 1 else "records hold"
        return (
            f"{difference.terms.title} - {difference.url}\n"
            f"{count:,} {noun} another text, read {span}. The store's was read {difference.terms.read.isoformat()}."
        )

    @staticmethod
    def __item_of(difference: LicenseDifference) -> QListWidgetItem:
        """A license's row, unchecked.

        :param difference: the license.
        :returns: the row.
        """
        item = QListWidgetItem(LicenseRefreshDialog.describe(difference))
        names = [str(holder.record) for holder in difference.holders]
        more = len(names) - TOOLTIP_RECORDS
        item.setToolTip("\n".join([*names[:TOOLTIP_RECORDS], f"... and {more:,} more"] if more > 0 else names))
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Unchecked)
        return item

    def __update_replace(self) -> None:
        """Offer the replacement while a license is checked."""
        self.replace_button.setEnabled(bool(self.chosen))
