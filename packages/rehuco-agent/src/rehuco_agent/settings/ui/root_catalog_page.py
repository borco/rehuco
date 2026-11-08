"""Root Catalog settings page: how the Roots view drives the Documents preview (#457), and the layouts a new root can
start with (#578)."""

from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ..persistent_settings import persistent_settings
from ..root_catalog_settings import DEFAULT_AUTO_PREVIEW, DEFAULT_ROOT_LAYOUTS, shared_root_catalog_settings
from .root_catalog_page_ui import Ui_RootCatalogPage


class RootCatalogPage(QWidget):
    """Configure whether the Roots view previews the record of the row it stands on, and the default root layouts.

    Both are staged in the widgets until :meth:`save_changes` writes them, like every settings page here. **Both can
    also be saved behind the page's back**: the preview choice by the Root Catalog menu, which applies it as it is
    clicked, and the layouts by the Add Roots dialog's *New layout…*. The page says so (:attr:`saved_changed`) and the
    dialog rebases it: a page with no edit shows the new saved values and stays clean; a page with an edit keeps it,
    and it stops being one if it now equals the saved values.

    :param parent: optional Qt parent.
    """

    saved_changed = Signal()
    """Emitted whenever a saved value changes -- by this page's Apply, the menu's toggle or *New layout…*."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RootCatalogPage()
        self.__ui.setupUi(self)
        self.drop_changes()
        settings = shared_root_catalog_settings()
        settings.auto_preview_changed.connect(lambda _value: self.saved_changed.emit())
        settings.default_layouts_changed.connect(lambda _value: self.saved_changed.emit())

    def is_dirty(self) -> bool:
        """Whether the staged choices differ from what is saved."""
        settings = shared_root_catalog_settings()
        return (
            self.__ui.auto_preview_check_box.isChecked() != settings.auto_preview
            or self.__ui.default_layouts_editor.layouts != settings.default_layouts
        )

    def save_changes(self) -> None:
        """Apply the staged choices, to every place that shows them, and persist them."""
        settings = shared_root_catalog_settings()
        settings.auto_preview = self.__ui.auto_preview_check_box.isChecked()
        settings.default_layouts = self.__ui.default_layouts_editor.layouts or DEFAULT_ROOT_LAYOUTS
        settings.save(persistent_settings())
        # a list applied empty is the seed again: show what was saved, so the page is clean
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding the widgets from the shared settings."""
        settings = shared_root_catalog_settings()
        self.__ui.auto_preview_check_box.setChecked(settings.auto_preview)
        self.__ui.default_layouts_editor.layouts = settings.default_layouts

    def seed_defaults(self) -> None:
        """Stage the factory values (#342)."""
        self.__ui.auto_preview_check_box.setChecked(DEFAULT_AUTO_PREVIEW)
        self.__ui.default_layouts_editor.layouts = DEFAULT_ROOT_LAYOUTS
