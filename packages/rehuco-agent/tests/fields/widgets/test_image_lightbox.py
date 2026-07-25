"""Tests for ImageLightbox: the maximized screenshot viewer and its three surfaces."""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLineEdit, QMainWindow, QToolButton, QVBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from qt_waits import wait_destroyed
from rehuco_agent.fields.widgets.image_lightbox import ImageLightbox, ImageViewerMode
from rehuco_agent.fields.widgets.image_selector import PreviewLabel

PATH: Final = Path("/fake/info03.png")


# region fixtures
@fixture(autouse=True)
def loadable_image(mocker: MockerFixture) -> None:
    """Make every screenshot load as a real pixmap, with no file on disk.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch("rehuco_agent.fields.widgets.image_lightbox.QPixmap", side_effect=lambda *_: QPixmap(320, 180))


@fixture
def document(qtbot: QtBot) -> Iterator[QWidget]:
    """A stand-in for the open document a viewer belongs to, inside a main window's client area.

    Shaped like the real host chain -- a document widget nested in a `QMainWindow`'s central widget --
    so both overlay modes have a genuine surface to resolve and cover.

    A generator fixture, not a plain one: the window is a local, and yielding from inside the fixture
    is what keeps it alive for the test -- returning only its descendant would let Python collect the
    window, taking the document down with it.

    :param qtbot: pytest-qt fixture.
    :returns: the document stand-in, shown.
    """
    window = QMainWindow()
    central = QWidget()
    layout = QVBoxLayout(central)
    document = QWidget()
    layout.addWidget(document)
    window.setCentralWidget(central)
    qtbot.addWidget(window)
    window.resize(800, 600)
    window.show()
    qtbot.waitExposed(window)
    yield document


# endregion


def test_document_overlay_covers_the_document_it_belongs_to(document: QWidget, qtbot: QtBot) -> None:
    """The document overlay is a child of the document, sized to it -- never a window.

    **Test steps:**

    * reveal a viewer in document-overlay mode
    * verify it is parented to the document, is not a window, and covers the document's whole rect
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)

    lightbox.reveal()

    assert lightbox.parentWidget() is document
    assert not lightbox.isWindow()
    assert lightbox.geometry() == document.rect()


def test_app_window_overlay_covers_the_main_windows_client_area(document: QWidget, qtbot: QtBot) -> None:
    """The app-window overlay is a child of the main window's central widget, sized to it.

    **Test steps:**

    * reveal a viewer in app-window-overlay mode over a document nested in a main window
    * verify it is parented to that window's central widget and covers it
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
    qtbot.addWidget(lightbox)

    lightbox.reveal()

    window = document.window()
    assert isinstance(window, QMainWindow)
    central = window.centralWidget()
    assert lightbox.parentWidget() is central
    assert lightbox.geometry() == central.rect()


def test_full_screen_is_a_frameless_window_owned_by_the_document(document: QWidget, qtbot: QtBot) -> None:
    """Full-screen is a frameless top-level window, still parented to the document that owns it.

    **Test steps:**

    * reveal a viewer in full-screen mode
    * verify it is a window, is frameless, and keeps the document as its Qt parent
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.FULL_SCREEN, document)
    qtbot.addWidget(lightbox)

    lightbox.reveal()

    assert lightbox.isWindow()
    assert lightbox.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert lightbox.parent() is document


def test_escape_dismisses_and_deletes_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """ESC closes the viewer, which then deletes itself rather than lingering hidden.

    **Test steps:**

    * reveal a viewer and press ESC on it
    * verify it reports ``closed`` and is destroyed
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()
    dismissed: list[bool] = []
    lightbox.closed.connect(lambda: dismissed.append(True))

    with wait_destroyed(qtbot, lightbox):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)

    assert dismissed == [True]


def test_the_close_button_dismisses_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """The corner close affordance dismisses the viewer, same as ESC.

    **Test steps:**

    * reveal a viewer and click its close button
    * verify it is destroyed
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()
    button = lightbox.findChild(QToolButton)
    assert isinstance(button, QToolButton)

    with wait_destroyed(qtbot, lightbox):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_clicking_the_image_does_not_dismiss_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """A click on the image leaves the viewer up -- only ESC and the close button dismiss.

    Regression: the two halves of the image are the prev/next affordance, so a click there must never
    also mean "close".

    **Test steps:**

    * reveal a viewer and left-click the middle of it
    * verify it is still shown
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    qtbot.mouseClick(lightbox, Qt.MouseButton.LeftButton, pos=lightbox.rect().center())

    assert not lightbox.isHidden()


def test_another_key_leaves_the_viewer_up(document: QWidget, qtbot: QtBot) -> None:
    """Only ESC dismisses; other keys pass through, leaving the viewer open.

    **Test steps:**

    * reveal a viewer and press a key that isn't ESC
    * verify it is still shown
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    qtbot.keyClick(lightbox, Qt.Key.Key_A)

    assert not lightbox.isHidden()


