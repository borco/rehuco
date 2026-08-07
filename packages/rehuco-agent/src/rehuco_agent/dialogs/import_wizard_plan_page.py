"""Step 3 of `Import Legacy Catalog…`: the plan table, one row per resource (#191, #192)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from .import_wizard_plan_page_ui import Ui_ImportWizardPlanPage


class ImportWizardPlanPage(QWidget):
    """The scan's plan, as a filterable checkbox table, wired by
    :class:`~rehuco_agent.dialogs.import_legacy_catalog_wizard.ImportLegacyCatalogWizard`, which owns
    the model shown in :attr:`ui`'s ``plan_table_view``.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ui: Final = Ui_ImportWizardPlanPage()
        self.ui.setupUi(self)
