"""Tests for the Windows foreground-forcing helper (the AttachThreadInput workaround)."""

from typing import Final

from borco_pyside.platforms.windows import window_activation
from PySide6.QtWidgets import QWidget
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot

WA: Final = "borco_pyside.platforms.windows.window_activation"
"""Module path prefix for ``mocker.patch`` targets below."""

FOREGROUND_HWND: Final = 111
FOREGROUND_THREAD: Final = 222
CURRENT_THREAD: Final = 333


@mark.windows
def test_force_foreground_attaches_borrows_input_and_detaches(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The helper attaches this thread's input to the foreground thread, forces itself to the
    front, then detaches again.

    ``ctypes.windll`` doesn't exist off Windows, so each call is patched with ``create=True``,
    matching ``test_win_registration.py``'s convention for this exact gotcha.

    **Test steps:**

    * mock every ``user32``/``kernel32`` call the helper makes, recording ``AttachThreadInput``
      calls in order
    * call ``force_foreground`` on a real (shown) widget
    * verify the foreground/current thread ids were looked up, ``AttachThreadInput`` was called
      to attach then to detach (in that order), and the window was restored, raised, and made
      the foreground window
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    attach_calls: list[tuple[int, int, bool]] = []
    show_window_calls: list[tuple[int, int]] = []
    bring_to_top_calls: list[int] = []
    set_foreground_calls: list[int] = []

    mocker.patch(f"{WA}.ctypes.windll.user32.GetForegroundWindow", create=True, return_value=FOREGROUND_HWND)
    mocker.patch(f"{WA}.ctypes.windll.user32.GetWindowThreadProcessId", create=True, return_value=FOREGROUND_THREAD)
    mocker.patch(f"{WA}.ctypes.windll.kernel32.GetCurrentThreadId", create=True, return_value=CURRENT_THREAD)
    mocker.patch(
        f"{WA}.ctypes.windll.user32.AttachThreadInput",
        create=True,
        side_effect=lambda a, b, c: attach_calls.append((a, b, c)),
    )
    mocker.patch(
        f"{WA}.ctypes.windll.user32.ShowWindow",
        create=True,
        side_effect=lambda hwnd, cmd: show_window_calls.append((hwnd, cmd)),
    )
    mocker.patch(f"{WA}.ctypes.windll.user32.BringWindowToTop", create=True, side_effect=bring_to_top_calls.append)
    mocker.patch(f"{WA}.ctypes.windll.user32.SetForegroundWindow", create=True, side_effect=set_foreground_calls.append)

    window_activation.force_foreground(widget)

    hwnd = int(widget.winId())
    assert attach_calls == [(CURRENT_THREAD, FOREGROUND_THREAD, True), (CURRENT_THREAD, FOREGROUND_THREAD, False)]
    assert show_window_calls == [(hwnd, 9)]
    assert bring_to_top_calls == [hwnd]
    assert set_foreground_calls == [hwnd]
