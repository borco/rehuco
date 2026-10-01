"""A user-facing shortcut, declared once: what it is called, what it does, and where its keys reach."""

from dataclasses import dataclass
from enum import Enum, StrEnum, auto
from typing import Final

from PySide6.QtCore import QKeyCombination, Qt
from PySide6.QtGui import QKeySequence

type KeySpec = QKeySequence.StandardKey | QKeyCombination | Qt.Key | str
"""A default key as declared: plain key data, never a `QKeySequence` -- a catalog is built at import time,
before any `QApplication` exists. A string is the portable spelling (``"Ctrl+Shift+`"``)."""


class CommandScope(StrEnum):
    """Where a command's keys reach -- what a binding turns into a `Qt.ShortcutContext`.

    The scopes exist to keep **one key on one enabled action per scope**: two enabled actions on the same
    key in the same scope fire *neither* (Qt calls the shortcut ambiguous), which is the trap #41 fell
    into with two dirty documents' Save actions under one window. The stored value is the member's name
    in lower case, so a keymap written by one version reads back in the next.
    """

    WIDGET = auto()
    """Armed by focus on the one widget the action was added to (`Qt.ShortcutContext.WidgetShortcut`) --
    an in-place editor open on a list keeps its own keys. Never routable app-wide."""

    DOCUMENT_FOCUSED = auto()
    """Armed by focus anywhere in the subtree of the widget the action was added to
    (`Qt.ShortcutContext.WidgetWithChildrenShortcut`). This is how a per-document action stays
    unambiguous: a document is a `QMainWindow` embedded in a dock, not a real top-level window, so a
    `WindowShortcut` would resolve to the one window every open document shares, and two documents' actions
    on one key would cancel out (#41). Scoped to its own subtree, only the document holding focus fires."""

    DOCUMENT_APP_WIDE = auto()
    """A per-document command fired on the focused document from anywhere in the app. Declared for the
    keymap and the settings page; a binding carries no keys for it until the app-wide router exists."""

    WINDOW = auto()
    """Armed while the action's window is active (`Qt.ShortcutContext.WindowShortcut`). Deaf while a
    torn-out dock has focus: a floating dock is a top-level window of its own."""

    APP_WIDE = auto()
    """Armed whenever the application is active (`Qt.ShortcutContext.ApplicationShortcut`) -- including
    from a torn-out dock. Only for a command with exactly one action carrying its keys."""

    @property
    def context(self) -> Qt.ShortcutContext | None:
        """The shortcut context a binding gives its action, or ``None`` where it carries no keys."""
        return SCOPE_CONTEXTS[self]


SCOPE_CONTEXTS: Final[dict[CommandScope, Qt.ShortcutContext | None]] = {
    CommandScope.WIDGET: Qt.ShortcutContext.WidgetShortcut,
    CommandScope.DOCUMENT_FOCUSED: Qt.ShortcutContext.WidgetWithChildrenShortcut,
    CommandScope.DOCUMENT_APP_WIDE: None,
    CommandScope.WINDOW: Qt.ShortcutContext.WindowShortcut,
    CommandScope.APP_WIDE: Qt.ShortcutContext.ApplicationShortcut,
}
"""Each scope's shortcut context; ``None`` for the one no binding carries keys for yet."""


class BindingRole(Enum):
    """What a bound action does with its command's keys."""

    INSTANCE = auto()
    """The action carries the keys, in the command's scope, and names them in its tooltip."""

    LABEL = auto()
    """The action only names the keys in its tooltip -- a toolbar companion of an action that carries
    them. Two actions carrying one key would be ambiguous; this one stays clickable and still says it."""


@dataclass(frozen=True)
class Command:
    """One user-facing shortcut: a stable id, the words a settings page shows, and its defaults.

    The name and description are declared here, never read off an action: a per-document command has to
    be listed with no document open.

    :ivar id: stable, dotted, like ``document.save`` -- the keymap's key, so it never changes once
        shipped, and never holds a ``/`` (a settings group separator).
    :ivar name: the short label a settings page lists.
    :ivar description: one sentence on what it does.
    :ivar default_keys: the keys it has with no override, as :data:`KeySpec`; a
        `QKeySequence.StandardKey` stays one, so a platform's own binding is used rather than stored.
    :ivar scopes: the scopes a user may choose from; the first is the default.
    :ivar focus_group: the family of widgets the command is armed on, for commands whose keys only ever
        reach one kind of widget: two commands in *different* focus groups never share a focus, so they
        may share a key.
    """

    id: str
    name: str
    description: str
    default_keys: tuple[KeySpec, ...]
    scopes: tuple[CommandScope, ...]
    focus_group: str | None = None

    def __post_init__(self) -> None:
        if not self.id or "/" in self.id:
            raise ValueError(f"a command id must be non-empty and free of '/': {self.id!r}")
        if not self.scopes:
            raise ValueError(f"command {self.id!r} allows no scope")

    @property
    def default_scope(self) -> CommandScope:
        """The scope the command has with no override."""
        return self.scopes[0]

    def default_key_sequences(self) -> tuple[QKeySequence, ...]:
        """The default keys as sequences, a standard key expanded to this platform's bindings.

        :returns: every default sequence, in declaration order, empties dropped.
        """
        sequences: list[QKeySequence] = []
        for key in self.default_keys:
            if isinstance(key, QKeySequence.StandardKey):
                sequences.extend(QKeySequence.keyBindings(key))
            elif isinstance(key, str):
                sequences.append(QKeySequence.fromString(key, QKeySequence.SequenceFormat.PortableText))
            else:
                sequences.append(QKeySequence(key))
        return tuple(sequence for sequence in sequences if not sequence.isEmpty())
