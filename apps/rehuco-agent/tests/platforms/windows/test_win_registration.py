"""Tests for Windows HKCU file-association and app-identity registration."""

from typing import Final

import pytest
from pytest import fixture, mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent.platforms.windows import win_registration  # noqa: E402  # pylint: disable=wrong-import-position

EXE_PATH: Final = r"C:\fake\rehuco-agent.exe"
ICO_PATH: Final = r"C:\fake\rehuco-agent.ico"

WR: Final = "rehuco_agent.platforms.windows.win_registration"
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
    :mod:`rehuco_agent.platforms.windows.win_registration` makes.
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
        would exist while ``...\\shell`` itself does not, and :func:`win_registration.unregister`'s
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
    """Replace every Win32 call ``win_registration`` makes with an in-memory fake.

    :param mocker: pytest-mock fixture.
    :returns: the fake registry, so tests can inspect what got written.
    """
    registry = FakeRegistry()
    mocker.patch(f"{WR}.winreg.CreateKeyEx", side_effect=registry.create_key_ex)
    mocker.patch(f"{WR}.winreg.OpenKey", side_effect=registry.open_key)
    mocker.patch(f"{WR}.winreg.SetValueEx", side_effect=registry.set_value_ex)
    mocker.patch(f"{WR}.winreg.QueryValueEx", side_effect=registry.query_value_ex)
    mocker.patch(f"{WR}.winreg.DeleteKey", side_effect=registry.delete_key)
    mocker.patch(f"{WR}.winreg.EnumKey", side_effect=registry.enum_key)
    mocker.patch(f"{WR}.ctypes.windll.shell32.SHChangeNotify", side_effect=registry.notify_shell)
    return registry


@mark.windows
def test_register_writes_progid_and_extension_binding(fake_registry: FakeRegistry) -> None:
    """``register`` writes the ProgID, its icon/command/AUMID, and the ``.rehu`` binding.

    **Test steps:**

    * call ``register`` with an exe path and no explicit icon
    * verify the ProgID's default value, ``DefaultIcon``, ``shell\\open\\command`` and
      ``Application\\AppUserModelId`` all hold the expected values
    * verify ``.rehu``'s default value points at the ProgID
    * verify ``.rehu\\OpenWithProgids`` also lists the ProgID (the stronger "recommended
      handler" signal for Explorer's open-with picker, alongside the plain default value)
    * verify the icon falls back to the exe path when no ``.ico`` is given
    """
    win_registration.register(EXE_PATH)

    progid_key = rf"Software\Classes\{win_registration.PROGID}"
    ext_key = rf"Software\Classes\.{win_registration.EXTENSION}"
    assert fake_registry.values[progid_key][""] == win_registration.FRIENDLY_NAME
    assert fake_registry.values[f"{progid_key}\\DefaultIcon"][""] == f"{EXE_PATH},0"
    assert fake_registry.values[f"{progid_key}\\shell\\open\\command"][""] == f'"{EXE_PATH}" "%1"'
    assert fake_registry.values[f"{progid_key}\\Application"]["AppUserModelId"] == win_registration.AUMID
    assert fake_registry.values[ext_key][""] == win_registration.PROGID
    assert win_registration.PROGID in fake_registry.values[f"{ext_key}\\OpenWithProgids"]


@mark.windows
def test_register_with_explicit_icon(fake_registry: FakeRegistry) -> None:
    """An explicit ``ico_path`` overrides the exe-path icon fallback.

    **Test steps:**

    * call ``register`` with an explicit ``.ico`` path
    * verify ``DefaultIcon`` points at the ``.ico``, not the exe
    """
    win_registration.register(EXE_PATH, ICO_PATH)
    progid_key = rf"Software\Classes\{win_registration.PROGID}"
    assert fake_registry.values[f"{progid_key}\\DefaultIcon"][""] == f"{ICO_PATH},0"


@mark.windows
def test_register_notifies_shell(fake_registry: FakeRegistry) -> None:
    """Registering refreshes Explorer's association cache without a logoff.

    **Test steps:**

    * call ``register``
    * verify ``SHChangeNotify`` was invoked exactly once
    """
    win_registration.register(EXE_PATH)
    assert fake_registry.shell_notify_calls == 1


@mark.windows
def test_unregister_removes_progid_and_extension_binding(fake_registry: FakeRegistry) -> None:
    """``unregister`` deletes the whole ProgID key tree and the extension binding it owns.

    **Test steps:**

    * register, then unregister
    * verify the ProgID key and all its sub-keys are gone
    * verify the ``.rehu`` extension key is gone too, since it pointed at the ProgID
    """
    win_registration.register(EXE_PATH)
    win_registration.unregister()

    progid_key = rf"Software\Classes\{win_registration.PROGID}"
    assert not any(key.startswith(progid_key) for key in fake_registry.values)
    assert rf"Software\Classes\.{win_registration.EXTENSION}" not in fake_registry.values


@mark.windows
def test_unregister_keeps_extension_binding_pointing_elsewhere(fake_registry: FakeRegistry) -> None:
    """A ``.rehu`` binding reassigned to another ProgID survives ``unregister``.

    **Test steps:**

    * register, then repoint the ``.rehu`` extension key at a different ProgID (simulating
      another app having claimed the extension since)
    * unregister
    * verify the extension key is untouched
    """
    win_registration.register(EXE_PATH)
    ext_key = rf"Software\Classes\.{win_registration.EXTENSION}"
    fake_registry.values[ext_key][""] = "SomeOtherApp.Document"

    win_registration.unregister()

    assert fake_registry.values[ext_key][""] == "SomeOtherApp.Document"


@mark.windows
def test_unregister_when_nothing_registered_is_a_noop(fake_registry: FakeRegistry) -> None:
    """``unregister`` on a clean registry raises nothing and notifies the shell anyway.

    **Test steps:**

    * call ``unregister`` without a prior ``register``
    * verify no exception propagates and the shell is still notified
    """
    win_registration.unregister()
    assert fake_registry.shell_notify_calls == 1
