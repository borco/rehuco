"""Tests for `CommandRegistry`: binding live actions to commands and re-applying a keymap to them."""

from typing import Any

from borco_pyside.shortcuts import BindingRole, Command, CommandRegistry, CommandScope, Keymap, bind_or_apply
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QAction, QKeySequence
from pytest import fixture, raises
from pytestqt.qtbot import QtBot

# region Sample classes

SAVE: Command = Command("document.save", "Save", "Save the document", ("Ctrl+S",), (CommandScope.DOCUMENT_FOCUSED,))
QUIT: Command = Command("app.quit", "Quit", "Quit the app", ("Ctrl+Q",), (CommandScope.WINDOW, CommandScope.APP_WIDE))
ROUTED: Command = Command(
    "document.routed", "Routed", "Fired on the focused document", ("F7",), (CommandScope.DOCUMENT_APP_WIDE,)
)


@fixture
def registry(qapp: Any) -> CommandRegistry:
    """A registry holding :data:`SAVE`, :data:`QUIT` and :data:`ROUTED`, installed nowhere.

    :param qapp: pytest-qt's application fixture -- actions and key sequences need one.
    :returns: the registry.
    """
    del qapp
    registry = CommandRegistry()
    registry.register(SAVE, QUIT, ROUTED)
    return registry


def native(text: str) -> str:
    """A portable key spelling as this platform writes it in a tooltip.

    :param text: the portable spelling.
    :returns: the native one.
    """
    return QKeySequence(text).toString(QKeySequence.SequenceFormat.NativeText)


# endregion

# region CommandRegistry tests


def test_bind_sets_keys_context_and_the_tooltip_suffix(registry: CommandRegistry) -> None:
    """One call gives an action everything its command says about keys.

    **Test steps:**

    * bind an action with a tooltip
    * verify its keys, its context, and the tooltip naming the key
    """
    action = QAction("Save")

    registry.bind(action, SAVE.id, tooltip="Save the document")

    assert action.shortcuts() == [QKeySequence("Ctrl+S")]
    assert action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert action.toolTip() == f"Save the document ({native('Ctrl+S')})"
    assert registry.bound_actions(SAVE.id) == [action]


def test_binding_an_unknown_command_raises(registry: CommandRegistry) -> None:
    """Only a registered command can be bound to.

    **Test steps:**

    * bind to an id the registry does not hold
    * verify it raises
    """
    with raises(KeyError):
        registry.bind(QAction("Nothing"), "no.such.command")


def test_registering_an_id_twice_raises(registry: CommandRegistry) -> None:
    """Ids are unique across the catalog.

    **Test steps:**

    * register a command already held
    * verify it raises
    """
    with raises(ValueError):
        registry.register(SAVE)


def test_set_keymap_reaches_every_live_action(registry: CommandRegistry, qtbot: QtBot) -> None:
    """A new keymap re-keys every bound action, then says so.

    **Test steps:**

    * bind two actions to one command
    * set a keymap overriding its keys
    * verify both carry the new key and name it, and ``keymap_changed`` fired
    """
    first, second = QAction("Save"), QAction("Save")
    registry.bind(first, SAVE.id, tooltip="Save")
    registry.bind(second, SAVE.id, tooltip="Save")
    keymap = Keymap()
    keymap.set_keys(SAVE, [QKeySequence("F2")])

    with qtbot.waitSignal(registry.keymap_changed, timeout=1000):
        registry.set_keymap(keymap)

    for action in (first, second):
        assert action.shortcuts() == [QKeySequence("F2")]
        assert action.toolTip() == f"Save ({native('F2')})"


def test_an_unbound_override_clears_the_keys_and_the_suffix(registry: CommandRegistry) -> None:
    """ "No keys" leaves the action keyless and its tooltip bare.

    **Test steps:**

    * bind an action
    * set a keymap unbinding its command
    * verify no keys and the plain tooltip
    """
    action = QAction("Save")
    registry.bind(action, SAVE.id, tooltip="Save")
    keymap = Keymap()
    keymap.set_keys(SAVE, [])

    registry.set_keymap(keymap)

    assert action.shortcuts() == []
    assert action.toolTip() == "Save"


