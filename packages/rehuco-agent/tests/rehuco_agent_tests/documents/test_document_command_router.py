"""Tests for DocumentCommandRouter: an app-wide key fired on the focused document's own action (#345)."""

import json
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

import PySide6QtAds as QtAds
from borco_pyside.shortcuts import BindingRole, CommandScope
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QMainWindow, QVBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.commands import REFRESH_FILES, SAVE_DOCUMENT, shared_command_registry
from rehuco_agent.documents import document_widget
from rehuco_agent.documents.document_command_router import DocumentCommandRouter
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.documents.files_view import FilesView

from rehuco_agent_tests.qt_waits import wait_destroyed

FIRST_PATH: Final = Path.cwd() / "fake" / "tutorials" / "sculpting" / "info.rehu"
SECOND_PATH: Final = Path.cwd() / "fake" / "tutorials" / "painting" / "info.rehu"
TUTORIAL: Final = {
    "format_version": 1,
    "type": "Tutorial",
    "sources": [{"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True}],
}

# region Sample classes


class Host(QMainWindow):
    """A window holding a documents area and, beside it, a line edit standing in for the Log dock -- a
    focus target outside every document -- with the router built over the two as `MainWindow` builds it.
    """

    def __init__(self) -> None:
        super().__init__()
        central = QWidget(self)
        layout = QVBoxLayout(central)
        self.documents = DocumentsDock(central)
        self.outside = QLineEdit(central)
        layout.addWidget(self.documents)
        layout.addWidget(self.outside)
        self.setCentralWidget(central)
        self.router = DocumentCommandRouter(self.documents, shared_command_registry(), self)


@fixture
def host(mocker: MockerFixture, qtbot: QtBot) -> Host:
    """A :class:`Host` serving the tutorial fixture for every path it opens, with nothing open yet.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt fixture.
    :returns: the host.
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))
    host = Host()
    qtbot.addWidget(host)
    return host


@fixture
def saved(mocker: MockerFixture) -> MagicMock:
    """Replace the save every document's Save action runs, so a test sees which document it ran for.

    :param mocker: pytest-mock fixture.
    :returns: the stand-in, called ``(widget, model)``.
    """
    return mocker.patch.object(document_widget, "save_or_prompt_retry")


def route_app_wide(command_id: str) -> None:
    """Set a command to the app-wide document scope in the shared registry's keymap.

    :param command_id: the command to route.
    """
    registry = shared_command_registry()
    keymap = registry.keymap
    keymap.set_scope(registry.command(command_id), CommandScope.DOCUMENT_APP_WIDE)
    registry.set_keymap(keymap)


def saved_widgets(saved: MagicMock) -> list[object]:
    """The document widgets a save ran for, in order.

    :param saved: the :func:`saved` stand-in.
    :returns: each call's widget.
    """
    return [call.args[0] for call in saved.call_args_list]


def open_dirty(host: Host, path: Path) -> DocumentWidget:
    """Open a document and edit it, so its Save is enabled -- a clean document's is not.

    :param host: the host to open it in.
    :param path: the path to open.
    :returns: the document's widget, now focused.
    """
    document = host.documents.open_document(path)
    document.model.title = "Changed"
    return document


def files_dock_of(document: DocumentWidget) -> QtAds.CDockWidget:
    """The document's Files dock (private by design -- the widget exposes no dock).

    :param document: the open document.
    :returns: its Files dock.
    """
    return document._DocumentWidget__files_dock  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def shown_files_view_of(document: DocumentWidget) -> FilesView:
    """The document's Files view, its dock shown -- a closed QtAds dock has no Qt parent at all, so its
    actions are no document's until it is opened.

    :param document: the open document.
    :returns: its Files view, two dock managers below the documents area.
    """
    dock = files_dock_of(document)
    dock.toggleView(True)
    view = dock.widget()
    assert isinstance(view, FilesView)
    assert document.isAncestorOf(view)
    return view


# endregion

# region DocumentCommandRouter tests


def test_routed_app_wide_the_router_alone_carries_the_key(host: Host) -> None:
    """With two documents open and Save routed, only the router holds Ctrl+S, app-wide.

    **Test steps:**

    * open two documents, route Save app-wide
    * verify the router's action holds the Save keys app-wide and neither document's action holds any
    """
    first = host.documents.open_document(FIRST_PATH)
    second = host.documents.open_document(SECOND_PATH)

    route_app_wide(SAVE_DOCUMENT.id)

    router_action = host.router.action(SAVE_DOCUMENT.id)
    assert router_action.shortcuts() == list(SAVE_DOCUMENT.default_key_sequences())
    assert router_action.shortcutContext() == Qt.ShortcutContext.ApplicationShortcut
    assert first.save_action.shortcuts() == second.save_action.shortcuts() == []


def test_the_router_saves_the_focused_document_only(host: Host, saved: MagicMock) -> None:
    """A routed Save reaches the focused document, whichever that is, and never the other.

    **Test steps:**

    * open two edited documents (the second is focused), route Save app-wide
    * trigger the router, verify the second saved
    * focus the first, trigger again, verify the first saved
    """
    first = open_dirty(host, FIRST_PATH)
    second = open_dirty(host, SECOND_PATH)
    route_app_wide(SAVE_DOCUMENT.id)

    host.router.action(SAVE_DOCUMENT.id).trigger()
    host.documents.focus_document(first)
    host.router.action(SAVE_DOCUMENT.id).trigger()

    assert saved_widgets(saved) == [second, first]


def test_the_key_pressed_outside_every_document_saves_the_focused_one(
    host: Host, qtbot: QtBot, saved: MagicMock
) -> None:
    """Ctrl+S with focus outside every document -- the Log dock -- saves the focused document.

    **Test steps:**

    * show the host, open two edited documents, route Save app-wide
    * focus the stand-in Log dock, press Save's key there
    * verify the focused (second) document saved, and only it
    """
    host.show()
    qtbot.waitExposed(host)
    host.activateWindow()
    qtbot.waitUntil(lambda: QApplication.activeWindow() is host)
    open_dirty(host, FIRST_PATH)
    second = open_dirty(host, SECOND_PATH)
    route_app_wide(SAVE_DOCUMENT.id)
    host.outside.setFocus()

    qtbot.keySequence(host.outside, SAVE_DOCUMENT.default_key_sequences()[0])

    assert saved_widgets(saved) == [second]


def test_switched_back_each_document_carries_the_key_and_the_router_none(host: Host) -> None:
    """Back on the focused-document scope, the keys return to the documents' own actions.

    **Test steps:**

    * open two documents, route Save app-wide, then reset the keymap
    * verify each document's action holds the key in its own subtree and the router holds none
    """
    first = host.documents.open_document(FIRST_PATH)
    second = host.documents.open_document(SECOND_PATH)
    route_app_wide(SAVE_DOCUMENT.id)
    keymap = shared_command_registry().keymap
    keymap.reset(SAVE_DOCUMENT.id)

    shared_command_registry().set_keymap(keymap)

    keys = list(SAVE_DOCUMENT.default_key_sequences())
    for action in (first.save_action, second.save_action):
        assert action.shortcuts() == keys
        assert action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert host.router.action(SAVE_DOCUMENT.id).shortcuts() == []


def test_with_no_document_focused_the_router_is_disabled(host: Host, saved: MagicMock) -> None:
    """Nothing to route to: the router is off, so its key falls through to whatever has focus.

    **Test steps:**

    * route Save app-wide with nothing open
    * verify the router's action is disabled and routing does nothing
    * open a document, verify it is enabled; close it, verify disabled again
    """
    route_app_wide(SAVE_DOCUMENT.id)

    assert not host.router.action(SAVE_DOCUMENT.id).isEnabled()
    assert not host.router.route(SAVE_DOCUMENT.id)

    host.documents.open_document(FIRST_PATH)
    assert host.router.action(SAVE_DOCUMENT.id).isEnabled()

    host.documents.close_focused_document()
    assert not host.router.action(SAVE_DOCUMENT.id).isEnabled()
    saved.assert_not_called()


def test_a_disabled_instance_is_not_triggered(host: Host, saved: MagicMock) -> None:
    """A focused document whose Save is disabled -- a pending placeholder's -- stays inert.

    **Test steps:**

    * open two edited documents, disable the focused one's Save, route Save app-wide
    * verify routing fires nothing -- not even the other document's enabled Save
    """
    first = open_dirty(host, FIRST_PATH)
    second = open_dirty(host, SECOND_PATH)
    assert first.save_action.isEnabled()
    second.save_action.setEnabled(False)
    route_app_wide(SAVE_DOCUMENT.id)

    assert not host.router.route(SAVE_DOCUMENT.id)
    saved.assert_not_called()


def test_closing_a_routed_document_leaves_no_dangling_binding(host: Host, qtbot: QtBot, saved: MagicMock) -> None:
    """A closed document's action is gone from the registry, and the next press reaches the one left.

    **Test steps:**

    * open an edited document and a clean one, route Save app-wide
    * close the focused (clean, second) one -- no prompt -- and let it be deleted
    * verify only the first's action is still bound, and routing saves the first
    """
    first = open_dirty(host, FIRST_PATH)
    second = host.documents.open_document(SECOND_PATH)
    route_app_wide(SAVE_DOCUMENT.id)

    with wait_destroyed(qtbot, second):
        host.documents.close_focused_document()

    assert shared_command_registry().bound_actions(SAVE_DOCUMENT.id, BindingRole.INSTANCE) == [first.save_action]
    assert host.router.route(SAVE_DOCUMENT.id)
    assert saved_widgets(saved) == [first]


def test_a_routed_refresh_reaches_the_files_view_two_managers_down(host: Host) -> None:
    """The Files view's Refresh sits under the document's own dock manager; routing still finds it.

    **Test steps:**

    * open two documents, show each one's Files dock, route the files refresh app-wide
    * count each document's Files view refreshes, trigger the router
    * verify only the focused document's view refreshed
    """
    first = host.documents.open_document(FIRST_PATH)
    second = host.documents.open_document(SECOND_PATH)
    route_app_wide(REFRESH_FILES.id)
    fired: dict[object, int] = {first: 0, second: 0}
    for document in (first, second):
        shown_files_view_of(document).refresh_action.triggered.connect(
            lambda _=False, document=document: fired.update({document: fired[document] + 1})
        )

    assert host.router.route(REFRESH_FILES.id)

    assert fired == {first: 0, second: 1}


def test_a_routed_refresh_skips_a_closed_files_view(host: Host) -> None:
    """A Files dock the user closed is out of the widget tree, so a routed refresh does not reach it.

    **Test steps:**

    * open a document, its Files dock closed as a document opens
    * route the files refresh app-wide, trigger the router
    * verify nothing fired
    """
    document = host.documents.open_document(FIRST_PATH)
    view = files_dock_of(document).widget()
    assert isinstance(view, FilesView)
    route_app_wide(REFRESH_FILES.id)
    fired: list[bool] = []
    view.refresh_action.triggered.connect(lambda _=False: fired.append(True))

    assert not host.router.route(REFRESH_FILES.id)

    assert not fired


def test_only_document_commands_are_routed(host: Host) -> None:
    """The router carries an action per command allowing the app-wide document scope, and no other; with
    no override, none of them holds a key.

    **Test steps:**

    * verify a routable command has a router action and a window command has none
    * verify the Save router action holds no key under the default scope
    """
    assert host.router.action(SAVE_DOCUMENT.id).text() == SAVE_DOCUMENT.name
    routed = [
        command.id
        for command in shared_command_registry().commands()
        if shared_command_registry().bound_actions(command.id, BindingRole.ROUTER)
    ]
    assert SAVE_DOCUMENT.id in routed
    assert "app.quit" not in routed
    assert all(
        CommandScope.DOCUMENT_APP_WIDE in shared_command_registry().command(command_id).scopes for command_id in routed
    )
    assert host.router.action(SAVE_DOCUMENT.id).shortcuts() == []


# endregion
