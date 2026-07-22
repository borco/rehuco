"""Tests for the Windows foreground-forcing helper (the AttachThreadInput workaround)."""

from typing import Final

import pytest
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
        side_effect=lambda a, b, c: attach_calls.append((a, b, c)) or True,
    )
    mocker.patch(
        f"{WA}.ctypes.windll.user32.ShowWindow",
        create=True,
        side_effect=lambda hwnd, cmd: show_window_calls.append((hwnd, cmd)) or True,
    )
    mocker.patch(
        f"{WA}.ctypes.windll.user32.BringWindowToTop",
        create=True,
        side_effect=lambda hwnd: bring_to_top_calls.append(hwnd) or True,
    )
    mocker.patch(
        f"{WA}.ctypes.windll.user32.SetForegroundWindow",
        create=True,
        side_effect=lambda hwnd: set_foreground_calls.append(hwnd) or True,
    )

    window_activation.force_foreground(widget)

    hwnd = int(widget.winId())
    assert attach_calls == [(CURRENT_THREAD, FOREGROUND_THREAD, True), (CURRENT_THREAD, FOREGROUND_THREAD, False)]
    assert show_window_calls == [(hwnd, 9)]
    assert bring_to_top_calls == [hwnd]
    assert set_foreground_calls == [hwnd]


@mark.windows
def test_force_foreground_skips_attach_when_already_foreground_thread(mocker: MockerFixture, qtbot: QtBot) -> None:
    """When the foreground window's thread is this process's own thread, ``AttachThreadInput``
    is skipped entirely -- calling it with matching thread ids fails and would make the paired
    detach below "succeed" against nothing.

    **Test steps:**

    * mock the foreground/current thread lookups to return the same id
    * call ``force_foreground``
    * verify ``AttachThreadInput`` was never called, while the raise/restore calls still happened
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    attach = mocker.patch(f"{WA}.ctypes.windll.user32.AttachThreadInput", create=True, return_value=True)
    mocker.patch(f"{WA}.ctypes.windll.user32.GetForegroundWindow", create=True, return_value=FOREGROUND_HWND)
    mocker.patch(f"{WA}.ctypes.windll.user32.GetWindowThreadProcessId", create=True, return_value=CURRENT_THREAD)
    mocker.patch(f"{WA}.ctypes.windll.kernel32.GetCurrentThreadId", create=True, return_value=CURRENT_THREAD)
    mocker.patch(f"{WA}.ctypes.windll.user32.ShowWindow", create=True, return_value=True)
    set_foreground = mocker.patch(f"{WA}.ctypes.windll.user32.SetForegroundWindow", create=True, return_value=True)
    mocker.patch(f"{WA}.ctypes.windll.user32.BringWindowToTop", create=True, return_value=True)

    window_activation.force_foreground(widget)

    attach.assert_not_called()
    set_foreground.assert_called_once_with(int(widget.winId()))


@mark.windows
def test_force_foreground_detaches_even_if_set_foreground_window_raises(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The detach happens even when a call between attach and detach blows up, so a ctypes-level
    surprise never leaves the input queues attached.

    **Test steps:**

    * mock ``SetForegroundWindow`` to raise
    * call ``force_foreground`` and expect the exception to propagate
    * verify ``AttachThreadInput`` was still called a second time, to detach
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    attach_calls: list[bool] = []

    mocker.patch(f"{WA}.ctypes.windll.user32.GetForegroundWindow", create=True, return_value=FOREGROUND_HWND)
    mocker.patch(f"{WA}.ctypes.windll.user32.GetWindowThreadProcessId", create=True, return_value=FOREGROUND_THREAD)
    mocker.patch(f"{WA}.ctypes.windll.kernel32.GetCurrentThreadId", create=True, return_value=CURRENT_THREAD)
    mocker.patch(
        f"{WA}.ctypes.windll.user32.AttachThreadInput",
        create=True,
        side_effect=lambda a, b, c: attach_calls.append(c) or True,
    )
    mocker.patch(f"{WA}.ctypes.windll.user32.ShowWindow", create=True, return_value=True)
    mocker.patch(f"{WA}.ctypes.windll.user32.BringWindowToTop", create=True, return_value=True)
    mocker.patch(f"{WA}.ctypes.windll.user32.SetForegroundWindow", create=True, side_effect=OSError("boom"))

    with pytest.raises(OSError, match="boom"):
        window_activation.force_foreground(widget)

    assert attach_calls == [True, False]


@mark.windows
def test_force_foreground_logs_win32_call_failures(
    mocker: MockerFixture, qtbot: QtBot, caplog: pytest.LogCaptureFixture
) -> None:
    """A ``0`` return from ``AttachThreadInput``, ``BringWindowToTop``, or ``SetForegroundWindow``
    is a documented Win32 failure signal and gets logged, instead of being silently ignored.

    **Test steps:**

    * mock every failure-checked call to report failure (``0``/``False``)
    * call ``force_foreground``
    * verify a warning was logged for each of the three failure-checked calls
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    mocker.patch(f"{WA}.ctypes.windll.user32.GetForegroundWindow", create=True, return_value=FOREGROUND_HWND)
    mocker.patch(f"{WA}.ctypes.windll.user32.GetWindowThreadProcessId", create=True, return_value=FOREGROUND_THREAD)
    mocker.patch(f"{WA}.ctypes.windll.kernel32.GetCurrentThreadId", create=True, return_value=CURRENT_THREAD)
    mocker.patch(f"{WA}.ctypes.windll.user32.AttachThreadInput", create=True, return_value=False)
    mocker.patch(f"{WA}.ctypes.windll.user32.ShowWindow", create=True, return_value=True)
    mocker.patch(f"{WA}.ctypes.windll.user32.BringWindowToTop", create=True, return_value=False)
    mocker.patch(f"{WA}.ctypes.windll.user32.SetForegroundWindow", create=True, return_value=False)

    with caplog.at_level("WARNING", logger=WA):
        window_activation.force_foreground(widget)

    messages = [record.message for record in caplog.records]
    assert any("AttachThreadInput" in message for message in messages)
    assert any("BringWindowToTop" in message for message in messages)
    assert any("SetForegroundWindow" in message for message in messages)


