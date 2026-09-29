"""The web search engines editor: one row per engine, a name and a URL template (#388)."""

# the table chrome here is `LocationReplacementsEditor`'s: both are multi-column rows over
# `ItemListEditor`, and the view settings a table like that needs are the same whichever domain it holds
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

from ...item_action_icons import apply_item_action_icons
from ..web_search_settings import SearchEngine
from .web_search_engines_model import ACTIVE_COLUMN, NAME_COLUMN, URL_COLUMN, WebSearchEnginesModel
from .web_search_engines_radio_delegate import WebSearchEnginesRadioDelegate


class WebSearchEnginesEditor(ItemListEditor):
    """`ItemListEditor`'s machinery over a :class:`WebSearchEnginesModel` (#388), chromed the way
    :class:`~rehuco_agent.settings.ui.location_replacements_editor.LocationReplacementsEditor` is: the
    Reset is shown, since there is a shipped list
    (:data:`~rehuco_agent.settings.web_search_settings.DEFAULT_ENGINES`) to go back to.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = WebSearchEnginesModel()
        table = ContentSizedTableView()
        super().__init__(table, model, parent)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type."""

        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        # one line per engine: a wrapped cell grows its row, and a view sized to its rows would then
        # report a height measured before the columns were laid out
        table.setWordWrap(False)
        header = table.horizontalHeader()
        table.setItemDelegateForColumn(ACTIVE_COLUMN, WebSearchEnginesRadioDelegate(table))
        # the radio leads the row on screen, but stays the last *model* column: `ItemListEditor` opens
        # model column 0 on Add and abandons a row whose column 0 is blank, and a radio cell is neither
        # editable nor ever non-blank -- an insert would open nothing, and the name typed into it later
        # would be thrown away as an abandoned row
        header.moveSection(header.visualIndex(ACTIVE_COLUMN), 0)
        header.setSectionResizeMode(ACTIVE_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(URL_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        apply_item_action_icons(self)

    @property
    def values(self) -> tuple[SearchEngine, ...]:
        """Every engine, in order, exactly as typed -- the active flag included."""
        return self.__model.entries

    @values.setter
    def values(self, values: Sequence[SearchEngine]) -> None:
        """Replace every engine, reporting one edit if the list actually changed.

        :param values: the engines to show, in order.
        """
        self.__model.set_entries(values)

    @property
    def defaults(self) -> tuple[SearchEngine, ...]:
        """What Reset restores."""
        return self.__model.defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[SearchEngine]) -> None:
        """Set what Reset restores.

        :param defaults: the engines Reset should put back.
        """
        self.__model.defaults = defaults
