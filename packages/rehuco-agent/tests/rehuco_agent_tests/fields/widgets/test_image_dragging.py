"""Tests for dragging a screenshot out of the Description strip and the images editor's list and preview (#395).

Every drag goes through a real :class:`ImageExporter` over a temporary staging folder, with only ``QDrag`` replaced, as
the grid's and the lightbox's tests do; what is asserted is the staged file the drag carries (#485).
"""

from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from pytest import MonkeyPatch, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import ImageExporter, ImageSelector, ImageStrip
from rehuco_agent.fields.widgets.image_selector import NAME_COLUMN, PreviewLabel
from rehuco_agent.fields.widgets.image_strip import ThumbnailLabel

from rehuco_agent_tests.fields.widgets import test_image_selector
from rehuco_agent_tests.fields.widgets.test_image_export_gestures import mouse
from rehuco_agent_tests.fields.widgets.test_image_selector import FakeResource, list_view, shown

pytestmark = mark.usefixtures("real_path_stat")

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"
NAMES: Final = ["info00.png", "info01.png", "info02.png"]


@fixture
def pack(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """A resource folder holding three real screenshots, which the selector's in-memory resource lists from.

    :param tmp_path: pytest's temporary folder.
    :param monkeypatch: pytest fixture.
    :returns: the folder.
    """
    folder = tmp_path / "Pack"
    folder.mkdir()
    for name in NAMES:
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkCyan)
        assert image.save(str(folder / name))
    monkeypatch.setattr(test_image_selector, "DIRECTORY", folder)
    return folder


@fixture
def exporter(tmp_path: Path, pack: Path) -> ImageExporter:
    """A real exporter staging under a temporary folder, naming files relative to the pack.

    :param tmp_path: pytest's temporary folder.
    :param pack: the resource folder.
    :returns: the exporter.
    """
    return ImageExporter(tmp_path / "staged", lambda: ID, lambda: pack)


@fixture
def drag_class(mocker: MockerFixture) -> MagicMock:
    """``QDrag`` as the exporter builds it, replaced so no drag loop runs.

    :param mocker: pytest-mock fixture.
    :returns: the class mock.
    """
    return mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")


def staged_name(drag_class: MagicMock) -> str:
    """The name of the staged file the one drag carried.

    :param drag_class: the replaced ``QDrag``.
    :returns: the file name.
    """
    drag_class.return_value.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    (mime,) = drag_class.return_value.setMimeData.call_args.args
    (url,) = mime.urls()
    return Path(url.toLocalFile()).name


def strip_of(
    qtbot: QtBot, mocker: MockerFixture, pack: Path, exporter: ImageExporter | None
) -> tuple[QWidget, ImageStrip, list[Path]]:
    """A shown strip over the pack's first two screenshots; its thumbnails' pictures are stand-ins.

    :param qtbot: pytest-qt fixture.
    :param mocker: pytest-mock fixture.
    :param pack: the resource folder.
    :param exporter: what stages an image dragged out, or none.
    :returns: the host, which the caller holds so the strip outlives the call, the strip, and its screenshots.
    """
    mocker.patch(
        "rehuco_agent.fields.widgets.image_strip.ThumbnailLoader",
        return_value=mocker.Mock(failed=lambda *a: False, request=lambda *a: QPixmap(20, 20)),
    )
    paths = [pack / NAMES[0], pack / NAMES[1]]
    host = QWidget()
    qtbot.addWidget(host)
    strip = ImageStrip(parent=host)
    if exporter is not None:
        strip.set_exporter(exporter)
    strip.set_images(paths)
    host.show()
    return host, strip, paths


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


