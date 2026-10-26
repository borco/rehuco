"""Tests for showing and ending a process that holds a file (#505).

Two kinds, as with naming the holders: the **dispatch** is mocked, and what Windows does to a real process
is not -- that test starts a child of its own to end, and carries ``windows``.
"""

import subprocess  # nosec B404 -- the test starts its own interpreter, with fixed arguments
import sys
from typing import Final

from borco_core import end_process, has_window, show_window
from pytest import mark
from pytest_mock import MockerFixture

WINDOWS_MODULE: Final = "borco_core.platforms.windows.process_control"
"""Where the Windows branch lands, patched at its source module -- the import happens inside the call."""

PID: Final = 4242

END_TIMEOUT: Final = 10.0
"""Generous: a terminated process is gone in milliseconds, and a slow machine is no reason to fail."""


def test_off_windows_there_is_nothing_to_show_or_end(mocker: MockerFixture) -> None:
    """Off Windows nobody is ever named a holder, so every answer is no.

    **Test steps:**

    * force ``sys.platform`` to Linux
    * verify a process has no window, cannot be shown, and is not ended
    """
    mocker.patch("borco_core.process_control.sys.platform", "linux")

    assert not has_window(PID)
    assert not show_window(PID)
    assert not end_process(PID, END_TIMEOUT)


@mark.windows
def test_windows_asks_the_windows_calls(mocker: MockerFixture) -> None:
    """On Windows each question goes to its Windows call.

    **Test steps:**

    * patch the three Windows calls
    * ask each question, and verify each was handed the pid (and the wait) and its answer returned
    """
    has = mocker.patch(f"{WINDOWS_MODULE}.has_window", return_value=True)
    show = mocker.patch(f"{WINDOWS_MODULE}.show_window", return_value=True)
    end = mocker.patch(f"{WINDOWS_MODULE}.end_process", return_value=True)

    assert has_window(PID)
    assert show_window(PID)
    assert end_process(PID, END_TIMEOUT)

    has.assert_called_once_with(PID)
    show.assert_called_once_with(PID)
    end.assert_called_once_with(PID, END_TIMEOUT)


@mark.windows
def test_a_running_child_is_ended() -> None:
    """A process this one started is ended and gone within the wait, and has no window to show.

    **Test steps:**

    * start an interpreter that sleeps, with no window
    * verify it has no taskbar window, then end it
    * verify it is gone, with the exit code Task Manager gives
    """
    assert sys.platform == "win32"  # narrows the platform for the type checker on other systems
    with subprocess.Popen(  # nosec B603 -- our own interpreter, fixed arguments
        (sys.executable, "-c", "import time; time.sleep(60)"), creationflags=subprocess.CREATE_NO_WINDOW
    ) as child:
        try:
            assert not has_window(child.pid)
            assert end_process(child.pid, END_TIMEOUT)
            assert child.wait(END_TIMEOUT) == 1
        finally:
            child.kill()
