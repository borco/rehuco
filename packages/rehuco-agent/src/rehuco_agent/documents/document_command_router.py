"""One app-wide action per routable document command, passing each press on to the focused document (#345)."""

from typing import Final

from borco_pyside.shortcuts import BindingRole, CommandRegistry, CommandScope
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QWidget

from .documents_dock import DocumentsDock


class DocumentCommandRouter(QObject):
    """Carries the keys of every per-document command set to `CommandScope.DOCUMENT_APP_WIDE`, and fires the
    focused document's own action when one is pressed -- so ``Ctrl+S`` saves the focused document while focus
    sits in the Log dock or a floating one.

    **One carrier at a time.** Every open document has its own action for such a command, and two enabled
    actions on one key fire neither (#41). So for each routable command this adds one action to ``parent``,
    bound with `BindingRole.ROUTER`: under the app-wide scope it carries the keys
    (`Qt.ShortcutContext.ApplicationShortcut`) and the documents' actions carry none, under any other scope
    the other way round. The registry re-applies both sides on every keymap change, so flipping the scope on
    the Shortcuts page moves the keys and nothing here has to follow.

    **Which action fires** is decided at the press: the focused document's own action for the command --
    one whose Qt parent lies under that document's widget -- provided it is enabled and visible, so a
    pending placeholder's disabled Save stays as inert as its toolbar button. With no document focused the
    router actions are disabled, and the key goes to whatever has focus as though unbound.

    The actions are added to ``parent`` without being shown in any menu: an action set invisible would stop
    answering its keys too.

    :param documents_dock: the open documents, and which of them is focused.
    :param registry: the app's registry -- its catalog decides which commands are routed.
    :param parent: the window the router's actions are added to, and this router's own parent.
    """

    def __init__(self, documents_dock: DocumentsDock, registry: CommandRegistry, parent: QWidget) -> None:
        super().__init__(parent)
        self.__documents_dock: Final = documents_dock
        self.__registry: Final = registry
        self.__actions: Final[dict[str, QAction]] = {}
        for command in registry.commands():
            if CommandScope.DOCUMENT_APP_WIDE not in command.scopes:
                continue
            action = QAction(command.name, parent)
            registry.bind(action, command.id, tooltip=command.description, role=BindingRole.ROUTER)
            action.triggered.connect(lambda _=False, command_id=command.id: self.route(command_id))
            parent.addAction(action)
            self.__actions[command.id] = action  # pylint: disable=unsupported-assignment-operation
        documents_dock.document_focus_changed.connect(self.__on_document_focus_changed)
        self.__on_document_focus_changed(documents_dock.focused_document_widget())

    def action(self, command_id: str) -> QAction:
        """The router's own action for a routed command.

        :param command_id: a command allowing `CommandScope.DOCUMENT_APP_WIDE`.
        :returns: the action carrying its keys while it is routed.
        :raises KeyError: if the command is not routed.
        """
        return self.__actions[command_id]

    def route(self, command_id: str) -> bool:
        """Fire the focused document's own action for a command.

        :param command_id: the command pressed.
        :returns: whether an action fired -- not when no document is focused, or its action is disabled or
            hidden.
        """
        document = self.__documents_dock.focused_document_widget()
        if document is None:
            return False
        for action in self.__registry.bound_actions(command_id, BindingRole.INSTANCE):
            if action.isEnabled() and action.isVisible() and self.__lies_under(action, document):
                action.trigger()
                return True
        return False

    def __on_document_focus_changed(self, document: QWidget | None) -> None:
        """Arm the router actions only while a document is focused, as ``File`` > ``Close`` is.

        :param document: the newly-focused document's widget, or ``None``.
        """
        for action in self.__actions.values():
            action.setEnabled(document is not None)

    @staticmethod
    def __lies_under(action: QAction, document: QWidget) -> bool:
        """Whether ``action`` belongs to ``document``: its parent is the document's widget or lies below it,
        however many dock managers down -- the Files view's Refresh sits under the document's own one.

        A sub-dock the user closed is no document's: QtAds takes a closed dock out of the widget tree, and
        its actions answer nothing until it is opened again.

        :param action: an instance action of a routed command.
        :param document: the focused document's widget.
        :returns: whether the action is that document's.
        """
        parent = action.parent()
        return isinstance(parent, QWidget) and (parent is document or document.isAncestorOf(parent))
