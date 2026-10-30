"""Tests for the Windows in-memory window picture (``PrintWindow`` into a ``QImage``)."""

from typing import Final

from borco_pyside.platforms.windows import window_picture
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from pytest import mark, skip
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

WP: Final = "borco_pyside.platforms.windows.window_picture"


def native_widget(qtbot: QtBot, colour: QColor) -> QWidget:
    """A shown widget with a native window of its own, filled with one colour.

    :param qtbot: pytest-qt fixture.
    :param colour: its background.
    :returns: the widget.
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
    widget.setAutoFillBackground(True)
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Window, colour)
    widget.setPalette(palette)
    widget.resize(64, 48)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


@mark.windows
def test_the_picture_is_the_windows_content_in_memory(qtbot: QtBot) -> None:
    """Needs the real ``windows`` platform plugin: under ``offscreen`` there is no window for the system to print.

    **Test steps:**

    * show a native widget filled with one colour and take its picture
    * verify the image has the widget's size and that colour in its middle
    """
    if QApplication.platformName() != "windows":
        skip("a real window is needed")
    widget = native_widget(qtbot, QColor(10, 200, 30))

    image = window_picture.picture_of(widget)

    assert image is not None
    assert (image.width(), image.height()) == (64, 48)
    assert QColor(image.pixel(32, 24)) == QColor(10, 200, 30)


@mark.windows
def test_a_window_the_system_will_not_print_gives_none(qtbot: QtBot, mocker: MockerFixture) -> None:
    """**Test steps:**

    * have ``PrintWindow`` refuse
    * verify ``None``
    """
    widget = native_widget(qtbot, QColor(0, 0, 0))
    mocker.patch(f"{WP}.ctypes.windll.user32.PrintWindow", create=True, return_value=0)

    assert window_picture.picture_of(widget) is None


@mark.windows
def test_a_window_with_no_size_gives_none(qtbot: QtBot) -> None:
    """**Test steps:**

    * ask for the picture of a widget never sized
    * verify ``None``, with no system call made
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.resize(0, 0)

    assert window_picture.picture_of(widget) is None


@mark.windows
def test_a_printed_window_becomes_an_image_of_its_size(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The system's bits are read into an image of the window's size; here the system is told to print nothing, so the
    path is exercised under any platform plugin.

    **Test steps:**

    * have ``PrintWindow`` succeed without drawing
    * verify an image of the widget's size comes back
    """
    widget = native_widget(qtbot, QColor(0, 0, 0))
    mocker.patch(f"{WP}.ctypes.windll.user32.PrintWindow", create=True, return_value=1)

    image = window_picture.picture_of(widget)

    assert image is not None
    assert (image.width(), image.height()) == (64, 48)


@mark.windows
def test_bits_the_system_will_not_hand_over_give_none(qtbot: QtBot, mocker: MockerFixture) -> None:
    """**Test steps:**

    * have ``PrintWindow`` succeed and ``GetDIBits`` read no rows
    * verify ``None``
    """
    widget = native_widget(qtbot, QColor(0, 0, 0))
    mocker.patch(f"{WP}.ctypes.windll.user32.PrintWindow", create=True, return_value=1)
    mocker.patch(f"{WP}.ctypes.windll.gdi32.GetDIBits", create=True, return_value=0)

    assert window_picture.picture_of(widget) is None
