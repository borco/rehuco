"""Root Catalog settings page: how the Roots view drives the Documents preview (#457)."""

from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ..persistent_settings import persistent_settings
from ..root_catalog_settings import DEFAULT_AUTO_PREVIEW, shared_root_catalog_settings
from .root_catalog_page_ui import Ui_RootCatalogPage


class RootCatalogPage(QWidget):
    """Configure whether the Roots view previews the record of the row it stands on.

    One checkbox, staged in the widget until :meth:`save_changes` writes it, like every settings page here. **The
    choice also lives in the Root Catalog menu**, which applies it as it is clicked -- so the saved value can change
    behind the page's back. The page says so (:attr:`saved_changed`) and the dialog rebases it: a page with no edit
    shows the new saved value and stays clean; a page with an edit keeps it, and it stops being one if it now equals
    the saved value.

    :param parent: optional Qt parent.
    """

    saved_changed = Signal()
    """Emitted whenever the saved value changes -- by this page's Apply or by the menu's toggle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RootCatalogPage()
        self.__ui.setupUi(self)
        self.drop_changes()
        shared_root_catalog_settings().auto_preview_changed.connect(lambda _value: self.saved_changed.emit())

    def is_dirty(self) -> bool:
        """Whether the staged checkbox differs from what is saved."""
        return self.__ui.auto_preview_check_box.isChecked() != shared_root_catalog_settings().auto_preview

    def save_changes(self) -> None:
        """Apply the staged choice, to every place that shows it, and persist it."""
        settings = shared_root_catalog_settings()
        settings.auto_preview = self.__ui.auto_preview_check_box.isChecked()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, re-seeding the checkbox from the shared setting."""
        self.__stage(shared_root_catalog_settings().auto_preview)

    def seed_defaults(self) -> None:
        """Stage the factory value (#342)."""
        self.__stage(DEFAULT_AUTO_PREVIEW)

    def __stage(self, checked: bool) -> None:
        """Show ``checked`` in the checkbox.

        :param checked: whether the box is ticked.
        """
        self.__ui.auto_preview_check_box.setChecked(checked)
