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
    """A per-document command fired on the focused document from anywhere in the app. Its per-document
    actions carry no keys under it -- one per open document on one app-wide key would be ambiguous -- and a
    single `BindingRole.ROUTER` action carries them instead, passing each press on to the focused
    document's own action."""

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

    @property
    def label(self) -> str:
        """A short user-facing name, for a column that lists each command's scope."""
        return SCOPE_LABELS[self]

    @property
    def hint(self) -> str:
        """Where the keys reach, in a few words a user choosing between scopes can act on."""
        return SCOPE_HINTS[self]


SCOPE_CONTEXTS: Final[dict[CommandScope, Qt.ShortcutContext | None]] = {
    CommandScope.WIDGET: Qt.ShortcutContext.WidgetShortcut,
    CommandScope.DOCUMENT_FOCUSED: Qt.ShortcutContext.WidgetWithChildrenShortcut,
    CommandScope.DOCUMENT_APP_WIDE: None,
    CommandScope.WINDOW: Qt.ShortcutContext.WindowShortcut,
    CommandScope.APP_WIDE: Qt.ShortcutContext.ApplicationShortcut,
}
"""Each scope's shortcut context for a `BindingRole.INSTANCE` action; ``None`` for the one whose keys only a
`BindingRole.ROUTER` action carries."""

SCOPE_LABELS: Final[dict[CommandScope, str]] = {
    CommandScope.WIDGET: "Focused widget",
    CommandScope.DOCUMENT_FOCUSED: "Focused document",
    CommandScope.DOCUMENT_APP_WIDE: "Focused document, app-wide",
    CommandScope.WINDOW: "Main window",
    CommandScope.APP_WIDE: "Anywhere in the app",
}
"""Each scope's :attr:`CommandScope.label`."""

SCOPE_HINTS: Final[dict[CommandScope, str]] = {
    CommandScope.WIDGET: "only while its list or editor has focus",
    CommandScope.DOCUMENT_FOCUSED: "only while focus is inside the document",
    CommandScope.DOCUMENT_APP_WIDE: "on the focused document, from anywhere in the app",
    CommandScope.WINDOW: "while the main window is active, not while a floating dock has focus",
    CommandScope.APP_WIDE: "from anywhere in the app, floating docks included",
}
"""Each scope's :attr:`CommandScope.hint` -- the `WINDOW` one says it goes deaf under a torn-out dock, the
one thing about it a user cannot guess from its name."""


class BindingRole(Enum):
    """What a bound action does with its command's keys."""

    INSTANCE = auto()
    """The action carries the keys, in the command's scope, and names them in its tooltip."""

    LABEL = auto()
    """The action only names the keys in its tooltip -- a toolbar companion of an action that carries
    them. Two actions carrying one key would be ambiguous; this one stays clickable and still says it."""

    ROUTER = auto()
    """The one action that carries the keys app-wide (`Qt.ShortcutContext.ApplicationShortcut`) while the
    command's scope is `CommandScope.DOCUMENT_APP_WIDE`, and none under any other -- the inverse of the
    command's instances, so exactly one side carries the keys whichever scope is in force. What it does
    when triggered is its owner's: pass the press on to the focused document's own action."""

    def context(self, scope: CommandScope) -> Qt.ShortcutContext | None:
        """The shortcut context an action in this role gets under ``scope``.

        :param scope: the command's effective scope.
        :returns: the context, or ``None`` where the action carries no keys.
        """
        if self is BindingRole.INSTANCE:
            return scope.context
        if self is BindingRole.ROUTER and scope is CommandScope.DOCUMENT_APP_WIDE:
            return Qt.ShortcutContext.ApplicationShortcut
        return None


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
