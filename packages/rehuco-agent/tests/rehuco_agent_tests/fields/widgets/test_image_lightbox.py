"""Tests for ImageLightbox: the maximized screenshot viewer, its three surfaces, and its navigation."""

# one cohesive suite over the viewer's surfaces, focus discipline, and navigation; a scoped disable
# reads better than an arbitrary split (same precedent as test_rehu_document_model.py).
# pylint: disable=too-many-lines

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QEnterEvent, QImage, QWheelEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QMainWindow, QToolButton, QVBoxLayout, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_lightbox import (
    CLOSE_BUTTON_NAME,
    CORNER_HOVER_OPACITY,
    CORNER_ICON_SIZE,
    CORNER_MARGIN,
    DEFAULT_BACKDROP,
    DEFAULT_STRIP_HEIGHT,
    HOVER_INFO_NAME,
    INFO_OVERLAY_NAME,
    INFO_TOGGLE_BUTTON_NAME,
    NAVIGATION_HOVER_OPACITY,
    NAVIGATION_IDLE_OPACITY,
    NAVIGATION_PRESSED_OPACITY,
    NAVIGATION_ZONE_DIVISIONS,
    NAVIGATION_ZONE_WIDTH,
    NEXT_BUTTON_NAME,
    PREVIOUS_BUTTON_NAME,
    STRIP_TOGGLE_BUTTON_NAME,
    ImageInfoOverlay,
    ImageLightbox,
    ImageViewerMode,
    OverlayButton,
)
from rehuco_agent.fields.widgets.image_selector import PreviewLabel
from rehuco_agent.fields.widgets.image_source import PathImageSource
from rehuco_agent.fields.widgets.thumbnail_row import ThumbnailRow

from rehuco_agent_tests.qt_waits import wait_destroyed

PATH: Final = Path("/fake/info03.png")
PATHS: Final = [Path("/fake/info00.png"), Path("/fake/info01.png"), Path("/fake/info02.png")]

IMAGE_WIDTH: Final = 320
IMAGE_HEIGHT: Final = 180
"""What every fake screenshot decodes to."""

WIDE_VIEWER_WIDTH: Final = 800
NARROW_VIEWER_WIDTH: Final = 200
"""Viewer widths either side of where the band rule changes hands: a band is
``min(NAVIGATION_ZONE_WIDTH, width // NAVIGATION_ZONE_DIVISIONS)``, so the fixed width wins on the
wide one and the eighth wins on the narrow one."""


# region fixtures
@fixture(autouse=True)
def loadable_image(mocker: MockerFixture) -> None:
    """Make every screenshot decode as a real image, with no file on disk.

    Patched at the source's own seam, which both the viewer's maximized copy and the row's thumbnails
    read through -- and honouring the height cap the way the real decode does, so a row thumbnail
    comes back row-sized rather than full-sized.

    :param mocker: pytest-mock fixture.
    """

    def load(index: int, max_height: int | None) -> QImage:
        del index
        height = IMAGE_HEIGHT if max_height is None else min(IMAGE_HEIGHT, max_height)
        return QImage(round(IMAGE_WIDTH * height / IMAGE_HEIGHT), height, QImage.Format.Format_RGB32)

    mocker.patch.object(PathImageSource, "load", side_effect=load)


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


def control(lightbox: ImageLightbox, name: str) -> QToolButton:
    """One of the viewer's named controls.

    :param lightbox: the viewer under test.
    :param name: the control's object name.
    :returns: that control.
    """
    button = lightbox.findChild(QToolButton, name)
    assert isinstance(button, QToolButton)
    return button


def overlay(lightbox: ImageLightbox, name: str) -> OverlayButton:
    """One of the viewer's named opacity-driven controls.

    :param lightbox: the viewer under test.
    :param name: the control's object name.
    :returns: that control, typed for its ``opacity()``.
    """
    button = lightbox.findChild(OverlayButton, name)
    assert isinstance(button, OverlayButton)
    return button


def strip_of(lightbox: ImageLightbox) -> ThumbnailRow:
    """The viewer's own thumbnail row.

    :param lightbox: the viewer under test.
    :returns: the row it hosts.
    """
    strip = lightbox.findChild(ThumbnailRow)
    assert isinstance(strip, ThumbnailRow)
    return strip


def info_of(lightbox: ImageLightbox) -> ImageInfoOverlay:
    """The viewer's info overlay (#221).

    :param lightbox: the viewer under test.
    :returns: the overlay.
    """
    info = lightbox.findChild(ImageInfoOverlay, INFO_OVERLAY_NAME)
    assert isinstance(info, ImageInfoOverlay)
    return info


def paths_of(lightbox: ImageLightbox) -> list[Path]:
    """The set the viewer navigates, as the paths it was opened over.

    :param lightbox: the viewer under test.
    :returns: the paths, in order.
    """
    source = lightbox.source
    return [source.key(index) for index in range(len(source))]  # type: ignore[misc]


def click_thumbnail(qtbot: QtBot, lightbox: ImageLightbox, index: int) -> None:
    """Click the thumbnail at ``index`` in the viewer's row, where the row lays it out.

    :param qtbot: pytest-qt fixture.
    :param lightbox: the viewer under test.
    :param index: the thumbnail's position.
    """
    row = strip_of(lightbox)
    model = row.model()
    assert model is not None
    qtbot.mouseClick(row.viewport(), Qt.MouseButton.LeftButton, pos=row.visualRect(model.index(index, 0)).center())


def open_viewer(
    images: list[Path], current: Path, mode: ImageViewerMode, document: QWidget, **kwargs: Any
) -> ImageLightbox:
    """Build a viewer over ``images``, opened on ``current``, the way the document opens one.

    :param images: the set to navigate.
    :param current: which of them to open on; one outside the set opens as a set of its own, which is
        the owner's rule (`DocumentWidget.__on_image_activated`) rather than the viewer's.
    :param mode: which surface to paint on.
    :param document: the document stand-in.
    :param kwargs: keyword arguments passed straight through to the viewer.
    :returns: the viewer, not yet revealed.
    """
    images = images if current in images else [current]
    return ImageLightbox(PathImageSource(images), images.index(current), mode, document, **kwargs)


WHEEL_STEP: Final = 120
"""One wheel notch, in eighths of a degree -- the unit Qt reports and every mouse produces."""


def send_wheel(target: QWidget, degrees: int) -> None:
    """Turn the wheel over ``target`` by ``degrees``, as a real mouse does.

    :param target: the widget under the pointer.
    :param degrees: the vertical wheel delta; negative is a downward turn.
    """
    position = QPointF(target.rect().center())
    QApplication.sendEvent(
        target,
        QWheelEvent(
            position,
            target.mapToGlobal(position),
            QPoint(0, 0),
            QPoint(0, degrees),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,  # noqa: FBT003  # positional-only in Qt's signature
        ),
    )


