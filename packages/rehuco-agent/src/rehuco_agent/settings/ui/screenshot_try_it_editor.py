"""The screenshot "try it" editor: sample filenames beside the slot the live patterns assign each one
([[acquisition-tooling#screenshot-schemes]], #287).
"""

from collections.abc import Callable, Sequence
from typing import Final

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget
from rehuco_core import ScreenshotNamePattern

from ...item_action_icons import apply_item_action_icons
from .screenshot_try_it_model import FILENAME_COLUMN, SLOT_COLUMN, ScreenshotTryItModel


class ScreenshotTryItEditor(ItemListEditor):
    """`ItemListEditor`'s machinery over a :class:`ScreenshotTryItModel` (#287).

    Two columns: an editable sample filename, and the read-only slot the current pattern list assigns
    it -- so editing a pattern above shows its effect on real names immediately, without leaving the
    settings page. :meth:`refresh_slots` recomputes the slot column; the page calls it whenever the
    pattern list changes.

    The samples are a settings-page value like the patterns above them: :attr:`values` holds what was
    typed, :attr:`defaults` is what Reset restores, and the page stages, applies and drops them with the
    patterns. The ordering column is hidden, since a sample's row carries nothing.

    :param parent: optional Qt parent -- the widget as Designer constructs it, with
        :attr:`patterns_provider` and :attr:`defaults` still empty until the page sets them.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = ScreenshotTryItModel()
        table = ContentSizedTableView()
        super().__init__(table, model, parent, with_ordering=False)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type -- the base knows only
        ``QAbstractItemModel``, and the samples are what this widget is for."""

        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        # the filename stretches, since it is unbounded; the slot is a fixed two-digit column (or the
        # short "not a screenshot" text) that never benefits from extra width
        header.setSectionResizeMode(FILENAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(SLOT_COLUMN, QHeaderView.ResizeMode.ResizeToContents)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        apply_item_action_icons(self)
        # nothing to restore until the page sets the defaults, so Reset waits with them
        self.defaults = ()

    @property
    def patterns_provider(self) -> Callable[[], Sequence[ScreenshotNamePattern]]:
        """Called on every read of the slot column to get the live pattern list; see
        :class:`ScreenshotTryItModel`."""
        return self.__model.patterns_provider

    @patterns_provider.setter
    def patterns_provider(self, patterns_provider: Callable[[], Sequence[ScreenshotNamePattern]]) -> None:
        """Set :attr:`patterns_provider`; does not by itself refresh the slot column -- call
        :meth:`refresh_slots` (or edit a pattern, which does) once the source it reads from is ready.

        :param patterns_provider: the callable to read the live pattern list from.
        """
        self.__model.patterns_provider = patterns_provider

    def refresh_slots(self) -> None:
        """Recompute the slot column against the current pattern list."""
        self.__model.refresh_slots()

    @property
    def values(self) -> tuple[str, ...]:
        """Every sample filename, in order, exactly as typed -- unnormalized, since normalizing is the
        owner's."""
        return self.__model.entries

    @values.setter
    def values(self, values: Sequence[str]) -> None:
        """Replace every sample filename, reporting one edit if the list actually changed.

        :param values: the sample filenames to show, in order.
        """
        self.__model.set_entries(values)

    @property
    def defaults(self) -> tuple[str, ...]:
        """What Reset restores; an empty one hides Reset rather than offering to empty the list."""
        return self.__model.defaults

    @defaults.setter
    def defaults(self, defaults: Sequence[str]) -> None:
        """Set what Reset restores, showing or hiding the action to match.

        :param defaults: the sample filenames Reset should put back.
        """
        self.__model.defaults = defaults
        self.item_actions.reset_action.setVisible(bool(self.__model.defaults))
