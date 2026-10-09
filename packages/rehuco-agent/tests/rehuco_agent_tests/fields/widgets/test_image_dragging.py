"""Tests for dragging a screenshot out of the Description strip and the images editor's list and preview (#395)."""

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import ImageExporter, ImageSelector, ImageStrip
from rehuco_agent.fields.widgets.image_selector import NAME_COLUMN, PreviewLabel
from rehuco_agent.fields.widgets.image_strip import ThumbnailLabel

from rehuco_agent_tests.fields.widgets.test_image_export_gestures import mouse
from rehuco_agent_tests.fields.widgets.test_image_selector import FakeResource, list_view, shown

pytestmark = mark.usefixtures("real_path_stat")


def press_and_drag(widget: QWidget, start: QPoint) -> None:
    """Press the left button on a widget and move well past the drag distance.

    :param widget: the widget under the pointer.
    :param start: where the press lands.
    """
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    far = start + QPoint(0, 3 * QApplication.startDragDistance())
    QApplication.sendEvent(
        widget, mouse(QEvent.Type.MouseMove, far, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)


# region the strip


def test_dragging_a_strip_thumbnail_hands_its_screenshot_to_the_exporter(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A press on a thumbnail that moves the drag distance drags that thumbnail's screenshot out, with its own
    picture under the pointer.

    **Test steps:**

    * give a strip two screenshots and an exporter
    * press-and-move the second thumbnail
    * verify the exporter was asked to drag that screenshot from that thumbnail, once
    """
    mocker.patch(
        "rehuco_agent.fields.widgets.image_strip.ThumbnailLoader",
        return_value=mocker.Mock(failed=lambda *a: False, request=lambda *a: QPixmap(20, 20)),
    )
    paths = [Path("/fake/info00.jpg"), Path("/fake/info01.jpg")]
    host = QWidget()
    qtbot.addWidget(host)
    strip = ImageStrip(parent=host)
    exporter = mocker.Mock(spec=ImageExporter)
    strip.set_exporter(exporter)
    strip.set_images(paths)
    host.show()
    label = strip.findChildren(ThumbnailLabel)[1]

    press_and_drag(label, QPoint(3, 3))

    exporter.drag_path.assert_called_once()
    widget, path, picture = exporter.drag_path.call_args.args
    assert (widget, path) == (label, paths[1])
    assert isinstance(picture, QPixmap)


def test_a_strip_with_no_exporter_drags_nothing(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Without an exporter, a press-and-move on a thumbnail does nothing.

    **Test steps:**

    * give a strip a screenshot and no exporter, then press-and-move it
    * verify nothing blew up and no drag was made
    """
    mocker.patch(
        "rehuco_agent.fields.widgets.image_strip.ThumbnailLoader",
        return_value=mocker.Mock(failed=lambda *a: False, request=lambda *a: QPixmap(20, 20)),
    )
    drag = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    host = QWidget()
    qtbot.addWidget(host)
    strip = ImageStrip(parent=host)
    strip.set_images([Path("/fake/info00.jpg")])
    host.show()

    press_and_drag(strip.findChildren(ThumbnailLabel)[0], QPoint(3, 3))

    drag.assert_not_called()


# endregion

# region the images editor


def test_dragging_a_row_of_the_list_drags_its_screenshot(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A press on a row that moves the drag distance drags that row's screenshot, with the row as drawn under the
    pointer; the list's own selection still follows the press.

    **Test steps:**

    * show a selector of three screenshots with an exporter
    * press-and-move the second row's name
    * verify the exporter dragged the second screenshot from the list's viewport, and the row became current
    """
    selector = shown(qtbot, FakeResource(["info00.jpg", "info01.jpg", "info02.jpg"]))
    exporter = mocker.Mock(spec=ImageExporter)
    selector.set_exporter(exporter)
    view = list_view(selector)
    cell = view.visualRect(view.model().index(1, NAME_COLUMN))

    press_and_drag(view.viewport(), cell.center())

    exporter.drag_path.assert_called_once()
    widget, path, picture = exporter.drag_path.call_args.args
    assert widget is view.viewport()
    assert path.name == "info01.jpg"
    assert isinstance(picture, QPixmap)
    assert selector.current_index == 1


def test_dragging_the_preview_drags_the_current_screenshot(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The preview shows the current screenshot, and a press-and-move on it drags that one out.

    **Test steps:**

    * show a selector with an exporter and make the third screenshot current
    * press-and-move the preview
    * verify the exporter dragged the third screenshot from the preview
    """
    selector = shown(qtbot, FakeResource(["info00.jpg", "info01.jpg", "info02.jpg"]))
    exporter = mocker.Mock(spec=ImageExporter)
    selector.set_exporter(exporter)
    selector.set_current_index(2)
    preview = selector.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)

    press_and_drag(preview, QPoint(5, 5))

    exporter.drag_path.assert_called_once()
    widget, path, _picture = exporter.drag_path.call_args.args
    assert widget is preview
    assert path.name == "info02.jpg"


def test_a_press_on_no_row_or_without_an_exporter_drags_nothing(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A press below the last row, and any press with no exporter, drag nothing.

    **Test steps:**

    * press-and-move the list's empty area with an exporter, and a row with none
    * verify no drag was asked for
    """
    selector: ImageSelector = shown(qtbot, FakeResource(["info00.jpg"]))
    view = list_view(selector)
    cell = view.visualRect(view.model().index(0, NAME_COLUMN))
    exporter = mocker.Mock(spec=ImageExporter)

    press_and_drag(view.viewport(), cell.center())
    selector.set_exporter(exporter)
    press_and_drag(view.viewport(), QPoint(5, view.viewport().height() - 3))

    exporter.drag_path.assert_not_called()


# endregion