def reveal_over(document: QWidget, images: list[Path], current: Path, **kwargs: Any) -> ImageLightbox:
    """Reveal a document-overlay viewer over ``document``, opened on ``current``.

    :param document: the document stand-in to cover.
    :param images: the curated set to navigate.
    :param current: which of them to open on.
    :param kwargs: keyword arguments passed straight through to the viewer (``strip_visible``).
    :returns: the revealed viewer.
    """
    lightbox = open_viewer(images, current, ImageViewerMode.DOCUMENT_OVERLAY, document, **kwargs)
    lightbox.reveal()
    return lightbox


# endregion


def test_document_overlay_covers_the_document_it_belongs_to(document: QWidget, qtbot: QtBot) -> None:
    """The document overlay is a child of the document, sized to it -- never a window.

    **Test steps:**

    * reveal a viewer in document-overlay mode
    * verify it is parented to the document, is not a window, and covers the document's whole rect
    """
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.FULL_SCREEN, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()
    button = control(lightbox, CLOSE_BUTTON_NAME)

    with wait_destroyed(qtbot, lightbox):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_a_double_click_on_the_image_dismisses_the_viewer_when_allowed(document: QWidget, qtbot: QtBot) -> None:
    """A left double-click on the image closes the viewer -- the gesture that opened it -- when the
    owner allows it, which it does by default; refused, the double-click leaves the viewer up, and the
    owner can flip the answer on an open viewer (#221).

    **Test steps:**

    * reveal a viewer with the dismissal refused, double-click its middle and verify it stays up
    * allow it and verify a double-click destroys the viewer
    """
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document, double_click_closes=False)
    qtbot.addWidget(lightbox)
    lightbox.reveal()
    assert lightbox.double_click_closes is False

    qtbot.mouseDClick(lightbox, Qt.MouseButton.LeftButton, pos=lightbox.rect().center())
    assert not lightbox.isHidden()

    lightbox.set_double_click_closes(True)
    assert lightbox.double_click_closes is True
    with wait_destroyed(qtbot, lightbox):
        qtbot.mouseDClick(lightbox, Qt.MouseButton.LeftButton, pos=lightbox.rect().center())


def test_clicking_the_image_does_not_dismiss_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """A click on the image leaves the viewer up -- only ESC, the close button and a double-click dismiss.

    Regression: the two halves of the image are the prev/next affordance, so a click there must never
    also mean "close".

    **Test steps:**

    * reveal a viewer and left-click the middle of it
    * verify it is still shown
    """
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    lightbox.reveal()
    button = control(lightbox, CLOSE_BUTTON_NAME)

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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    first = open_viewer([PATH], PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
    qtbot.addWidget(first)
    first.reveal()
    second = open_viewer([PATH], PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
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
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.APP_WINDOW_OVERLAY, document)
    lightbox.reveal()

    with wait_destroyed(qtbot, lightbox):
        document.deleteLater()


def test_a_full_screen_viewer_dies_with_its_document(document: QWidget, qtbot: QtBot) -> None:
    """A full-screen viewer is destroyed with the document, never orphaned on top of the desktop.

    **Test steps:**

    * reveal a full-screen viewer, then destroy the document it belongs to
    * verify the viewer is destroyed too
    """
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.FULL_SCREEN, document)
    lightbox.reveal()

    with wait_destroyed(qtbot, lightbox):
        document.deleteLater()


def test_the_screenshot_is_scaled_to_fit_preserving_aspect(document: QWidget, qtbot: QtBot) -> None:
    """The screenshot is painted scaled to fit the viewer, keeping its aspect ratio.

    **Test steps:**

    * reveal a document overlay over a sized document, with a 16:9 source
    * verify the rendered pixmap fits inside the viewer and keeps 16:9
    """
    lightbox = open_viewer([PATH], PATH, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)

    lightbox.reveal()

    preview = lightbox.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)
    pixmap = preview.pixmap()
    assert pixmap.width() <= lightbox.width()
    assert pixmap.height() <= lightbox.height()
    assert abs(pixmap.width() / pixmap.height() - 320 / 180) < 0.05


# region navigation tests (#161)
def test_the_right_key_shows_the_next_screenshot(document: QWidget, qtbot: QtBot) -> None:
    """RIGHT moves one forward through the curated set.

    **Test steps:**

    * reveal a viewer opened on the first of three screenshots
    * press RIGHT
    * verify the second one is now shown
    """
    lightbox = reveal_over(document, PATHS, PATHS[0])
    qtbot.addWidget(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_Right)

    assert lightbox.current_key == PATHS[1]


def test_the_left_key_shows_the_previous_screenshot(document: QWidget, qtbot: QtBot) -> None:
    """LEFT moves one back through the curated set.

    **Test steps:**

    * reveal a viewer opened on the last of three screenshots
    * press LEFT
    * verify the middle one is now shown
    """
    lightbox = reveal_over(document, PATHS, PATHS[2])
    qtbot.addWidget(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_Left)

    assert lightbox.current_key == PATHS[1]


