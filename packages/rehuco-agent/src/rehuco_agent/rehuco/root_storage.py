"""What a root's folder lives on, as the Roots view says it: the words, the glyphs and the combo box that picks one
(#378, [[mounts-and-storage#rehuco-scope]]).

The root card and the Add Root dialog both pick a :class:`~rehuco_core.RootStorage`, and the Roots view draws a root
by it, so the mapping lives here once.
"""

from typing import Final

from borco_pyside.theming import themed_svg_icon
from PySide6.QtWidgets import QComboBox
from rehuco_core import RootStorage

ROOT_STORAGE_ICONS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: ":/icons/file_browser_folder.svg",
    RootStorage.NETWORK: ":/icons/network.svg",
    RootStorage.REMOVABLE: ":/icons/removable.svg",
    RootStorage.COMPACT_DISK: ":/icons/compact_disk.svg",
}
"""One glyph per storage; all four are present. An unreachable root keeps its glyph and is drawn greyed out -- or,
for a local folder, struck through -- rather than getting a glyph of its own."""

ROOT_STORAGE_LABELS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: "Local folder",
    RootStorage.NETWORK: "Network share",
    RootStorage.REMOVABLE: "Removable drive (USB stick, external disk)",
    RootStorage.COMPACT_DISK: "CD or DVD",
}
"""What the storage combo lists, in the order it lists them."""

ROOT_STORAGE_OFFLINE_ROWS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: "Folder not found",
    RootStorage.NETWORK: "Share not connected",
    RootStorage.REMOVABLE: "Drive not connected",
    RootStorage.COMPACT_DISK: "Disc not inserted",
}
"""The one row an unreachable root's column shows, so an away root never reads as an empty one (#245)."""

ROOT_STORAGE_OFFLINE_TOOLTIPS: Final[dict[RootStorage, str]] = {
    RootStorage.LOCAL: "This folder was not found, so it could not be listed. Its resources are kept as they were.",
    RootStorage.NETWORK: "This network share is not connected, so it could not be listed. Its resources are kept "
    "as they were.",
    RootStorage.REMOVABLE: "This drive is not connected, so it could not be listed. Its resources are kept as "
    "they were.",
    RootStorage.COMPACT_DISK: "This disc is not inserted, so it could not be listed. Its resources are kept as "
    "they were.",
}
"""What hovering an unreachable root says."""

FOLDER_NOT_FOUND_ROW: Final = "Folder not found"
"""The one row an unlistable folder under a reachable root shows."""


def fill_root_storage_combo(combo: QComboBox) -> None:
    """Fill ``combo`` with every storage, each with its glyph and its :class:`~rehuco_core.RootStorage` as item data.

    :param combo: the combo box to fill; any items it had are dropped.
    """
    combo.clear()
    for storage, label in ROOT_STORAGE_LABELS.items():
        combo.addItem(themed_svg_icon(ROOT_STORAGE_ICONS[storage]), label, storage)


def selected_root_storage(combo: QComboBox) -> RootStorage:
    """The storage ``combo`` shows.

    :param combo: a combo filled by :func:`fill_root_storage_combo`.
    :returns: its current storage; local when nothing is current.
    """
    try:
        # item data is a QVariant, which hands a StrEnum back as the plain string it is
        return RootStorage(combo.currentData())
    except ValueError:
        return RootStorage.LOCAL


def select_root_storage(combo: QComboBox, storage: RootStorage) -> None:
    """Make ``storage`` the one ``combo`` shows, without telling anyone: the combo's signals are blocked meanwhile.

    :param combo: a combo filled by :func:`fill_root_storage_combo`.
    :param storage: the storage to show.
    """
    blocked = combo.blockSignals(True)
    try:
        combo.setCurrentIndex(max(combo.findData(storage), 0))
    finally:
        combo.blockSignals(blocked)
