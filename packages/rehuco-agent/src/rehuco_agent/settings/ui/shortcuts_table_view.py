"""The Shortcuts table, promoted to a `~.settings_frame_filter.ValueControl` so the draft keymap gets the same
dirty highlighting and Apply/Reset/Defaults header every other settings value does (#344, #342).
"""

from borco_pyside.shortcuts import Keymap
from PySide6.QtCore import QAbstractItemModel, QAbstractProxyModel
from PySide6.QtWidgets import QTableView

from .shortcuts_table_model import ShortcutsTableModel


class ShortcutsTableView(QTableView):
    """A plain `QTableView` -- it scrolls itself, filling what the page leaves it -- whose "value" is the
    model's draft keymap, which `~.settings_frame_filter.SettingsFrameFilter` cannot read off a table by any
    generic rule. The same seam `~.scrapers_table_view.ScrapersTableView` uses, so the frame's Reset restores
    the saved keys and its Defaults the factory ones with no per-page hook.
    """

    def settings_value(self) -> object:
        """The draft keymap, which compares by value."""
        model = self.__source_model()
        return model.draft() if model is not None else None

    def set_settings_value(self, value: object) -> None:
        """Write a keymap `settings_value` returned earlier back into the model.

        :param value: the `Keymap`.
        """
        model = self.__source_model()
        if model is not None and isinstance(value, Keymap):
            model.set_draft(value)

    def __source_model(self) -> ShortcutsTableModel | None:
        """The shortcuts model behind this view, through its filter proxy when it has one."""
        model: QAbstractItemModel | None = self.model()
        while isinstance(model, QAbstractProxyModel):
            model = model.sourceModel()
        return model if isinstance(model, ShortcutsTableModel) else None
