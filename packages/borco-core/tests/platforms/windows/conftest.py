"""Shared fixtures for HKCU-registry-backed tests (file association, directory context menu)."""

from typing import Final

import pytest
from pytest import fixture

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole tree there

from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

HKCU: Final = "borco_core.platforms.windows.hkcu_registry"
"""Module path prefix for ``mocker.patch`` targets below -- every real ``winreg``/``SHChangeNotify``
call funnels through here now, regardless of which higher-level module (``file_association``,
``directory_context_menu``) triggered it."""


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
    :mod:`borco_core.platforms.windows.hkcu_registry` makes.
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
        would exist while ``...\\shell`` itself does not, and :func:`~hkcu_registry.delete_key_tree`'s
        recursive delete would loop forever failing to ``OpenKey`` that never-created ancestor.
        """
        parts = path.split("\\")
        for end in range(1, len(parts) + 1):
            self.values.setdefault("\\".join(parts[:end]), {})
        return FakeKey(path)

    def open_key(self, _root: int, path: str, access: int = 0) -> FakeKey:
        """Fake for ``winreg.OpenKey`` -- raises ``FileNotFoundError`` if ``path`` doesn't exist,
        mirroring real ``winreg`` (an ``OSError`` subclass, not a bare ``OSError``)."""
        del access
        if path not in self.values:
            raise FileNotFoundError(f"no such key: {path}")
        return FakeKey(path)

    def set_value_ex(self, key: FakeKey, name: str, _reserved: int, _value_type: int, value: str) -> None:
        """Fake for ``winreg.SetValueEx``."""
        self.values.setdefault(key.path, {})[name] = value

    def query_value_ex(self, key: FakeKey, name: str) -> tuple[str, int]:
        """Fake for ``winreg.QueryValueEx`` -- raises ``FileNotFoundError`` if ``name`` doesn't exist,
        mirroring real ``winreg`` (an ``OSError`` subclass, not a bare ``KeyError``)."""
        values = self.values.get(key.path, {})
        if name not in values:
            raise FileNotFoundError(f"no such value: {key.path}[{name!r}]")
        return values[name], winreg.REG_SZ

    def delete_key(self, _root: int, path: str) -> None:
        """Fake for ``winreg.DeleteKey`` -- raises ``OSError`` if ``path`` doesn't exist."""
        if path not in self.values:
            raise OSError(f"no such key: {path}")
        del self.values[path]

    def delete_value(self, key: FakeKey, name: str) -> None:
        """Fake for ``winreg.DeleteValue`` -- raises ``FileNotFoundError`` if ``name`` doesn't exist,
        mirroring real ``winreg`` (an ``OSError`` subclass)."""
        values = self.values.get(key.path, {})
        if name not in values:
            raise FileNotFoundError(f"no such value: {key.path}[{name!r}]")
        del values[name]

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
    """Replace every Win32 call ``hkcu_registry`` makes with an in-memory fake.

    :param mocker: pytest-mock fixture.
    :returns: the fake registry, so tests can inspect what got written.
    """
    registry = FakeRegistry()
    mocker.patch(f"{HKCU}.winreg.CreateKeyEx", side_effect=registry.create_key_ex)
    mocker.patch(f"{HKCU}.winreg.OpenKey", side_effect=registry.open_key)
    mocker.patch(f"{HKCU}.winreg.SetValueEx", side_effect=registry.set_value_ex)
    mocker.patch(f"{HKCU}.winreg.QueryValueEx", side_effect=registry.query_value_ex)
    mocker.patch(f"{HKCU}.winreg.DeleteKey", side_effect=registry.delete_key)
    mocker.patch(f"{HKCU}.winreg.DeleteValue", side_effect=registry.delete_value)
    mocker.patch(f"{HKCU}.winreg.EnumKey", side_effect=registry.enum_key)
    mocker.patch(f"{HKCU}.ctypes.windll.shell32.SHChangeNotify", side_effect=registry.notify_shell)
    return registry
