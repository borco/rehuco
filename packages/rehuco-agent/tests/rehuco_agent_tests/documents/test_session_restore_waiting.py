"""Tests for what stands in for a maximized view a session remembers while its document waits for its storage
([[plugins#session-restore]], #698).

The document and its curated set are ``test_session_restore_lightbox``'s; the wait is the model's
:attr:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.storage_wait`, set here as the documents area sets
it.
"""

# the sub-docks' waiting overlay is reached through its name-mangled member, as the lightbox is in the module beside
# pylint: disable=protected-access

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_sub_docks import (
    LEAVE_MAXIMIZED_HINT,
    OFFLINE_STORAGE_MESSAGE,
    RESTORING_PLAYER_MESSAGE,
    RESTORING_VIEWER_MESSAGE,
    WAITING_STORAGE_MESSAGE,
)
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.storage_wait import StorageWait
from rehuco_agent.documents.waiting_overlay import WaitingOverlay
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode
from rehuco_agent.settings.maximized_view import PLAYER_KIND, MaximizedView

from .test_document_widget import loadable_lightbox_image
from .test_session_restore_lightbox import (  # noqa: F401  # pylint: disable=unused-import
    IMAGES,
    RECORD,
    curated,
    curated_view,
    fixture_widget,
    open_viewer,
)


def waiting(widget: DocumentWidget) -> WaitingOverlay | None:
    """What stands in for the document's held view.

    :param widget: the document.
    :returns: it, or ``None``.
    """
    return widget.sub_docks._DocumentSubDocks__waiting_overlay  # type: ignore[attr-defined]


def test_a_view_of_a_document_waiting_for_its_storage_is_stood_in_for(widget: DocumentWidget) -> None:
    """The session's view comes back on its surface at once, as a surface saying what is being restored and what
    it waits for, and is reported as a view reopened is.

    **Test steps:**

    * say the document's storage was asked, and restore a view
    * verify an overlay stands on the view's surface, saying all three things, and was reported
    * verify no viewer is open, and the view is still what is remembered
    """
    curated(widget, [])
    reported: list[object] = []
    widget.maximized_restored.connect(reported.append)
    widget.model.storage_wait = StorageWait.ASKING

    widget.restore_maximized(curated_view())

    overlay = waiting(widget)
    assert overlay is not None
    assert overlay.mode is OverlayMode.DOCUMENT_OVERLAY
    assert overlay.text.split("\n") == [
        RESTORING_VIEWER_MESSAGE,
        WAITING_STORAGE_MESSAGE.format(path=RECORD),
        LEAVE_MAXIMIZED_HINT,
    ]
    assert reported == [overlay]
    assert open_viewer(widget) is None
    assert not widget.holds_wide_view


def test_a_view_held_before_its_document_waits_is_stood_in_for_once_it_does(widget: DocumentWidget) -> None:
    """Whichever comes first, the view or the wait, the overlay stands once both are there, and not before.

    **Test steps:**

    * restore a view over a set not there yet, and verify nothing stands in for it
    * say the document's storage was asked, and verify the overlay stands
    """
    curated(widget, [])
    widget.restore_maximized(curated_view())

    assert waiting(widget) is None

    widget.model.storage_wait = StorageWait.ASKING

    assert waiting(widget) is not None


def test_what_it_says_follows_the_storage(widget: DocumentWidget) -> None:
    """A storage that does not answer is said; answered, the view is still being restored until it opens.

    **Test steps:**

    * stand the overlay in, then say the storage did not answer; verify the words
    * say the wait is over, and verify it still stands, saying only what is restored
    """
    curated(widget, [])
    widget.model.storage_wait = StorageWait.ASKING
    widget.restore_maximized(curated_view())
    overlay = waiting(widget)
    assert overlay is not None

    widget.model.storage_wait = StorageWait.OFFLINE

    assert overlay.text.split("\n")[1] == OFFLINE_STORAGE_MESSAGE.format(path=RECORD)

    widget.model.storage_wait = None

    assert waiting(widget) is overlay
    assert overlay.text.split("\n") == [RESTORING_VIEWER_MESSAGE, LEAVE_MAXIMIZED_HINT]


