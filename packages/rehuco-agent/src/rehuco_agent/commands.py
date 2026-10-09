"""Every user-facing shortcut this app has, declared once as a command (#343).

The catalog is the single source of the keys: no `.ui` file or widget spells one out. A widget binds its
action to a command id through :func:`shared_command_registry`, and the user's overrides
(:mod:`~rehuco_agent.settings.shortcuts_settings`) reach every live action from there. A command with no
default keys is still listed, so the user can give it some.

**Scopes** follow from what the action belongs to:

- the main window's own actions are `CommandScope.WINDOW`;
- a per-document action is `CommandScope.DOCUMENT_FOCUSED` -- one action per open document, and only the
  focused document's fires, which is what keeps two documents from cancelling out on one key (#41);
- a per-document action the user may want from anywhere also allows `CommandScope.DOCUMENT_APP_WIDE`, under
  which the window's `DocumentCommandRouter` carries the key and passes it on to the focused document (#345);
- a key that must work from a torn-out dock too, with one action carrying it, is `CommandScope.APP_WIDE`;
- a key that belongs to one widget, leaving an in-place editor's keys alone, is `CommandScope.WIDGET`.

A **focus group** says the command only ever reaches one kind of widget, so two such commands in
different groups may share a key -- the Files view's and Content Images' F5 are never both armed.
"""

from functools import lru_cache
from typing import Final

from borco_pyside.logging import LOG_COMMANDS
from borco_pyside.shortcuts import Command, CommandRegistry, CommandScope
from borco_pyside.widgets import CARD_LIST_COMMANDS, LIST_EDITOR_COMMANDS
from borco_pyside.widgets.item_actions import LIST_EDITOR_FOCUS_GROUP
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

from .settings.shortcuts_settings import shared_shortcuts_settings

WINDOW: Final = (CommandScope.WINDOW,)
DOCUMENT: Final = (CommandScope.DOCUMENT_FOCUSED, CommandScope.DOCUMENT_APP_WIDE)
WIDGET: Final = (CommandScope.WIDGET,)

# region the main window

OPEN_REHU: Final = Command("app.open_rehu", "Open rehu", "Open a .rehu file", ("Ctrl+O",), WINDOW)
OPEN_FOLDER: Final = Command("app.open_folder", "Open folder", "Open the resource in a folder", (), WINDOW)
OPEN_COMPANION: Final = Command(
    "app.open_companion", "Open companion", "Open the resource a companion file belongs to", (), WINDOW
)
NEW_REHUCO: Final = Command(
    "app.new_rehuco", "New root catalog", "Create a root catalog (.rehuco) and open it", (), WINDOW
)
OPEN_REHUCO: Final = Command("app.open_rehuco", "Open root catalog", "Open a root catalog (.rehuco)", (), WINDOW)
CLOSE_DOCUMENT: Final = Command("app.close_document", "Close", "Close the focused document", ("Ctrl+W",), WINDOW)
CLOSE_MISSING: Final = Command(
    "app.close_missing", "Close missing files", "Close every document whose file is gone", (), WINDOW
)
CLOSE_ALL: Final = Command("app.close_all", "Close all", "Close every open document", ("Ctrl+Shift+W",), WINDOW)
SAVE_ALL: Final = Command("app.save_all", "Save all", "Save every modified document", ("Ctrl+Shift+S",), WINDOW)
IMPORT_LEGACY_CATALOG: Final = Command(
    "app.import_legacy_catalog",
    "Import legacy catalog",
    "Bulk-convert a folder tree of legacy .tc resources to .rehu",
    (),
    WINDOW,
)
QUIT: Final = Command("app.quit", "Quit", "Quit the app", ("Ctrl+Q",), WINDOW)
CYCLE_THEME: Final = Command("view.cycle_theme", "Cycle theme", "Cycle theme: follow system, light, dark", (), WINDOW)
IMAGE_PREVIEWS: Final = Command(
    "view.image_previews",
    "Image previews",
    "Show or hide the images of every open document",
    ("Ctrl+Shift+`",),
    # app-wide first: a torn-out dock is a top-level window of its own, and a window-scoped key would go
    # deaf the moment one had focus -- safe, since exactly one action carries this key
    (CommandScope.APP_WIDE, CommandScope.WINDOW),
)