@mark.windows
def test_force_foreground_logs_detach_failure(
    mocker: MockerFixture, qtbot: QtBot, caplog: pytest.LogCaptureFixture
) -> None:
    """A failed detach is logged too -- distinct from the attach failure covered above, since
    ``attached`` only becomes ``True`` (and the detach call happens at all) when the attach itself
    succeeded.

    **Test steps:**

    * mock ``AttachThreadInput`` to succeed on attach but fail on detach
    * call ``force_foreground``
    * verify a warning was logged for the detach failure
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.show()

    mocker.patch(f"{WA}.ctypes.windll.user32.GetForegroundWindow", create=True, return_value=FOREGROUND_HWND)
    mocker.patch(f"{WA}.ctypes.windll.user32.GetWindowThreadProcessId", create=True, return_value=FOREGROUND_THREAD)
    mocker.patch(f"{WA}.ctypes.windll.kernel32.GetCurrentThreadId", create=True, return_value=CURRENT_THREAD)
    mocker.patch(
        f"{WA}.ctypes.windll.user32.AttachThreadInput",
        create=True,
        side_effect=lambda a, b, attach: attach,
    )
    mocker.patch(f"{WA}.ctypes.windll.user32.ShowWindow", create=True, return_value=True)
    mocker.patch(f"{WA}.ctypes.windll.user32.BringWindowToTop", create=True, return_value=True)
    mocker.patch(f"{WA}.ctypes.windll.user32.SetForegroundWindow", create=True, return_value=True)

    with caplog.at_level("WARNING", logger=WA):
        window_activation.force_foreground(widget)

    assert any("AttachThreadInput(detach)" in record.message for record in caplog.records)
