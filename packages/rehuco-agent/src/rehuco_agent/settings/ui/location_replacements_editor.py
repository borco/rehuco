"""The location replacement rules editor: one row per text -> replacement rule (#350)."""

# the table chrome here is `AuthorsListEditor`'s: both are multi-column rows over `ItemListEditor`, and
# the view settings a table like that needs are the same whichever domain it holds
# pylint: disable=duplicate-code

from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget

from ...item_action_icons import apply_item_action_icons
from ..location_replacements_settings import ReplacementRule
from .location_replacements_model import REGEX_COLUMN, REPLACEMENT_COLUMN, TEXT_COLUMN, LocationReplacementsModel


class LocationReplacementsEditor(ItemListEditor):
    """`ItemListEditor`'s machinery over a :class:`LocationReplacementsModel` (#350).

    Built the way :class:`~rehuco_agent.fields.widgets.authors_list_editor.AuthorsListEditor` is: the
    two text columns stretched, the regexp checkbox column sized to its contents, and -- unlike the
    authors editor -- a Reset that is shown, since there genuinely is a shipped default
    (:data:`~rehuco_agent.settings.location_replacements_settings.DEFAULT_RULES`) to go back to, the
    same call
    :class:`~rehuco_agent.settings.ui.location_template_patterns_editor.LocationTemplatePatternsEditor`
    makes for its own list.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = LocationReplacementsModel()
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
        # one line per rule: a table wraps its cells by default, so a long value in a narrow column
        # grows its row to two lines -- and a view sized to its rows then reports a height measured
        # before the columns were laid out, which clips the last rule off the bottom
        table.setWordWrap(False)
        header = table.horizontalHeader()
        # the two text columns stretched to half the remaining width each: neither is naturally wider
        # than the other, and with the regexp column fixed to its own content there is nothing left to
        # scroll sideways to, which is why the bar is off rather than merely unused
        header.setSectionResizeMode(TEXT_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(REPLACEMENT_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(REGEX_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # the same glyphs the settings pages' string lists wear, from the one place that names them
        apply_item_action_icons(self)

    @property
    def values(self) -> tuple[ReplacementRule, ...]:
        """Every rule, in order, exactly as typed -- unnormalized, since normalizing is the owner's."""
        return self.__model.entries

    @values.setter
    def values(self, values: Sequence[ReplacementRule]) -> None:
        """Replace every rule, reporting one edit if the list actually changed.

        :param values: the rules to show, in order.
        """
        self.__model.set_entries(values)

    @property
    def defaults(self) -> tuple[ReplacementRule, ...]:
        """What Reset restores."""
        return self.__model.defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[ReplacementRule]) -> None:
        """Set what Reset restores.

        :param defaults: the rules Reset should put back.
        """
        self.__model.defaults = defaults
