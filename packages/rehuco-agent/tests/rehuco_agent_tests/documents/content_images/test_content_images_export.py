"""Tests for taking an image out of the Content Images grid -- a drag, or Copy on the selected one (#395)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QAction, QContextMenuEvent, QGuiApplication, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QToolBar
from pytest import MonkeyPatch, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.content_images import (
    ContentDisplayFlags,
    ContentImagesModel,
    ContentImagesPanel,
    ContentImagesView,
)
from rehuco_agent.fields.widgets import ImageExporter, ThumbnailLoader

from rehuco_agent_tests.documents.content_images.conftest import PACK, REHU_DIRECTORY, entry
from rehuco_agent_tests.documents.content_images.test_content_images_view import settle

pytestmark = mark.usefixtures("real_path_stat")

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"


class RecordingMenu(QMenu):
    """A menu that records what it was asked to show instead of running a modal loop."""

    shown: list[list[QAction]] = []

    def exec(self, *_args: object) -> None:  # type: ignore[override]
        """Record the menu's actions."""
        RecordingMenu.shown.append(self.actions())


@fixture
def staging(tmp_path: Path) -> Path:
    """The staging folder, not created yet."""
    return tmp_path / "staged"


@fixture
def exporting(
    qtbot: QtBot, content_model: ContentImagesModel, loader: ThumbnailLoader, staging: Path
) -> ContentImagesView:
    """A shown grid, like the plain ``view`` fixture, that stages what leaves it under ``ID``, over two packed images.

    :param qtbot: pytest-qt fixture.
    :param content_model: the model, over the fake archive.
    :param loader: the loader.
    :param staging: the staging folder.
    :returns: the view, settled.
    """
    built = ContentImagesView(
        content_model,
        loader,
        min_height=100,
        max_height=200,
        flags=ContentDisplayFlags(banners=False),
        exporter=ImageExporter(staging, lambda: ID),
    )
    qtbot.addWidget(built)
    built.resize(1000, 400)
    built.show()
    qtbot.waitExposed(built)
    content_model.set_entries([entry(PACK, "a.png"), entry(PACK, "sub/b.png")], REHU_DIRECTORY)
    settle(qtbot, built, content_model)
    return built


@fixture
def clipboard() -> Iterator[None]:
    """Leave the clipboard empty after the test, whatever it put there."""
    yield
    QGuiApplication.clipboard().clear()


