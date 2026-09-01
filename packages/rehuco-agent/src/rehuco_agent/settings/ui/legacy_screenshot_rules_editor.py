"""The legacy screenshot rules editor: one row per series, its cover and its rest template
([[acquisition-tooling#screenshot-schemes]], #53).
"""

# the table chrome here is `AuthorsListEditor`'s, for the reason its own module records: both are two
# unbounded text columns over `ItemListEditor`, and the settings a two-column list needs are the same
# settings whichever domain it holds ([[appendices.settings-pages]])
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Final, override

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget
from rehuco_core import LegacyScreenshotRule

from ...item_action_icons import apply_item_action_icons
from .legacy_screenshot_rules_model import COVER_COLUMN, REST_COLUMN, LegacyScreenshotRulesModel


class LegacyScreenshotRulesEditor(ItemListEditor):
    """`ItemListEditor`'s machinery over a :class:`LegacyScreenshotRulesModel` (#53).

    The two-column sibling of the settings pages' `StringListEditor`, built the way
    :class:`~rehuco_agent.fields.widgets.authors_list_editor.AuthorsListEditor` is: everything about
    *how* the list is edited -- the insert/edit/delete buttons, the four move buttons, the keys, one
    model call per edit -- comes from the base. What is here is what a list of **screenshot rules** is:
    two columns, a Reset that restores the shipped set, and an ordering column that stays visible
    because the order decides which rule claims a directory.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = LegacyScreenshotRulesModel()
        table = ContentSizedTableView()
        super().__init__(table, model, parent)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type -- the base knows only
        ``QAbstractItemModel``, and the rules are what this widget is for."""

        # a row is one rule, so a click anywhere on it acts on that rule; multi-select would promise a
        # bulk edit none of the actions here can carry out
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # the row numbers would number the rules, and the *order* is already what the rows show
        table.verticalHeader().setVisible(False)
        # banded rows already separate one rule from the next; a grid on top of them draws a table
        # where there are only two fields per rule
        table.setShowGrid(False)
        # one line per rule: a table wraps its cells by default, so a long template in a narrow column
        # grows its row to two lines -- and a view sized to its rows then reports a height measured
        # before the columns were laid out, which clips the last rule off the bottom
        table.setWordWrap(False)
        header = table.horizontalHeader()
        # both stretched to half the width each: a cover and a template are each unbounded, so neither
        # gets to take the row -- and with the two always summing to the viewport there is nothing to
        # scroll sideways to, which is why the bar is off rather than merely unused
        header.setSectionResizeMode(COVER_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(REST_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # the same glyphs the settings pages' string lists wear, from the one place that names them
        apply_item_action_icons(self)

    @override
    def row_is_blank(self, row: int) -> bool:
        """Whether ``row`` holds nothing in **either** cell -- what makes an insert abandonable.

        Both columns rather than the base's first one: a rule half-typed into its rest column is a rule
        somebody is writing, and undoing the insert because the cover is still empty would throw away
        what they had just typed.

        :param row: the row to test.
        :returns: whether both cells are empty.
        """
        return self.__model.row_is_blank(row)

    @property
    def values(self) -> tuple[LegacyScreenshotRule, ...]:
        """Every rule, in order, exactly as typed -- unnormalized, since normalizing is the owner's."""
        return self.__model.entries

    @values.setter
    def values(self, values: Sequence[LegacyScreenshotRule]) -> None:
        """Replace every rule, reporting one edit if the list actually changed.

        :param values: the rules to show, in order.
        """
        self.__model.set_entries(values)

    @property
    def defaults(self) -> tuple[LegacyScreenshotRule, ...]:
        """What Reset restores; an empty one hides Reset rather than offering to empty the list."""
        return self.__model.defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[LegacyScreenshotRule]) -> None:
        """Set what Reset restores, showing or hiding the action to match.

        :param defaults: the rules Reset should put back.
        """
        self.__model.defaults = defaults
        self.item_actions.reset_action.setVisible(bool(self.__model.defaults))
