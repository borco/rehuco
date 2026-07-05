"""Tests for generic Windows HKCU file-type association registration."""

from typing import Final

import pytest
from pytest import fixture, mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from borco_core.platforms.windows import file_association  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

PROGID: Final = "Test.Document"
EXTENSION: Final = "test"
FRIENDLY_NAME: Final = "Test Document"
AUMID: Final = "test.app"
EXE_PATH: Final = r"C:\fake\test-app.exe"
ICO_PATH: Final = r"C:\fake\test-app.ico"
COMMAND: Final = f'"{EXE_PATH}" "%1"'
ICON: Final = f"{EXE_PATH},0"

FA: Final = "borco_core.platforms.windows.file_association"
"""Module path prefix for ``mocker.patch`` targets below."""


class FakeKey:
    """Context-manager stand-in for a ``winreg`` key handle, tied to a path in :class:`FakeRegistry`."""

    def __init__(self, path: str) -> None:
        self.path = path

    def __enter__(self) -> FakeKey:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeRegistry:
    """In-memory stand-in for ``HKEY_CURRENT_USER``, keyed by registry path.

    Also records ``SHChangeNotify`` calls, so a single fixture can back every Win32 call
    :mod:`borco_core.platforms.windows.file_association` makes.
    """

    def __init__(self) -> None:
        self.values: dict[str, dict[str, str]] = {}
        self.shell_notify_calls = 0

    def children_of(self, path: str) -> list[str]:
        """Direct child key names under ``path``, in first-seen order.

        :param path: registry path relative to ``HKEY_CURRENT_USER``.
        :returns: immediate child key names (not full paths).
        """
        prefix = f"{path}\\"
        children: list[str] = []
        for existing in self.values:
            if existing.startswith(prefix):
                child = existing[len(prefix) :].split("\\", 1)[0]
                if child not in children:
                    children.append(child)
        return children

    def create_key_ex(self, _root: int, path: str) -> FakeKey:
        """Fake for ``winreg.CreateKeyEx`` -- creates ``path`` and any missing ancestor keys.

        Mirrors real ``winreg.CreateKeyEx``, which creates every intermediate key along the
        path (like ``mkdir -p``) -- without this, a leaf like ``...\\shell\\open\\command``
        would exist while ``...\\shell`` itself does not, and :meth:`FileAssociation.unregister`'s
        recursive delete would loop forever failing to ``OpenKey`` that never-created ancestor.
        """
        parts = path.split("\\")
        for end in range(1, len(parts) + 1):
            self.values.setdefault("\\".join(parts[:end]), {})
        return FakeKey(path)

    def open_key(self, _root: int, path: str, access: int = 0) -> FakeKey:
        """Fake for ``winreg.OpenKey`` -- raises ``OSError`` if ``path`` doesn't exist."""
        del access
        if path not in self.values:
            raise OSError(f"no such key: {path}")
        return FakeKey(path)

    def set_value_ex(self, key: FakeKey, name: str, _reserved: int, _value_type: int, value: str) -> None:
        """Fake for ``winreg.SetValueEx``."""
        self.values.setdefault(key.path, {})[name] = value

    def query_value_ex(self, key: FakeKey, name: str) -> tuple[str, int]:
        """Fake for ``winreg.QueryValueEx``."""
        return self.values[key.path][name], winreg.REG_SZ

    def delete_key(self, _root: int, path: str) -> None:
        """Fake for ``winreg.DeleteKey`` -- raises ``OSError`` if ``path`` doesn't exist."""
        if path not in self.values:
            raise OSError(f"no such key: {path}")
        del self.values[path]

    def enum_key(self, key: FakeKey, index: int) -> str:
        """Fake for ``winreg.EnumKey`` -- raises ``OSError`` once ``index`` runs out of children."""
        children = self.children_of(key.path)
        if index >= len(children):
            raise OSError("no more items")
        return children[index]

    def notify_shell(self, *args: object) -> None:
        """Fake for ``ctypes.windll.shell32.SHChangeNotify``."""
        del args
        self.shell_notify_calls += 1


@fixture
def fake_registry(mocker: MockerFixture) -> FakeRegistry:
    """Replace every Win32 call ``file_association`` makes with an in-memory fake.

    :param mocker: pytest-mock fixture.
    :returns: the fake registry, so tests can inspect what got written.
    """
    registry = FakeRegistry()
    mocker.patch(f"{FA}.winreg.CreateKeyEx", side_effect=registry.create_key_ex)
    mocker.patch(f"{FA}.winreg.OpenKey", side_effect=registry.open_key)
    mocker.patch(f"{FA}.winreg.SetValueEx", side_effect=registry.set_value_ex)
    mocker.patch(f"{FA}.winreg.QueryValueEx", side_effect=registry.query_value_ex)
    mocker.patch(f"{FA}.winreg.DeleteKey", side_effect=registry.delete_key)
    mocker.patch(f"{FA}.winreg.EnumKey", side_effect=registry.enum_key)
    mocker.patch(f"{FA}.ctypes.windll.shell32.SHChangeNotify", side_effect=registry.notify_shell)
    return registry


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