def centre_of(view: ContentImagesView, index: int) -> QPoint:
    """The middle of an image's cell, in viewport coordinates.

    :param view: the grid.
    :param index: the image.
    :returns: the point.
    """
    table = view.layout_table
    assert table is not None
    x, y, w, h = table.rects[index]
    return QPoint(x + w // 2, y + h // 2)


def move_to(view: ContentImagesView, point: QPoint) -> None:
    """Move the pointer to ``point`` with the left button held, as a hand starting a drag does.

    :param view: the grid.
    :param point: where to, in viewport coordinates.
    """
    viewport = view.viewport()
    at = QPointF(point)
    QApplication.sendEvent(
        viewport,
        QMouseEvent(
            QEvent.Type.MouseMove,
            at,
            viewport.mapToGlobal(at),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )


def press_and_drag(view: ContentImagesView, index: int) -> None:
    """Press the left button on an image and move well past the drag distance.

    :param view: the grid.
    :param index: the image pressed.
    """
    start = centre_of(view, index)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    move_to(view, start + QPoint(3 * QApplication.startDragDistance(), 0))


def test_pressing_and_moving_an_image_drags_a_copy_of_it_out(
    exporting: ContentImagesView, staging: Path, mocker: MockerFixture
) -> None:
    """A press on an image that moves the drag distance drags it out as a copy: one file URL to the staged image,
    named by the resource and the member's path with the archive as a segment; the image becomes the selection.

    **Test steps:**

    * with ``QDrag`` replaced, press the second image and move
    * verify one copy drag carrying the staged file, holding the member's bytes, and the image selected
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")

    press_and_drag(exporting, 1)

    drag = drag_class.return_value
    drag.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    (mime,) = drag.setMimeData.call_args.args
    (url,) = mime.urls()
    staged = Path(url.toLocalFile())
    assert staged == staging / f"rehu-{ID}__pack.zip__sub__b.png"
    assert staged.read_bytes() == exporting.source.read(1)
    assert exporting.selected == 1


def test_a_press_that_moves_less_than_the_drag_distance_still_selects(
    exporting: ContentImagesView, mocker: MockerFixture
) -> None:
    """A hand that shakes a little while clicking clicks: no drag, and the release selects.

    **Test steps:**

    * with ``QDrag`` replaced, press an image, move one pixel, release
    * verify no drag and the image selected
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    start = centre_of(exporting, 0)

    QTest.mousePress(exporting.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    move_to(exporting, start + QPoint(1, 0))
    QTest.mouseRelease(exporting.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)

    drag_class.assert_not_called()
    assert exporting.selected == 0


def test_the_release_that_ends_a_drag_is_no_click(exporting: ContentImagesView, mocker: MockerFixture) -> None:
    """A platform that delivers the release after the drag must not have it toggle the dragged image off; the next
    press is a click again.

    **Test steps:**

    * drag the first image, then send the release
    * verify it stays selected
    * click it again and verify the click toggles it off as usual
    """
    mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    start = centre_of(exporting, 0)

    press_and_drag(exporting, 0)
    QTest.mouseRelease(exporting.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    assert exporting.selected == 0

    QTest.mouseClick(exporting.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    assert exporting.selected is None


def test_a_press_off_an_image_or_with_another_button_drags_nothing(
    exporting: ContentImagesView, mocker: MockerFixture
) -> None:
    """Only a left press on an image starts a drag: a gap below the images and a right press do not.

    **Test steps:**

    * with ``QDrag`` replaced, press-and-move in the empty area, then right-press an image and move
    * verify no drag was built
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    empty = QPoint(5, exporting.viewport().height() - 5)
    assert exporting.index_at(empty) is None

    QTest.mousePress(exporting.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    move_to(exporting, empty + QPoint(50, 0))
    QTest.mouseRelease(exporting.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, empty)
    start = centre_of(exporting, 0)
    QTest.mousePress(exporting.viewport(), Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, start)
    move_to(exporting, start + QPoint(50, 0))

    drag_class.assert_not_called()


def test_a_grid_with_no_exporter_drags_nothing_and_offers_no_copy(
    view: ContentImagesView, content_model: ContentImagesModel, qtbot: QtBot, mocker: MockerFixture
) -> None:
    """Without an exporter nothing leaves the grid: a press-and-move only selects, and Copy stays disabled.

    **Test steps:**

    * with ``QDrag`` replaced, press-and-move an image on a grid built with no exporter
    * select one and copy
    * verify no drag was built and Copy is disabled
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    content_model.set_entries([entry(PACK, "a.png")], REHU_DIRECTORY)
    settle(qtbot, view, content_model)

    press_and_drag(view, 0)
    view.set_selected(0)
    view.copy_selected()

    drag_class.assert_not_called()
    assert not view.copy_action.isEnabled()


def test_copy_is_enabled_by_a_selection_and_puts_the_staged_file_on_the_clipboard(
    exporting: ContentImagesView, staging: Path, clipboard: None
) -> None:
    """Copy follows the selection, and copies the selected image as the drag does.

    **Test steps:**

    * verify Copy is disabled with nothing selected
    * select the first image and trigger Copy
    * verify the clipboard holds the staged file; clear the selection and verify Copy is disabled again
    """
    del clipboard
    assert not exporting.copy_action.isEnabled()

    exporting.set_selected(0)
    assert exporting.copy_action.isEnabled()
    exporting.copy_action.trigger()

    held = QGuiApplication.clipboard().mimeData()
    assert held is not None
    assert [Path(url.toLocalFile()) for url in held.urls()] == [staging / f"rehu-{ID}__pack.zip__a.png"]
    exporting.set_selected(None)
    assert not exporting.copy_action.isEnabled()


def test_an_image_that_cannot_be_read_says_so_on_the_status_line(
    qtbot: QtBot, content_model: ContentImagesModel, loader: ThumbnailLoader, staging: Path, mocker: MockerFixture
) -> None:
    """A member that reads as nothing -- an offline share, a re-packed zip -- is neither copied nor dragged, and the
    status line says which.

    **Test steps:**

    * over a pack with an unreadable member, copy it, then drag it with ``QDrag`` replaced
    * verify the status line named it each time and no drag was built
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    grid = ContentImagesView(
        content_model, loader, flags=ContentDisplayFlags(banners=False), exporter=ImageExporter(staging, lambda: ID)
    )
    qtbot.addWidget(grid)
    grid.resize(1000, 400)
    grid.show()
    qtbot.waitExposed(grid)
    content_model.set_entries([entry(PACK, "broken.png")], REHU_DIRECTORY)
    qtbot.waitUntil(lambda: grid.layout_table is not None and len(grid.layout_table.rects) == 1)
    said: list[str] = []
    grid.status_changed.connect(said.append)

    grid.set_selected(0)
    grid.copy_selected()
    assert said[-1] == "Could not copy pack.zip/broken.png"

    said.clear()
    press_and_drag(grid, 0)
    assert said[-1] == "Could not copy pack.zip/broken.png"
    drag_class.assert_not_called()


def test_the_context_menu_selects_the_image_and_offers_copy(
    exporting: ContentImagesView, monkeypatch: MonkeyPatch
) -> None:
    """A right-click on an image makes it the selection and offers Copy; over empty space there is no menu.

    **Test steps:**

    * with the menu recorded, ask for it over the second image, then over empty space
    * verify one menu holding Copy, and the second image selected
    """
    monkeypatch.setattr("rehuco_agent.documents.content_images.content_images_view.QMenu", RecordingMenu)
    RecordingMenu.shown = []
    viewport = exporting.viewport()

    for point in (centre_of(exporting, 1), QPoint(5, viewport.height() - 5)):
        QApplication.sendEvent(
            viewport, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, viewport.mapToGlobal(point))
        )

    assert len(RecordingMenu.shown) == 1
    assert RecordingMenu.shown[0] == [exporting.copy_action]
    assert exporting.selected == 1


def test_the_panel_puts_copy_on_its_toolbar(
    content_model: ContentImagesModel, loader: ThumbnailLoader, staging: Path, qtbot: QtBot
) -> None:
    """The toolbar carries the grid's own Copy beside Refresh -- one action, every surface.

    **Test steps:**

    * build the panel around a grid
    * verify its toolbar holds Refresh then Copy
    """
    grid = ContentImagesView(content_model, loader, exporter=ImageExporter(staging, lambda: ID))
    panel = ContentImagesPanel(grid)
    qtbot.addWidget(panel)

    toolbar = panel.findChild(QToolBar)
    assert isinstance(toolbar, QToolBar)
    assert toolbar.actions() == [panel.refresh_action, grid.copy_action]
