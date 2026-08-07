"""Step 5 of `Import Legacy Catalog…`: the result table and Retry Failed (#192)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from .import_wizard_result_page_ui import Ui_ImportWizardResultPage


class ImportWizardResultPage(QWidget):
    """The same plan table, now carrying an outcome per row, plus Retry Failed and copy/save-to-text,
    wired by :class:`~rehuco_agent.dialogs.import_legacy_catalog_wizard.ImportLegacyCatalogWizard`.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui: Final = Ui_ImportWizardResultPage()
        self.ui.setupUi(self)
