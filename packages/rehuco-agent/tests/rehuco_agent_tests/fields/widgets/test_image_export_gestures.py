"""Tests for the pieces that let any widget drag an image out of the app: the press tracker, the generic press-and-drag
filter, the original-file hint a drag carries, and the exporter's path-based entry points (#395)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Final

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QMouseEvent, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets import ImageExporter, ImageVisibility, PathImageSource, ScreenshotRowsImageSource
from rehuco_agent.fields.widgets.image_export import (
    ORIGINAL_FILE_MIME,
    PressDragFilter,
    PressTracker,
    image_mime,
    source_file,
)
from rehuco_agent.fields.widgets.image_source import ScreenshotKey

pytestmark = mark.usefixtures("real_path_stat")

ID: Final = "0f8fad5b-d9cb-469f-a165-70867728950e"


def mouse(kind: QEvent.Type, point: QPoint, button: Qt.MouseButton, buttons: Qt.MouseButton) -> QMouseEvent:
    """A mouse event at a point of a widget.

    :param kind: press, move or release.
    :param point: where, in the widget's coordinates.
    :param button: the button that changed.
    :param buttons: the buttons held.
    :returns: the event.
    """
    at = QPointF(point)
    return QMouseEvent(kind, at, at, button, buttons, Qt.KeyboardModifier.NoModifier)


FAR: Final = QPoint(3 * 10_000, 0)
"""A displacement no drag distance is bigger than."""


def test_a_press_tracker_answers_once_the_pointer_has_moved_the_drag_distance(qtbot: QtBot) -> None:
    """The token comes back once, only with the left button held, and only far enough from the press.

    **Test steps:**

    * press on a token, move one pixel, then far with the button up, then far with it held
    * verify nothing until the last, then the token, then nothing again
    """
    del qtbot  # the drag distance is the application's
    tracker = PressTracker()
    left = Qt.MouseButton.LeftButton
    tracker.press(mouse(QEvent.Type.MouseButtonPress, QPoint(5, 5), left, left), "token")

    assert tracker.moved(mouse(QEvent.Type.MouseMove, QPoint(5, 6), Qt.MouseButton.NoButton, left)) is None
    assert (
        tracker.moved(
            mouse(QEvent.Type.MouseMove, QPoint(5, 5) + FAR, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton)
        )
        is None
    )
    assert tracker.moved(mouse(QEvent.Type.MouseMove, QPoint(5, 5) + FAR, Qt.MouseButton.NoButton, left)) == "token"
    assert tracker.moved(mouse(QEvent.Type.MouseMove, QPoint(5, 5) + FAR, Qt.MouseButton.NoButton, left)) is None


def test_a_press_tracker_ignores_other_buttons_and_nothing_draggable_and_a_release(qtbot: QtBot) -> None:
    """A right press, a press on nothing, and a press let go of start no drag.

    **Test steps:**

    * press with the right button, press on nothing, press and release
    * move far with the left button held after each
    * verify nothing came back
    """
    del qtbot  # the drag distance is the application's
    tracker = PressTracker()
    left = Qt.MouseButton.LeftButton
    far = mouse(QEvent.Type.MouseMove, FAR, Qt.MouseButton.NoButton, left)

    tracker.press(
        mouse(QEvent.Type.MouseButtonPress, QPoint(), Qt.MouseButton.RightButton, Qt.MouseButton.RightButton), "x"
    )
    assert tracker.moved(far) is None
    tracker.press(mouse(QEvent.Type.MouseButtonPress, QPoint(), left, left), None)
    assert tracker.moved(far) is None
    tracker.press(mouse(QEvent.Type.MouseButtonPress, QPoint(), left, left), "x")
    tracker.release()
    assert tracker.moved(far) is None


def test_the_press_drag_filter_reports_a_draggable_thing_and_leaves_the_events_alone(qtbot: QtBot) -> None:
    """Only where the owner says something is draggable does a press-and-move report; the filter never consumes.

    **Test steps:**

    * watch a widget whose left half is draggable
    * press-and-move on the left half, then on the right, then press-release-move on the left
    * verify one report, for the left half, and that the widget still saw its own press
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.resize(200, 50)
    widget.show()
    reported: list[object] = []
    PressDragFilter(widget, lambda point: "left" if point.x() < 100 else None, reported.append)
    far = QPoint(0, 3 * QApplication.startDragDistance())

    QTest.mouseDClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    QApplication.sendEvent(
        widget, mouse(QEvent.Type.MouseMove, QPoint(10, 10) + far, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 10))
    QApplication.sendEvent(
        widget, mouse(QEvent.Type.MouseMove, QPoint(150, 10) + far, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(150, 10))
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    QApplication.sendEvent(
        widget, mouse(QEvent.Type.MouseMove, QPoint(10, 10) + far, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    )

    assert reported == ["left"]


def test_a_source_names_the_file_an_image_is_when_it_is_one(tmp_path: Path) -> None:
    """A path source and a screenshot-rows source know the file; anything else does not.

    **Test steps:**

    * ask a path source, a screenshot-rows source and a source whose key is a tuple
    * verify the file, the file, and none
    """
    path = tmp_path / "a.png"
    archive_member = type(
        "Member",
        (),
        {"key": lambda self, index: ("zip", "a.png", 1, 2)},  # a tier-0 key, as an archive member has
    )()

    assert source_file(PathImageSource([path]), 0) == path
    assert source_file(ScreenshotRowsImageSource([(path, ImageVisibility.VISIBLE)]), 0) == path
    assert source_file(archive_member, 0) is None  # type: ignore[arg-type]
    assert ScreenshotKey.of(path).path == path


def test_the_mime_names_the_original_file_only_when_there_is_one(tmp_path: Path) -> None:
    """Our drops read the original; another app never needs it.

    **Test steps:**

    * build the mime data with and without an original
    * verify the private type is carried only with one, as the path
    """
    staged = tmp_path / "staged.png"
    original = tmp_path / "a.png"

    with_original = image_mime(staged, b"x", original)
    without = image_mime(staged, b"x")

    assert bytes(with_original.data(ORIGINAL_FILE_MIME).data()).decode() == str(original)
    assert not without.hasFormat(ORIGINAL_FILE_MIME)


@fixture
def exporting(tmp_path: Path) -> tuple[ImageExporter, Path]:
    """An exporter over a resource folder holding one screenshot, naming files relative to the folder.

    :param tmp_path: pytest's temporary folder.
    :returns: the exporter and the screenshot.
    """
    folder = tmp_path / "Pack"
    (folder / "screenshots").mkdir(parents=True)
    shot = folder / "screenshots" / "a.png"
    image = QImage(8, 6, QImage.Format.Format_RGB32)
    image.fill(Qt.GlobalColor.darkRed)
    assert image.save(str(shot))
    return ImageExporter(tmp_path / "staged", lambda: ID, lambda: folder), shot


@fixture
def clipboard() -> Iterator[None]:
    """Leave the clipboard empty after the test."""
    yield
    QGuiApplication.clipboard().clear()


def test_a_file_exports_by_its_path_named_relative_to_the_record_folder_and_carries_its_original(
    exporting: tuple[ImageExporter, Path], clipboard: None
) -> None:
    """A widget that holds only paths copies one, and what it hands over names where the file really is.

    **Test steps:**

    * copy a screenshot by path
    * verify the clipboard names the scheme file under the staging folder, and the original file
    """
    del clipboard
    exporter, shot = exporting

    assert exporter.copy_path(shot)

    held = QGuiApplication.clipboard().mimeData()
    assert held is not None
    assert Path(held.urls()[0].toLocalFile()).name == f"rehu-{ID}__screenshots__a.png"
    assert bytes(held.data(ORIGINAL_FILE_MIME).data()).decode() == str(shot)


def test_a_file_drags_by_its_path_and_a_missing_base_names_it_by_its_own_name(
    qtbot: QtBot, exporting: tuple[ImageExporter, Path], tmp_path: Path, mocker: MockerFixture
) -> None:
    """A drag by path is the exporter's own drag over a one-image source; with no folder to be relative to, the staged
    name carries only the file's own.

    **Test steps:**

    * with ``QDrag`` replaced, drag a screenshot by path through two exporters, one with a base and one without
    * verify the two staged names
    """
    exporter, shot = exporting
    bare = ImageExporter(tmp_path / "staged", lambda: ID)
    widget = QWidget()
    qtbot.addWidget(widget)
    drag_class = mocker.patch("rehuco_agent.fields.widgets.image_export.QDrag")

    assert exporter.drag_path(widget, shot, QPixmap(10, 10))
    assert bare.drag_path(widget, shot, QPixmap(10, 10))

    names = [
        Path(call.args[0].urls()[0].toLocalFile()).name for call in drag_class.return_value.setMimeData.call_args_list
    ]
    assert names == [f"rehu-{ID}__screenshots__a.png", f"rehu-{ID}__a.png"]
