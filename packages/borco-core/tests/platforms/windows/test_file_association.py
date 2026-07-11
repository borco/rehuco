"""Tests for generic Windows HKCU file-type association registration."""

from typing import Final

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from borco_core.platforms.windows import file_association  # noqa: E402  # pylint: disable=wrong-import-position

from .conftest import FakeRegistry  # noqa: E402  # pylint: disable=wrong-import-position

PROGID: Final = "Test.Document"
EXTENSION: Final = "test"
FRIENDLY_NAME: Final = "Test Document"
AUMID: Final = "test.app"
EXE_PATH: Final = r"C:\fake\test-app.exe"
ICO_PATH: Final = r"C:\fake\test-app.ico"
COMMAND: Final = f'"{EXE_PATH}" "%1"'
ICON: Final = f"{EXE_PATH},0"


@mark.windows
def test_register_writes_progid_and_extension_binding(fake_registry: FakeRegistry) -> None:
    """``register`` writes the ProgID, its icon/command/AUMID, and the extension binding.

    **Test steps:**

    * call ``register`` with a command/icon and an AUMID
    * verify the ProgID's default value, ``DefaultIcon``, ``shell\\open\\command`` and
      ``Application\\AppUserModelId`` all hold the expected values
    * verify the extension's default value points at the ProgID
    * verify the extension's ``OpenWithProgids`` also lists the ProgID (the stronger "recommended
      handler" signal for Explorer's open-with picker, alongside the plain default value)
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)

    progid_key = rf"Software\Classes\{PROGID}"
    ext_key = rf"Software\Classes\.{EXTENSION}"
    assert fake_registry.values[progid_key][""] == FRIENDLY_NAME
    assert fake_registry.values[f"{progid_key}\\DefaultIcon"][""] == ICON
    assert fake_registry.values[f"{progid_key}\\shell\\open\\command"][""] == COMMAND
    assert fake_registry.values[f"{progid_key}\\Application"]["AppUserModelId"] == AUMID
    assert fake_registry.values[ext_key][""] == PROGID
    assert PROGID in fake_registry.values[f"{ext_key}\\OpenWithProgids"]


@mark.windows
def test_register_without_an_aumid_skips_the_application_key(fake_registry: FakeRegistry) -> None:
    """``aumid=None`` (the default) writes no ``Application`` key at all.

    **Test steps:**

    * call ``register`` without an ``aumid``
    * verify no ``Application`` subkey was created under the ProgID
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON)

    progid_key = rf"Software\Classes\{PROGID}"
    assert f"{progid_key}\\Application" not in fake_registry.values


@mark.windows
def test_register_notifies_shell(fake_registry: FakeRegistry) -> None:
    """Registering refreshes Explorer's association cache without a logoff.

    **Test steps:**

    * call ``register``
    * verify ``SHChangeNotify`` was invoked exactly once
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_is_registered_is_true_right_after_register(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``True`` immediately after a matching ``register`` call.

    **Test steps:**

    * register
    * check ``is_registered`` with the same arguments
    * verify ``True``
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)

    assert file_association.FileAssociation.is_registered(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_is_registered_is_false_when_never_registered(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``False`` when nothing was ever registered.

    **Test steps:**

    * check ``is_registered`` without a prior ``register``
    * verify ``False``
    """
    assert not file_association.FileAssociation.is_registered(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)
    assert fake_registry.values == {}


@mark.windows
def test_is_registered_is_false_when_the_command_is_stale(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``False`` when the registered command points elsewhere now.

    **Test steps:**

    * register, then overwrite the command as if the exe moved
    * check ``is_registered`` against the original command
    * verify ``False``
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)
    progid_key = rf"Software\Classes\{PROGID}"
    fake_registry.values[f"{progid_key}\\shell\\open\\command"][""] = '"C:\\elsewhere\\test-app.exe" "%1"'

    assert not file_association.FileAssociation.is_registered(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)


@mark.windows
def test_is_registered_is_false_when_the_icon_is_stale(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``False`` when the registered icon points elsewhere now.

    **Test steps:**

    * register, then overwrite the icon as if the exe moved
    * check ``is_registered`` against the original icon
    * verify ``False``
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)
    progid_key = rf"Software\Classes\{PROGID}"
    fake_registry.values[f"{progid_key}\\DefaultIcon"][""] = r"C:\elsewhere\test-app.exe,0"

    assert not file_association.FileAssociation.is_registered(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)


@mark.windows
def test_is_registered_is_false_when_the_aumid_is_stale(fake_registry: FakeRegistry) -> None:
    """``is_registered`` reports ``False`` when an expected AUMID doesn't match the registered one.

    **Test steps:**

    * register with one AUMID
    * check ``is_registered`` expecting a different AUMID
    * verify ``False``
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)

    assert not file_association.FileAssociation.is_registered(
        PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, "some.other.app"
    )
    progid_key = rf"Software\Classes\{PROGID}"
    assert fake_registry.values[f"{progid_key}\\Application"]["AppUserModelId"] == AUMID


@mark.windows
def test_is_registered_ignores_the_application_key_when_no_aumid_is_expected(fake_registry: FakeRegistry) -> None:
    """``is_registered`` doesn't check the ``Application`` key at all when ``aumid`` is ``None``.

    **Test steps:**

    * register with an AUMID, but check ``is_registered`` without one
    * verify ``True`` regardless of the (unrelated) ``Application`` key's presence
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)

    assert file_association.FileAssociation.is_registered(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON)
    progid_key = rf"Software\Classes\{PROGID}"
    assert fake_registry.values[f"{progid_key}\\Application"]["AppUserModelId"] == AUMID


@mark.windows
def test_unregister_removes_progid_and_extension_binding(fake_registry: FakeRegistry) -> None:
    """``unregister`` deletes the whole ProgID key tree and the extension binding it owns.

    **Test steps:**

    * register, then unregister
    * verify the ProgID key and all its sub-keys are gone
    * verify the extension key is gone too, since it pointed at the ProgID
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)
    file_association.FileAssociation.unregister(PROGID, EXTENSION)

    progid_key = rf"Software\Classes\{PROGID}"
    assert not any(key.startswith(progid_key) for key in fake_registry.values)
    assert rf"Software\Classes\.{EXTENSION}" not in fake_registry.values


@mark.windows
def test_unregister_keeps_extension_binding_pointing_elsewhere(fake_registry: FakeRegistry) -> None:
    """An extension binding reassigned to another ProgID survives ``unregister``.

    **Test steps:**

    * register, then repoint the extension key at a different ProgID (simulating another app
      having claimed the extension since)
    * unregister
    * verify the extension key is untouched
    """
    file_association.FileAssociation.register(PROGID, EXTENSION, FRIENDLY_NAME, COMMAND, ICON, AUMID)
    ext_key = rf"Software\Classes\.{EXTENSION}"
    fake_registry.values[ext_key][""] = "SomeOtherApp.Document"

    file_association.FileAssociation.unregister(PROGID, EXTENSION)

    assert fake_registry.values[ext_key][""] == "SomeOtherApp.Document"


@mark.windows
def test_unregister_when_nothing_registered_is_a_noop(fake_registry: FakeRegistry) -> None:
    """``unregister`` on a clean registry raises nothing and notifies the shell anyway.

    **Test steps:**

    * call ``unregister`` without a prior ``register``
    * verify no exception propagates and the shell is still notified
    """
    file_association.FileAssociation.unregister(PROGID, EXTENSION)
    assert fake_registry.shell_notify_calls == 1
