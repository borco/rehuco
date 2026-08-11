"""Tray settings page: whether closing the window minimizes to tray (#205)."""

from typing import Final

from PySide6.QtWidgets import QSystemTrayIcon, QWidget

from ..persistent_settings import persistent_settings
from ..tray_settings import shared_tray_settings
from .tray_page_ui import Ui_TrayPage


class TrayPage(QWidget):
    """Configure whether tray mode is on (#205).

    One checkbox, staged until :meth:`save_changes` pushes it into the shared `TraySettings`
    instance -- firing its ``enabled_changed`` signal, which `MainWindow` follows to create or tear
    down the tray icon immediately, not just on the next launch (the same shape `DescriptionsPage`
    uses for `MarkdownRenderingSettings`).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_TrayPage()
        self.__ui.setupUi(self)
        # a desktop's tray availability does not change over the app's lifetime, so this is read once
        # rather than re-checked on every poll -- the checkbox itself is left enabled either way, since
        # a preference set with no tray today is still worth saving: it engages on the next launch
        # under a desktop that has one
        self.__ui.unavailable_label.setVisible(not QSystemTrayIcon.isSystemTrayAvailable())
        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Tray"

    def is_dirty(self) -> bool:
        """Whether the staged checkbox differs from the shared settings' current value."""
        return self.__ui.enabled_check_box.isChecked() != shared_tray_settings().enabled

    def save_changes(self) -> None:
        """Push the staged choice into the shared settings object (live-updating the tray icon) and
        persist it."""
        settings = shared_tray_settings()
        settings.enabled = self.__ui.enabled_check_box.isChecked()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, reverting the checkbox to the shared settings' current value."""
        self.__ui.enabled_check_box.setChecked(shared_tray_settings().enabled)
