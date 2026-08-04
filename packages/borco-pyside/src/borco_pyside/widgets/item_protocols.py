"""The three roles an item-list editor is split into: what the list holds, where an entry sits, and
which one is current.
"""

from typing import Protocol, runtime_checkable

from PySide6.QtCore import SignalInstance


@runtime_checkable
class ItemEditor(Protocol):
    """Adding, deleting, resetting -- what the list holds.

    A pure data role: every method takes the row it acts on and hands back the row the result lives at,
    rather than tracking a "current" row of its own. That is what lets a plain data model -- one with no
    view, no selection -- satisfy this protocol on its own: :class:`ItemViewer` is where "current" lives,
    and an :class:`~borco_pyside.widgets.item_action_button_column.ItemEditActionsColumn` is handed both,
    reading the row to act on from the viewer and handing the result back to it.
    """

    def insert(self, at: int) -> int:  # pyright: ignore[reportReturnType]
        """Insert a blank entry, and say where it landed.

        :param at: the row to insert after, or a negative row to append.
        :returns: the new entry's row.
        """

    def delete(self, at: int) -> None:
        """Drop one entry.

        :param at: the row to drop; a negative row is a no-op.
        """

    def reset(self) -> None:
        """Replace the whole list with whatever this editor's defaults are -- a no-op for one with none."""


@runtime_checkable
class ItemOrderingEditor(Protocol):
    """Reordering -- where an entry sits.

    Same shape as :class:`ItemEditor`: every move takes the row it acts on and returns the row the
    entry ended up at, rather than remembering one itself.
    """

    def move_to_top(self, at: int) -> int:  # pyright: ignore[reportReturnType]
        """Move one entry to the first row.

        :param at: the row to move.
        :returns: the row it ended up at.
        """

    def move_up(self, at: int) -> int:  # pyright: ignore[reportReturnType]
        """Move one entry up a row.

        :param at: the row to move.
        :returns: the row it ended up at.
        """

    def move_down(self, at: int) -> int:  # pyright: ignore[reportReturnType]
        """Move one entry down a row.

        :param at: the row to move.
        :returns: the row it ended up at.
        """

    def move_to_bottom(self, at: int) -> int:  # pyright: ignore[reportReturnType]
        """Move one entry to the last row.

        :param at: the row to move.
        :returns: the row it ended up at.
        """

    @property
    def count(self) -> int:  # pyright: ignore[reportReturnType]
        """How many entries there are -- what an ordering column reads to know whether a row is at
        either end."""

    count_changed: SignalInstance
    """Fires whenever :attr:`count` changes -- an entry added, dropped, or the whole list replaced."""


@runtime_checkable
class ItemViewer(Protocol):
    """Which entry is current, and opening it for typing.

    The one role only something holding the actual view can play: no data model can open an in-place
    editor or own a selection, so this is implemented by the widget
    (:class:`~borco_pyside.widgets.item_list_editor.ItemListEditor`), never by a model.
    """

    @property
    def current_index(self) -> int:  # pyright: ignore[reportReturnType]
        """The row being acted on, or a negative row when there is none."""

    def set_current_index(self, row: int) -> None:
        """Make ``row`` the current one.

        :param row: the row to select, or a negative row to select none.
        """

    current_index_changed: SignalInstance
    """Fires whenever :attr:`current_index` changes."""

    def edit_current(self) -> None:
        """Open the current entry for in-place editing; a no-op with no current entry."""
