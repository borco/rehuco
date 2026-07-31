"""This app's icons on a `StringListEditor`'s eight actions (#231).

`borco_pyside.widgets.StringListEditor` ships no icons: it exposes its actions and leaves the glyphs to
whoever uses it, which is what keeps a generic widget library out of rehuco's icon set. This is the
other half of that arrangement -- one place naming which SVG each action wears, so a second list editor
elsewhere in the app looks like the first without restating the mapping.

Each icon is kept recolored for the current theme by an `ActionIconThemeHandler` parented to its own
action (#104), so applying them is a single call with nothing to hold on to afterwards.
"""

from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import StringListEditor

INSERT_ICON_RESOURCE: Final = ":/icons/items_add.svg"
"""Insert a new entry below the current one -- the add glyph, since inserting is how entries appear."""

EDIT_ICON_RESOURCE: Final = ":/icons/items_edit.svg"
"""Reopen the current entry for typing."""

DELETE_ICON_RESOURCE: Final = ":/icons/items_delete.svg"
"""Drop the current entry."""

RESET_ICON_RESOURCE: Final = ":/icons/items_restore.svg"
"""Replace the list with its defaults."""

MOVE_TO_TOP_ICON_RESOURCE: Final = ":/icons/items_top.svg"
"""Move the current entry to the first row."""

MOVE_UP_ICON_RESOURCE: Final = ":/icons/items_up.svg"
"""Move the current entry one row up."""

MOVE_DOWN_ICON_RESOURCE: Final = ":/icons/items_down.svg"
"""Move the current entry one row down."""

MOVE_TO_BOTTOM_ICON_RESOURCE: Final = ":/icons/items_bottom.svg"
"""Move the current entry to the last row."""


def apply_string_list_editor_icons(editor: StringListEditor) -> None:
    """Give every one of ``editor``'s actions this app's icon for it, kept theme-recolored.

    :param editor: the list editor to dress; both its columns are covered, whether or not the ordering
        one is shown.
    """
    icons = {
        editor.item_actions.insert_action: INSERT_ICON_RESOURCE,
        editor.item_actions.edit_action: EDIT_ICON_RESOURCE,
        editor.item_actions.delete_action: DELETE_ICON_RESOURCE,
        editor.item_actions.reset_action: RESET_ICON_RESOURCE,
        editor.ordering_actions.move_to_top_action: MOVE_TO_TOP_ICON_RESOURCE,
        editor.ordering_actions.move_up_action: MOVE_UP_ICON_RESOURCE,
        editor.ordering_actions.move_down_action: MOVE_DOWN_ICON_RESOURCE,
        editor.ordering_actions.move_to_bottom_action: MOVE_TO_BOTTOM_ICON_RESOURCE,
    }
    for action, icon in icons.items():
        # parents itself to the action, which is what makes this a call with nothing to keep
        ActionIconThemeHandler(action, icon)
