"""The user's shortcut overrides, and the conflicts they leave between commands."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations
from typing import Final

from PySide6.QtCore import QSettings
from PySide6.QtGui import QKeySequence

from .command import Command, CommandScope

KEYS_GROUP: Final = "keys"
SCOPES_GROUP: Final = "scope"
"""The two sub-groups a keymap is stored under, inside whatever group its owner opened: ``keys/<id>`` and
``scope/<id>``, one entry per overridden command."""

UNBOUND: Final = "<unbound>"
"""What a command overridden to **no** keys is stored as. An empty string would read back the same as an
entry that was never written, i.e. as "no override" -- the command's defaults would quietly return."""

PORTABLE: Final = QKeySequence.SequenceFormat.PortableText
NATIVE: Final = QKeySequence.SequenceFormat.NativeText


def keys_text(keys: Iterable[QKeySequence], native: bool = True) -> str:
    """Spell ``keys`` as one string -- ``"Ctrl+S, F5"`` -- the way a tooltip or a comparison wants them.

    :param keys: the sequences to spell.
    :param native: the platform's own spelling (``⌘S`` on macOS) when true, the portable one otherwise.
    :returns: the sequences joined, or ``""`` for none.
    """
    return QKeySequence.listToString(list(keys), NATIVE if native else PORTABLE)


def same_keys(first: Iterable[QKeySequence], second: Iterable[QKeySequence]) -> bool:
    """Whether two key lists are the same, in order -- compared by portable spelling, which is what is
    stored, so a round trip through settings never reads as a change.

    :param first: one key list.
    :param second: the other.
    :returns: whether they spell alike.
    """
    return keys_text(first, native=False) == keys_text(second, native=False)


@dataclass
class Keymap:
    """The commands whose keys or scope the user changed -- **overrides only**.

    A command absent from :attr:`keys` has its default keys, and one absent from :attr:`scopes` its default
    scope; setting either back to the default drops the entry, so a later change of a default reaches every
    user who never touched it. Ids are kept as plain strings, so an override for a command this build does
    not know (one renamed or removed, or added by a newer version) is kept and written back untouched.

    :ivar keys: the overridden keys by command id; an empty tuple is an explicit "no keys".
    :ivar scopes: the overridden scope by command id.
    """

    keys: dict[str, tuple[QKeySequence, ...]] = field(default_factory=dict)
    scopes: dict[str, CommandScope] = field(default_factory=dict)

    def effective_keys(self, command: Command) -> tuple[QKeySequence, ...]:
        """The keys ``command`` has: its override, else its defaults.

        :param command: the command to look up.
        :returns: its keys, possibly none.
        """
        override = self.keys.get(command.id)
        return override if override is not None else command.default_key_sequences()

    def effective_scope(self, command: Command) -> CommandScope:
        """The scope ``command`` has: its override when the command allows it, else its default.

        :param command: the command to look up.
        :returns: its scope.
        """
        scope = self.scopes.get(command.id)
        return scope if scope is not None and scope in command.scopes else command.default_scope

    def set_keys(self, command: Command, keys: Iterable[QKeySequence]) -> None:
        """Override ``command``'s keys, or drop the override when ``keys`` are its defaults.

        :param command: the command to change.
        :param keys: its new keys; none at all is an explicit "no keys".
        """
        keys = tuple(keys)
        if same_keys(keys, command.default_key_sequences()):
            self.keys.pop(command.id, None)
        else:
            self.keys[command.id] = keys  # pylint: disable=unsupported-assignment-operation

    def set_scope(self, command: Command, scope: CommandScope) -> None:
        """Override ``command``'s scope, or drop the override when ``scope`` is its default.

        :param command: the command to change.
        :param scope: its new scope, one of ``command.scopes``.
        :raises ValueError: if ``command`` does not allow ``scope``.
        """
        if scope not in command.scopes:
            raise ValueError(f"command {command.id!r} does not allow the scope {scope!r}")
        if scope == command.default_scope:
            self.scopes.pop(command.id, None)
        else:
            self.scopes[command.id] = scope  # pylint: disable=unsupported-assignment-operation

    def reset(self, command_id: str) -> None:
        """Drop every override of one command.

        :param command_id: the command to put back to its defaults.
        """
        self.keys.pop(command_id, None)
        self.scopes.pop(command_id, None)

    def reset_all(self) -> None:
        """Drop every override."""
        self.keys.clear()
        self.scopes.clear()

    def is_default(self, command: Command) -> bool:
        """Whether ``command`` has neither its keys nor its scope overridden.

        :param command: the command to check.
        :returns: whether nothing about it differs from its declaration.
        """
        return command.id not in self.keys and command.id not in self.scopes

    def copy(self) -> Keymap:
        """An independent copy, for an editor to change before applying.

        :returns: a keymap with the same overrides.
        """
        return Keymap(dict(self.keys), dict(self.scopes))

    def load(self, settings: QSettings) -> None:
        """Replace the overrides with those stored under the group ``settings`` has open.

        A scope string this build does not know is dropped; a key list that does not parse is read as
        what Qt makes of it, the same thing the settings page would show, with the empty sequences Qt makes
        of blank text left out -- so a hand-emptied entry reads as "no keys", never as one blank key.

        :param settings: the settings, positioned at the keymap's own group.
        """
        self.reset_all()
        # a false positive on plain dicts, seen only in modules importing PySide6 (the same one the agent's
        # test conftest suppresses for its FakeSettings)
        # pylint: disable=unsupported-assignment-operation
        settings.beginGroup(KEYS_GROUP)
        for command_id in settings.childKeys():
            text = stored_text(settings.value(command_id))
            parsed = () if text == UNBOUND else QKeySequence.listFromString(text, PORTABLE)
            self.keys[command_id] = tuple(sequence for sequence in parsed if not sequence.isEmpty())
        settings.endGroup()
        settings.beginGroup(SCOPES_GROUP)
        for command_id in settings.childKeys():
            text = stored_text(settings.value(command_id))
            if text in {scope.value for scope in CommandScope}:
                self.scopes[command_id] = CommandScope(text)
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Write the overrides under the group ``settings`` has open, replacing what was there -- so an
        override reset since the last save is gone from storage too.

        :param settings: the settings, positioned at the keymap's own group.
        """
        settings.remove(KEYS_GROUP)
        settings.remove(SCOPES_GROUP)
        settings.beginGroup(KEYS_GROUP)
        for command_id, keys in self.keys.items():
            settings.setValue(command_id, keys_text(keys, native=False) if keys else UNBOUND)
        settings.endGroup()
        settings.beginGroup(SCOPES_GROUP)
        for command_id, scope in self.scopes.items():
            settings.setValue(command_id, scope.value)
        settings.endGroup()


def stored_text(value: object) -> str:
    """One stored string, whatever shape the backend handed it back in.

    The ini backend reads an unquoted value holding a comma back as a *list* -- ``Ctrl+,`` is a key -- so a
    list is joined back with the comma it was split on.

    :param value: what ``QSettings.value`` returned.
    :returns: the text, or ``""`` for anything that is not text.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        return ",".join(entry for entry in value if isinstance(entry, str))
    return ""


