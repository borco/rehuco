"""Tests for taking the image on screen out of a lightbox -- Copy, and a drag that starts on the picture (#395)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QAction, QContextMenuEvent, QGuiApplication, QImage, QKeySequence, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidget
from pytest import MonkeyPatch, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import (
    CuratingImageLightbox,
    ImageExporter,
    ImageLightbox,
    ImageViewerMode,
    ImageVisibility,
    PathImageSource,
    ScreenshotRowsImageSource,
)
from rehuco_agent.fields.widgets.image_selector import PreviewLabel
from rehuco_agent.fields.widgets.thumbnail_row import ThumbnailRow

pytestmark = mark.usefixtures("real_path_stat")

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"


class RecordingMenu(QMenu):
    """A menu that records what it was asked to show instead of running a modal loop."""

    shown: list[list[QAction]] = []

    def exec(self, *_args: object) -> None:  # type: ignore[override]
        """Record the menu's actions."""
        RecordingMenu.shown.append(self.actions())


@fixture
def resource(tmp_path: Path) -> Path:
    """A resource's folder holding two wide screenshots under ``screenshots/``."""
    folder = tmp_path / "Pack"
    (folder / "screenshots").mkdir(parents=True)
    for name in ("a.png", "b.png"):
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkGreen)
        assert image.save(str(folder / "screenshots" / name))
    return folder


@fixture
def staging(tmp_path: Path) -> Path:
    """The staging folder, not created yet."""
    return tmp_path / "staged"


@fixture
def document(qtbot: QtBot) -> QWidget:
    """A shown 800 x 600 widget standing in for the open document the viewer covers."""
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.resize(800, 600)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@fixture
def clipboard() -> Iterator[None]:
    """Leave the clipboard empty after the test, whatever it put there."""
    yield
    QGuiApplication.clipboard().clear()


def open_viewer(qtbot: QtBot, document: QWidget, resource: Path, exporter: ImageExporter | None) -> ImageLightbox:
    """Open a document-overlay viewer over the two screenshots, its row hidden, and wait for the picture.

    :param qtbot: pytest-qt fixture.
    :param document: the surface it covers.
    :param resource: the resource folder the paths are named against.
    :param exporter: what stages an image taken out, or none.
    :returns: the viewer, revealed and laid out.
    """
    images = [resource / "screenshots" / "a.png", resource / "screenshots" / "b.png"]
    viewer = ImageLightbox(
        PathImageSource(images, resource), 0, ImageViewerMode.DOCUMENT_OVERLAY, document, exporter=exporter
    )
    viewer.reveal()
    qtbot.waitUntil(lambda: viewer.width() == document.width() and not picture_rect(viewer).isEmpty())
    return viewer


def picture_rect(viewer: ImageLightbox) -> QRect:
    """Where the picture is drawn, in the viewer's coordinates."""
    preview = viewer.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)
    return preview.image_rect().translated(preview.pos())


