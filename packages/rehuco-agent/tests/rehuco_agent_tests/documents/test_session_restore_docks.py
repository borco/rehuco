"""Tests for what the Documents dock restores of a session beyond its documents: the preview entry, the maximized dock
and the stack of wide views ([[plugins#session-restore]], #576)."""

# the area's parts are reached through their name-mangled members, as test_documents_dock does
# astroid reads the settings' ordered dict and the sub-docks' name-to-dock dict's values wrongly
# pylint: disable=protected-access,unsupported-assignment-operation,no-member

from pathlib import Path
from typing import Final, cast

from borco_core import Presence
from PySide6.QtWidgets import QMainWindow, QWidget
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_dock import LOCKED_DOCK_MARKER
from rehuco_agent.documents.document_fields import EDITOR_IMAGES_TAB
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.documents.maximized_restore import MaximizedStack, is_wide
from rehuco_agent.documents.storage_wait import StorageWait
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode, OverlaySurface
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.maximized_view import CURATED_SET, LIGHTBOX_KIND, MaximizedView
from rehuco_core.access import ResourceKey

from .test_document_widget import image_selector
from .test_documents_dock import FAKE_PATH, dock_for, load_document

SECOND: Final = FAKE_PATH.with_name("second.rehu")
THIRD: Final = FAKE_PATH.with_name("third.rehu")
FOURTH: Final = FAKE_PATH.with_name("fourth.rehu")
TIMEOUT: Final = 5000


def view_on(mode: OverlayMode) -> MaximizedView:
    """A session's lightbox view on a surface.

    :param mode: the surface.
    :returns: the view.
    """
    return MaximizedView(LIGHTBOX_KIND, "a.png", mode.value, CURATED_SET)


def preview_session(name: str = "Preview-7") -> DocumentSessionSettings:
    """A session with nothing but a preview.

    :param name: the preview dock's object name.
    :returns: the session.
    """
    session = DocumentSessionSettings()
    session.preview = DocumentSessionSettings.Preview(
        FAKE_PATH, name, DocumentSessionSettings.Item(open=True, state=b"")
    )
    return session


# region The preview