def test_a_held_player_is_named_and_a_surface_wider_than_the_document_is_wide(widget: DocumentWidget) -> None:
    """**Test steps:**

    * say the document is being read and waits for its storage, and restore a player's view on the app window
    * verify the overlay names the player, and the document says it holds a wide view
    """
    widget.model.reading = RECORD
    widget.model.storage_wait = StorageWait.ASKING

    widget.restore_maximized(MaximizedView(PLAYER_KIND, "a.mp4", OverlayMode.APP_WINDOW_OVERLAY.value))

    overlay = waiting(widget)
    assert overlay is not None
    assert overlay.mode is OverlayMode.APP_WINDOW_OVERLAY
    assert overlay.text.split("\n")[0] == RESTORING_PLAYER_MESSAGE
    assert widget.holds_wide_view


def test_dismissing_it_is_leaving_the_maximized_view(widget: DocumentWidget, qtbot: QtBot) -> None:
    """A double-click on a view being restored unmaximizes it: nothing stands in, and the view is not remembered.

    **Test steps:**

    * stand the overlay in, and double-click it
    * verify nothing stands in for the view, and nothing is remembered
    """
    curated(widget, [])
    widget.show()
    qtbot.waitExposed(widget)
    widget.model.storage_wait = StorageWait.ASKING
    widget.restore_maximized(curated_view())
    overlay = waiting(widget)
    assert overlay is not None

    with qtbot.waitSignal(overlay.closed):
        QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton)

    assert waiting(widget) is None
    assert widget.capture_maximized() is None


def test_the_view_opening_takes_its_place(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """Once the storage has answered and the view's set is there, the view opens and what stood in for it goes.

    **Test steps:**

    * stand the overlay in, say the wait is over, and say the set is there
    * verify the viewer is open and nothing stands in for it
    """
    loadable_lightbox_image(mocker)
    curated(widget, [])
    widget.model.storage_wait = StorageWait.ASKING
    widget.restore_maximized(curated_view())
    overlay = waiting(widget)
    assert overlay is not None
    closed: list[bool] = []
    overlay.closed.connect(lambda: closed.append(True))
    widget.model.storage_wait = None

    curated(widget, IMAGES)

    assert open_viewer(widget) is not None
    assert waiting(widget) is None
    assert closed == [True]


def test_a_capture_takes_it_away_and_keeps_the_view(widget: DocumentWidget) -> None:
    """Quitting while a view is still being restored loses nothing: the view is what is remembered, and the docks are
    captured with nothing over them.

    **Test steps:**

    * stand the overlay in, and capture
    * verify the view is what is remembered, twice, and nothing stands in for it
    """
    curated(widget, [])
    widget.model.storage_wait = StorageWait.ASKING
    widget.restore_maximized(curated_view())

    assert widget.capture_maximized() == curated_view()
    assert waiting(widget) is None
    assert widget.capture_maximized() == curated_view()


def test_the_document_becoming_current_gives_it_the_keyboard(widget: DocumentWidget, mocker: MockerFixture) -> None:
    """Esc reaches a view being restored once its tab is the current one, as it reaches an open viewer.

    **Test steps:**

    * stand the overlay in, and tell the document it became the current one
    * verify the overlay was given the keyboard
    """
    curated(widget, [])
    widget.model.storage_wait = StorageWait.ASKING
    widget.restore_maximized(curated_view())
    overlay = waiting(widget)
    assert overlay is not None
    focus = mocker.patch.object(overlay, "setFocus")

    widget.take_focus()

    focus.assert_called_once_with(Qt.FocusReason.ActiveWindowFocusReason)