def move_to(viewer: ImageLightbox, point: QPoint) -> None:
    """Move the pointer to ``point`` with the left button held.

    :param viewer: the viewer.
    :param point: where to, in the viewer's coordinates.
    """
    at = QPointF(point)
    QApplication.sendEvent(
        viewer,
        QMouseEvent(
            QEvent.Type.MouseMove,
            at,
            viewer.mapToGlobal(at),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def press_and_move(viewer: ImageLightbox, start: QPoint, distance: int) -> None:
    """Press the left button at ``start`` and move ``distance`` pixels down.

    :param viewer: the viewer.
    :param start: where the button goes down.
    :param distance: how far to move.
    """
    QTest.mousePress(viewer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    move_to(viewer, start + QPoint(0, distance))


def test_copy_takes_the_image_on_screen_and_rides_ctrl_c(
    qtbot: QtBot, document: QWidget, resource: Path, staging: Path, clipboard: None
) -> None:
    """Copy is the viewer's own, on the platform's Copy keys while the viewer has the keyboard, and copies whichever
    image is on screen.

    **Test steps:**

    * open a viewer with an exporter and step to the second screenshot
    * verify Copy is bound to the Copy keys within the viewer
    * trigger it and verify the clipboard holds the second screenshot's staged file
    """
    del clipboard
    viewer = open_viewer(qtbot, document, resource, ImageExporter(staging, lambda: ID))
    QTest.keyClick(viewer, Qt.Key.Key_Right)
    action = viewer.copy_action
    assert action is not None
    assert action.shortcuts() == QKeySequence.keyBindings(QKeySequence.StandardKey.Copy)
    assert action.shortcutContext() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    assert action in viewer.actions()

    action.trigger()

    held = QGuiApplication.clipboard().mimeData()
    assert held is not None
    assert [Path(url.toLocalFile()) for url in held.urls()] == [staging / f"rehu-{ID}__screenshots__b.png"]


def test_a_viewer_with_no_exporter_offers_nothing_to_take_out(
    qtbot: QtBot, document: QWidget, resource: Path, monkeypatch: MonkeyPatch, mocker: MockerFixture
) -> None:
    """No exporter, no Copy, no menu, no drag.

    **Test steps:**

    * open a viewer with no exporter
    * ask for the context menu, copy, and press-and-move on the picture
    * verify there is no action, no menu was shown and no drag was built
    """
    monkeypatch.setattr("rehuco_agent.fields.widgets.image_lightbox.QMenu", RecordingMenu)
    RecordingMenu.shown = []
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    viewer = open_viewer(qtbot, document, resource, None)
    centre = picture_rect(viewer).center()

    QApplication.sendEvent(
        viewer, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, centre, viewer.mapToGlobal(centre))
    )
    viewer.copy_current()
    press_and_move(viewer, centre, 3 * QApplication.startDragDistance())

    assert viewer.copy_action is None
    assert not viewer.drag_enabled()
    assert not RecordingMenu.shown
    drag_class.assert_not_called()


def test_the_context_menu_offers_copy(
    qtbot: QtBot, document: QWidget, resource: Path, staging: Path, monkeypatch: MonkeyPatch
) -> None:
    """A right-click anywhere on the viewer offers Copy for the image on screen.

    **Test steps:**

    * with the menu recorded, ask for it over the picture
    * verify one menu holding the viewer's Copy
    """
    monkeypatch.setattr("rehuco_agent.fields.widgets.image_lightbox.QMenu", RecordingMenu)
    RecordingMenu.shown = []
    viewer = open_viewer(qtbot, document, resource, ImageExporter(staging, lambda: ID))
    centre = picture_rect(viewer).center()

    QApplication.sendEvent(
        viewer, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, centre, viewer.mapToGlobal(centre))
    )

    assert len(RecordingMenu.shown) == 1
    assert RecordingMenu.shown[0] == [viewer.copy_action]


def test_pressing_the_picture_and_moving_drags_a_copy_out(
    qtbot: QtBot, document: QWidget, resource: Path, staging: Path, mocker: MockerFixture
) -> None:
    """A press on the picture that moves the drag distance drags the image on screen out as a copy.

    **Test steps:**

    * with ``QDrag`` replaced, press the picture's middle and move
    * verify one copy drag carrying the first screenshot's staged file, and the viewer still open
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    viewer = open_viewer(qtbot, document, resource, ImageExporter(staging, lambda: ID))

    press_and_move(viewer, picture_rect(viewer).center(), 3 * QApplication.startDragDistance())

    drag = drag_class.return_value
    drag.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    (mime,) = drag.setMimeData.call_args.args
    assert [Path(url.toLocalFile()) for url in mime.urls()] == [staging / f"rehu-{ID}__screenshots__a.png"]
    assert viewer.isVisible()


def test_a_press_beside_the_picture_or_one_that_barely_moves_drags_nothing(
    qtbot: QtBot, document: QWidget, resource: Path, staging: Path, mocker: MockerFixture
) -> None:
    """The backdrop around a letterboxed picture is not the picture; a press that moves less than the drag distance,
    or that was let go first, is not a drag.

    **Test steps:**

    * with ``QDrag`` replaced, press-and-move on the backdrop above the picture
    * press the picture, move one pixel; then press it, release, and move
    * verify no drag was built
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    viewer = open_viewer(qtbot, document, resource, ImageExporter(staging, lambda: ID))
    picture = picture_rect(viewer)
    backdrop = QPoint(picture.center().x(), picture.top() // 2)
    assert picture.top() > 0
    assert not picture.contains(backdrop)

    press_and_move(viewer, backdrop, 3 * QApplication.startDragDistance())
    press_and_move(viewer, picture.center(), 1)
    QTest.mouseRelease(viewer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, picture.center())
    move_to(viewer, picture.center() + QPoint(0, 3 * QApplication.startDragDistance()))

    drag_class.assert_not_called()


def test_a_double_click_on_the_picture_still_closes_the_viewer(
    qtbot: QtBot, document: QWidget, resource: Path, staging: Path, mocker: MockerFixture
) -> None:
    """The gesture that opened the viewer still dismisses it: a press that does not move never drags.

    **Test steps:**

    * with ``QDrag`` replaced, double-click the picture
    * verify the viewer closed and no drag was built
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    viewer = open_viewer(qtbot, document, resource, ImageExporter(staging, lambda: ID))
    closed: list[bool] = []
    viewer.closed.connect(lambda: closed.append(True))

    QTest.mouseDClick(viewer, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, picture_rect(viewer).center())

    assert closed == [True]
    drag_class.assert_not_called()


def test_the_curating_viewer_copies_too(
    qtbot: QtBot, document: QWidget, resource: Path, staging: Path, clipboard: None
) -> None:
    """The screenshots editor's viewer is a lightbox like the others: its rows can be copied out.

    **Test steps:**

    * open a curating viewer over the screenshot rows with an exporter
    * trigger its Copy and verify the clipboard holds the staged screenshot
    """
    del clipboard
    rows = [(resource / "screenshots" / "a.png", ImageVisibility.VISIBLE)]
    viewer = CuratingImageLightbox(
        ScreenshotRowsImageSource(rows, resource),
        0,
        ImageViewerMode.DOCUMENT_OVERLAY,
        document,
        exporter=ImageExporter(staging, lambda: ID),
    )
    viewer.reveal()
    action = viewer.copy_action
    assert action is not None

    action.trigger()

    held = QGuiApplication.clipboard().mimeData()
    assert held is not None
    assert [Path(url.toLocalFile()).name for url in held.urls()] == [f"rehu-{ID}__screenshots__a.png"]
    viewer.close()
    qtbot.waitUntil(lambda: not viewer.isVisible())


def test_a_thumbnail_dragged_out_of_the_viewers_row_is_taken_out_too(
    qtbot: QtBot, document: QWidget, resource: Path, staging: Path, mocker: MockerFixture
) -> None:
    """The viewer's own thumbnail row drags what it shows, through the viewer's exporter.

    **Test steps:**

    * open a viewer with its row shown and press-and-move the second thumbnail, with ``QDrag`` replaced
    * verify one copy drag carrying that screenshot's staged file, and that the viewer stayed on the first
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    images = [resource / "screenshots" / "a.png", resource / "screenshots" / "b.png"]
    viewer = ImageLightbox(
        PathImageSource(images, resource),
        0,
        ImageViewerMode.DOCUMENT_OVERLAY,
        document,
        strip_visible=True,
        exporter=ImageExporter(staging, lambda: ID),
    )
    viewer.reveal()
    row = viewer.findChild(ThumbnailRow)
    assert isinstance(row, ThumbnailRow)
    qtbot.waitUntil(lambda: not row.visualRect(row.model().index(1, 0)).isEmpty())
    start = row.visualRect(row.model().index(1, 0)).center()

    QTest.mousePress(row.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    move_to_widget = QPoint(start.x(), start.y() + 3 * QApplication.startDragDistance())
    QApplication.sendEvent(
        row.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(move_to_widget),
            QPointF(move_to_widget),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )

    (mime,) = drag_class.return_value.setMimeData.call_args.args
    assert Path(mime.urls()[0].toLocalFile()).name == f"rehu-{ID}__screenshots__b.png"
    assert viewer.current_index == 0
