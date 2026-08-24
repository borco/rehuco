"""Session settings page: whether a restart restores the previous session's documents (#65)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ..persistent_settings import persistent_settings
from ..session_restore_settings import SessionRestoreSettings
from .session_page_ui import Ui_SessionPage


class SessionPage(QWidget):
    """Configure whether the previous session's open documents come back on the next start.

    One checkbox, staged in the widget until :meth:`save_changes` writes it -- the same shape as
    every other settings page here.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_SessionPage()
        self.__ui.setupUi(self)
        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Session"

    def is_dirty(self) -> bool:
        """Whether the staged checkbox differs from what's saved."""
        saved = SessionRestoreSettings()
        saved.load(persistent_settings())
        return self.__ui.restore_on_startup_check_box.isChecked() != saved.restore_on_startup

    def save_changes(self) -> None:
        """Persist the staged choice."""
        settings = SessionRestoreSettings(restore_on_startup=self.__ui.restore_on_startup_check_box.isChecked())
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, re-seeding the checkbox from persistent storage."""
        saved = SessionRestoreSettings()
        saved.load(persistent_settings())
        self.__ui.restore_on_startup_check_box.setChecked(saved.restore_on_startup)
