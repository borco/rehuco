"""Tests for dragging a thumbnail out of the lightbox's thumbnail row (#395)."""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import ImageExporter, PathImageSource, ThumbnailLoader
from rehuco_agent.fields.widgets.thumbnail_row import ThumbnailRow

from rehuco_agent_tests.fields.widgets.test_image_export_gestures import mouse

pytestmark = mark.usefixtures("real_path_stat")

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"


@fixture
def pictures(tmp_path: Path) -> PathImageSource:
    """Two real pictures, named relative to their folder.

    :param tmp_path: pytest's temporary folder.
    :returns: the source over them.
    """
    folder = tmp_path / "Pack"
    folder.mkdir()
    for name in ("a.png", "b.png"):
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.darkBlue)
        assert image.save(str(folder / name))
    return PathImageSource([folder / "a.png", folder / "b.png"], folder)


def shown_row(qtbot: QtBot, source: PathImageSource, exporter: ImageExporter | None) -> ThumbnailRow:
    """A shown row over a source, with its first thumbnail laid out.

    :param qtbot: pytest-qt fixture.
    :param source: the images.
    :param exporter: what stages an image dragged out, or none.
    :returns: the row.
    """
    row = ThumbnailRow(ThumbnailLoader(), height=60)
    qtbot.addWidget(row)
    row.resize(400, 60)
    row.show()
    qtbot.waitExposed(row)
    row.set_exporter(exporter)
    row.set_source(source)
    qtbot.waitUntil(lambda: not row.visualRect(row.model().index(0, 0)).isEmpty())
    return row


def centre(row: ThumbnailRow, index: int) -> QPoint:
    """The middle of a thumbnail, in the viewport's coordinates.

    :param row: the row.
    :param index: the thumbnail.
    :returns: the point.
    """
    return row.visualRect(row.model().index(index, 0)).center()


def drag_from(row: ThumbnailRow, point: QPoint) -> None:
    """Press at a point and move well past the drag distance.

    :param row: the row.
    :param point: where the press lands.
    """
    viewport = row.viewport()
    QTest.mousePress(viewport, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    far = point + QPoint(0, 3 * QApplication.startDragDistance())
    QApplication.sendEvent(
        viewport, mouse(QEvent.Type.MouseMove, far, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )


def test_dragging_a_thumbnail_drags_its_image_out_and_the_release_that_follows_navigates_nowhere(
    qtbot: QtBot, pictures: PathImageSource, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A press on a thumbnail that moves the drag distance drags that image out as a copy, named relative to its
    record -- and the click Qt then reports on the release is not an activation.

    **Test steps:**

    * with ``QDrag`` replaced, drag the second thumbnail and release
    * verify one copy drag carrying that image's staged file, and no activation
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    row = shown_row(qtbot, pictures, ImageExporter(tmp_path / "staged", lambda: ID))
    activated: list[int] = []
    row.activated_index.connect(activated.append)
    point = centre(row, 1)

    drag_from(row, point)
    QTest.mouseRelease(row.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)

    drag = drag_class.return_value
    drag.exec.assert_called_once_with(Qt.DropAction.CopyAction)
    (mime,) = drag.setMimeData.call_args.args
    assert Path(mime.urls()[0].toLocalFile()).name == f"rehu-{ID}__b.png"
    assert not activated


def test_a_plain_click_still_activates_a_thumbnail(
    qtbot: QtBot, pictures: PathImageSource, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A press and release without moving is a click: no drag, and the activation as before; so is the click after
    an earlier drag.

    **Test steps:**

    * with ``QDrag`` replaced, drag a thumbnail, then click the other one
    * verify the click was reported and exactly one drag was made
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    row = shown_row(qtbot, pictures, ImageExporter(tmp_path / "staged", lambda: ID))
    activated: list[int] = []
    row.activated_index.connect(activated.append)
    drag_from(row, centre(row, 0))
    QTest.mouseRelease(row.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(row, 0))

    QTest.mouseClick(row.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(row, 1))

    assert activated == [1]
    drag_class.return_value.exec.assert_called_once()


def test_a_row_with_no_exporter_or_pressed_on_a_gap_drags_nothing(
    qtbot: QtBot, pictures: PathImageSource, tmp_path: Path, mocker: MockerFixture
) -> None:
    """Without an exporter nothing leaves the row, and neither does a press beside the thumbnails.

    **Test steps:**

    * with ``QDrag`` replaced, drag a thumbnail of a row with no exporter
    * give the row one and press-and-move past the last thumbnail
    * verify no drag was built
    """
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")
    row = shown_row(qtbot, pictures, None)
    drag_from(row, centre(row, 0))
    QTest.mouseRelease(row.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(row, 0))
    row.set_exporter(ImageExporter(tmp_path / "staged", lambda: ID))

    drag_from(row, QPoint(row.viewport().width() - 2, 5))

    drag_class.assert_not_called()
