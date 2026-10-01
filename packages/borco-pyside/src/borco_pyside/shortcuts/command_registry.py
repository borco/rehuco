"""The commands an app declares, and every live action bound to one of them."""

from collections.abc import Iterable
from typing import ClassVar, Final

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence

from .command import BindingRole, Command, CommandScope
from .keymap import Keymap, keys_text


def apply_keys(
    action: QAction,
    keys: Iterable[QKeySequence],
    scope: CommandScope,
    tooltip: str,
    role: BindingRole = BindingRole.INSTANCE,
) -> None:
    """Give ``action`` its keys, their context and a tooltip naming them -- all three at once, so none can
    drift from the others.

    :param action: the action to set up.
    :param keys: the keys the command has; none leaves the action unbound and the tooltip bare.
    :param scope: the scope they reach; one with no context (`CommandScope.DOCUMENT_APP_WIDE`) leaves
        the action carrying no keys, though its tooltip still names them.
    :param tooltip: what the action does, in words -- the keys are appended to it, since an icon-only
        button is otherwise the only place a user could discover them.
    :param role: `BindingRole.LABEL` names the keys without carrying them.
    """
    keys = tuple(keys)
    context = scope.context if role is BindingRole.INSTANCE else None
    action.setShortcuts(list(keys) if context is not None else [])
    if context is not None:
        action.setShortcutContext(context)
    action.setToolTip(f"{tooltip} ({keys_text(keys)})" if keys else tooltip)


class CommandBinding(QObject):
    """Ties one action to one command, as a child of the action -- so it goes when the action goes, and
    the registry forgets it then without its owner keeping any books.

    :param action: the bound action, and this binding's parent.
    :param command_id: the command it is bound to.
    :param tooltip: the action's tooltip without the keys, which every re-apply appends afresh.
    :param role: what the action does with the keys.
    """

    def __init__(self, action: QAction, command_id: str, tooltip: str, role: BindingRole) -> None:
        super().__init__(action)
        self.__action: Final = action
        self.command_id = command_id
        self.tooltip = tooltip
        self.role = role

    @property
    def action(self) -> QAction:
        """The bound action."""
        return self.__action


