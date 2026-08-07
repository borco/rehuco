"""Step 4 of `Import Legacy Catalog…`: enqueuing and watching the conversion jobs (#192)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from .import_wizard_import_page_ui import Ui_ImportWizardImportPage


class ImportWizardImportPage(QWidget):
    """Progress against the selected count while the queue works through the enqueued
    :class:`~rehuco_core.TcImportJob` s, wired by
    :class:`~rehuco_agent.dialogs.import_legacy_catalog_wizard.ImportLegacyCatalogWizard`.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui: Final = Ui_ImportWizardImportPage()
        self.ui.setupUi(self)
