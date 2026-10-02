"""Tests for the app's command catalog and its shared registry (#343)."""

from typing import Any

from borco_pyside.shortcuts import CommandRegistry, CommandScope, Keymap, find_conflicts
from PySide6.QtGui import QKeySequence
from pytest import mark
from rehuco_agent.commands import COMMANDS, shared_command_registry
from rehuco_agent.settings.shortcuts_settings import shared_shortcuts_settings

# what each command's keys were as literals before the catalog existed -- the regression guard that the
# migration changed no key and no scope; portable spellings, or a standard key, resolved at assert time
PRE_MIGRATION_LITERALS: list[tuple[str, Any, CommandScope]] = [
    ("app.open_rehu", "Ctrl+O", CommandScope.WINDOW),
    ("app.close_document", "Ctrl+W", CommandScope.WINDOW),
    ("app.close_all", "Ctrl+Shift+W", CommandScope.WINDOW),
    ("app.save_all", "Ctrl+Shift+S", CommandScope.WINDOW),
    ("app.quit", "Ctrl+Q", CommandScope.WINDOW),
    ("view.image_previews", "Ctrl+Shift+`", CommandScope.APP_WIDE),
    ("document.save", QKeySequence.StandardKey.Save, CommandScope.DOCUMENT_FOCUSED),
    ("document.files.refresh", "F5", CommandScope.DOCUMENT_FOCUSED),
    ("document.content_images.refresh", "F5", CommandScope.DOCUMENT_FOCUSED),
    ("document.description.complete_images", "Ctrl+Space", CommandScope.WIDGET),
    ("document.screenshots.convert", "C", CommandScope.WIDGET),
    ("document.screenshots.toggle_visibility", "Space", CommandScope.WIDGET),
    ("list_editor.insert", "Ins", CommandScope.WIDGET),
    ("list_editor.duplicate", "Ctrl+D", CommandScope.WIDGET),
    ("list_editor.edit", "F2", CommandScope.WIDGET),
    ("list_editor.delete", QKeySequence.StandardKey.Delete, CommandScope.WIDGET),
    ("list_editor.move_to_top", "Ctrl+Home", CommandScope.WIDGET),
    ("list_editor.move_up", "Ctrl+Up", CommandScope.WIDGET),
    ("list_editor.move_down", "Ctrl+Down", CommandScope.WIDGET),
    ("list_editor.move_to_bottom", "Ctrl+End", CommandScope.WIDGET),
    ("card_list.delete", "Ctrl+Del", CommandScope.WIDGET),
    ("card_list.insert", "Ctrl+Ins", CommandScope.WIDGET),
    ("card_list.move_to_top", "Ctrl+Home", CommandScope.WIDGET),
    ("card_list.move_up", "Ctrl+Up", CommandScope.WIDGET),
    ("card_list.move_down", "Ctrl+Down", CommandScope.WIDGET),
    ("card_list.move_to_bottom", "Ctrl+End", CommandScope.WIDGET),
    ("log.copy", QKeySequence.StandardKey.Copy, CommandScope.DOCUMENT_FOCUSED),
]


def test_every_id_is_unique_and_free_of_a_settings_separator() -> None:
    """An id is a settings key: two alike would share one override, and a ``/`` would open a group.

    **Test steps:**

    * collect every catalog id
    * verify none repeats and none holds ``/``
    """
    ids = [command.id for command in COMMANDS]

    assert len(ids) == len(set(ids))
    assert not [command_id for command_id in ids if "/" in command_id]


@mark.parametrize(("command_id", "key", "scope"), PRE_MIGRATION_LITERALS)
def test_the_defaults_are_the_pre_migration_literals(command_id: str, key: Any, scope: CommandScope, qapp: Any) -> None:
    """Moving the keys into the catalog changed none of them.

    **Test steps:**

    * look the command up
    * verify its default keys and scope are what the literal was

    :param command_id: the command.
    :param key: its literal key before the catalog.
    :param scope: its literal scope before the catalog.
    :param qapp: pytest-qt's application fixture -- key sequences need one.
    """
    del qapp
    command = next(command for command in COMMANDS if command.id == command_id)
    expected = (
        tuple(QKeySequence.keyBindings(key)) if isinstance(key, QKeySequence.StandardKey) else (QKeySequence(key),)
    )

    assert command.default_key_sequences() == expected
    assert command.default_scope is scope


def test_the_document_commands_may_be_routed_app_wide() -> None:
    """Each per-document command offers the app-wide scope (#345), and only those do.

    **Test steps:**

    * collect the commands allowing `CommandScope.DOCUMENT_APP_WIDE`
    * verify they are the four document commands, each still focused-document by default
    """
    routable = [command for command in COMMANDS if CommandScope.DOCUMENT_APP_WIDE in command.scopes]

    assert [command.id for command in routable] == [
        "document.save",
        "document.maximize",
        "document.files.refresh",
        "document.content_images.refresh",
    ]
    assert all(command.default_scope is CommandScope.DOCUMENT_FOCUSED for command in routable)


def test_the_default_catalog_has_no_conflicts(qapp: Any) -> None:
    """Out of the box, no two commands collide where both are armed.

    **Test steps:**

    * check the catalog under an empty keymap
    * verify no conflict

    :param qapp: pytest-qt's application fixture.
    """
    del qapp

    assert not find_conflicts(COMMANDS, Keymap())


def test_the_shared_registry_holds_the_catalog_under_the_stored_keymap(qapp: Any) -> None:
    """The registry is built from the catalog and the user's keymap, and installed for generic widgets.

    **Test steps:**

    * store an override in the (isolated) shortcuts settings
    * build the shared registry
    * verify it holds every command, applies the override, and is the installed one

    :param qapp: pytest-qt's application fixture.
    """
    del qapp
    quit_command = next(command for command in COMMANDS if command.id == "app.quit")
    shared_shortcuts_settings().keymap.set_keys(quit_command, [QKeySequence("Ctrl+Shift+Q")])

    registry = shared_command_registry()

    assert registry.commands() == COMMANDS
    assert registry.keys("app.quit") == (QKeySequence("Ctrl+Shift+Q"),)
    assert CommandRegistry.installed() is registry
