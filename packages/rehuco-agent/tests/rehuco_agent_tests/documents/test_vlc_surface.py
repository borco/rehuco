"""Tests for the widget libvlc's frames are painted on (#319)."""

from PySide6.QtGui import QColor, QImage
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.vlc_surface import VlcSurface


def shown(qtbot: QtBot, width: int = 200, height: int = 100) -> VlcSurface:
    """A surface of a given size.

    :param qtbot: pytest-qt fixture.
    :param width: its width.
    :param height: its height.
    :returns: the surface.
    """
    surface = VlcSurface()
    qtbot.addWidget(surface)
    surface.resize(width, height)
    return surface


def test_with_no_frame_the_surface_is_black(qtbot: QtBot) -> None:
    """**Test steps:**

    * paint a surface with no frame
    * verify black
    """
    surface = shown(qtbot)

    picture = surface.grab().toImage()

    assert surface.frame is None
    assert QColor(picture.pixel(100, 50)) == QColor(0, 0, 0)


def test_a_frame_is_painted_to_fit_and_centred_on_black(qtbot: QtBot) -> None:
    """A 4:3 frame on a 2:1 surface fills the height, centred, with black at both sides.

    **Test steps:**

    * show a red 40x30 frame on a 200x100 surface
    * verify red in the middle, black at the far left and right, and the frame kept
    """
    surface = shown(qtbot)
    frame = QImage(40, 30, QImage.Format.Format_RGB32)
    frame.fill(QColor(255, 0, 0))

    surface.set_frame(frame)
    picture = surface.grab().toImage()

    assert surface.frame is frame
    assert QColor(picture.pixel(100, 50)) == QColor(255, 0, 0)
    assert QColor(picture.pixel(5, 50)) == QColor(0, 0, 0)
    assert QColor(picture.pixel(195, 50)) == QColor(0, 0, 0)


def test_a_frame_is_scaled_smoothly(qtbot: QtBot) -> None:
    """As the still a pause shows is: scaled by repeating pixels, a scale near 1 draws some rows and columns twice.

    **Test steps:**

    * show a 2x1 frame, black then white, on a 200x100 surface
    * verify the seam between them is grey, which only a smoothed scale draws
    """
    surface = shown(qtbot)
    frame = QImage(2, 1, QImage.Format.Format_RGB32)
    frame.setPixelColor(0, 0, QColor(0, 0, 0))
    frame.setPixelColor(1, 0, QColor(255, 255, 255))

    surface.set_frame(frame)
    picture = surface.grab().toImage()

    assert 0 < QColor(picture.pixel(100, 50)).red() < 255


def test_an_ordinary_widget_can_be_drawn_over_the_surface(qtbot: QtBot) -> None:
    """The point of painting the frames: the surface has no native window, so a sibling widget shows over it.

    **Test steps:**

    * show a red frame, then raise a green child widget over the surface's middle
    * verify green where the child is and red beside it
    """
    from PySide6.QtWidgets import QWidget  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

    surface = shown(qtbot)
    frame = QImage(40, 20, QImage.Format.Format_RGB32)
    frame.fill(QColor(255, 0, 0))
    surface.set_frame(frame)
    overlay = QWidget(surface)
    overlay.setStyleSheet("background: rgb(0, 255, 0)")
    overlay.setGeometry(80, 40, 40, 20)
    overlay.show()

    picture = surface.grab().toImage()

    assert QColor(picture.pixel(100, 50)) == QColor(0, 255, 0)
    assert QColor(picture.pixel(60, 50)) == QColor(255, 0, 0)
