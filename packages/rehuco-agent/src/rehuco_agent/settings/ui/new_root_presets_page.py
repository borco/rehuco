"""Roots › New Root Presets settings page: the layouts a root made from a folder can start with (#578, #637)."""

from typing import Final

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from ..persistent_settings import persistent_settings
from ..root_catalog_settings import DEFAULT_ROOT_LAYOUTS, shared_root_catalog_settings
from .new_root_presets_page_ui import Ui_NewRootPresetsPage


class NewRootPresetsPage(QWidget):
    """Edit the default root layouts: the presets the Add Roots dialog offers a root made from a folder.

    Staged in the editor until :meth:`save_changes`. **They can also grow behind the page's back**, from the Add Roots
    dialog's *New layout…*, which saves at once: the page says so (:attr:`saved_changed`) and the dialog rebases it, so
    a page with no edit shows the new presets and stays clean, and one with an edit keeps it.

    :param parent: optional Qt parent.
    """

    saved_changed = Signal()
    """Emitted whenever the saved presets change -- by this page's Apply or *New layout…*."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_NewRootPresetsPage()
        self.__ui.setupUi(self)
        self.drop_changes()
        shared_root_catalog_settings().default_layouts_changed.connect(lambda _value: self.saved_changed.emit())

    def is_dirty(self) -> bool:
        """Whether the staged presets differ from what is saved."""
        return self.__ui.default_layouts_editor.layouts != shared_root_catalog_settings().default_layouts

    def save_changes(self) -> None:
        """Apply the staged presets, to every place that shows them, and persist them."""
        settings = shared_root_catalog_settings()
        settings.default_layouts = self.__ui.default_layouts_editor.layouts or DEFAULT_ROOT_LAYOUTS
        settings.save(persistent_settings())
        # a list applied empty is the seed again: show what was saved, so the page is clean
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding the editor from the shared settings."""
        self.__ui.default_layouts_editor.layouts = shared_root_catalog_settings().default_layouts

    def seed_defaults(self) -> None:
        """Stage the factory presets (#342)."""
        self.__ui.default_layouts_editor.layouts = DEFAULT_ROOT_LAYOUTS