def test_a_right_click_leaves_the_viewer_up(document: QWidget, qtbot: QtBot) -> None:
    """Only a left-click dismisses; other buttons leave the viewer open.

    **Test steps:**

    * reveal a viewer and right-click it
    * verify it is still shown
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    qtbot.mouseClick(lightbox, Qt.MouseButton.RightButton)

    assert not lightbox.isHidden()


def test_dismissing_returns_focus_where_it_came_from(document: QWidget, qtbot: QtBot) -> None:
    """The widget that had focus when the viewer opened gets it back on dismiss.

    **Test steps:**

    * focus an editor inside the document, then reveal a viewer (taking focus away)
    * dismiss it with ESC
    * verify the editor holds focus again
    """
    editor = QLineEdit(document)
    editor.show()
    editor.setFocus()
    assert editor.hasFocus()
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()
    assert not editor.hasFocus()

    with wait_destroyed(qtbot, lightbox):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)

    assert editor.hasFocus()


def test_dismissing_leaves_focus_alone_when_it_came_from_another_document(
    document: QWidget, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A remembered widget outside this viewer's document is not restored on dismiss.

    Regression: opening a second preview while the first held focus made the second remember a widget
    in the *other* document, so dismissing it threw the user into that unrelated dock.

    **Test steps:**

    * focus a widget outside the document, then open a viewer over the document
    * dismiss it with ESC
    * verify the viewer never re-focused that outside widget

    Asserted on the call, not on who ends up with focus: Qt restores a window's own last focus widget
    when the viewer covering it goes away, which would mask the difference here.
    """
    outsider = QLineEdit(document.window())
    outsider.show()
    outsider.setFocus()
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()
    restore = mocker.patch.object(outsider, "setFocus")

    with wait_destroyed(qtbot, lightbox):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)

    restore.assert_not_called()


def test_the_close_button_restores_focus_the_same_way_escape_does(document: QWidget, qtbot: QtBot) -> None:
    """The close button goes through the same dismissal path as ESC, restore included.

    **Test steps:**

    * focus an editor inside the document, open a viewer, and click its close button
    * verify that editor holds focus again
    """
    editor = QLineEdit(document)
    editor.show()
    editor.setFocus()
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()
    button = lightbox.findChild(QToolButton)
    assert isinstance(button, QToolButton)

    with wait_destroyed(qtbot, lightbox):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert editor.hasFocus()


def test_dismissing_tolerates_the_focused_widget_being_destroyed(document: QWidget, qtbot: QtBot) -> None:
    """A focused widget deleted while the viewer is up (a form rebuild) leaves nothing to restore.

    Regression: holding the widget blindly and re-focusing it on dismiss would reach into a deleted
    object.

    **Test steps:**

    * focus an editor, reveal a viewer, then destroy that editor
    * dismiss the viewer and verify it closes cleanly
    """
    editor = QLineEdit(document)
    editor.show()
    editor.setFocus()
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()

    with wait_destroyed(qtbot, editor):
        editor.deleteLater()
    with wait_destroyed(qtbot, lightbox):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)


def test_an_overlay_reclaims_focus_from_the_surface_it_covers(document: QWidget, qtbot: QtBot) -> None:
    """Focus landing under an open overlay is pulled straight back, so ESC still dismisses it.

    Regression: clicking another dock's tab handed the keyboard to a widget beneath the viewer, and
    ESC then reached nothing at all -- the viewer looked stuck.

    **Test steps:**

    * reveal an overlay, then focus an editor beneath it (as re-activating that document does)
    * verify the overlay holds focus again, and ESC dismisses it
    """
    editor = QLineEdit(document)
    editor.show()
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()

    editor.setFocus()

    assert lightbox.hasFocus()
    with wait_destroyed(qtbot, lightbox):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)


