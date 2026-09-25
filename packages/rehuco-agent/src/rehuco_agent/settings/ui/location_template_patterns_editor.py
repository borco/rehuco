"""The location name patterns editor: one row per format-string pattern (#322)."""

# the table chrome here is `ScreenshotNamePatternsEditor`'s, for the reason its own module records: both
# are unbounded text columns over `ItemListEditor`, and the settings a list needs are the same settings
# whichever domain it holds ([[appendices.settings-pages]])
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

from ...item_action_icons import apply_item_action_icons
from .location_template_patterns_model import PATTERN_COLUMN, LocationTemplatePatternsModel


class LocationTemplatePatternsEditor(ItemListEditor):
    """`ItemListEditor`'s machinery over a :class:`LocationTemplatePatternsModel` (#322).

    Built the way :class:`~rehuco_agent.settings.ui.screenshot_name_patterns_editor.ScreenshotNamePatternsEditor`
    is: everything about *how* the list is edited -- the insert/edit/delete buttons, the four move
    buttons, the keys, one model call per edit, which inserted row is still blank enough to abandon --
    comes from the base. What is here is what a list of **location name patterns** is: one column, a
    Reset that restores the shipped set, and an ordering column that stays visible because the order
    decides which suggestion is offered first.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = LocationTemplatePatternsModel()
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
    def values(self) -> tuple[str, ...]:
        """Every pattern, in order, exactly as typed -- unnormalized, since normalizing is the owner's."""
        return self.__model.entries

    @values.setter
    def values(self, values: Sequence[str]) -> None:
        """Replace every pattern, reporting one edit if the list actually changed.

        :param values: the patterns to show, in order.
        """
        self.__model.set_entries(values)

    @property
    def defaults(self) -> tuple[str, ...]:
        """What Reset restores; an empty one hides Reset rather than offering to empty the list."""
        return self.__model.defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[str]) -> None:
        """Set what Reset restores, showing or hiding the action to match.

        :param defaults: the patterns Reset should put back.
        """
        self.__model.defaults = defaults
        self.item_actions.reset_action.setVisible(bool(self.__model.defaults))

    @property
    def known_placeholders(self) -> frozenset[str]:
        """The placeholders a row may name (#349); ``KNOWN_PLACEHOLDERS`` unless the owning page's type
        accepts more."""
        return self.__model.known_placeholders

    @known_placeholders.setter
    def known_placeholders(self, known_placeholders: frozenset[str]) -> None:
        """Set the placeholders a row may name -- the owning page's job, once, before rows are loaded.

        :param known_placeholders: the placeholders this type's patterns accept.
        """
        self.__model.known_placeholders = known_placeholders