@dataclass(frozen=True)
class Conflict:
    """Two commands whose keys would collide where both are armed.

    :ivar first_id: the first command, in the order the commands were given.
    :ivar second_id: the second.
    :ivar keys: the first command's key that collides -- equal to, or a chord prefix of, one of the
        second's (or the other way round).
    """

    first_id: str
    second_id: str
    keys: QKeySequence


def keys_collide(first: QKeySequence, second: QKeySequence) -> bool:
    """Whether two sequences collide: equal, or one a chord prefix of the other -- after the shorter one,
    Qt would wait for the longer one's next chord, or fire the shorter one and never reach the longer one.

    :param first: one sequence.
    :param second: the other.
    :returns: whether they collide.
    """
    no_match = QKeySequence.SequenceMatch.NoMatch
    return first.matches(second) != no_match or second.matches(first) != no_match


def scopes_overlap(first: Command, first_scope: CommandScope, second: Command, second_scope: CommandScope) -> bool:
    """Whether two commands can be armed by the same focus.

    Every scope overlaps every other -- a window-wide key reaches into every widget of the window -- except
    two focus-armed commands (`CommandScope.WIDGET` or `CommandScope.DOCUMENT_FOCUSED`) declared in
    *different* focus groups: their keys only ever reach different widgets.

    :param first: one command.
    :param first_scope: its effective scope.
    :param second: the other command.
    :param second_scope: its effective scope.
    :returns: whether one key on both would be ambiguous somewhere.
    """
    focus_scopes = (CommandScope.WIDGET, CommandScope.DOCUMENT_FOCUSED)
    if first_scope in focus_scopes and second_scope in focus_scopes:
        return first.focus_group is None or second.focus_group is None or first.focus_group == second.focus_group
    return True


def find_conflicts(commands: Iterable[Command], keymap: Keymap) -> list[Conflict]:
    """Every pair of ``commands`` whose effective keys collide in overlapping scopes.

    :param commands: the commands to check, e.g. a registry's whole catalog.
    :param keymap: the overrides to check them under.
    :returns: one :class:`Conflict` per colliding pair, at its first colliding key, in command order.
    """
    effective = [(command, keymap.effective_keys(command), keymap.effective_scope(command)) for command in commands]
    conflicts: list[Conflict] = []
    for (first, first_keys, first_scope), (second, second_keys, second_scope) in combinations(effective, 2):
        if not scopes_overlap(first, first_scope, second, second_scope):
            continue
        clash = next((key for key in first_keys for other in second_keys if keys_collide(key, other)), None)
        if clash is not None:
            conflicts.append(Conflict(first.id, second.id, clash))
    return conflicts