def test_home_and_end_jump_to_the_ends_of_the_set(document: QWidget, qtbot: QtBot) -> None:
    """HOME and END go straight to the first and last screenshots.

    **Test steps:**

    * reveal a viewer opened on the middle of three screenshots
    * press END, then HOME
    * verify each landed on the matching end
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_End)
    assert lightbox.current_key == PATHS[2]

    qtbot.keyClick(lightbox, Qt.Key.Key_Home)
    assert lightbox.current_key == PATHS[0]


def test_navigation_stops_at_the_ends_rather_than_wrapping(document: QWidget, qtbot: QtBot) -> None:
    """Stepping past either end leaves the viewer where it is -- the set does not wrap.

    The end behaviour is a deliberate choice (#161): a wrap makes a three-image set feel endless, and
    the ends are where its shape is legible.

    **Test steps:**

    * reveal a viewer on the first screenshot and press LEFT
    * jump to the last and press RIGHT
    * verify neither moved
    """
    lightbox = reveal_over(document, PATHS, PATHS[0])
    qtbot.addWidget(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_Left)
    assert lightbox.current_key == PATHS[0]

    qtbot.keyClick(lightbox, Qt.Key.Key_End)
    qtbot.keyClick(lightbox, Qt.Key.Key_Right)
    assert lightbox.current_key == PATHS[2]


def test_pressing_a_hover_band_steps_through_the_set(document: QWidget, qtbot: QtBot) -> None:
    """The prev/next bands step exactly like the keys do (#161).

    **Test steps:**

    * reveal a viewer on the middle screenshot
    * click the next band, then the previous band
    * verify each moved one position
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    qtbot.mouseClick(control(lightbox, NEXT_BUTTON_NAME), Qt.MouseButton.LeftButton)
    assert lightbox.current_key == PATHS[2]

    qtbot.mouseClick(control(lightbox, PREVIOUS_BUTTON_NAME), Qt.MouseButton.LeftButton)
    assert lightbox.current_key == PATHS[1]


def test_a_hover_band_leaves_the_keyboard_with_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """Clicking a band does not take focus, so the keys keep working afterwards.

    Regression: a focusable control inside the viewer would swallow the keyboard, and ESC (and every
    navigation key) would then reach nothing.

    **Test steps:**

    * reveal a viewer and click its next band
    * verify the viewer still holds focus, and RIGHT still navigates
    """
    lightbox = reveal_over(document, PATHS, PATHS[0])
    qtbot.addWidget(lightbox)

    qtbot.mouseClick(control(lightbox, NEXT_BUTTON_NAME), Qt.MouseButton.LeftButton)

    assert lightbox.hasFocus()
    qtbot.keyClick(lightbox, Qt.Key.Key_Right)
    assert lightbox.current_key == PATHS[2]


def test_a_hover_band_is_hidden_at_the_end_it_points_past(document: QWidget, qtbot: QtBot) -> None:
    """With nothing to navigate to, the matching band is not there at all (#161).

    Hidden rather than merely faded out: an inert band would still swallow clicks over that edge of
    the screenshot.

    **Test steps:**

    * reveal a viewer on the first screenshot
    * verify the previous band is hidden and the next one is not
    * step to the last screenshot and verify the two swap
    """
    lightbox = reveal_over(document, PATHS, PATHS[0])
    qtbot.addWidget(lightbox)
    previous = control(lightbox, PREVIOUS_BUTTON_NAME)
    following = control(lightbox, NEXT_BUTTON_NAME)

    assert previous.isHidden()
    assert not following.isHidden()

    qtbot.keyClick(lightbox, Qt.Key.Key_End)

    assert not previous.isHidden()
    assert following.isHidden()


def test_a_single_screenshot_shows_no_hover_bands_at_all(document: QWidget, qtbot: QtBot) -> None:
    """A set of one has neither a previous nor a next, so neither band exists to hover.

    **Test steps:**

    * reveal a viewer over a single-screenshot set
    * verify both bands are hidden
    """
    lightbox = reveal_over(document, [PATH], PATH)
    qtbot.addWidget(lightbox)

    assert control(lightbox, PREVIOUS_BUTTON_NAME).isHidden()
    assert control(lightbox, NEXT_BUTTON_NAME).isHidden()


def test_a_hover_band_is_invisible_until_the_mouse_enters_it(document: QWidget, qtbot: QtBot) -> None:
    """A band shows nothing until hovered, then a faint hint, and nothing again once left (#161).

    **Test steps:**

    * reveal a viewer with a next band available
    * send it a real enter event, then a leave event
    * verify the opacity went idle -> hover -> idle
    """
    lightbox = reveal_over(document, PATHS, PATHS[0])
    qtbot.addWidget(lightbox)
    band = overlay(lightbox, NEXT_BUTTON_NAME)
    assert band.opacity() == NAVIGATION_IDLE_OPACITY

    inside = QPointF(band.rect().center())
    QApplication.sendEvent(band, QEnterEvent(inside, inside, inside))
    assert band.opacity() == NAVIGATION_HOVER_OPACITY

    QApplication.sendEvent(band, QEvent(QEvent.Type.Leave))
    assert band.opacity() == NAVIGATION_IDLE_OPACITY


def test_a_hover_band_brightens_while_it_is_held_down(document: QWidget, qtbot: QtBot) -> None:
    """A band is near-solid while pressed, and settles back once released (#161).

    **Test steps:**

    * reveal a viewer with a next band available and press that band
    * verify it is at the pressed opacity, and back below it after the release
    """
    lightbox = reveal_over(document, PATHS, PATHS[0])
    qtbot.addWidget(lightbox)
    band = overlay(lightbox, NEXT_BUTTON_NAME)

    qtbot.mousePress(band, Qt.MouseButton.LeftButton)
    assert band.opacity() == NAVIGATION_PRESSED_OPACITY

    qtbot.mouseRelease(band, Qt.MouseButton.LeftButton)
    assert band.opacity() < NAVIGATION_PRESSED_OPACITY


def test_the_hover_bands_are_a_fixed_width_along_each_edge(document: QWidget, qtbot: QtBot) -> None:
    """Each band is a fixed-width strip pinned to its own edge of a wide viewer (#161).

    **Test steps:**

    * reveal a viewer over a comfortably wide document
    * verify each band is :data:`NAVIGATION_ZONE_WIDTH` wide against its own edge
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    document.resize(WIDE_VIEWER_WIDTH, 400)

    previous = control(lightbox, PREVIOUS_BUTTON_NAME)
    following = control(lightbox, NEXT_BUTTON_NAME)
    assert previous.geometry().x() == 0
    assert previous.width() == NAVIGATION_ZONE_WIDTH
    assert following.width() == NAVIGATION_ZONE_WIDTH
    assert following.geometry().right() == lightbox.width() - 1


def test_the_hover_bands_take_an_eighth_of_a_narrow_viewer(document: QWidget, qtbot: QtBot) -> None:
    """Below the narrow threshold the bands scale down instead of swallowing the screenshot (#161).

    **Test steps:**

    * reveal a viewer and shrink the document below the narrow threshold
    * verify each band is an eighth of the viewer's width
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    document.resize(NARROW_VIEWER_WIDTH, 400)

    assert control(lightbox, PREVIOUS_BUTTON_NAME).width() == lightbox.width() // NAVIGATION_ZONE_DIVISIONS
    assert control(lightbox, NEXT_BUTTON_NAME).width() == lightbox.width() // NAVIGATION_ZONE_DIVISIONS


def test_the_hover_bands_stop_above_the_thumbnail_row(document: QWidget, qtbot: QtBot) -> None:
    """A shown thumbnail row shortens the bands, so they never cover a thumbnail (#161).

    Regression: a full-height band would sit over the row's own left/right ends and swallow the clicks
    meant for the thumbnails there.

    **Test steps:**

    * reveal a viewer with the row hidden and verify a band spans the full height
    * show the row and verify the band now stops above it
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    band = control(lightbox, NEXT_BUTTON_NAME)
    assert band.height() == lightbox.height()

    control(lightbox, STRIP_TOGGLE_BUTTON_NAME).setChecked(True)

    assert band.height() == lightbox.height() - DEFAULT_STRIP_HEIGHT


# endregion


# region thumbnail row tests (#161)
def test_the_thumbnail_row_follows_the_setting_it_was_opened_with(document: QWidget, qtbot: QtBot) -> None:
    """The row starts hidden or shown as the owner's stored preference asks (#161).

    **Test steps:**

    * reveal one viewer left at the default and one opened with the row shown
    * verify each row's visibility matches
    """
    default = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(default)
    shown = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(shown)

    assert strip_of(default).isHidden()
    assert not strip_of(shown).isHidden()


def test_opening_on_a_stored_preference_is_not_reported_as_a_change(document: QWidget, qtbot: QtBot) -> None:
    """Merely opening on the stored preference reports nothing -- only the user toggling does.

    Regression: seeding a checkable button emits ``toggled``, which would write the preference straight
    back on every single opening.

    **Test steps:**

    * connect to ``strip_visible_changed`` before revealing a viewer with the row shown
    * verify nothing was reported
    """
    lightbox = open_viewer(PATHS, PATHS[1], ImageViewerMode.DOCUMENT_OVERLAY, document, strip_visible=True)
    qtbot.addWidget(lightbox)
    reported: list[bool] = []
    lightbox.strip_visible_changed.connect(reported.append)

    lightbox.reveal()

    assert not reported


def test_the_row_toggle_shows_the_row_and_reports_the_choice(document: QWidget, qtbot: QtBot) -> None:
    """The corner toggle shows and hides the row, reporting each change for the owner to persist.

    **Test steps:**

    * reveal a viewer with the row hidden and click its toggle twice
    * verify the row followed, and both changes were reported
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    reported: list[bool] = []
    lightbox.strip_visible_changed.connect(reported.append)
    toggle = control(lightbox, STRIP_TOGGLE_BUTTON_NAME)

    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)
    assert not strip_of(lightbox).isHidden()
    assert lightbox.strip_visible

    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)
    assert strip_of(lightbox).isHidden()
    assert reported == [True, False]


def test_the_t_key_toggles_the_row_like_its_button(document: QWidget, qtbot: QtBot) -> None:
    """``T`` shows and hides the thumbnail row through its toggle, so the choice is reported for the
    owner to remember exactly as a click on the button is (#221).

    **Test steps:**

    * reveal a viewer with the row hidden and press ``T`` twice
    * verify the row came and went, and both changes were reported
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    reported: list[bool] = []
    lightbox.strip_visible_changed.connect(reported.append)

    qtbot.keyClick(lightbox, Qt.Key.Key_T)
    assert lightbox.strip_visible
    assert not strip_of(lightbox).isHidden()

    qtbot.keyClick(lightbox, Qt.Key.Key_T)
    assert not lightbox.strip_visible
    assert reported == [True, False]


@mark.parametrize("name", [STRIP_TOGGLE_BUTTON_NAME, CLOSE_BUTTON_NAME, INFO_TOGGLE_BUTTON_NAME])
def test_a_corner_control_is_absent_until_hovered(document: QWidget, qtbot: QtBot, name: str) -> None:
    """The three corner controls behave like the prev/next bands: nothing at all until the mouse is
    over them, solid while it is, whatever state they are in (#221).

    **Test steps:**

    * reveal a viewer and check the control's opacity at rest and with its state flipped
    * enter it and verify it appeared; leave it and verify it went
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    control = overlay(lightbox, name)
    assert control.opacity() == NAVIGATION_IDLE_OPACITY
    if control.isCheckable():
        control.setChecked(not control.isChecked())
        assert control.opacity() == NAVIGATION_IDLE_OPACITY

    QApplication.sendEvent(control, QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))
    assert control.opacity() == CORNER_HOVER_OPACITY

    QApplication.sendEvent(control, QEvent(QEvent.Type.Leave))
    assert control.opacity() == NAVIGATION_IDLE_OPACITY


def test_the_thumbnail_row_shows_no_scrollbars(document: QWidget, qtbot: QtBot) -> None:
    """The row scrolls programmatically, with no bar of its own painted on the backdrop (#161).

    **Test steps:**

    * reveal a viewer with the row shown
    * verify both scrollbar policies suppress the bar outright
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(lightbox)
    strip = strip_of(lightbox)

    assert strip.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert strip.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_the_row_lists_the_whole_curated_set(document: QWidget, qtbot: QtBot) -> None:
    """Every screenshot in the set gets a thumbnail, not just the current one.

    **Test steps:**

    * reveal a viewer over three screenshots with the row shown
    * verify the row lists three
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(lightbox)
    model = strip_of(lightbox).model()

    assert model is not None
    assert model.rowCount() == len(PATHS)


def test_the_current_screenshots_thumbnail_is_the_framed_one(document: QWidget, qtbot: QtBot) -> None:
    """The row marks which screenshot is being shown, and re-marks as navigation moves (#161).

    **Test steps:**

    * reveal a viewer on the middle screenshot with the row shown
    * verify that position is the framed one
    * step forward and verify the mark moved with it
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(lightbox)

    assert strip_of(lightbox).current_index == 1

    qtbot.keyClick(lightbox, Qt.Key.Key_Right)

    assert strip_of(lightbox).current_index == 2


def test_a_stale_thumbnail_activation_moves_nothing(document: QWidget, qtbot: QtBot) -> None:
    """A thumbnail reporting a position the set no longer holds leaves the viewer where it is.

    **Test steps:**

    * reveal a viewer with the row shown and have the row report a position outside the set
    * verify the current screenshot did not move
    """
    lightbox = reveal_over(document, PATHS, PATHS[0], strip_visible=True)
    qtbot.addWidget(lightbox)

    strip_of(lightbox).activated_index.emit(len(PATHS))

    assert lightbox.current_key == PATHS[0]


def test_clicking_a_thumbnail_jumps_to_that_screenshot(document: QWidget, qtbot: QtBot) -> None:
    """A thumbnail in the viewer's own row jumps straight to its screenshot (#161).

    **Test steps:**

    * reveal a viewer on the first screenshot with the row shown
    * click the last thumbnail
    * verify that screenshot is now the current one
    """
    lightbox = reveal_over(document, PATHS, PATHS[0], strip_visible=True)
    qtbot.addWidget(lightbox)

    click_thumbnail(qtbot, lightbox, len(PATHS) - 1)

    assert lightbox.current_key == PATHS[-1]


# endregion


# region live curated set tests (#161)
def test_a_rebuilt_set_keeps_the_screenshot_on_screen(document: QWidget, qtbot: QtBot) -> None:
    """A curation edit that spares the current screenshot leaves the viewer on it.

    **Test steps:**

    * reveal a viewer on the last of three screenshots
    * re-point it at a set with the first one curated away
    * verify it is still showing the same screenshot, now with the shorter set around it
    """
    lightbox = reveal_over(document, PATHS, PATHS[2])
    qtbot.addWidget(lightbox)

    lightbox.set_source(PathImageSource(PATHS[1:]))

    assert lightbox.current_key == PATHS[2]
    assert paths_of(lightbox) == PATHS[1:]


def test_a_rebuilt_set_falls_back_to_the_position_when_the_screenshot_goes(document: QWidget, qtbot: QtBot) -> None:
    """Hiding the screenshot being shown moves the viewer to whatever now holds its position.

    Regression: an open viewer that kept rendering a screenshot the user had just curated *out* of the
    lightbox would be showing something the strip no longer offers.

    **Test steps:**

    * reveal a viewer on the middle of three screenshots
    * re-point it at a set with that one curated away
    * verify it moved to the screenshot that took its position
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    lightbox.set_source(PathImageSource([PATHS[0], PATHS[2]]))

    assert lightbox.current_key == PATHS[2]


def test_a_rebuilt_set_clamps_when_the_last_screenshot_goes(document: QWidget, qtbot: QtBot) -> None:
    """Losing the *last* screenshot lands on the new last one rather than off the end.

    **Test steps:**

    * reveal a viewer on the last of three screenshots
    * re-point it at a set that drops the last two
    * verify it clamped to the only screenshot left
    """
    lightbox = reveal_over(document, PATHS, PATHS[2])
    qtbot.addWidget(lightbox)

    lightbox.set_source(PathImageSource(PATHS[:1]))

    assert lightbox.current_key == PATHS[0]


def test_an_emptied_set_dismisses_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """Curating away every screenshot leaves nothing to look at, so the viewer dismisses itself.

    **Test steps:**

    * reveal a viewer, then re-point it at an empty set
    * verify it is destroyed
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])

    with wait_destroyed(qtbot, lightbox):
        lightbox.set_source(PathImageSource([]))


def test_a_rebuilt_set_repaints_the_thumbnail_row(document: QWidget, qtbot: QtBot) -> None:
    """The row follows the rebuilt set, keeping the current screenshot marked (#161).

    **Test steps:**

    * reveal a viewer on the last of three screenshots with the row shown
    * re-point it at a set with the first curated away
    * verify the row lists the shorter set with the same screenshot framed
    """
    lightbox = reveal_over(document, PATHS, PATHS[2], strip_visible=True)
    qtbot.addWidget(lightbox)

    lightbox.set_source(PathImageSource(PATHS[1:]))

    row = strip_of(lightbox)
    model = row.model()
    assert model is not None
    assert model.rowCount() == 2
    assert row.current_index == 1


def test_a_position_past_the_end_opens_on_the_last_image(document: QWidget, qtbot: QtBot) -> None:
    """A viewer always has something to show: an opening position outside the set is clamped into it.

    **Test steps:**

    * build a viewer asked to open past the end of a three-image set
    * verify it opened on the last one
    """
    lightbox = ImageLightbox(PathImageSource(PATHS), len(PATHS) + 5, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    assert lightbox.current_key == PATHS[-1]


def test_an_empty_source_opens_showing_nothing(document: QWidget, qtbot: QtBot) -> None:
    """A viewer over nothing has no current image and paints no bands, and does not raise.

    **Test steps:**

    * build a viewer over an empty source and reveal it
    * verify it has no current key and both bands are hidden
    """
    lightbox = ImageLightbox(PathImageSource([]), 0, ImageViewerMode.DOCUMENT_OVERLAY, document)
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    assert lightbox.current_key is None
    assert control(lightbox, NEXT_BUTTON_NAME).isHidden()
    assert control(lightbox, PREVIOUS_BUTTON_NAME).isHidden()


# endregion


# region info overlay tests (#221)
def test_the_info_overlay_is_hidden_unless_opened_with_it(document: QWidget, qtbot: QtBot) -> None:
    """The overlay starts hidden by default and shown when the owner asks (#221).

    **Test steps:**

    * reveal one viewer left at the default and one opened with the overlay shown
    * verify each overlay's visibility matches
    """
    default = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(default)
    shown = reveal_over(document, PATHS, PATHS[1], info_visible=True)
    qtbot.addWidget(shown)

    assert info_of(default).isHidden()
    assert not default.info_visible
    assert not info_of(shown).isHidden()
    assert shown.info_visible


def test_the_i_key_toggles_the_info_overlay(document: QWidget, qtbot: QtBot) -> None:
    """``I`` shows the overlay and hides it again, for this viewer alone (#221).

    **Test steps:**

    * reveal a viewer and press ``I`` twice
    * verify the overlay came and went
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_I)
    assert lightbox.info_visible

    qtbot.keyClick(lightbox, Qt.Key.Key_I)
    assert not lightbox.info_visible


def test_the_info_overlay_names_the_image_its_pixels_and_its_bytes(
    document: QWidget, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """The overlay carries the image's path, ``W × H px`` and its stored size, and follows navigation.

    **Test steps:**

    * make the fake files report a size on disk and reveal a viewer with the overlay shown
    * verify the three lines
    * step forward and verify the path line moved with it
    """
    mocker.patch.object(Path, "stat", return_value=mocker.Mock(st_size=1_500_000))
    lightbox = reveal_over(document, PATHS, PATHS[1], info_visible=True)
    qtbot.addWidget(lightbox)

    assert info_of(lightbox).text() == f"{PATHS[1]}\n{IMAGE_WIDTH} × {IMAGE_HEIGHT} px\n1.5 MB"

    qtbot.keyClick(lightbox, Qt.Key.Key_Right)

    assert info_of(lightbox).text().startswith(str(PATHS[2]))


def test_the_info_overlay_elides_a_path_wider_than_the_viewer(
    document: QWidget, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A line wider than the viewer allows is middle-elided, so the box never runs off the edge; the
    bound follows the viewer's own width (#221).

    **Test steps:**

    * reveal a viewer with the overlay shown over an image whose path is very long
    * verify the path line is elided and the box fits inside the viewer's margins
    * bound the box by hand to nothing and verify the full path comes back
    """
    mocker.patch.object(Path, "stat", return_value=mocker.Mock(st_size=1_000))
    long_path = Path("/fake/" + "/".join(["folder"] * 60) + "/info.png")
    lightbox = reveal_over(document, [long_path], long_path, info_visible=True)
    qtbot.addWidget(lightbox)
    info = info_of(lightbox)
    # a size of this test's own, rather than whatever the document stand-in has settled at by now
    lightbox.resize(400, 300)
    qtbot.waitUntil(lambda: info.width() <= 400 - 2 * CORNER_MARGIN)

    path_line = info.text().split("\n")[0]
    assert path_line != str(long_path)
    assert "…" in path_line

    info.set_max_width(0)
    assert info.text().split("\n")[0] == str(long_path)


def test_the_info_overlay_says_when_the_file_size_is_unknown(
    document: QWidget, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A file that cannot be stat'ed reads as size unknown rather than raising (#221).

    **Test steps:**

    * make every stat fail as an offline mount's does, and reveal a viewer with the overlay shown
    * verify the third line says so
    """
    mocker.patch.object(Path, "stat", side_effect=OSError("offline"))
    lightbox = reveal_over(document, PATHS, PATHS[1], info_visible=True)
    qtbot.addWidget(lightbox)

    assert info_of(lightbox).text().endswith("file size unknown")


def test_the_info_overlay_sits_in_the_top_left_corner_and_takes_no_clicks(document: QWidget, qtbot: QtBot) -> None:
    """The overlay is anchored top-left over the image and is transparent to the mouse, so the prev
    band under it still answers (#221).

    **Test steps:**

    * reveal a viewer with the overlay shown
    * verify it sits at the viewer's top-left and ignores mouse events
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], info_visible=True)
    qtbot.addWidget(lightbox)
    info = info_of(lightbox)

    assert info.mapTo(lightbox, QPoint(0, 0)) == QPoint(CORNER_MARGIN, CORNER_MARGIN)
    assert info.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_hovering_a_thumbnail_names_it_in_a_box_above_the_row(
    document: QWidget, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """The pointer over a thumbnail shows the image's path and stored size in a box stacked over the
    row's toggle -- at once, and with no pixel line, since the thumbnail was never decoded at full size;
    leaving the row hides the box (#221).

    **Test steps:**

    * reveal a viewer with its row shown and verify the hover box is hidden
    * move the pointer onto the first thumbnail and verify the box shows its path and size, a corner
      margin in from the bottom-left of the image area -- over the row's toggle, which it paints above
    * take the pointer out of the row and verify the box is hidden
    """
    mocker.patch.object(Path, "stat", return_value=mocker.Mock(st_size=2_000))
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(lightbox)
    hover = lightbox.findChild(ImageInfoOverlay, HOVER_INFO_NAME)
    assert isinstance(hover, ImageInfoOverlay)
    row = lightbox.findChild(ThumbnailRow)
    assert isinstance(row, ThumbnailRow)
    model = row.model()
    assert model is not None
    # the pointer may have been left over the row's place by an earlier test, in which case the box
    # is rightly up already -- and a synthetic move elsewhere sends the row no Leave, as a real one
    # would: take it out of the row explicitly first
    QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
    assert hover.isHidden()

    qtbot.mouseMove(row.viewport(), row.visualRect(model.index(0, 0)).center())
    qtbot.waitUntil(lambda: not hover.isHidden())

    assert hover.text() == f"{PATHS[0]}\n2.0 kB"
    bottom_left = hover.mapTo(lightbox, QPoint(0, hover.height()))
    assert bottom_left == QPoint(CORNER_MARGIN, row.geometry().top() - CORNER_MARGIN)
    toggle = control(lightbox, STRIP_TOGGLE_BUTTON_NAME)
    hover_rect = QRect(hover.mapTo(lightbox, QPoint(0, 0)), hover.size())
    assert hover_rect.intersects(toggle.geometry())
    assert hover.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    QApplication.sendEvent(row, QEvent(QEvent.Type.Leave))
    assert hover.isHidden()


def test_the_info_toggle_sits_under_the_box_and_toggles_it(document: QWidget, qtbot: QtBot) -> None:
    """The corner toggle shows and hides the overlay -- and while the box is shown, sits directly
    below it, where the pointer goes to dismiss what it is reading (#221).

    **Test steps:**

    * reveal a viewer with the overlay shown and verify the toggle is checked and directly below the box
    * click the toggle and verify the box went and the toggle took its place in the corner
    * press ``I`` and verify the toggle reads checked again
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], info_visible=True)
    qtbot.addWidget(lightbox)
    toggle = control(lightbox, INFO_TOGGLE_BUTTON_NAME)
    info = info_of(lightbox)
    assert toggle.isChecked()
    assert toggle.mapTo(lightbox, QPoint(0, 0)).y() > info.mapTo(lightbox, QPoint(0, info.height())).y()

    qtbot.mouseClick(toggle, Qt.MouseButton.LeftButton)
    assert not lightbox.info_visible
    assert info.isHidden()
    qtbot.waitUntil(lambda: toggle.mapTo(lightbox, QPoint(0, 0)) == QPoint(CORNER_MARGIN, CORNER_MARGIN))

    qtbot.keyClick(lightbox, Qt.Key.Key_I)
    assert toggle.isChecked()
    assert lightbox.info_visible


def test_the_backdrop_is_opaque_and_follows_the_owner(document: QWidget, qtbot: QtBot, mocker: MockerFixture) -> None:
    """The viewer paints an opaque backdrop -- the default neutral grey, or whatever the owner names --
    and repaints when told a new one (#221).

    **Test steps:**

    * reveal a viewer with no backdrop named and verify it paints the default, opaque
    * set a new backdrop and verify a corner pixel takes it
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    corner = QPoint(lightbox.width() // 2, lightbox.height() - 2)
    assert lightbox.backdrop == QColor(DEFAULT_BACKDROP)
    assert lightbox.backdrop.alpha() == 255
    assert lightbox.grab().toImage().pixelColor(corner).name() == DEFAULT_BACKDROP

    lightbox.set_backdrop(QColor("#336699"))
    assert lightbox.grab().toImage().pixelColor(corner).name() == "#336699"

    # the colour it already has is a no-op, not a repaint
    repainted = mocker.spy(lightbox, "update")
    lightbox.set_backdrop(QColor("#336699"))
    repainted.assert_not_called()


# endregion


def test_the_screenshot_reaches_every_edge_of_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """Nothing is inset around the screenshot -- it gets the viewer's whole area (#161).

    **Test steps:**

    * reveal a viewer with the thumbnail row hidden
    * verify the label painting the screenshot covers the viewer exactly
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    preview = lightbox.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)
    assert preview.geometry() == lightbox.rect()


def test_the_screenshot_takes_every_pixel_the_thumbnail_row_leaves(document: QWidget, qtbot: QtBot) -> None:
    """With the row shown, the screenshot still reaches all three other edges and meets the row (#161).

    **Test steps:**

    * reveal a viewer with the row shown
    * verify the screenshot fills the viewer down to the row, with no gap between them
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(lightbox)

    preview = lightbox.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)
    strip = strip_of(lightbox)
    assert preview.geometry().topLeft() == lightbox.rect().topLeft()
    assert preview.width() == lightbox.width()
    assert preview.geometry().bottom() + 1 == strip.geometry().top()
    assert strip.geometry().bottom() == lightbox.rect().bottom()


def test_the_corner_controls_are_held_off_the_edge(document: QWidget, qtbot: QtBot) -> None:
    """The corner controls keep their own margin, even though the screenshot under them has none.

    Each sits flush in its corner and carries the margin *inside* itself -- a stylesheet margin, which
    grows the control around its glyph rather than moving the control -- so the screenshot underneath
    is still free to reach the viewer's every edge.

    **Test steps:**

    * reveal a viewer with the corner controls in place
    * verify each is anchored to its own corner and carries the margin around its glyph
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    toggle = control(lightbox, STRIP_TOGGLE_BUTTON_NAME)
    close = control(lightbox, CLOSE_BUTTON_NAME)
    info_toggle = control(lightbox, INFO_TOGGLE_BUTTON_NAME)
    inset = CORNER_ICON_SIZE + 2 * CORNER_MARGIN
    assert toggle.geometry().bottomLeft() == lightbox.rect().bottomLeft()
    assert toggle.width() >= inset
    assert toggle.height() >= inset
    assert close.geometry().right() == lightbox.rect().right()
    assert close.geometry().top() == lightbox.rect().top()
    assert close.width() >= inset
    # the info toggle's corner stack carries its margin: the glyph sits a margin in from the corner
    assert info_toggle.mapTo(lightbox, QPoint(0, 0)) == QPoint(CORNER_MARGIN, CORNER_MARGIN)


def test_the_thumbnail_row_is_as_tall_as_it_was_built(document: QWidget, qtbot: QtBot) -> None:
    """The row takes the height its owner asked for, and the bands stop above exactly that (#161).

    **Test steps:**

    * reveal a viewer with a non-default row height and the row shown
    * verify the row is that tall and the next band stops above it
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True, strip_height=120)
    qtbot.addWidget(lightbox)

    assert strip_of(lightbox).height() == 120
    assert control(lightbox, NEXT_BUTTON_NAME).height() == lightbox.height() - 120


def test_the_viewer_takes_the_keyboard_back_when_focus_goes_nowhere(document: QWidget, qtbot: QtBot) -> None:
    """Focus cleared without moving anywhere is reclaimed, so ESC keeps working (#161).

    Regression: dragging a splitter between two docks clears the keyboard without moving it to any
    widget at all. The viewer stayed up covering its document with ESC reaching nobody, and no dock
    change for `DocumentsDock` to notice either -- so the tab still read as current, and only
    re-selecting it brought the keyboard back.

    **Test steps:**

    * reveal an overlay and clear the focus it holds, as a splitter drag does
    * verify it took the keyboard back, and that ESC still dismisses it
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    assert lightbox.hasFocus()

    lightbox.clearFocus()

    assert lightbox.hasFocus()
    with wait_destroyed(qtbot, lightbox):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)


def test_a_viewer_that_did_not_hold_the_keyboard_does_not_snatch_at_it(
    document: QWidget, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Focus going nowhere from *elsewhere* is left alone -- only what this viewer had is reclaimed.

    **Test steps:**

    * reveal an overlay, then move focus to a widget outside the document it covers
    * clear that widget's focus and verify the viewer never reached for it
    """
    outsider = QLineEdit(document.window())
    outsider.show()
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    outsider.setFocus()
    assert not lightbox.hasFocus()
    reclaim = mocker.patch.object(lightbox, "setFocus")

    outsider.clearFocus()

    reclaim.assert_not_called()


def test_the_viewer_takes_the_keyboard_back_from_a_container_holding_its_document(
    document: QWidget, qtbot: QtBot
) -> None:
    """Focus landing on a container *around* the covered document is reclaimed (#161).

    Regression: dragging a splitter between two docks hands the keyboard to one of the containers
    holding the document -- its dock, that dock's area, the splitter, the dock manager -- none of
    which is under the covered surface. The viewer stayed up with ESC reaching nobody, and since the
    current dock never changed, `DocumentsDock` had nothing to notice: the tab still read as current
    and only re-selecting it brought the keyboard back.

    **Test steps:**

    * reveal an overlay, then focus the container the covered document sits in, as that drag does
    * verify the viewer took the keyboard back and ESC still dismisses it
    """
    container = document.parentWidget()
    assert container is not None
    container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    lightbox = reveal_over(document, PATHS, PATHS[1])
    assert lightbox.hasFocus()

    container.setFocus()

    assert lightbox.hasFocus()
    with wait_destroyed(qtbot, lightbox):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)


def test_a_viewer_leaves_focus_alone_when_it_lands_somewhere_unrelated(document: QWidget, qtbot: QtBot) -> None:
    """Focus moving somewhere off this document's containment line is the user navigating away.

    A sibling widget -- another document, the app's chrome, a settings dialog -- is neither under the
    covered surface nor a container holding it, so the viewer must not drag the keyboard back out of
    it.

    **Test steps:**

    * reveal an overlay, then focus a widget that is a sibling of the covered document
    * verify the viewer left it alone
    """
    sibling = QLineEdit()
    container = document.parentWidget()
    assert container is not None
    layout = container.layout()
    assert layout is not None
    layout.addWidget(sibling)
    sibling.show()
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    sibling.setFocus()

    assert sibling.hasFocus()
    assert not lightbox.hasFocus()


def test_re_applying_the_row_height_it_already_has_changes_nothing(
    document: QWidget, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """A height the viewer is already at is a no-op, not a needless row re-layout (#161).

    **Test steps:**

    * reveal a viewer with the row shown and re-apply its current height
    * verify the row was never asked to resize
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True, strip_height=120)
    qtbot.addWidget(lightbox)
    resized = mocker.spy(strip_of(lightbox), "set_height")

    lightbox.set_strip_height(120)

    resized.assert_not_called()


def test_the_row_toggle_sits_with_the_row_it_opens(document: QWidget, qtbot: QtBot) -> None:
    """The toggle rides the bottom of the screenshot: above the row, or in the corner without it.

    **Test steps:**

    * reveal a viewer with the row shown and verify the toggle sits directly above it
    * hide the row and verify the toggle drops to the viewer's own bottom-left corner
    """
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(lightbox)
    toggle = control(lightbox, STRIP_TOGGLE_BUTTON_NAME)

    assert toggle.geometry().left() == lightbox.rect().left()
    assert toggle.geometry().bottom() + 1 == strip_of(lightbox).geometry().top()

    toggle.setChecked(False)

    # the layout re-runs on the next event-loop turn, so the drop is not instantaneous
    qtbot.waitUntil(lambda: toggle.geometry().bottomLeft() == lightbox.rect().bottomLeft())


def test_clicking_a_thumbnail_does_not_also_step_the_viewer(document: QWidget, qtbot: QtBot) -> None:
    """A thumbnail click jumps to that screenshot and stops there (#161).

    Regression: the old row's ``QLabel`` thumbnails ignored mouse events, so the click propagated past
    the thumbnail to the viewer, which read a click on itself as prev/next. Since the row starts at
    the left edge, that extra step was almost always "previous" -- so clicking any thumbnail right of
    the current one landed on it and bounced straight back.

    **Test steps:**

    * reveal a viewer on the first screenshot with its row shown
    * click the second thumbnail, which sits left of the viewer's own centre
    * verify the viewer settled on that screenshot rather than stepping back off it
    """
    lightbox = reveal_over(document, PATHS, PATHS[0], strip_visible=True)
    qtbot.addWidget(lightbox)
    row = strip_of(lightbox)
    model = row.model()
    assert model is not None
    second = row.visualRect(model.index(1, 0))
    assert row.viewport().mapTo(lightbox, second.center()).x() < lightbox.rect().center().x()

    click_thumbnail(qtbot, lightbox, 1)

    assert lightbox.current_key == PATHS[1]


def test_the_wheel_over_the_screenshot_steps_through_the_set(document: QWidget, qtbot: QtBot) -> None:
    """Wheeling over the screenshot moves through the curated set, down for forward (#161).

    **Test steps:**

    * reveal a viewer on the middle screenshot
    * wheel down, then up
    * verify each moved one position, in the direction a list moves under the same gesture
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    send_wheel(lightbox, -WHEEL_STEP)
    assert lightbox.current_key == PATHS[2]

    send_wheel(lightbox, WHEEL_STEP)
    assert lightbox.current_key == PATHS[1]


def test_the_wheel_stops_at_the_ends_like_every_other_step(document: QWidget, qtbot: QtBot) -> None:
    """The wheel obeys the same stop-at-the-ends rule as the keys and the bands (#161).

    **Test steps:**

    * reveal a viewer on the first screenshot and wheel up, past the start
    * verify it stayed put
    """
    lightbox = reveal_over(document, PATHS, PATHS[0])
    qtbot.addWidget(lightbox)

    send_wheel(lightbox, WHEEL_STEP)

    assert lightbox.current_key == PATHS[0]


def test_the_wheel_over_the_thumbnail_row_scrolls_it_instead(document: QWidget, qtbot: QtBot) -> None:
    """Over the row the wheel scrolls sideways, and never doubles as a step (#161).

    The two gestures share a pointer position whenever the row is up, so the row consuming its own
    wheel is what keeps them apart.

    **Test steps:**

    * reveal a narrow viewer whose row overflows, with the row shown
    * wheel over the row
    * verify the row scrolled and the screenshot did not change
    """
    document.resize(200, 400)
    lightbox = reveal_over(document, PATHS, PATHS[1], strip_visible=True)
    qtbot.addWidget(lightbox)
    scrollbar = strip_of(lightbox).horizontalScrollBar()
    assert scrollbar.maximum() > 0

    send_wheel(strip_of(lightbox).viewport(), -WHEEL_STEP)

    assert scrollbar.value() > 0
    assert lightbox.current_key == PATHS[1]


def test_a_wheel_that_reports_no_movement_changes_nothing(document: QWidget, qtbot: QtBot) -> None:
    """A wheel event carrying no delta is ignored rather than counted as a step in some direction.

    Defensive: a trackpad's inertial tail can report a zero delta, which must not be read as forward.

    **Test steps:**

    * reveal a viewer and send a wheel event with no delta at all
    * verify the screenshot did not move
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)

    send_wheel(lightbox, 0)

    assert lightbox.current_key == PATHS[1]


def test_a_click_on_the_open_screenshot_does_nothing(document: QWidget, qtbot: QtBot) -> None:
    """Clicking the screenshot itself neither steps nor dismisses (#161).

    Regression: the viewer's whole left and right halves used to mean prev/next, which made half the
    surface a step target the user had not asked for and left the affordance's real bounds invisible.
    A step is the band, and only the band.

    **Test steps:**

    * reveal a viewer on the middle screenshot and click well clear of either band
    * verify it neither moved nor went away
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    centre = lightbox.rect().center()

    qtbot.mouseClick(lightbox, Qt.MouseButton.LeftButton, pos=centre + QPoint(1, 0))
    qtbot.mouseClick(lightbox, Qt.MouseButton.LeftButton, pos=centre - QPoint(1, 0))

    assert lightbox.current_key == PATHS[1]
    assert not lightbox.isHidden()


def test_a_click_just_inside_a_band_steps(document: QWidget, qtbot: QtBot) -> None:
    """The band's own area is what answers a click, right up to its inner edge (#161).

    **Test steps:**

    * reveal a viewer on the middle screenshot over a wide document
    * click one pixel inside the next band's inner edge
    * verify it stepped forward
    """
    document.resize(WIDE_VIEWER_WIDTH, 400)
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    band = control(lightbox, NEXT_BUTTON_NAME)

    qtbot.mouseClick(band, Qt.MouseButton.LeftButton, pos=QPoint(1, band.height() // 2))

    assert lightbox.current_key == PATHS[2]


def test_a_click_where_a_hidden_band_would_be_does_nothing(document: QWidget, qtbot: QtBot) -> None:
    """At an end there is no band, so a click over that edge steps nowhere (#161).

    **Test steps:**

    * reveal a viewer on the last screenshot, where the next band is hidden
    * click the viewer over the edge that band would have covered
    * verify nothing moved
    """
    document.resize(WIDE_VIEWER_WIDTH, 400)
    lightbox = reveal_over(document, PATHS, PATHS[-1])
    qtbot.addWidget(lightbox)
    assert control(lightbox, NEXT_BUTTON_NAME).isHidden()

    qtbot.mouseClick(lightbox, Qt.MouseButton.LeftButton, pos=QPoint(lightbox.width() - 2, lightbox.height() // 2))

    assert lightbox.current_key == PATHS[-1]


def test_the_bands_are_the_narrower_of_the_fixed_width_and_an_eighth(document: QWidget, qtbot: QtBot) -> None:
    """A band is ``min(fixed width, an eighth of the viewer)`` at any size (#161).

    **Test steps:**

    * reveal a viewer and measure a band at a wide and a narrow size
    * verify each matches the rule
    """
    lightbox = reveal_over(document, PATHS, PATHS[1])
    qtbot.addWidget(lightbox)
    band = control(lightbox, NEXT_BUTTON_NAME)

    for width in (WIDE_VIEWER_WIDTH, NARROW_VIEWER_WIDTH):
        document.resize(width, 400)
        expected = min(NAVIGATION_ZONE_WIDTH, lightbox.width() // NAVIGATION_ZONE_DIVISIONS)
        assert band.width() == expected
