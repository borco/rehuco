"""Tests for generic Windows HKCU per-file-extension shell-verb registration."""

from typing import Final

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from borco_core.platforms.windows import (  # noqa: E402  # pylint: disable=wrong-import-position
    file_extension_context_menu,
)

from .conftest import FakeRegistry  # noqa: E402  # pylint: disable=wrong-import-position

SUB_KEY: Final = "Test.AddInfo"
TEXT: Final = "Create or Open Test Info"
EXE_PATH: Final = r"C:\fake\test-app.exe"
COMMAND: Final = f'"{EXE_PATH}"'
ICON: Final = f"{EXE_PATH},0"


@mark.windows
def test_register_writes_label_icon_and_command_for_every_extension(fake_registry: FakeRegistry) -> None:
    """``register`` writes the label, icon, and a ``"%1"``-suffixed command under every extension.

    **Test steps:**

    * call ``register`` with two extensions
    * verify each extension's own sub-key holds the label, icon, and command default value
    """
    file_extension_context_menu.FileExtensionContextMenu.register([".zip", ".7z"], SUB_KEY, TEXT, COMMAND, ICON)

    for extension in (".zip", ".7z"):
        key = rf"Software\Classes\SystemFileAssociations\{extension}\shell\{SUB_KEY}"
        assert fake_registry.values[key][""] == TEXT
        assert fake_registry.values[key]["Icon"] == ICON
        assert fake_registry.values[f"{key}\\command"][""] == f'{COMMAND} "%1"'


@mark.windows
def test_register_notifies_shell(fake_registry: FakeRegistry) -> None:
    """Registering refreshes Explorer's shell-verb cache without a logoff.

    **Test steps:**

    * call ``register``
    * verify ``SHChangeNotify`` was invoked exactly once (not once per extension)
    """
    file_extension_context_menu.FileExtensionContextMenu.register([".zip", ".7z"], SUB_KEY, TEXT, COMMAND, ICON)
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_is_registered_is_true_right_after_register(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``True`` immediately after a matching ``register`` call.

    **Test steps:**

    * register two extensions
    * check ``is_registered`` with the same arguments
    * verify ``True``
    """
    file_extension_context_menu.FileExtensionContextMenu.register([".zip", ".7z"], SUB_KEY, TEXT, COMMAND, ICON)

    assert file_extension_context_menu.FileExtensionContextMenu.is_registered(
        [".zip", ".7z"], SUB_KEY, TEXT, COMMAND, ICON
    )
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_is_registered_is_false_when_never_registered(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``False`` when nothing was ever registered.

    **Test steps:**

    * check ``is_registered`` without a prior ``register``
    * verify ``False``
    """
    assert not file_extension_context_menu.FileExtensionContextMenu.is_registered(
        [".zip"], SUB_KEY, TEXT, COMMAND, ICON
    )
    assert fake_registry.values == {}


@mark.windows
def test_is_registered_is_false_when_only_some_extensions_are_registered(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``False`` if even one of the checked extensions is missing.

    **Test steps:**

    * register only ``.zip``
    * check ``is_registered`` for both ``.zip`` and ``.7z``
    * verify ``False``
    """
    file_extension_context_menu.FileExtensionContextMenu.register([".zip"], SUB_KEY, TEXT, COMMAND, ICON)

    assert not file_extension_context_menu.FileExtensionContextMenu.is_registered(
        [".zip", ".7z"], SUB_KEY, TEXT, COMMAND, ICON
    )
    assert rf"Software\Classes\SystemFileAssociations\.7z\shell\{SUB_KEY}" not in fake_registry.values


@mark.windows
def test_unregister_removes_key_tree_for_every_extension(fake_registry: FakeRegistry) -> None:
    """``unregister`` deletes the whole sub-key tree under every extension.

    **Test steps:**

    * register, then unregister, both with the same two extensions
    * verify no key under either extension's sub-key survives
    """
    file_extension_context_menu.FileExtensionContextMenu.register([".zip", ".7z"], SUB_KEY, TEXT, COMMAND, ICON)
    file_extension_context_menu.FileExtensionContextMenu.unregister([".zip", ".7z"], SUB_KEY)

    for extension in (".zip", ".7z"):
        key = rf"Software\Classes\SystemFileAssociations\{extension}\shell\{SUB_KEY}"
        assert not any(existing.startswith(key) for existing in fake_registry.values)


@mark.windows
def test_unregister_when_nothing_registered_is_a_noop(fake_registry: FakeRegistry) -> None:
    """``unregister`` on a clean registry raises nothing and notifies the shell anyway.

    **Test steps:**

    * call ``unregister`` without a prior ``register``
    * verify no exception propagates and the shell is still notified
    """
    file_extension_context_menu.FileExtensionContextMenu.unregister([".zip"], SUB_KEY)
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_register_keeps_extensions_independent(fake_registry: FakeRegistry) -> None:
    """Unregistering one extension's verb leaves another extension's verb untouched.

    **Test steps:**

    * register both ``.zip`` and ``.7z``
    * unregister only ``.zip``
    * verify ``.7z``'s sub-key still holds its label
    """
    file_extension_context_menu.FileExtensionContextMenu.register([".zip", ".7z"], SUB_KEY, TEXT, COMMAND, ICON)

    file_extension_context_menu.FileExtensionContextMenu.unregister([".zip"], SUB_KEY)

    zip_key = rf"Software\Classes\SystemFileAssociations\.zip\shell\{SUB_KEY}"
    other_key = rf"Software\Classes\SystemFileAssociations\.7z\shell\{SUB_KEY}"
    assert not any(existing.startswith(zip_key) for existing in fake_registry.values)
    assert fake_registry.values[other_key][""] == TEXT
