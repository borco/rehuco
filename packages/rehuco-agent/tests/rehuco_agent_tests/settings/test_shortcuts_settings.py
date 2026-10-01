"""Tests for `ShortcutsSettings` -- the keymap, stored under its own group (#343)."""

from typing import Any

from borco_pyside.shortcuts import UNBOUND
from PySide6.QtGui import QKeySequence
from rehuco_agent.commands import QUIT, SAVE_DOCUMENT
from rehuco_agent.settings.shortcuts_settings import GROUP, ShortcutsSettings

# region Sample classes


# unsupported-*-operation: a false positive on plain dicts, seen only in modules importing PySide6
# pylint: disable=unsupported-assignment-operation,unsupported-delete-operation
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """An in-memory stand-in for the ``QSettings`` group, key and value API a keymap uses."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__prefixes: list[str] = []

    @property
    def __prefix(self) -> str:
        return "".join(self.__prefixes)

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__prefixes.append(f"{name}/")

    def endGroup(self) -> None:  # noqa: N802
        self.__prefixes.pop()

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__prefix + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002
        del type
        return self.__data.get(self.__prefix + key, default)

    def childKeys(self) -> list[str]:  # noqa: N802
        prefix = self.__prefix
        nested = (key[len(prefix) :] for key in self.__data if key.startswith(prefix))
        return [rest for rest in nested if "/" not in rest]

    def remove(self, key: str) -> None:
        full = self.__prefix + key
        for stored in [stored for stored in self.__data if stored == full or stored.startswith(full + "/")]:
            del self.__data[stored]


# pylint: enable=unsupported-assignment-operation,unsupported-delete-operation


# endregion

# region ShortcutsSettings tests


def test_the_keymap_round_trips_under_its_group(qapp: Any) -> None:
    """What is saved reads back, under the ``shortcuts`` group.

    **Test steps:**

    * override one command's keys and unbind another
    * save, then load into a fresh section
    * verify both overrides survive and sit under the group

    :param qapp: pytest-qt's application fixture -- key sequences need one.
    """
    del qapp
    fake = FakeSettings()
    settings = ShortcutsSettings()
    settings.keymap.set_keys(QUIT, [QKeySequence("Ctrl+Shift+Q")])
    settings.keymap.set_keys(SAVE_DOCUMENT, [])

    settings.save(fake)  # type: ignore[arg-type]
    loaded = ShortcutsSettings()
    loaded.load(fake)  # type: ignore[arg-type]

    assert loaded.keymap.effective_keys(QUIT) == (QKeySequence("Ctrl+Shift+Q"),)
    assert loaded.keymap.effective_keys(SAVE_DOCUMENT) == ()
    assert fake.value(f"{GROUP}/keys/{SAVE_DOCUMENT.id}") == UNBOUND


def test_nothing_stored_is_every_default(qapp: Any) -> None:
    """A fresh install has no overrides.

    **Test steps:**

    * load from empty settings
    * verify the keymap is empty

    :param qapp: pytest-qt's application fixture.
    """
    del qapp
    settings = ShortcutsSettings()

    settings.load(FakeSettings())  # type: ignore[arg-type]

    assert not settings.keymap.keys and not settings.keymap.scopes


# endregion
