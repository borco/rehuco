"""Tests for `Keymap` -- overrides only, stored per command -- and for `find_conflicts`."""

from typing import Any

from borco_pyside.shortcuts import UNBOUND, Command, CommandScope, Keymap, find_conflicts
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from pytest import fixture, raises

# region Sample classes


# unsupported-*-operation: a false positive on plain dicts, seen only in modules importing PySide6
# pylint: disable=unsupported-assignment-operation,unsupported-delete-operation
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring
    """An in-memory stand-in for the ``QSettings`` group, key and value API a keymap uses."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.__prefixes: list[str] = []

    @property
    def __prefix(self) -> str:
        return "".join(self.__prefixes)

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__prefixes.append(f"{name}/")

    def endGroup(self) -> None:  # noqa: N802
        self.__prefixes.pop()

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.data[self.__prefix + key] = value

    def value(self, key: str, default: Any = None) -> Any:
        return self.data.get(self.__prefix + key, default)

    def childKeys(self) -> list[str]:  # noqa: N802
        prefix = self.__prefix
        return [key[len(prefix) :] for key in self.data if key.startswith(prefix) and "/" not in key[len(prefix) :]]

    def remove(self, key: str) -> None:
        full = self.__prefix + key
        for stored in [stored for stored in self.data if stored == full or stored.startswith(full + "/")]:
            del self.data[stored]


# pylint: enable=unsupported-assignment-operation,unsupported-delete-operation


SAVE: Command = Command(
    "document.save", "Save", "Save the document", (QKeySequence.StandardKey.Save,), (CommandScope.DOCUMENT_FOCUSED,)
)
QUIT: Command = Command(
    "app.quit",
    "Quit",
    "Quit the app",
    (Qt.KeyboardModifier.ControlModifier | Qt.Key.Key_Q,),
    (CommandScope.WINDOW, CommandScope.APP_WIDE),
)


def widget_command(command_id: str, key: str, focus_group: str | None, scope: CommandScope) -> Command:
    """A command on ``key`` in one scope and focus group -- what a conflict test pairs up.

    :param command_id: its id.
    :param key: its default key, portable spelling.
    :param focus_group: its focus group.
    :param scope: its only scope.
    :returns: the command.
    """
    return Command(command_id, command_id, command_id, (key,), (scope,), focus_group=focus_group)


@fixture
def keymap(qapp: Any) -> Keymap:
    """An empty keymap, with a `QApplication` up for the key sequences it holds.

    :param qapp: pytest-qt's application fixture.
    :returns: the keymap.
    """
    del qapp
    return Keymap()


# endregion

# region Command tests


def test_a_command_id_with_a_slash_or_no_scope_is_refused() -> None:
    """An id is a settings key, so a ``/`` would open a group; and a command needs a scope to default to.

    **Test steps:**

    * declare a command with a ``/`` in its id, then one with no scopes
    * verify both raise
    """
    with raises(ValueError):
        Command("bad/id", "Bad", "Bad", (), (CommandScope.WINDOW,))
    with raises(ValueError):
        Command("no.scope", "None", "None", (), ())


# endregion

# region Keymap tests


def test_a_command_with_no_override_has_its_defaults(keymap: Keymap) -> None:
    """A keymap stores overrides only, so an untouched command reads its declaration.

    **Test steps:**

    * ask an empty keymap for a command's keys and scope
    * verify both are the command's defaults
    """
    assert keymap.effective_keys(QUIT) == (QKeySequence("Ctrl+Q"),)
    assert keymap.effective_scope(QUIT) is CommandScope.WINDOW
    assert keymap.is_default(QUIT)


def test_a_standard_key_expands_to_the_platform_bindings(keymap: Keymap) -> None:
    """A standard key is resolved on this platform, never stored.

    **Test steps:**

    * ask for a Save command's keys
    * verify they are Qt's own bindings for Save
    """
    assert list(keymap.effective_keys(SAVE)) == QKeySequence.keyBindings(QKeySequence.StandardKey.Save)


def test_an_override_set_back_to_the_default_is_dropped(keymap: Keymap) -> None:
    """Overrides only: a key or scope equal to the default leaves no entry behind.

    **Test steps:**

    * override a command's keys and scope
    * set both back to the defaults
    * verify the keymap holds nothing for it
    """
    keymap.set_keys(QUIT, [QKeySequence("Ctrl+Shift+Q")])
    keymap.set_scope(QUIT, CommandScope.APP_WIDE)
    assert not keymap.is_default(QUIT)

    keymap.set_keys(QUIT, [QKeySequence("Ctrl+Q")])
    keymap.set_scope(QUIT, CommandScope.WINDOW)

    assert keymap.is_default(QUIT)


def test_a_scope_the_command_does_not_allow_is_refused_and_ignored(keymap: Keymap) -> None:
    """Setting a disallowed scope raises; one already stored (by another version) reads as the default.

    **Test steps:**

    * try to set a scope the command does not declare
    * store one directly, as a load would
    * verify the effective scope stays the default
    """
    with raises(ValueError):
        keymap.set_scope(QUIT, CommandScope.WIDGET)
    keymap.scopes[QUIT.id] = CommandScope.WIDGET  # pylint: disable=unsupported-assignment-operation

    assert keymap.effective_scope(QUIT) is CommandScope.WINDOW


def test_reset_drops_one_command_and_reset_all_every_one(keymap: Keymap) -> None:
    """``reset`` forgets one command's overrides, ``reset_all`` every command's.

    **Test steps:**

    * override two commands
    * reset one, then all
    * verify each step leaves the expected commands at their defaults
    """
    keymap.set_keys(QUIT, [])
    keymap.set_keys(SAVE, [])

    keymap.reset(QUIT.id)
    assert keymap.is_default(QUIT) and not keymap.is_default(SAVE)

    keymap.reset_all()
    assert keymap.is_default(SAVE)


def test_the_keymap_round_trips_through_settings(keymap: Keymap) -> None:
    """Keys, an explicit "no keys", a scope and an unknown command's override all read back as written.

    **Test steps:**

    * override keys (two of them), unbind another command, change a scope, and keep an unknown id
    * save, then load into a fresh keymap
    * verify every override survives, and "no keys" is stored as the explicit marker
    """
    settings = FakeSettings()
    keymap.set_keys(QUIT, [QKeySequence("Ctrl+Shift+Q"), QKeySequence("Ctrl+K, Q")])
    keymap.set_scope(QUIT, CommandScope.APP_WIDE)
    keymap.set_keys(SAVE, [])
    keymap.keys["gone.command"] = (QKeySequence("F9"),)  # pylint: disable=unsupported-assignment-operation

    keymap.save(settings)  # type: ignore[arg-type]
    loaded = Keymap()
    loaded.load(settings)  # type: ignore[arg-type]

    assert settings.data["keys/document.save"] == UNBOUND
    assert loaded.effective_keys(QUIT) == (QKeySequence("Ctrl+Shift+Q"), QKeySequence("Ctrl+K, Q"))
    assert loaded.effective_scope(QUIT) is CommandScope.APP_WIDE
    assert loaded.effective_keys(SAVE) == ()
    assert loaded.keys["gone.command"] == (QKeySequence("F9"),)


def test_a_save_drops_an_override_reset_since_the_last_one(keymap: Keymap) -> None:
    """Storage mirrors the keymap: a reset override does not linger to come back on the next load.

    **Test steps:**

    * save an override, reset it, save again
    * verify nothing is stored for it
    """
    settings = FakeSettings()
    keymap.set_keys(QUIT, [])
    keymap.save(settings)  # type: ignore[arg-type]

    keymap.reset_all()
    keymap.save(settings)  # type: ignore[arg-type]

    assert not settings.data


def test_an_unknown_scope_string_is_ignored_on_load(keymap: Keymap) -> None:
    """A scope this build does not know -- a newer version's -- is dropped rather than failing the load.

    **Test steps:**

    * store an unknown scope string
    * load
    * verify no scope override was read
    """
    settings = FakeSettings()
    settings.setValue("scope/app.quit", "somewhere_new")

    keymap.load(settings)  # type: ignore[arg-type]

    assert not keymap.scopes


def test_a_comma_key_split_by_the_ini_backend_is_joined_back(keymap: Keymap) -> None:
    """The ini backend reads an unquoted value holding a comma back as a list; ``Ctrl+,`` survives it.

    **Test steps:**

    * store ``Ctrl+,`` the way the backend hands it back, as two strings
    * load
    * verify the one key reads back
    """
    settings = FakeSettings()
    settings.setValue("keys/app.quit", ["Ctrl+", ""])

    keymap.load(settings)  # type: ignore[arg-type]

    assert keymap.effective_keys(QUIT) == (QKeySequence("Ctrl+,"),)


def test_a_value_that_is_not_text_reads_as_no_keys(keymap: Keymap) -> None:
    """A hand-edited entry the backend hands back as something other than text is not a crash.

    **Test steps:**

    * store a number as a command's keys
    * load
    * verify it reads as an override to no keys
    """
    settings = FakeSettings()
    settings.setValue("keys/app.quit", 42)

    keymap.load(settings)  # type: ignore[arg-type]

    assert keymap.effective_keys(QUIT) == ()


# endregion

# region find_conflicts tests


def test_an_equal_key_in_overlapping_scopes_conflicts(keymap: Keymap) -> None:
    """Two commands on one key, armed by the same focus, are reported.

    **Test steps:**

    * declare a window command and a widget command on F5
    * verify one conflict, on F5
    """
    first = widget_command("first", "F5", None, CommandScope.WINDOW)
    second = widget_command("second", "F5", "list", CommandScope.WIDGET)

    conflicts = find_conflicts([first, second], keymap)

    assert [(conflict.first_id, conflict.second_id) for conflict in conflicts] == [("first", "second")]
    assert conflicts[0].keys == QKeySequence("F5")


def test_a_chord_prefix_conflicts(keymap: Keymap) -> None:
    """A key that is the first chord of another command's key collides with it.

    **Test steps:**

    * declare Ctrl+K and Ctrl+K, Q in one scope
    * verify they conflict, both ways round
    """
    short = widget_command("short", "Ctrl+K", None, CommandScope.WINDOW)
    chord = widget_command("chord", "Ctrl+K, Q", None, CommandScope.WINDOW)

    assert len(find_conflicts([short, chord], keymap)) == 1
    assert len(find_conflicts([chord, short], keymap)) == 1


def test_different_focus_groups_never_conflict(keymap: Keymap) -> None:
    """Widget- or subtree-armed commands in different focus groups never share a focus.

    **Test steps:**

    * declare F5 twice as widget commands in two groups, and twice as subtree commands in two groups
    * verify no conflict
    """
    commands = [
        widget_command("list.a", "F5", "list_a", CommandScope.WIDGET),
        widget_command("list.b", "F5", "list_b", CommandScope.WIDGET),
    ]
    subtrees = [
        widget_command("files.refresh", "F5", "files", CommandScope.DOCUMENT_FOCUSED),
        widget_command("images.refresh", "F5", "images", CommandScope.DOCUMENT_FOCUSED),
    ]

    assert not find_conflicts(commands, keymap)
    assert not find_conflicts(subtrees, keymap)


def test_a_focus_group_against_none_conflicts(keymap: Keymap) -> None:
    """A command with no focus group may be armed anywhere, so a group does not shield the other one.

    **Test steps:**

    * declare F5 in a group and F5 with none, both subtree-armed
    * verify they conflict
    """
    grouped = widget_command("grouped", "F5", "files", CommandScope.DOCUMENT_FOCUSED)
    loose = widget_command("loose", "F5", None, CommandScope.DOCUMENT_FOCUSED)

    assert len(find_conflicts([grouped, loose], keymap)) == 1


def test_an_unbound_command_never_conflicts(keymap: Keymap) -> None:
    """An override to no keys takes the command out of every collision.

    **Test steps:**

    * declare two colliding commands
    * unbind one
    * verify no conflict
    """
    first = widget_command("first", "F5", None, CommandScope.WINDOW)
    second = widget_command("second", "F5", None, CommandScope.WINDOW)
    keymap.set_keys(second, [])

    assert not find_conflicts([first, second], keymap)


# endregion
