"""Step 2 of `Import Legacy Catalog…`: the dry-run scan (#191, #192)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from .import_wizard_scan_page_ui import Ui_ImportWizardScanPage


class ImportWizardScanPage(QWidget):
    """A running count and an indeterminate progress bar while :func:`~rehuco_core.plan_tc_conversion`
    walks the chosen root, wired by
    :class:`~rehuco_agent.dialogs.import_legacy_catalog_wizard.ImportLegacyCatalogWizard`.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui: Final = Ui_ImportWizardScanPage()
        self.ui.setupUi(self)
