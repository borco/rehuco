"""Scrapers settings page: the scripts folder, and what loaded from it (#269)."""

from typing import Final

from PySide6.QtWidgets import QFileDialog, QWidget

from ...scraping.registry import shared_scraper_registry
from ..persistent_settings import persistent_settings
from ..scrapers_settings import ScrapersSettings, shared_scrapers_settings
from .scrapers_page_ui import Ui_ScrapersPage
from .scrapers_table_model import ScrapersTableModel

SCANNED_TEMPLATE: Final = "Scanned: {folder}"
"""What the table's header line says -- the folder actually scanned, so a dirty path edit in the field
above is never mistaken for what the table below shows."""


class ScrapersPage(QWidget):
    """Configure the folder `rehuco_agent.scraping.registry.ScraperRegistry` loads user scripts from.

    Edits are staged in the folder field until :meth:`save_changes` pushes them into the shared
    `rehuco_agent.settings.scrapers_settings.ScrapersSettings`, persists them, and reloads the shared
    registry -- so Save is what makes a new folder take effect, the same as every other settings page.

    **Reload always scans the saved folder, never the one currently typed**: the table's header names
    that folder, so a path being edited is never confused with what the table already shows.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ScrapersPage()
        self.__ui.setupUi(self)
        self.__model: Final = ScrapersTableModel(self)
        self.__ui.scrapers_table.setModel(self.__model)
        self.__ui.browse_button.clicked.connect(self.__on_browse_clicked)
        self.__ui.reload_button.clicked.connect(self.__on_reload_clicked)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether the staged folder differs from what the shared settings currently hold."""
        return self.__ui.folder_edit.text() != shared_scrapers_settings().scripts_folder

    def save_changes(self) -> None:
        """Persist the staged folder and reload the shared registry from it."""
        settings = shared_scrapers_settings()
        settings.scripts_folder = self.__ui.folder_edit.text()
        settings.save(persistent_settings())
        shared_scraper_registry().reload()
        self.__refresh_table()

    def drop_changes(self) -> None:
        """Discard the staged edit, re-seeding the field from the shared settings."""
        self.__ui.folder_edit.setText(shared_scrapers_settings().scripts_folder)
        self.__refresh_table()

    def seed_defaults(self) -> None:
        """Stage the factory value: what an unloaded `ScrapersSettings` holds -- an empty path, meaning
        the default location (#342). The table is left alone: it always shows the *saved* folder's
        scan, never the one being typed."""
        self.__ui.folder_edit.setText(ScrapersSettings().scripts_folder)

    def __refresh_table(self) -> None:
        """Show the registry's current rows, and name the folder they came from."""
        registry = shared_scraper_registry()
        self.__model.set_modules(registry.modules)
        folder = shared_scrapers_settings().effective_scripts_folder
        self.__ui.scanned_label.setText(SCANNED_TEMPLATE.format(folder=folder))

    def __on_browse_clicked(self) -> None:
        """Pick the scripts folder with a file dialog, leaving a cancelled pick untouched."""
        folder = QFileDialog.getExistingDirectory(self, "Locate scraper scripts folder", self.__ui.folder_edit.text())
        if folder:
            self.__ui.folder_edit.setText(folder)

    def __on_reload_clicked(self) -> None:
        """Re-scan the saved folder and refresh the table."""
        shared_scraper_registry().reload()
        self.__refresh_table()