def test_a_scope_override_changes_the_context(registry: CommandRegistry) -> None:
    """The scope travels with the keymap too.

    **Test steps:**

    * bind a window command, then override its scope to app-wide
    * verify the context follows
    """
    action = QAction("Quit")
    registry.bind(action, QUIT.id)
    keymap = Keymap()
    keymap.set_scope(QUIT, CommandScope.APP_WIDE)

    registry.set_keymap(keymap)

    assert action.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut
    assert registry.scope(QUIT.id) is CommandScope.APP_WIDE


def test_a_deleted_action_is_forgotten(registry: CommandRegistry) -> None:
    """A per-document action going with its document needs no unbinding.

    **Test steps:**

    * bind two actions, ``deleteLater`` one and let it go
    * set a keymap
    * verify only the survivor is listed, and re-applying raised nothing
    """
    kept, dropped = QAction("Save"), QAction("Save")
    registry.bind(kept, SAVE.id)
    registry.bind(dropped, SAVE.id)

    dropped.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    registry.set_keymap(Keymap())

    assert registry.bound_actions(SAVE.id) == [kept]


def test_rebinding_repoints_the_action_instead_of_binding_it_twice(registry: CommandRegistry) -> None:
    """A widget re-keying a generic action moves it to its own command; the old one lets go of it.

    **Test steps:**

    * bind an action to one command, then to another, keeping the first tooltip
    * verify it carries the second command's key and is listed under that one only
    """
    action = QAction("Save")
    registry.bind(action, SAVE.id, tooltip="Do it")

    registry.bind(action, QUIT.id)

    assert action.shortcuts() == [QKeySequence("Ctrl+Q")]
    assert action.toolTip() == f"Do it ({native('Ctrl+Q')})"
    assert not registry.bound_actions(SAVE.id)
    assert registry.bound_actions(QUIT.id) == [action]


def test_a_label_binding_names_the_keys_without_carrying_them(registry: CommandRegistry) -> None:
    """A toolbar companion says the key; only the action carrying it fires, so neither is ambiguous.

    **Test steps:**

    * bind an action as a label
    * verify it has no keys but its tooltip names them
    """
    action = QAction("Quit")

    registry.bind(action, QUIT.id, tooltip="Quit", role=BindingRole.LABEL)

    assert action.shortcuts() == []
    assert action.toolTip() == f"Quit ({native('Ctrl+Q')})"


def test_under_the_routed_scope_the_router_carries_the_keys_and_the_instance_none(registry: CommandRegistry) -> None:
    """Only the router holds an app-wide document command's keys, so one key never sits on two actions.

    **Test steps:**

    * bind an instance and a router to a command scoped to the routed scope
    * verify the router carries the key app-wide, the instance none, and its tooltip still names it
    """
    instance, router = QAction("Routed"), QAction("Routed")

    registry.bind(instance, ROUTED.id, tooltip="Routed")
    registry.bind(router, ROUTED.id, role=BindingRole.ROUTER)

    assert router.shortcuts() == [QKeySequence("F7")]
    assert router.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut
    assert instance.shortcuts() == []
    assert instance.toolTip() == f"Routed ({native('F7')})"


