"""Tests for the Windows synchronous-first-paint helper (the ``UpdateWindow`` call)."""

from typing import Final

from borco_pyside.platforms.windows import window_painting
from PySide6.QtWidgets import QWidget
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

WP: Final = "borco_pyside.platforms.windows.window_painting"
"""Module path prefix for ``mocker.patch`` targets below."""


@mark.windows
def test_paint_now_updates_the_widgets_own_native_window(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The helper hands the widget's own ``HWND`` to ``UpdateWindow``, and nothing else.

    ``ctypes.windll`` doesn't exist off Windows, so the call is patched with ``create=True``,
    matching ``test_window_activation.py``'s convention for this exact gotcha.

    **Test steps:**

    * mock ``UpdateWindow`` on a real (shown) widget
    * call ``paint_now``
    * verify ``UpdateWindow`` was called once, with that widget's window handle
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()
    update_window = mocker.patch(f"{WP}.ctypes.windll.user32.UpdateWindow", create=True, return_value=True)

    window_painting.paint_now(widget)

    update_window.assert_called_once_with(int(widget.winId()))
