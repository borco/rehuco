"""Tests for generic Windows HKCU folder/directory-background shell-verb registration."""

from typing import Final

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from borco_core.platforms.windows import directory_context_menu  # noqa: E402  # pylint: disable=wrong-import-position

from .conftest import FakeRegistry  # noqa: E402  # pylint: disable=wrong-import-position

SUB_KEY: Final = "Test.OpenFolder"
TEXT: Final = "Open in Test"
EXE_PATH: Final = r"C:\fake\test-app.exe"
COMMAND: Final = f'"{EXE_PATH}"'
ICON: Final = f"{EXE_PATH},0"


# region register_folder/unregister_folder tests


@mark.windows
def test_register_folder_writes_label_icon_and_command(fake_registry: FakeRegistry) -> None:
    """``register_folder`` writes the label, icon, and a ``"%1"``-suffixed command.

    **Test steps:**

    * call ``register_folder``
    * verify the sub-key's default value, ``Icon``, and ``command`` default value
    """
    directory_context_menu.DirectoryContextMenu.register_folder(SUB_KEY, TEXT, COMMAND, ICON)

    key = rf"Software\Classes\Directory\shell\{SUB_KEY}"
    assert fake_registry.values[key][""] == TEXT
    assert fake_registry.values[key]["Icon"] == ICON
    assert fake_registry.values[f"{key}\\command"][""] == f'{COMMAND} "%1"'


@mark.windows
def test_register_folder_notifies_shell(fake_registry: FakeRegistry) -> None:
    """Registering refreshes Explorer's shell-verb cache without a logoff.

    **Test steps:**

    * call ``register_folder``
    * verify ``SHChangeNotify`` was invoked exactly once
    """
    directory_context_menu.DirectoryContextMenu.register_folder(SUB_KEY, TEXT, COMMAND, ICON)
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_unregister_folder_removes_key_tree(fake_registry: FakeRegistry) -> None:
    """``unregister_folder`` deletes the whole sub-key tree.

    **Test steps:**

    * register, then unregister
    * verify no key under the sub-key survives
    """
    directory_context_menu.DirectoryContextMenu.register_folder(SUB_KEY, TEXT, COMMAND, ICON)
    directory_context_menu.DirectoryContextMenu.unregister_folder(SUB_KEY)

    key = rf"Software\Classes\Directory\shell\{SUB_KEY}"
    assert not any(existing.startswith(key) for existing in fake_registry.values)


@mark.windows
def test_unregister_folder_when_nothing_registered_is_a_noop(fake_registry: FakeRegistry) -> None:
    """``unregister_folder`` on a clean registry raises nothing and notifies the shell anyway.

    **Test steps:**

    * call ``unregister_folder`` without a prior ``register_folder``
    * verify no exception propagates and the shell is still notified
    """
    directory_context_menu.DirectoryContextMenu.unregister_folder(SUB_KEY)
    assert fake_registry.shell_notify_calls == 1


# endregion

# region register_background/unregister_background tests


@mark.windows
def test_register_background_writes_label_icon_and_command(fake_registry: FakeRegistry) -> None:
    """``register_background`` writes the label, icon, and a ``"%V"``-suffixed command.

    **Test steps:**

    * call ``register_background``
    * verify the sub-key's default value, ``Icon``, and ``command`` default value
    """
    directory_context_menu.DirectoryContextMenu.register_background(SUB_KEY, TEXT, COMMAND, ICON)

    key = rf"Software\Classes\Directory\Background\shell\{SUB_KEY}"
    assert fake_registry.values[key][""] == TEXT
    assert fake_registry.values[key]["Icon"] == ICON
    assert fake_registry.values[f"{key}\\command"][""] == f'{COMMAND} "%V"'


@mark.windows
def test_register_background_notifies_shell(fake_registry: FakeRegistry) -> None:
    """Registering refreshes Explorer's shell-verb cache without a logoff.

    **Test steps:**

    * call ``register_background``
    * verify ``SHChangeNotify`` was invoked exactly once
    """
    directory_context_menu.DirectoryContextMenu.register_background(SUB_KEY, TEXT, COMMAND, ICON)
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_unregister_background_removes_key_tree(fake_registry: FakeRegistry) -> None:
    """``unregister_background`` deletes the whole sub-key tree.

    **Test steps:**

    * register, then unregister
    * verify no key under the sub-key survives
    """
    directory_context_menu.DirectoryContextMenu.register_background(SUB_KEY, TEXT, COMMAND, ICON)
    directory_context_menu.DirectoryContextMenu.unregister_background(SUB_KEY)

    key = rf"Software\Classes\Directory\Background\shell\{SUB_KEY}"
    assert not any(existing.startswith(key) for existing in fake_registry.values)


@mark.windows
def test_unregister_background_when_nothing_registered_is_a_noop(fake_registry: FakeRegistry) -> None:
    """``unregister_background`` on a clean registry raises nothing and notifies the shell anyway.

    **Test steps:**

    * call ``unregister_background`` without a prior ``register_background``
    * verify no exception propagates and the shell is still notified
    """
    directory_context_menu.DirectoryContextMenu.unregister_background(SUB_KEY)
    assert fake_registry.shell_notify_calls == 1


# endregion


@mark.windows
def test_register_folder_and_background_do_not_collide(fake_registry: FakeRegistry) -> None:
    """The folder and folder-background verbs live under separate roots and don't overwrite each other.

    **Test steps:**

    * register both verbs under the same ``sub_key`` with different labels
    * verify each root keeps its own label
    """
    directory_context_menu.DirectoryContextMenu.register_folder(SUB_KEY, "Folder text", COMMAND, ICON)
    directory_context_menu.DirectoryContextMenu.register_background(SUB_KEY, "Background text", COMMAND, ICON)

    folder_key = rf"Software\Classes\Directory\shell\{SUB_KEY}"
    background_key = rf"Software\Classes\Directory\Background\shell\{SUB_KEY}"
    assert fake_registry.values[folder_key][""] == "Folder text"
    assert fake_registry.values[background_key][""] == "Background text"
