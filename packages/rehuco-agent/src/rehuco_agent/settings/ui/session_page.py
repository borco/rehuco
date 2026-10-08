"""Session settings page: whether a restart restores the previous session's documents and root catalog (#65, #408)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ..persistent_settings import persistent_settings
from ..session_restore_settings import SessionRestoreSettings
from .session_page_ui import Ui_SessionPage


class SessionPage(QWidget):
    """Configure whether the previous session's open documents and root catalog come back on the next start.

    Three checkboxes (the documents on local storage, those on remote or removable storage, the root catalog), staged
    in the widget until :meth:`save_changes` writes them -- the same shape as
    every other settings page here.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_SessionPage()
        self.__ui.setupUi(self)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether a staged checkbox differs from what's saved."""
        saved = SessionRestoreSettings()
        saved.load(persistent_settings())
        return (
            self.__ui.restore_local_documents_check_box.isChecked() != saved.restore_local_documents
            or self.__ui.restore_remote_documents_check_box.isChecked() != saved.restore_remote_documents
            or self.__ui.restore_root_catalog_check_box.isChecked() != saved.restore_root_catalog
        )

    def save_changes(self) -> None:
        """Persist the staged choices."""
        settings = SessionRestoreSettings(
            restore_local_documents=self.__ui.restore_local_documents_check_box.isChecked(),
            restore_remote_documents=self.__ui.restore_remote_documents_check_box.isChecked(),
            restore_root_catalog=self.__ui.restore_root_catalog_check_box.isChecked(),
        )
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, re-seeding the checkboxes from persistent storage."""
        saved = SessionRestoreSettings()
        saved.load(persistent_settings())
        self.__stage(saved)

    def seed_defaults(self) -> None:
        """Stage the factory values: what an unloaded `SessionRestoreSettings` holds (#342)."""
        self.__stage(SessionRestoreSettings())

    def __stage(self, settings: SessionRestoreSettings) -> None:
        """Show ``settings`` in the checkboxes."""
        self.__ui.restore_local_documents_check_box.setChecked(settings.restore_local_documents)
        self.__ui.restore_remote_documents_check_box.setChecked(settings.restore_remote_documents)
        self.__ui.restore_root_catalog_check_box.setChecked(settings.restore_root_catalog)