def test_dragging_a_strip_thumbnail_stages_its_screenshot_and_drags_the_staged_file(
    qtbot: QtBot, mocker: MockerFixture, pack: Path, exporter: ImageExporter, drag_class: MagicMock
) -> None:
    """A press on a thumbnail that moves the drag distance drags that thumbnail's screenshot out as a staged copy,
    named by the record and the screenshot, with the thumbnail's own picture under the pointer.

    **Test steps:**

    * give a strip two real screenshots and an exporter
    * press-and-move the second thumbnail, with ``QDrag`` replaced
    * verify one copy drag carrying the second screenshot's staged file, holding its bytes, with a picture
    """
    _host, strip, paths = strip_of(qtbot, mocker, pack, exporter)
    label = strip.findChildren(ThumbnailLabel)[1]

    press_and_drag(label, QPoint(3, 3))

    assert staged_name(drag_class) == f"rehu-{ID}__{NAMES[1]}"
    (mime,) = drag_class.return_value.setMimeData.call_args.args
    assert Path(mime.urls()[0].toLocalFile()).read_bytes() == paths[1].read_bytes()
    (picture,) = drag_class.return_value.setPixmap.call_args.args
    assert not picture.isNull()


def test_a_strip_with_no_exporter_reports_the_drag_but_stages_and_drags_nothing(
    qtbot: QtBot, mocker: MockerFixture, pack: Path, tmp_path: Path, drag_class: MagicMock
) -> None:
    """The thumbnail does report the gesture, so the silence below is the strip's, not the label's.

    **Test steps:**

    * give a strip a real screenshot and no exporter, and watch the thumbnail's drag signal
    * press-and-move the thumbnail
    * verify the signal fired once, no drag was built, and nothing was staged
    """
    _host, strip, paths = strip_of(qtbot, mocker, pack, None)
    label = strip.findChildren(ThumbnailLabel)[0]
    reported: list[Path] = []
    label.drag_started.connect(reported.append)

    press_and_drag(label, QPoint(3, 3))

    assert reported == [paths[0]]
    drag_class.assert_not_called()
    assert not (tmp_path / "staged").exists()


