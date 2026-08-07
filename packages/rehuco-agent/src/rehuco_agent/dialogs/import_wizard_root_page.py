"""Step 1 of `Import Legacy Catalog…`: the folder to scan (#192)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from .import_wizard_root_page_ui import Ui_ImportWizardRootPage


class ImportWizardRootPage(QWidget):
    """A folder picker and a recent-roots combo box, wired by
    :class:`~rehuco_agent.dialogs.import_legacy_catalog_wizard.ImportLegacyCatalogWizard`, which owns
    everything this page's controls do.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui: Final = Ui_ImportWizardRootPage()
        self.ui.setupUi(self)
