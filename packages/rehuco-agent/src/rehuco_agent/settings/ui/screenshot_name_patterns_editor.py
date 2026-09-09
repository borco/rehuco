"""The screenshot name patterns editor: one row per regex pattern
([[acquisition-tooling#screenshot-schemes]], #53, #287).
"""

# the table chrome here is `AuthorsListEditor`'s, for the reason its own module records: both are
# unbounded text columns over `ItemListEditor`, and the settings a list needs are the same settings
# whichever domain it holds ([[appendices.settings-pages]])
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget
from rehuco_core import ScreenshotNamePattern

from ...item_action_icons import apply_item_action_icons
from .screenshot_name_patterns_model import PATTERN_COLUMN, ScreenshotNamePatternsModel


class ScreenshotNamePatternsEditor(ItemListEditor):
    """`ItemListEditor`'s machinery over a :class:`ScreenshotNamePatternsModel` (#53, #287).

    The one-column sibling of the settings pages' `StringListEditor`, built the way
    :class:`~rehuco_agent.fields.widgets.authors_list_editor.AuthorsListEditor` is: everything about
    *how* the list is edited -- the insert/edit/delete buttons, the four move buttons, the keys, one
    model call per edit, which inserted row is still blank enough to abandon -- comes from the base.
    What is here is what a list of **screenshot name patterns** is: one column, a Reset that restores
    the shipped set, and an ordering column that stays visible because the order decides which pattern
    matches first.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = ScreenshotNamePatternsModel()
        table = ContentSizedTableView()
        super().__init__(table, model, parent)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type -- the base knows only
        ``QAbstractItemModel``, and the patterns are what this widget is for."""

        # a row is one pattern, so a click anywhere on it acts on that pattern; multi-select would
        # promise a bulk edit none of the actions here can carry out
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # the row numbers would number the patterns, and the *order* is already what the rows show
        table.verticalHeader().setVisible(False)
        # banded rows already separate one pattern from the next; a grid on top of them draws a table
        # where there is only one field per row
        table.setShowGrid(False)
        # one line per pattern: a table wraps its cells by default, so a long pattern in a narrow column
        # grows its row to two lines -- and a view sized to its rows then reports a height measured
        # before the columns were laid out, which clips the last pattern off the bottom
        table.setWordWrap(False)
        header = table.horizontalHeader()
        # stretched to the full width: a pattern is unbounded, and with it always filling the viewport
        # there is nothing to scroll sideways to, which is why the bar is off rather than merely unused
        header.setSectionResizeMode(PATTERN_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # the same glyphs the settings pages' string lists wear, from the one place that names them
        apply_item_action_icons(self)

    @property
    def values(self) -> tuple[ScreenshotNamePattern, ...]:
        """Every pattern, in order, exactly as typed -- unnormalized, since normalizing is the owner's."""
        return self.__model.entries

    @values.setter
    def values(self, values: Sequence[ScreenshotNamePattern]) -> None:
        """Replace every pattern, reporting one edit if the list actually changed.

        :param values: the patterns to show, in order.
        """
        self.__model.set_entries(values)

    @property
    def defaults(self) -> tuple[ScreenshotNamePattern, ...]:
        """What Reset restores; an empty one hides Reset rather than offering to empty the list."""
        return self.__model.defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[ScreenshotNamePattern]) -> None:
        """Set what Reset restores, showing or hiding the action to match.

        :param defaults: the patterns Reset should put back.
        """
        self.__model.defaults = defaults
        self.item_actions.reset_action.setVisible(bool(self.__model.defaults))