def test_the_preview_comes_back_under_its_name_as_a_preview_unread(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The saved layout knows the dock by its name; it is still the preview, read when its tab shows.

    **Test steps:**

    * restore a session with a preview named as a layout would
    * verify the dock has that name, is the preview and is not read
    * verify a later preview is numbered past it
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    dock.restore_session(preview_session())

    widget = dock.preview_document_widget()
    assert widget is not None
    assert dock.preview_dock_name() == "Preview-7"
    assert widget.model.pending is True
    assert dock._DocumentsDock__preview_count == 7  # type: ignore[attr-defined]


def test_a_preview_not_in_the_paths_to_restore_is_left_for_later(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The Session page's toggles left it out, so no dock is made for it.

    **Test steps:**

    * restore a session naming no path to restore
    * verify there is no preview
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)

    dock.restore_session(preview_session(), set())

    assert dock.preview_document_widget() is None


def test_a_preview_of_a_document_open_in_its_own_dock_makes_no_second_dock(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A document the session has open in an ordinary dock stays there, as showing it in a preview would leave it.

    **Test steps:**

    * restore a session with the same document open and as the preview
    * verify there is one dock and no preview
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    session = preview_session()
    session.items[FAKE_PATH] = DocumentSessionSettings.Item(open=True)

    dock.restore_session(session)

    assert len(dock.open_document_widgets()) == 1
    assert dock.preview_document_widget() is None


# endregion


# region Which documents are read at the start


@mark.parametrize(
    ("mode", "read"),
    [(OverlayMode.DOCUMENT_OVERLAY, False), (OverlayMode.APP_WINDOW_OVERLAY, True), (OverlayMode.FULL_SCREEN, True)],
)
def test_a_view_wider_than_its_document_is_read_at_the_start(
    mocker: MockerFixture, qtbot: QtBot, mode: OverlayMode, read: bool
) -> None:
    """A wide surface shows whichever tab is in front, so a background document with one cannot wait for its tab.

    **Test steps:**

    * restore a session with one unfocused document with a view on the surface
    * verify it was asked for its file only when the surface is wider than the document
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    session = DocumentSessionSettings()
    session.items[FAKE_PATH] = DocumentSessionSettings.Item(open=True, maximized=view_on(mode))

    dock.restore_session(session)

    widget = dock.open_document_widgets()[0]
    assert (not widget.model.pending or widget.model.reading is not None) is read


# endregion


def test_the_maximized_document_dock_comes_back_on_screen(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The dock filling the area is named beside the layout, and fills it again once the area is shown.

    **Test steps:**

    * restore a session with two documents, naming one as maximized, on a hidden area
    * verify the name reads as saved
    * show the area, and verify it stands
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    first = dock.open_document(ResourceKey(FAKE_PATH))
    second = dock.open_document(ResourceKey(SECOND))
    del first, second
    layout = dock.save_state()
    name = next(iter(dock._DocumentsDock__document_docks)).objectName()  # type: ignore[attr-defined]
    session = DocumentSessionSettings()
    session.docks_layout = layout
    session.maximized_dock = name

    dock.restore_state(session.docks_layout, session.maximized_dock)
    assert dock.maximized_dock_name == name

    dock.resize(800, 600)
    dock.show()

    handler = dock._DocumentsDock__maximize_handler  # type: ignore[attr-defined]
    qtbot.waitUntil(lambda: handler.maximized_dock is not None, timeout=TIMEOUT)
    assert dock.maximized_dock_name == name


# region The stack


def overlays_over(qtbot: QtBot, count: int) -> tuple[QMainWindow, list[OverlaySurface]]:
    """A shown window with views over its whole client area, as two documents' wide views are.

    :param qtbot: pytest-qt fixture.
    :param count: how many.
    :returns: the window and the views.
    """
    window = QMainWindow()
    qtbot.addWidget(window)
    window.setCentralWidget(QWidget())
    window.resize(400, 300)
    window.show()
    views = [OverlaySurface(OverlayMode.APP_WINDOW_OVERLAY, QWidget(window)) for _ in range(count)]
    for view in views:
        view.reveal()
    return window, views


def stacked(views: list[OverlaySurface]) -> list[OverlaySurface]:
    """The views as they are stacked, bottom first.

    :param views: the views, children of one parent.
    :returns: them, as that parent's children list them.
    """
    siblings = cast(QWidget, views[0].parentWidget()).children()
    return sorted(views, key=siblings.index)


def test_views_stack_in_session_order_whatever_order_their_reads_answer_in(qtbot: QtBot) -> None:
    """Reads answer in any order, so each view opening puts all of them back in order, the focused one's on top.

    **Test steps:**

    * say the session's order, with the first document focused
    * add the views in another order
    * verify they stack as the session says after each, the focused document's on top at the end
    """
    _, (first, second, third) = overlays_over(qtbot, 3)
    stack = MaximizedStack()
    stack.set_order([FAKE_PATH, SECOND, THIRD], FAKE_PATH)

    stack.add(FAKE_PATH, first)
    stack.add(THIRD, third)
    assert stacked([first, third]) == [third, first]

    stack.add(SECOND, second)
    assert stacked([first, second, third]) == [second, third, first]
    assert stack.holds_any is True


def test_a_view_closed_leaves_the_stack(qtbot: QtBot) -> None:
    """A view closed is not raised again by the next one opening.

    **Test steps:**

    * add two views and close one
    * add a third, which must not reach for the closed one
    * close the rest, and verify nothing is held
    """
    _, (first, second, third) = overlays_over(qtbot, 3)
    stack = MaximizedStack()
    stack.set_order([FAKE_PATH, SECOND, THIRD], None)
    stack.add(FAKE_PATH, first)
    stack.add(SECOND, second)

    first.close()
    stack.add(THIRD, third)

    assert stacked([second, third]) == [second, third]
    second.close()
    third.close()
    assert stack.holds_any is False


def test_a_view_on_its_own_document_is_no_part_of_the_stack(qtbot: QtBot) -> None:
    """A document overlay shows only with its tab, so nothing orders it against the others.

    **Test steps:**

    * add a view over a document, and an unnamed path's view over the window
    * verify only the wide one is held, and that a remembered surface reads as wide or not
    """
    window, (wide,) = overlays_over(qtbot, 1)
    document = QWidget(window)
    narrow = OverlaySurface(OverlayMode.DOCUMENT_OVERLAY, document)
    stack = MaximizedStack()

    stack.add(FAKE_PATH, narrow)
    assert stack.holds_any is False

    stack.add(None, wide)
    assert stack.holds_any is True
    assert is_wide(OverlayMode.FULL_SCREEN.value) is True
    assert is_wide(OverlayMode.DOCUMENT_OVERLAY.value) is False
    assert is_wide("a surface of a newer build") is False


# endregion


# region What waits for a document's first read


@mark.usefixtures("real_sub_docks")
def test_quitting_before_a_document_is_read_keeps_what_it_was_opened_with(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A document never viewed has only a placeholder's docks: capturing them would cost it its layout and its view.

    **Test steps:**

    * build a state from an opened document, and restore a session of it with a maximized view
    * verify, with it unread, that its state is what it was given and its view is still the one remembered
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    state = dock.open_document(ResourceKey(FAKE_PATH)).save_state()
    dock.close_all()
    view = view_on(OverlayMode.DOCUMENT_OVERLAY)
    session = DocumentSessionSettings()
    session.items[FAKE_PATH] = DocumentSessionSettings.Item(open=True, state=state, maximized=view)

    dock.restore_session(session)

    widget = dock.open_document_widgets()[0]
    assert widget.model.pending is True
    assert widget.save_state() == state
    assert widget.capture_maximized() == view


@mark.usefixtures("real_sub_docks")
def test_a_maximized_sub_dock_comes_back_once_its_document_is_read(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A sub-dock only the type builds is not there on the placeholder: its maximize waits for the read and the screen.

    **Test steps:**

    * open a reference pack on a shown area, show Content Images and maximize it; save the state
    * restore a session of it into a new area, and verify it names the dock but nothing is maximized while unread
    * show the area, and verify the dock fills the document once it is read
    """
    pack = {"type": "ReferenceImages", "sources": [{"title": "Pack", "primary": True}]}
    load_document(mocker, pack)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    dock.resize(800, 600)
    dock.show()
    first = dock.open_document(ResourceKey(FAKE_PATH))
    sub_docks = first.sub_docks
    content = sub_docks._DocumentSubDocks__content_images_dock  # type: ignore[attr-defined]
    content.toggleView(True)
    handler = first._DocumentWidget__maximize_handler  # type: ignore[attr-defined]
    handler.maximize(content)
    state = first.save_state()
    name = content.objectName()
    dock.close_all()

    restored_area = DocumentsDock()
    qtbot.addWidget(restored_area)
    restored_area.resize(800, 600)
    session = DocumentSessionSettings()
    session.items[FAKE_PATH] = DocumentSessionSettings.Item(open=True, state=state)
    restored_area.restore_session(session)
    widget = restored_area.open_document_widgets()[0]
    assert widget.model.pending is True
    assert widget.maximized_dock is None

    restored_area.show()

    qtbot.waitUntil(lambda: widget.maximized_dock is not None, timeout=TIMEOUT)
    maximized = widget.maximized_dock
    assert maximized is not None
    assert maximized.objectName() == name


@mark.usefixtures("real_sub_docks")
def test_the_screenshots_split_comes_back_through_a_documents_first_read(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The images editor's split survives the placeholder and the form its first read rebuilds (#72).

    **Test steps:**

    * open a document on a shown area, show the images editor and move its split; save the state
    * restore a session of it into a new area, and show it until the document is read
    * show the images editor, and verify the split is where it was
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    dock.resize(1000, 800)
    dock.show()
    first = dock.open_document(ResourceKey(FAKE_PATH))
    selector = image_selector(first)
    images_dock = first.sub_docks._DocumentSubDocks__editor_docks[EDITOR_IMAGES_TAB]  # type: ignore[attr-defined]
    images_dock.toggleView(True)
    images_dock.setAsCurrentTab()
    qtbot.waitUntil(selector.isVisible, timeout=TIMEOUT)
    selector.setSizes([120, 380])
    qtbot.waitUntil(lambda: selector.sizes()[0] > 0, timeout=TIMEOUT)
    saved = selector.sizes()
    state = first.save_state()
    dock.close_all()

    restored_area = DocumentsDock()
    qtbot.addWidget(restored_area)
    restored_area.resize(1000, 800)
    session = DocumentSessionSettings()
    session.items[FAKE_PATH] = DocumentSessionSettings.Item(open=True, state=state)
    restored_area.restore_session(session)
    widget = restored_area.open_document_widgets()[0]
    restored_area.show()
    qtbot.waitUntil(lambda: not widget.model.pending and widget.model.reading is None, timeout=TIMEOUT)

    restored = image_selector(widget)
    qtbot.waitUntil(restored.isVisible, timeout=TIMEOUT)

    qtbot.waitUntil(lambda: restored.sizes()[0] > 0, timeout=TIMEOUT)
    assert restored.sizes() == saved


# endregion


def test_a_preview_shown_already_is_not_replaced_by_the_sessions(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A preview that is up when the session is restored stays, and is not held for the session's storage.

    **Test steps:**

    * show a document in a preview, then restore a session whose preview is held
    * verify the preview still shows that document, is the only dock, and waits for no storage
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    reader = dock.show_in_preview(ResourceKey(SECOND))

    dock.restore_session(preview_session(), held={FAKE_PATH})

    assert dock.preview_document_widget() is reader
    assert len(dock.open_document_widgets()) == 1
    assert reader.model.storage_wait is None


@mark.parametrize(("mode", "focused"), [(OverlayMode.DOCUMENT_OVERLAY, True), (OverlayMode.FULL_SCREEN, False)])
def test_a_view_on_its_document_leaves_the_keyboard_with_the_document_in_front(
    mocker: MockerFixture, qtbot: QtBot, mode: OverlayMode, focused: bool
) -> None:
    """A view opening takes the keyboard; the one on top keeps it, or with none wide the current document takes it back.

    **Test steps:**

    * open a document, and report a view on the surface reopened
    * verify the current document was asked to take the keyboard only when the view is not wide
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(ResourceKey(FAKE_PATH))
    take_focus = mocker.spy(widget, "take_focus")

    widget.maximized_restored.emit(OverlaySurface(mode, widget))

    assert take_focus.called is focused


def test_the_previews_maximized_view_waits_for_its_read(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The current record comes back with its view, which it is handed as any document is.

    **Test steps:**

    * restore a session whose preview had a view on its own document
    * verify the preview remembers it, unread
    """
    load_document(mocker)
    restored = mocker.spy(DocumentWidget, "restore_maximized")
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    session = preview_session()
    assert session.preview is not None
    view = view_on(OverlayMode.DOCUMENT_OVERLAY)
    session.preview.item.maximized = view

    dock.restore_session(session)

    widget = dock.preview_document_widget()
    assert widget is not None
    restored.assert_called_once_with(widget, view)


def test_the_sessions_view_is_not_put_over_a_document_that_is_open_already(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A document open before the session is restored is the reader's: the session's view does not cover it, and it
    is not held for its storage, having been read.

    **Test steps:**

    * open a document, then restore a session that has it held, with a wide view
    * verify the view was not handed to it, and it waits for no storage
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(ResourceKey(FAKE_PATH))
    restored = mocker.spy(DocumentWidget, "restore_maximized")
    session = DocumentSessionSettings()
    session.items[FAKE_PATH] = DocumentSessionSettings.Item(open=True, maximized=view_on(OverlayMode.FULL_SCREEN))

    dock.restore_session(session, held={FAKE_PATH})

    restored.assert_not_called()
    assert dock.open_document_widgets() == [widget]
    assert widget.model.storage_wait is None


# region Documents whose storage has to be asked (#698)


def saved_row(*paths: Path, current: Path) -> dict[str, object]:
    """A saved documents layout: one row of tabs.

    :param paths: the documents, in tab order.
    :param current: the one whose tab is current.
    :returns: the layout.
    """
    return {
        "format": 1,
        "main": {
            "area": [{"name": str(ResourceKey(path)), "closed": False} for path in paths],
            "current": str(ResourceKey(current)),
        },
    }


def row_of(dock: DocumentsDock) -> list[Path]:
    """The documents' tab order as the area would save it.

    :param dock: the documents area.
    :returns: the paths, in tab order.
    """
    names = [entry["name"] for entry in dock.save_state()["main"]["area"]]
    return [Path(name) for name in names]


def session_of(*paths: Path, row: dict[str, object], focused: Path) -> DocumentSessionSettings:
    """A session with every one of ``paths`` open.

    :param paths: the documents.
    :param row: its saved layout.
    :param focused: the focused document.
    :returns: the session.
    """
    session = DocumentSessionSettings()
    for path in paths:
        session.items[path] = DocumentSessionSettings.Item(open=True)  # pylint: disable=unsupported-assignment-operation
    session.docks_layout = row
    session.focused_path = focused
    return session


def widget_at(dock: DocumentsDock, path: Path) -> DocumentWidget:
    """The widget of the document at a path.

    :param dock: the documents area.
    :param path: the document's path.
    :returns: its widget.
    """
    return next(widget for widget in dock.open_document_widgets() if widget.model.path == path)


def unread(widget: DocumentWidget) -> bool:
    """Whether a document's file has not been asked for.

    :param widget: its widget.
    :returns: the answer.
    """
    return widget.model.pending and widget.model.reading is None


def test_every_document_comes_back_in_its_place_and_the_held_ones_locked_and_unread(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A session with documents on local drives and a share comes back whole at once: the saved order, the focused
    document, and the share's documents in their places, locked, with nothing read of them (#698).

    **Test steps:**

    * restore a session of four documents, two of them held, whose saved row is in another order than its entries
    * verify the row reads as saved and the focused document is the saved one
    * verify the held ones wait for their storage, unread, their tabs marked locked, and the others wait for nothing
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    row = saved_row(FAKE_PATH, SECOND, THIRD, FOURTH, current=THIRD)
    session = session_of(THIRD, FOURTH, FAKE_PATH, SECOND, row=row, focused=THIRD)

    dock.restore_session(session, held={SECOND, FOURTH})

    assert row_of(dock) == [FAKE_PATH, SECOND, THIRD, FOURTH]
    assert dock.focused_document_path() == THIRD
    for path in (SECOND, FOURTH):
        widget = widget_at(dock, path)
        assert widget.model.storage_wait is StorageWait.ASKING
        assert unread(widget)
        assert dock_for(dock, widget).windowTitle().startswith(LOCKED_DOCK_MARKER)
    for path in (FAKE_PATH, THIRD):
        widget = widget_at(dock, path)
        assert widget.model.storage_wait is None
        assert not dock_for(dock, widget).windowTitle().startswith(LOCKED_DOCK_MARKER)


def test_the_focused_document_is_held_too_and_read_once_its_storage_answers(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """The session's focused document on a share is the current tab from the start, unread, with nothing asked twice
    while the start's answer is out; the answer that it is there reads it where it stands (#698).

    **Test steps:**

    * show the area and restore a session whose focused document is held
    * verify it is the focused one, unread, and its storage was not asked for again
    * say its storage is there
    * verify it waits for nothing, was asked for its file, and its tab lost the lock marker
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    dock.show()
    qtbot.waitExposed(dock)
    asked: list[Path] = []
    dock.storage_asked.connect(asked.append)
    session = session_of(FAKE_PATH, SECOND, row=saved_row(FAKE_PATH, SECOND, current=SECOND), focused=SECOND)

    dock.restore_session(session, held={SECOND})

    widget = widget_at(dock, SECOND)
    assert dock.focused_document_widget() is widget
    assert unread(widget)
    assert not asked

    dock.storage_answered(SECOND, Presence.PRESENT)

    assert widget.model.storage_wait is None
    assert not unread(widget)
    assert not dock_for(dock, widget).windowTitle().startswith(LOCKED_DOCK_MARKER)


def test_a_storage_that_does_not_answer_is_asked_again_when_the_document_is_reached(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A document whose share did not answer stays locked and says so; reaching it asks its storage again instead of
    reading it (#698).

    **Test steps:**

    * restore a session with a held document behind the focused one, and say its storage did not answer
    * verify it says its storage is offline, and is still unread
    * open that document, as any focus route does
    * verify its storage was asked for again, it says so, and it is still unread
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    session = session_of(FAKE_PATH, SECOND, row=saved_row(FAKE_PATH, SECOND, current=FAKE_PATH), focused=FAKE_PATH)
    dock.restore_session(session, held={SECOND})
    widget = widget_at(dock, SECOND)
    asked: list[Path] = []
    dock.storage_asked.connect(asked.append)

    dock.storage_answered(SECOND, Presence.OFFLINE)

    assert widget.model.storage_wait is StorageWait.OFFLINE
    assert unread(widget)
    assert not asked

    dock.open_document(ResourceKey(SECOND))

    assert asked == [SECOND]
    assert widget.model.storage_wait is StorageWait.ASKING
    assert unread(widget)


@mark.parametrize("presence", [Presence.PRESENT, Presence.GONE])
def test_a_background_document_whose_storage_answered_is_read_when_its_tab_is_reached(
    mocker: MockerFixture, qtbot: QtBot, presence: Presence
) -> None:
    """A held document behind another is let go by its storage's answer and still read only when it is reached: one
    whose file is there, and one whose file is gone, which then says so as any vanished file does (#698).

    **Test steps:**

    * restore a session with a held document behind the focused one, and say what its storage answered
    * verify it waits for nothing, and is still unread
    * open that document, and verify it was asked for its file
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    session = session_of(FAKE_PATH, SECOND, row=saved_row(FAKE_PATH, SECOND, current=FAKE_PATH), focused=FAKE_PATH)
    dock.restore_session(session, held={SECOND})
    widget = widget_at(dock, SECOND)

    dock.storage_answered(SECOND, presence)

    assert widget.model.storage_wait is None
    assert unread(widget)

    dock.open_document(ResourceKey(SECOND))

    assert not unread(widget)


@mark.parametrize(("wide", "read"), [(True, True), (False, False)])
def test_a_held_document_with_a_wide_view_is_read_as_soon_as_its_storage_answers(
    mocker: MockerFixture, qtbot: QtBot, wide: bool, read: bool
) -> None:
    """A view wider than its document shows whichever tab is in front, so the document behind it is read the moment
    its storage answers; one with no such view waits for its tab (#698).

    **Test steps:**

    * restore a session with a held document behind the focused one, holding a view that is wide or not
    * say its storage is there
    * verify it was asked for its file only when its view is wide
    """
    load_document(mocker)
    mocker.patch.object(DocumentWidget, "holds_wide_view", new_callable=mocker.PropertyMock, return_value=wide)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    session = session_of(FAKE_PATH, SECOND, row=saved_row(FAKE_PATH, SECOND, current=FAKE_PATH), focused=FAKE_PATH)
    dock.restore_session(session, held={SECOND})
    widget = widget_at(dock, SECOND)

    dock.storage_answered(SECOND, Presence.PRESENT)

    assert unread(widget) is not read


def test_an_answer_about_a_document_that_is_not_held_changes_nothing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """**Test steps:**

    * open a document, and say its storage and that of a document with no dock did not answer
    * verify the open one waits for nothing
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.open_document(ResourceKey(FAKE_PATH))

    dock.storage_answered(FAKE_PATH, Presence.OFFLINE)
    dock.storage_answered(SECOND, Presence.OFFLINE)

    assert widget.model.storage_wait is None


def test_closing_a_held_document_ends_its_wait(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The reader closes what is no longer available: the dock goes, and a later answer finds nothing to let go
    (#698).

    **Test steps:**

    * restore a session with one held document, and close every document
    * verify its wait ended as it closed, and an answer about it afterward changes nothing
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    session = session_of(FAKE_PATH, row=saved_row(FAKE_PATH, current=FAKE_PATH), focused=FAKE_PATH)
    dock.restore_session(session, held={FAKE_PATH})
    waits: list[object] = []
    widget_at(dock, FAKE_PATH).model.storage_wait_changed.connect(waits.append)  # type: ignore[attr-defined]

    dock.close_all()
    dock.storage_answered(FAKE_PATH, Presence.PRESENT)

    assert waits == [None]
    assert not dock.open_document_widgets()


def test_a_held_preview_that_moves_on_to_another_document_stops_waiting(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The session's preview on a share is held as a document is; shown another document, it reads that one (#698).

    **Test steps:**

    * restore a session whose preview is held, and verify it waits for its storage
    * show another document in the preview
    * verify the preview shows it, waits for nothing and was asked for its file
    """
    load_document(mocker)
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    dock.restore_session(preview_session(), held={FAKE_PATH})
    preview = dock.preview_document_widget()
    assert preview is not None
    assert preview.model.storage_wait is StorageWait.ASKING

    dock.show_in_preview(ResourceKey(SECOND))

    assert preview.model.path == SECOND
    assert preview.model.storage_wait is None
    assert not unread(preview)


# endregion