def test_a_scope_flip_moves_the_keys_between_the_instances_and_the_router(registry: CommandRegistry) -> None:
    """Switching a document command between its two scopes hands its keys from one side to the other.

    **Test steps:**

    * bind two instances and a router to a document command
    * verify the instances carry the key in their own subtree, the router none
    * route it app-wide, verify the router alone carries it
    * set it back, verify the instances carry it again and the router none
    """
    routable = Command(
        "document.routable",
        "Routable",
        "Saved wherever focus is",
        ("Ctrl+S",),
        (CommandScope.DOCUMENT_FOCUSED, CommandScope.DOCUMENT_APP_WIDE),
    )
    registry.register(routable)
    first, second, router = QAction("Save"), QAction("Save"), QAction("Save")
    registry.bind(first, routable.id)
    registry.bind(second, routable.id)
    registry.bind(router, routable.id, role=BindingRole.ROUTER)

    assert first.shortcuts() == second.shortcuts() == [QKeySequence("Ctrl+S")]
    assert first.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert router.shortcuts() == []

    keymap = Keymap()
    keymap.set_scope(routable, CommandScope.DOCUMENT_APP_WIDE)
    registry.set_keymap(keymap)

    assert first.shortcuts() == second.shortcuts() == []
    assert router.shortcuts() == [QKeySequence("Ctrl+S")]
    assert router.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut

    registry.set_keymap(Keymap())

    assert first.shortcuts() == second.shortcuts() == [QKeySequence("Ctrl+S")]
    assert router.shortcuts() == []


def test_bound_actions_filters_by_role(registry: CommandRegistry) -> None:
    """A router asks for the instances it passes a press on to, without itself or a toolbar label.

    **Test steps:**

    * bind an instance, a label and a router to one command
    * verify each role lists its own action, and no role lists all three
    """
    instance, label, router = QAction("Routed"), QAction("Routed"), QAction("Routed")
    registry.bind(instance, ROUTED.id)
    registry.bind(label, ROUTED.id, role=BindingRole.LABEL)
    registry.bind(router, ROUTED.id, role=BindingRole.ROUTER)

    assert registry.bound_actions(ROUTED.id, BindingRole.INSTANCE) == [instance]
    assert registry.bound_actions(ROUTED.id, BindingRole.LABEL) == [label]
    assert registry.bound_actions(ROUTED.id, BindingRole.ROUTER) == [router]
    assert registry.bound_actions(ROUTED.id) == [instance, label, router]


def test_install_makes_the_registry_the_one_generic_widgets_find(registry: CommandRegistry) -> None:
    """``installed`` answers the registry ``install``-ed, until ``uninstall``.

    **Test steps:**

    * verify none is installed, install, verify it is found, uninstall
    """
    assert CommandRegistry.installed() is None

    registry.install()
    assert CommandRegistry.installed() is registry

    CommandRegistry.uninstall()
    assert CommandRegistry.installed() is None


def test_bind_or_apply_falls_back_to_the_defaults_with_no_registry(qapp: Any) -> None:
    """A generic widget in a host with no registry still gets its command's keys.

    **Test steps:**

    * apply a command with nothing installed
    * verify its default keys, context and tooltip
    """
    del qapp
    action = QAction("Save")

    bind_or_apply(action, SAVE, tooltip="Save")

    assert action.shortcuts() == [QKeySequence("Ctrl+S")]
    assert action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert action.toolTip() == f"Save ({native('Ctrl+S')})"


def test_bind_or_apply_binds_through_the_installed_registry(registry: CommandRegistry) -> None:
    """With a registry installed that knows the command, the action follows its keymap.

    **Test steps:**

    * install a registry, apply a command
    * set an overriding keymap
    * verify the action follows it
    """
    registry.install()
    action = QAction("Save")
    bind_or_apply(action, SAVE)
    keymap = Keymap()
    keymap.set_keys(SAVE, [QKeySequence("F2")])

    registry.set_keymap(keymap)

    assert action.shortcuts() == [QKeySequence("F2")]


# endregion


def test_every_scope_has_a_label_and_a_hint() -> None:
    """The settings page can name any scope, and the window scope warns about floating docks.

    **Test steps:**

    * read the label and hint of every scope
    * verify each is non-empty, the labels are distinct, and the window hint names the floating dock
    """
    assert all(scope.label and scope.hint for scope in CommandScope)
    assert len({scope.label for scope in CommandScope}) == len(CommandScope)
    assert "floating dock" in CommandScope.WINDOW.hint
