"""The two action columns a list editor is built from -- what a row *is*, and where it sits -- each
wired straight to the two protocols (:class:`~borco_pyside.widgets.item_protocols.ItemEditor` /
:class:`~borco_pyside.widgets.item_protocols.ItemOrderingEditor`) and the one shared
:class:`~borco_pyside.widgets.item_protocols.ItemViewer` that says which row is current.
"""

from collections.abc import Callable
from typing import Final

from PySide6.QtWidgets import QWidget

from .action_button_column import ActionButtonColumn
from .item_actions import (
    DeleteItemAction,
    DuplicateItemAction,
    EditItemAction,
    InsertItemAction,
    MoveDownItemAction,
    MoveToBottomItemAction,
    MoveToTopItemAction,
    MoveUpItemAction,
    ResetItemAction,
)
from .item_protocols import ItemEditor, ItemOrderingEditor, ItemViewer


class ItemEditActionsColumn(ActionButtonColumn):
    """Insert / Duplicate / Edit / Delete / Reset, wired straight to an
    :class:`~borco_pyside.widgets.item_protocols.ItemEditor` and an
    :class:`~borco_pyside.widgets.item_protocols.ItemViewer`.

    Insert and Duplicate both touch editor and viewer: each asks the editor for a new row after the
    viewer's current one and makes the result current. Insert then opens it for typing -- "insert
    always opens the new entry" and "click Edit" both end up calling
    :meth:`~borco_pyside.widgets.item_protocols.ItemViewer.edit_current`, so neither path can drift from
    the other -- while Duplicate does not: a copy is already typed, and opening it would only invite the
    Escape that undoes a blank insert. Duplicate, Edit and Delete answer to the viewer's current row;
    Reset is list-wide, so it neither reads nor needs one -- and is, unlike the others, not something
    every editor wants: hide its button with ``reset_action.setVisible(False)`` when there is no reset
    concept at all (`ActionButtonColumn.add_action_button` is what makes that actually hide it), and
    likewise ``duplicate_action`` where an entry is not the editor's to copy.

    :param editor: performs the insert/duplicate/delete/reset.
    :param viewer: says which row is current, and opens it for typing.
    :param parent: optional Qt parent.
    """

    def __init__(self, editor: ItemEditor, viewer: ItemViewer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__editor: Final = editor
        self.__viewer: Final = viewer

        self.__insert_action: Final = InsertItemAction(self)
        self.__duplicate_action: Final = DuplicateItemAction(self)
        self.__edit_action: Final = EditItemAction(self)
        self.__delete_action: Final = DeleteItemAction(self)
        self.__reset_action: Final = ResetItemAction(self)
        for action in (
            self.__insert_action,
            self.__duplicate_action,
            self.__edit_action,
            self.__delete_action,
            self.__reset_action,
        ):
            self.add_action_button(action)

        self.__insert_action.triggered.connect(self.__on_insert)
        self.__duplicate_action.triggered.connect(self.__on_duplicate)
        self.__edit_action.triggered.connect(viewer.edit_current)
        self.__delete_action.triggered.connect(self.__on_delete)
        self.__reset_action.triggered.connect(editor.reset)
        viewer.current_index_changed.connect(self.__update_enabled)
        self.__update_enabled()

    @property
    def insert_action(self) -> InsertItemAction:
        """Add a new entry below the current one -- and the only way into an emptied list."""
        return self.__insert_action

    @property
    def duplicate_action(self) -> DuplicateItemAction:
        """Insert a copy of the current entry below it."""
        return self.__duplicate_action

    @property
    def edit_action(self) -> EditItemAction:
        """Reopen the current entry for typing."""
        return self.__edit_action

    @property
    def delete_action(self) -> DeleteItemAction:
        """Drop the current entry."""
        return self.__delete_action

    @property
    def reset_action(self) -> ResetItemAction:
        """Replace the whole list with its defaults -- if it has any; see the class docstring."""
        return self.__reset_action

    def __on_insert(self) -> None:
        """Insert after the current row, make the new one current, and open it for typing."""
        new_index = self.__editor.insert(self.__viewer.current_index)
        self.__viewer.set_current_index(new_index)
        self.__viewer.edit_current()

    def __on_duplicate(self) -> None:
        """Copy the current row below itself and make the copy current -- without opening it."""
        new_index = self.__editor.duplicate(self.__viewer.current_index)
        self.__viewer.set_current_index(new_index)

    def __on_delete(self) -> None:
        """Drop the current entry."""
        self.__editor.delete(self.__viewer.current_index)

    def __update_enabled(self) -> None:
        """Duplicate, Edit and Delete answer to whether there is a current row; Insert and Reset are
        list-wide."""
        has_current = self.__viewer.current_index >= 0
        self.__duplicate_action.setEnabled(has_current)
        self.__edit_action.setEnabled(has_current)
        self.__delete_action.setEnabled(has_current)


class ItemOrderingActionsColumn(ActionButtonColumn):
    """Top / Up / Down / Bottom, wired straight to an
    :class:`~borco_pyside.widgets.item_protocols.ItemOrderingEditor` and an
    :class:`~borco_pyside.widgets.item_protocols.ItemViewer`.

    Every move reads the row to act on from the viewer's current index and writes the result straight
    back to it, so the moved entry stays current and every other row's index is left to Qt's own
    ``moveRow`` to keep sane.

    :param editor: performs the actual moves.
    :param viewer: says which row is current, and receives it back after a move.
    :param parent: optional Qt parent.
    """

    def __init__(self, editor: ItemOrderingEditor, viewer: ItemViewer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__editor: Final = editor
        self.__viewer: Final = viewer

        self.__move_to_top_action: Final = MoveToTopItemAction(self)
        self.__move_up_action: Final = MoveUpItemAction(self)
        self.__move_down_action: Final = MoveDownItemAction(self)
        self.__move_to_bottom_action: Final = MoveToBottomItemAction(self)
        for action in self.__actions():
            self.add_action_button(action)

        self.__move_to_top_action.triggered.connect(lambda: self.__move(editor.move_to_top))
        self.__move_up_action.triggered.connect(lambda: self.__move(editor.move_up))
        self.__move_down_action.triggered.connect(lambda: self.__move(editor.move_down))
        self.__move_to_bottom_action.triggered.connect(lambda: self.__move(editor.move_to_bottom))
        viewer.current_index_changed.connect(self.__update_enabled)
        editor.count_changed.connect(self.__update_enabled)
        self.__update_enabled()

    @property
    def move_to_top_action(self) -> MoveToTopItemAction:
        """Move the current entry to the first row."""
        return self.__move_to_top_action

    @property
    def move_up_action(self) -> MoveUpItemAction:
        """Move the current entry one row up."""
        return self.__move_up_action

    @property
    def move_down_action(self) -> MoveDownItemAction:
        """Move the current entry one row down."""
        return self.__move_down_action

    @property
    def move_to_bottom_action(self) -> MoveToBottomItemAction:
        """Move the current entry to the last row."""
        return self.__move_to_bottom_action

    def __actions(
        self,
    ) -> tuple[MoveToTopItemAction, MoveUpItemAction, MoveDownItemAction, MoveToBottomItemAction]:
        """This column's four actions, in the order their buttons appear.

        :returns: top, up, down, bottom.
        """
        return (
            self.__move_to_top_action,
            self.__move_up_action,
            self.__move_down_action,
            self.__move_to_bottom_action,
        )

    def __move(self, move: Callable[[int], int]) -> None:
        """Run one of the editor's move methods on the current row and make its result current.

        :param move: the editor method to call (``move_to_top``/``move_up``/``move_down``/``move_to_bottom``).
        """
        self.__viewer.set_current_index(move(self.__viewer.current_index))

    def __update_enabled(self) -> None:
        """Every move needs a current row; top/up also need it not already first, down/bottom not last."""
        row = self.__viewer.current_index
        count = self.__editor.count
        has_current = row >= 0
        self.__move_to_top_action.setEnabled(has_current and row > 0)
        self.__move_up_action.setEnabled(has_current and row > 0)
        self.__move_down_action.setEnabled(has_current and row < count - 1)
        self.__move_to_bottom_action.setEnabled(has_current and row < count - 1)