def test_two_open_viewers_do_not_fight_over_focus(document: QWidget, qtbot: QtBot) -> None:
    """A second viewer over the same surface takes focus without the first snatching it back.

    Regression: two app-window overlays cover one surface, so each would see the other's focus as
    "landed underneath me" and pull it back, forever.

    **Test steps:**

    * reveal two app-window overlays over the same main window
    * verify the second holds focus, and ESC dismisses that one
    """
    first = ImageLightbox(PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
    qtbot.addWidget(first)
    first.reveal()
    second = ImageLightbox(PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
    second.reveal()

    assert second.hasFocus()
    assert not first.hasFocus()
    with wait_destroyed(qtbot, second):
        qtbot.keyClick(second, Qt.Key.Key_Escape)


def test_an_overlay_leaves_focus_alone_outside_the_surface_it_covers(document: QWidget, qtbot: QtBot) -> None:
    """Focus moving to a widget this viewer does not cover is left where the user put it.

    A document overlay covers its own document only, so another document (with or without a viewer of
    its own) must stay usable while this one is up.

    **Test steps:**

    * reveal a document overlay, then focus an editor outside that document
    * verify the overlay did not steal the focus back
    """
    outsider = QLineEdit(document.window())
    outsider.show()
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    outsider.setFocus()

    assert outsider.hasFocus()
    assert not lightbox.hasFocus()


def test_an_overlay_follows_the_surface_it_covers_as_it_resizes(document: QWidget, qtbot: QtBot) -> None:
    """Resizing the covered surface resizes the overlay with it.

    Regression: an overlay is positioned by hand, not by a layout, so nothing else would follow.

    **Test steps:**

    * reveal a document overlay, then resize the document
    * verify the overlay still covers it exactly
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    document.resize(300, 200)

    assert lightbox.geometry() == document.rect()


def test_an_app_window_overlay_closes_when_its_document_goes_away(document: QWidget, qtbot: QtBot) -> None:
    """Closing the document takes an app-window overlay down with it.

    Regression: that overlay is parented to the main window, not the document, so nothing would
    otherwise remove it -- leaving a screenshot of a closed document covering the app.

    **Test steps:**

    * reveal an app-window overlay, then destroy the document it belongs to
    * verify the overlay is destroyed too
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
    lightbox.reveal()

    with wait_destroyed(qtbot, lightbox):
        document.deleteLater()


def test_a_document_close_under_an_app_window_overlay_restores_no_focus(document: QWidget, qtbot: QtBot) -> None:
    """Closing the document under an app-window overlay tears the viewer down without touching focus.

    Regression: the viewer closes *during* the document's destruction, and asking the half-destroyed
    document whether it still owned the remembered focus widget raised instead of skipping the
    restore. Needs a focused editor -- with nothing remembered, the restore short-circuits and the
    ordering bug stays invisible.

    **Test steps:**

    * focus an editor inside the document, then reveal an app-window overlay (remembering that editor)
    * destroy the document and verify the viewer is destroyed cleanly with it
    """
    editor = QLineEdit(document)
    editor.show()
    editor.setFocus()
    lightbox = ImageLightbox(PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
    lightbox.reveal()

    with wait_destroyed(qtbot, lightbox):
        document.deleteLater()


def test_a_full_screen_viewer_dies_with_its_document(document: QWidget, qtbot: QtBot) -> None:
    """A full-screen viewer is destroyed with the document, never orphaned on top of the desktop.

    **Test steps:**

    * reveal a full-screen viewer, then destroy the document it belongs to
    * verify the viewer is destroyed too
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.FULL_SCREEN, document)
    lightbox.reveal()

    with wait_destroyed(qtbot, lightbox):
        document.deleteLater()


def test_the_screenshot_is_scaled_to_fit_preserving_aspect(document: QWidget, qtbot: QtBot) -> None:
    """The screenshot is painted scaled to fit the viewer, keeping its aspect ratio.

    **Test steps:**

    * reveal a document overlay over a sized document, with a 16:9 source
    * verify the rendered pixmap fits inside the viewer and keeps 16:9
    """
    lightbox = ImageLightbox(PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)

    lightbox.reveal()

    preview = lightbox.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)
    pixmap = preview.pixmap()
    assert pixmap.width() <= lightbox.width()
    assert pixmap.height() <= lightbox.height()
    assert abs(pixmap.width() / pixmap.height() - 320 / 180) < 0.05
