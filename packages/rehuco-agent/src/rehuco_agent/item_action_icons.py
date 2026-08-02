"""This app's icons on a list editor's actions (#231, #97).

`borco_pyside.widgets.ItemListEditor` ships no icons: it exposes its actions and leaves the glyphs to
whoever uses it, which is what keeps a generic widget library out of rehuco's icon set. This is the
other half of that arrangement -- one place naming which SVG each action wears, so the settings pages'
string lists and the ``authors`` record rows look like each other without either restating the mapping.

Dispatch is by the action's own type, not by a fixed set of named columns: every editor's item column
carries all four actions including Reset (some editors, e.g. the ``authors`` rows, simply hide its
button rather than never building it), and every action gets dressed regardless of whether its button
is currently shown.

Each icon is kept recolored for the current theme by an `ActionIconThemeHandler` parented to its own
action (#104), so applying them is a single call with nothing to hold on to afterwards.
"""

from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import (
    DeleteItemAction,
    EditItemAction,
    InsertItemAction,
    ItemListEditor,
    MoveDownItemAction,
    MoveToBottomItemAction,
    MoveToTopItemAction,
    MoveUpItemAction,
    ResetItemAction,
)
from PySide6.QtWidgets import QToolButton

ICONS_BY_ACTION_TYPE: Final = {
    InsertItemAction: ":/icons/items_add.svg",
    EditItemAction: ":/icons/items_edit.svg",
    DeleteItemAction: ":/icons/items_delete.svg",
    ResetItemAction: ":/icons/items_restore.svg",
    MoveToTopItemAction: ":/icons/items_top.svg",
    MoveUpItemAction: ":/icons/items_up.svg",
    MoveDownItemAction: ":/icons/items_down.svg",
    MoveToBottomItemAction: ":/icons/items_bottom.svg",
}
"""Which SVG each item-action type wears, keyed by the action's own class."""


def apply_item_action_icons(editor: ItemListEditor) -> None:
    """Give every action ``editor``'s two columns hold a button for this app's icon, kept theme-recolored.

    :param editor: the list editor to dress -- both columns, whichever actions each one carries.
    """
    for column in (editor.item_actions, editor.ordering_actions):
        for button in column.findChildren(QToolButton):
            action = button.defaultAction()
            icon = ICONS_BY_ACTION_TYPE.get(type(action))
            if icon is not None:
                # parents itself to the action, which is what makes this a call with nothing to keep
                ActionIconThemeHandler(action, icon)