# endregion

# region a document

SAVE_DOCUMENT: Final = Command(
    "document.save", "Save", "Save the focused document", (QKeySequence.StandardKey.Save,), DOCUMENT
)
MAXIMIZE_DOCK: Final = Command(
    "document.maximize",
    "Maximize current dock",
    "Maximize the focused document's current dock over its other docks, or restore them",
    ("Ctrl+Shift+M",),
    DOCUMENT,
)
REFRESH_FILES: Final = Command(
    "document.files.refresh", "Refresh files", "Read the browsed folder again", (Qt.Key.Key_F5,), DOCUMENT, "files_view"
)
REFRESH_CONTENT_IMAGES: Final = Command(
    "document.content_images.refresh",
    "Refresh content images",
    "Read the resource's content images again",
    (Qt.Key.Key_F5,),
    DOCUMENT,
    "content_images",
)
COPY_IMAGE: Final = Command(
    "images.copy",
    "Copy image",
    "Copy the selected or shown image, to paste it into another app",
    (QKeySequence.StandardKey.Copy,),
    # focused-only on purpose: app-wide, it would take Ctrl+C from every text field
    (CommandScope.DOCUMENT_FOCUSED,),
    # armed on the Content Images grid and on a lightbox, never both, and on no text field
    "images",
)
COMPLETE_IMAGES: Final = Command(
    "document.description.complete_images",
    "Complete image names",
    "Offer this resource's image filenames in the description editor",
    ("Ctrl+Space",),
    WIDGET,
    "markdown_edit",
)
CONVERT_SCREENSHOT: Final = Command(
    "document.screenshots.convert",
    "Convert screenshot",
    "Take the current image into the numbered set",
    (Qt.Key.Key_C,),
    WIDGET,
    # armed on the screenshot list, beside the list-editor actions it shares that list with
    LIST_EDITOR_FOCUS_GROUP,
)
TOGGLE_SCREENSHOT_VISIBILITY: Final = Command(
    "document.screenshots.toggle_visibility",
    "Toggle screenshot visibility",
    "Show or hide the current screenshot in the lightbox",
    (Qt.Key.Key_Space,),
    WIDGET,
    LIST_EDITOR_FOCUS_GROUP,
)

# endregion

COMMANDS: Final = (
    OPEN_REHU,
    OPEN_FOLDER,
    OPEN_COMPANION,
    NEW_REHUCO,
    OPEN_REHUCO,
    CLOSE_DOCUMENT,
    CLOSE_MISSING,
    CLOSE_ALL,
    SAVE_ALL,
    IMPORT_LEGACY_CATALOG,
    QUIT,
    CYCLE_THEME,
    IMAGE_PREVIEWS,
    SAVE_DOCUMENT,
    MAXIMIZE_DOCK,
    REFRESH_FILES,
    REFRESH_CONTENT_IMAGES,
    COPY_IMAGE,
    COMPLETE_IMAGES,
    CONVERT_SCREENSHOT,
    TOGGLE_SCREENSHOT_VISIBILITY,
    *LIST_EDITOR_COMMANDS,
    *CARD_LIST_COMMANDS,
    *LOG_COMMANDS,
)
"""The whole catalog, in the order a settings page lists it."""


@lru_cache(maxsize=1)
def shared_command_registry() -> CommandRegistry:
    """The app's one registry: the :data:`COMMANDS` under the user's keymap, installed so the generic
    widgets bind through it too.

    Built first thing in `MainWindow.__init__`, before any widget binds; a widget built without a window
    (a test) builds it on first use all the same.

    :returns: the shared registry.
    """
    registry = CommandRegistry()
    registry.register(*COMMANDS)
    registry.set_keymap(shared_shortcuts_settings().keymap)
    registry.install()
    return registry