def test_a_strip_press_that_barely_moves_drags_nothing(
    qtbot: QtBot, mocker: MockerFixture, pack: Path, exporter: ImageExporter, drag_class: MagicMock
) -> None:
    """A press that moves less than the drag distance is a click, not a drag.

    **Test steps:**

    * press a strip thumbnail and move one pixel
    * verify no drag was built
    """
    _host, strip, _paths = strip_of(qtbot, mocker, pack, exporter)
    label = strip.findChildren(ThumbnailLabel)[0]

    QTest.mousePress(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(3, 3))
    QApplication.sendEvent(
        label, mouse(QEvent.Type.MouseMove, QPoint(3, 4), Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    QTest.mouseRelease(label, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(3, 4))

    drag_class.assert_not_called()


def test_a_double_click_on_a_strip_thumbnail_does_not_arm_a_drag(
    qtbot: QtBot, mocker: MockerFixture, pack: Path, exporter: ImageExporter, drag_class: MagicMock
) -> None:
    """The double-click that opens the viewer is not the start of a drag: held and moved, it drags nothing from the
    label underneath (the base class would replay it as a press).

    **Test steps:**

    * click, then double-click a thumbnail and move well past the drag distance with the button held
    * verify the viewer was asked for once and no drag was built
    * press-and-move the same thumbnail and verify it still drags
    """
    _host, strip, paths = strip_of(qtbot, mocker, pack, exporter)
    label = strip.findChildren(ThumbnailLabel)[0]
    clicked: list[Path] = []
    label.clicked.connect(clicked.append)
    left = Qt.MouseButton.LeftButton
    start = QPoint(3, 3)
    far = start + QPoint(0, 3 * QApplication.startDragDistance())

    QTest.mouseClick(label, left, Qt.KeyboardModifier.NoModifier, start)
    QApplication.sendEvent(label, mouse(QEvent.Type.MouseButtonDblClick, start, left, left))
    QApplication.sendEvent(label, mouse(QEvent.Type.MouseMove, far, Qt.MouseButton.NoButton, left))

    assert clicked == [paths[0]]
    drag_class.assert_not_called()
    QTest.mouseRelease(label, left, Qt.KeyboardModifier.NoModifier, start)
    press_and_drag(label, start)
    drag_class.return_value.exec.assert_called_once()


# endregion

# region the images editor


def test_dragging_a_row_of_the_list_stages_its_screenshot(
    qtbot: QtBot, exporter: ImageExporter, drag_class: MagicMock
) -> None:
    """A press on a row that moves the drag distance drags that row's screenshot as a staged copy, with the row as
    drawn under the pointer; the list's own selection still follows the press.

    **Test steps:**

    * show a selector of three real screenshots with an exporter
    * press-and-move the second row's name, with ``QDrag`` replaced
    * verify the drag carried the second screenshot's staged file, from a picture, and the row became current
    """
    selector = shown(qtbot, FakeResource(NAMES))
    selector.set_exporter(exporter)
    view = list_view(selector)
    cell = view.visualRect(view.model().index(1, NAME_COLUMN))

    press_and_drag(view.viewport(), cell.center())

    assert staged_name(drag_class) == f"rehu-{ID}__{NAMES[1]}"
    (picture,) = drag_class.return_value.setPixmap.call_args.args
    assert not picture.isNull()
    assert drag_class.call_args.args[0] is view.viewport()
    assert selector.current_index == 1


def test_dragging_the_preview_stages_the_current_screenshot(
    qtbot: QtBot, exporter: ImageExporter, drag_class: MagicMock
) -> None:
    """The preview shows the current screenshot, and a press-and-move on it drags that one out as a staged copy.

    **Test steps:**

    * show a selector with an exporter and make the third screenshot current
    * press-and-move the preview, with ``QDrag`` replaced
    * verify the drag carried the third screenshot's staged file, started from the preview
    """
    selector = shown(qtbot, FakeResource(NAMES))
    selector.set_exporter(exporter)
    selector.set_current_index(2)
    preview = selector.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)

    press_and_drag(preview, QPoint(5, 5))

    assert staged_name(drag_class) == f"rehu-{ID}__{NAMES[2]}"
    assert drag_class.call_args.args[0] is preview


def test_a_press_below_the_last_row_drags_nothing(qtbot: QtBot, exporter: ImageExporter, drag_class: MagicMock) -> None:
    """With the exporter attached, a press below the last row has nothing under it to drag.

    **Test steps:**

    * attach an exporter to a selector of one screenshot
    * press-and-move the list's empty area, below the row
    * verify no drag was built; then press-and-move the row itself and verify it does drag
    """
    selector: ImageSelector = shown(qtbot, FakeResource(NAMES[:1]))
    selector.set_exporter(exporter)
    view = list_view(selector)
    cell = view.visualRect(view.model().index(0, NAME_COLUMN))
    below = QPoint(5, view.viewport().height() - 3)
    assert not view.indexAt(below).isValid()

    press_and_drag(view.viewport(), below)
    drag_class.assert_not_called()

    press_and_drag(view.viewport(), cell.center())
    drag_class.return_value.exec.assert_called_once()


# endregion


def test_a_preview_with_no_picture_has_no_picture_area(qtbot: QtBot) -> None:
    """Nothing to drag from a label that shows nothing.

    **Test steps:**

    * ask an empty preview where its picture is
    * verify there is no area
    """
    preview = PreviewLabel()
    qtbot.addWidget(preview)

    assert preview.image_rect().isEmpty()


def test_the_previews_double_click_still_asks_for_the_viewer_with_an_exporter(
    qtbot: QtBot, exporter: ImageExporter, drag_class: MagicMock
) -> None:
    """Watching the preview for a drag changes nothing it did: a double-click on it still opens the curating viewer.

    **Test steps:**

    * give a selector an exporter and double-click its preview, on the current screenshot
    * verify the viewer was asked for, on that row, and nothing dragged
    """
    selector = shown(qtbot, FakeResource(NAMES[:2]))
    selector.set_exporter(exporter)
    selector.set_current_index(1)
    preview = selector.findChild(PreviewLabel)
    assert isinstance(preview, PreviewLabel)
    asked: list[int] = []
    selector.viewer_requested.connect(asked.append)

    QTest.mouseDClick(preview, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(5, 5))

    assert asked == [1]
    drag_class.assert_not_called()
