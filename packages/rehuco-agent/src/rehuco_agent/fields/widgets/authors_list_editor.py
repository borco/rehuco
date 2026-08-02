"""The ``authors`` record editor: one row per author, name and author-page URL
([[plugins#field-toolkit]], [[field-schema#authors]]).
"""

from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget
from rehuco_core import AuthorEntry

from ...item_action_icons import apply_item_action_icons
from .authors_table_model import NAME_COLUMN, URL_COLUMN, AuthorsTableModel


class AuthorsListEditor(ItemListEditor):
    """The record-list half of the ``authors`` editor: `ItemListEditor`'s machinery over an
    :class:`AuthorsTableModel` ([[field-schema#authors]]).

    Everything about *how* the list is edited -- the insert/edit/delete buttons, the four move buttons,
    the keys, one model call per edit, the abandoned-insert rule -- comes from the base, which is the
    whole reason the record editor and the settings pages' `StringListEditor` behave the same way
    without either knowing about the other. What is here is what a list of **authors** is: two columns,
    and no Reset -- hidden outright, since there is no such thing as a default set of authors to
    restore, not merely none *right now*.

    The name column is the one an insert opens and the one the base's blank-row rule reads, so an
    insert abandoned without a name is undone exactly as it is for a plain string list.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = AuthorsTableModel()
        table = ContentSizedTableView()
        super().__init__(table, model, parent)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type -- the base knows only
        ``QAbstractItemModel``, and the entries are what this widget is for."""

        # a row is one author, so a click anywhere on it acts on that author; multi-select would
        # promise a bulk edit none of the actions here can carry out
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # the row numbers say nothing -- credit order is read off the rows themselves
        table.verticalHeader().setVisible(False)
        # banded rows already separate one entry from the next; a grid on top of them draws a table
        # where there are only two fields per author
        table.setShowGrid(False)
        # one line per author: a table wraps its cells by default, so a long URL in a narrow column
        # grows its row to two lines -- and a view sized to its rows then reports a height measured
        # before the columns were laid out, which clips the last entry off the bottom
        table.setWordWrap(False)
        header = table.horizontalHeader()
        # both stretched to half the width each: a name and a link are each unbounded, so neither gets
        # to take the row -- and with the two always summing to the viewport there is nothing to scroll
        # sideways to, which is why the bar is off rather than merely unused
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(URL_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # a default author list would be someone else's authors -- there is no reset concept here at
        # all, not just none configured, so the button is hidden rather than left disabled
        self.item_actions.reset_action.setVisible(False)
        # the same glyphs the settings pages' string lists wear, from the one place that names them
        apply_item_action_icons(self)

    @property
    def entries(self) -> tuple[AuthorEntry, ...]:
        """Every author, in row order, in canonical minimal form ([[field-schema#authors]])."""
        return self.__model.entries

    def set_entries(self, entries: Sequence[AuthorEntry]) -> None:
        """Show ``entries``, reporting one edit if that changed anything.

        :param entries: the authors list to show, in order.
        """
        self.__model.set_entries(entries)