class CommandRegistry(QObject):
    """The app's catalog of :class:`Command`\\ s, its :class:`Keymap`, and every live action bound to a
    command -- the one place a changed keymap is re-applied from.

    An action is bound with :meth:`bind`, which sets its keys, their context and its tooltip at once and
    tracks it through a :class:`CommandBinding` child; :meth:`set_keymap` then reaches every action still
    alive. Per-document actions -- one per open document -- need no bookkeeping on the owner's side: a
    destroyed action takes its binding with it, and the registry drops it on the binding's ``destroyed``.

    A generic widget that cannot know the app binds through the one registry :meth:`install`\\ ed, if any
    (:func:`bind_or_apply`), and falls back to its command's defaults without one.

    :param parent: optional Qt parent.
    """

    keymap_changed = Signal()
    """Emitted after :meth:`set_keymap` has re-applied the keymap to every live binding."""

    __installed: ClassVar[CommandRegistry | None] = None

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__commands: Final[dict[str, Command]] = {}
        self.__keymap = Keymap()
        self.__bindings: Final[dict[int, CommandBinding]] = {}

    # region the catalog

    def register(self, *commands: Command) -> None:
        """Add ``commands`` to the catalog.

        :param commands: the commands to add.
        :raises ValueError: if an id is already registered.
        """
        for command in commands:
            if command.id in self.__commands:
                raise ValueError(f"command {command.id!r} is already registered")
            self.__commands[command.id] = command  # pylint: disable=unsupported-assignment-operation

    def has(self, command_id: str) -> bool:
        """Whether ``command_id`` is in the catalog.

        :param command_id: the id to look up.
        :returns: whether it is registered.
        """
        return command_id in self.__commands

    def command(self, command_id: str) -> Command:
        """The command registered under ``command_id``.

        :param command_id: the id to look up.
        :returns: the command.
        :raises KeyError: if it is not registered.
        """
        return self.__commands[command_id]

    def commands(self) -> tuple[Command, ...]:
        """The whole catalog, in registration order."""
        return tuple(self.__commands.values())

    # endregion

    # region the keymap

    @property
    def keymap(self) -> Keymap:
        """A copy of the keymap in force -- change it and hand it to :meth:`set_keymap`."""
        return self.__keymap.copy()

    def set_keymap(self, keymap: Keymap) -> None:
        """Put ``keymap`` in force and re-apply it to every live binding.

        :param keymap: the overrides to apply; copied, so later changes to it do nothing until set again.
        """
        self.__keymap = keymap.copy()
        for binding in list(self.__bindings.values()):
            self.__apply(binding)
        self.keymap_changed.emit()

    def keys(self, command_id: str) -> tuple[QKeySequence, ...]:
        """The keys a command has under the keymap in force.

        :param command_id: a registered command.
        :returns: its keys, possibly none.
        """
        return self.__keymap.effective_keys(self.command(command_id))

    def scope(self, command_id: str) -> CommandScope:
        """The scope a command has under the keymap in force.

        :param command_id: a registered command.
        :returns: its scope.
        """
        return self.__keymap.effective_scope(self.command(command_id))

    # endregion

    # region bindings

    def bind(
        self,
        action: QAction,
        command_id: str,
        *,
        tooltip: str | None = None,
        role: BindingRole = BindingRole.INSTANCE,
    ) -> CommandBinding:
        """Bind ``action`` to a command: give it the command's keys, their context and a tooltip naming
        them, and keep doing so on every :meth:`set_keymap` for as long as the action lives.

        An action already bound -- by this registry or another -- is re-pointed rather than bound twice,
        which is how a widget re-keys an action a generic class bound to a generic command.

        :param action: the action to bind.
        :param command_id: a registered command.
        :param tooltip: the tooltip without the keys; defaults to the one a previous binding recorded,
            else to the action's own tooltip as it is now (Qt falls back to the action's text).
        :param role: what the action does with the keys.
        :returns: the binding, a child of ``action``.
        :raises KeyError: if ``command_id`` is not registered.
        """
        self.command(command_id)
        binding = action.findChild(CommandBinding, options=Qt.FindChildOption.FindDirectChildrenOnly)
        if binding is None:
            binding = CommandBinding(action, command_id, tooltip if tooltip is not None else action.toolTip(), role)
        else:
            binding.command_id = command_id
            binding.role = role
            if tooltip is not None:
                binding.tooltip = tooltip
        key = id(binding)
        if key not in self.__bindings:
            self.__bindings[key] = binding  # pylint: disable=unsupported-assignment-operation
            bindings = self.__bindings
            # the dict, not self: the registry may be gone by the time a late action is destroyed
            binding.destroyed.connect(lambda _=None, key=key: bindings.pop(key, None))
        self.__apply(binding)
        return binding

    def bound_actions(self, command_id: str) -> list[QAction]:
        """Every live action bound to a command.

        :param command_id: the command to look up.
        :returns: its actions, in binding order.
        """
        return [binding.action for binding in self.__bindings.values() if binding.command_id == command_id]

    def __apply(self, binding: CommandBinding) -> None:
        """Re-apply the keymap in force to one binding's action.

        :param binding: the binding to refresh.
        """
        command = self.command(binding.command_id)
        apply_keys(
            binding.action,
            self.__keymap.effective_keys(command),
            self.__keymap.effective_scope(command),
            binding.tooltip,
            binding.role,
        )

    # endregion

    # region the installed registry

    def install(self) -> None:
        """Make this the registry generic widgets bind through (:meth:`installed`)."""
        CommandRegistry.__installed = self

    @classmethod
    def installed(cls) -> CommandRegistry | None:
        """The registry :meth:`install`\\ ed, or ``None`` in a host that installed none."""
        return CommandRegistry.__installed

    @classmethod
    def uninstall(cls) -> None:
        """Forget the installed registry -- for a test leaving none behind."""
        CommandRegistry.__installed = None

    # endregion


def bind_or_apply(
    action: QAction,
    command: Command,
    *,
    tooltip: str | None = None,
    role: BindingRole = BindingRole.INSTANCE,
) -> None:
    """Bind ``action`` through the installed registry when it knows ``command``, else apply ``command``'s
    defaults to it directly -- what a generic widget does, not knowing whether its host keeps a keymap.

    :param action: the action to set up.
    :param command: the command it fires.
    :param tooltip: the tooltip without the keys; defaults to the action's own.
    :param role: what the action does with the keys.
    """
    registry = CommandRegistry.installed()
    if registry is not None and registry.has(command.id):
        registry.bind(action, command.id, tooltip=tooltip, role=role)
        return
    apply_keys(
        action,
        command.default_key_sequences(),
        command.default_scope,
        tooltip if tooltip is not None else action.toolTip(),
        role,
    )
