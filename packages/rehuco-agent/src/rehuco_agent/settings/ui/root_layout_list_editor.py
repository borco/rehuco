"""The names of the default root layouts, as an ordered list editor (#578)."""

from typing import Final

from borco_pyside.widgets import ContentSizedListView, ItemListEditor
from PySide6.QtWidgets import QAbstractItemView, QWidget

from ...item_action_icons import apply_item_action_icons
from .root_layout_list_model import RootLayoutListModel


class RootLayoutListEditor(ItemListEditor):
    """`ItemListEditor`'s machinery over a :class:`RootLayoutListModel`: insert, duplicate, delete, reorder and Reset
    to the shipped layouts, one row per layout named.

    :param parent: optional Qt parent; what a ``.ui`` promotes the widget with.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = RootLayoutListModel()
        view = ContentSizedListView()
        super().__init__(view, model, parent)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type."""
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        apply_item_action_icons(self)

    @property
    def layout_model(self) -> RootLayoutListModel:
        """The layouts, at their concrete type."""
        return self.__model
