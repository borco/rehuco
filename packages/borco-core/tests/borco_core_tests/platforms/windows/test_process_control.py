"""Tests for finding, raising and ending a holder's process (#505).

Windows-only, like the module: ``user32`` and ``kernel32`` are loaded at import, so the whole file skips off
Windows the way the Restart Manager tests beside it do. Every Win32 call is a stand-in here; what Windows
really does to a process is measured in ``tests/test_process_control.py``.
"""

from typing import Any, Final
from unittest.mock import MagicMock

import pytest
from pytest import fixture, raises

pytest.importorskip("msvcrt")  # a Windows-only module stands in for "is this Windows" -- see the docstring

# these must follow the skip above, or collection fails off Windows -- hence the suppressions
from borco_core.platforms.windows import process_control  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "borco_core.platforms.windows.process_control"
"""Where the Win32 calls are patched -- every one of them funnels through this module."""

PID: Final = 4242
OTHER_PID: Final = 7

TASKBAR: Final = 101
"""A visible, unowned, titled window of :data:`PID` -- the one to show."""
HIDDEN: Final = 102
OWNED: Final = 103
UNTITLED: Final = 104
SOMEONE_ELSES: Final = 105

HANDLE: Final = 9001
"""A stand-in for the process handle ``OpenProcess`` returns."""

FOREGROUND_THREAD: Final = 11
CURRENT_THREAD: Final = 12

ERROR_ACCESS_DENIED: Final = 5


@fixture(name="windows")
def fixture_windows(mocker: MockerFixture) -> dict[str, MagicMock]:
    """Patch the window calls over five top-level windows, one of each kind, :data:`TASKBAR` first.

    :param mocker: pytest-mock fixture.
    :returns: the stand-ins, by call name.
    """
    owners = {TASKBAR: PID, HIDDEN: PID, OWNED: PID, UNTITLED: PID, SOMEONE_ELSES: OTHER_PID}

    def enum_windows(callback: Any, parameter: int) -> bool:
        for window in owners:
            callback(window, parameter)
        return True

    def thread_process_id(window: int, owner: Any) -> int:
        if owner is not None:
            owner._obj.value = owners.get(window, 0)  # pylint: disable=protected-access
        return FOREGROUND_THREAD

    return {
        "enum": mocker.patch(f"{MODULE}.ENUM_WINDOWS", side_effect=enum_windows),
        "owner": mocker.patch(f"{MODULE}.GET_WINDOW_THREAD_PROCESS_ID", side_effect=thread_process_id),
        "visible": mocker.patch(f"{MODULE}.IS_WINDOW_VISIBLE", side_effect=lambda window: window != HIDDEN),
        "owned": mocker.patch(f"{MODULE}.GET_WINDOW", side_effect=lambda window, _kind: 1 if window == OWNED else None),
        "title": mocker.patch(f"{MODULE}.GET_WINDOW_TEXT_LENGTH", side_effect=lambda window: window != UNTITLED),
        "iconic": mocker.patch(f"{MODULE}.IS_ICONIC", return_value=False),
        "show": mocker.patch(f"{MODULE}.SHOW_WINDOW", return_value=True),
        "foreground": mocker.patch(f"{MODULE}.SET_FOREGROUND_WINDOW", return_value=True),
        "current_foreground": mocker.patch(f"{MODULE}.GET_FOREGROUND_WINDOW", return_value=SOMEONE_ELSES),
        "attach": mocker.patch(f"{MODULE}.ATTACH_THREAD_INPUT", return_value=True),
        "current_thread": mocker.patch(f"{MODULE}.GET_CURRENT_THREAD_ID", return_value=CURRENT_THREAD),
    }


@fixture(name="process")
def fixture_process(mocker: MockerFixture) -> dict[str, MagicMock]:
    """Patch the process calls: it opens, ends and exits within the wait.

    :param mocker: pytest-mock fixture.
    :returns: the stand-ins, by call name.
    """
    return {
        "open": mocker.patch(f"{MODULE}.OPEN_PROCESS", return_value=HANDLE),
        "terminate": mocker.patch(f"{MODULE}.TERMINATE_PROCESS", return_value=True),
        "wait": mocker.patch(f"{MODULE}.WAIT_FOR_SINGLE_OBJECT", return_value=process_control.WAIT_OBJECT_0),
        "close": mocker.patch(f"{MODULE}.CLOSE_HANDLE", return_value=True),
        "last_error": mocker.patch(f"{MODULE}.ctypes.get_last_error", return_value=ERROR_ACCESS_DENIED),
    }


@pytest.mark.usefixtures("windows")
def test_only_a_taskbar_window_of_the_process_counts() -> None:
    """A hidden, owned or untitled window is no window to show, and neither is another process's.

    **Test steps:**

    * list five windows: the process's taskbar one, its hidden, owned and untitled ones, and someone else's
    * verify only the taskbar one is found, and the process has a window while another pid has none
    """
    assert process_control.top_windows(PID) == (TASKBAR,)
    assert process_control.has_window(PID)
    assert not process_control.has_window(OTHER_PID + 1)


def test_showing_brings_the_taskbar_window_forward(windows: dict[str, MagicMock]) -> None:
    """The window found is the one handed the foreground, with no input attached when that is allowed.

    **Test steps:**

    * show the process
    * verify the taskbar window took the foreground, nothing was restored and no input was attached
    """
    assert process_control.show_window(PID)

    windows["foreground"].assert_called_once_with(TASKBAR)
    windows["show"].assert_not_called()
    windows["attach"].assert_not_called()


def test_a_minimized_window_is_restored_first(windows: dict[str, MagicMock]) -> None:
    """A window on the taskbar only is restored before it is brought forward.

    **Test steps:**

    * make the window minimized, and show the process
    * verify it was restored, then brought forward
    """
    windows["iconic"].return_value = True

    assert process_control.show_window(PID)

    windows["show"].assert_called_once_with(TASKBAR, process_control.SW_RESTORE)
    windows["foreground"].assert_called_once_with(TASKBAR)


def test_a_refused_foreground_retries_with_input_attached(windows: dict[str, MagicMock]) -> None:
    """Refused the foreground, the call is made again with input attached to the foreground thread, then
    detached.

    **Test steps:**

    * refuse the first foreground request and grant the second
    * show the process
    * verify input was attached to the foreground thread and detached again after the retry
    """
    windows["foreground"].side_effect = [False, True]

    assert process_control.show_window(PID)

    assert windows["attach"].call_args_list == [
        ((CURRENT_THREAD, FOREGROUND_THREAD, True),),
        ((CURRENT_THREAD, FOREGROUND_THREAD, False),),
    ]


def test_a_failed_attach_is_not_detached(windows: dict[str, MagicMock]) -> None:
    """An attach that failed leaves nothing to undo, and the retry's answer is still the answer.

    **Test steps:**

    * refuse the foreground both times, and refuse the attach
    * show the process
    * verify the answer is no and the attach was tried once, never undone
    """
    windows["foreground"].return_value = False
    windows["attach"].return_value = False

    assert not process_control.show_window(PID)

    windows["attach"].assert_called_once_with(CURRENT_THREAD, FOREGROUND_THREAD, True)


def test_the_foreground_thread_being_this_one_attaches_nothing(windows: dict[str, MagicMock]) -> None:
    """A thread cannot attach its input to itself, so when it holds the foreground it only retries.

    **Test steps:**

    * make this thread the foreground one, and refuse the first foreground request
    * show the process
    * verify the retry happened with no attach
    """
    windows["foreground"].side_effect = [False, True]
    windows["current_thread"].return_value = FOREGROUND_THREAD

    assert process_control.show_window(PID)

    windows["attach"].assert_not_called()


def test_a_process_with_no_window_shows_nothing(windows: dict[str, MagicMock]) -> None:
    """With no taskbar window there is nothing to bring forward.

    **Test steps:**

    * show a process that has no windows
    * verify the answer is no and no window was touched
    """
    assert not process_control.show_window(OTHER_PID + 1)

    windows["foreground"].assert_not_called()


def test_ending_terminates_waits_and_closes(process: dict[str, MagicMock]) -> None:
    """The process is ended, waited for, and its handle closed.

    **Test steps:**

    * end the process with a two-second wait
    * verify it was opened with the right to end and wait on it, ended, waited for in milliseconds, and
      its handle closed
    """
    assert process_control.end_process(PID, 2.0)

    process["open"].assert_called_once_with(process_control.PROCESS_TERMINATE | process_control.SYNCHRONIZE, False, PID)
    process["terminate"].assert_called_once_with(HANDLE, process_control.TERMINATED_EXIT_CODE)
    process["wait"].assert_called_once_with(HANDLE, 2000)
    process["close"].assert_called_once_with(HANDLE)


def test_a_process_still_there_after_the_wait_is_not_gone(process: dict[str, MagicMock]) -> None:
    """A process that outlived the wait is reported as still running.

    **Test steps:**

    * make the wait time out, and end the process
    * verify the answer is no and the handle was closed
    """
    process["wait"].return_value = 0x102  # WAIT_TIMEOUT

    assert not process_control.end_process(PID, 2.0)

    process["close"].assert_called_once_with(HANDLE)


def test_a_process_already_gone_is_gone(process: dict[str, MagicMock]) -> None:
    """An id no process has any more is what was asked for.

    **Test steps:**

    * make opening the process fail with the invalid-parameter error
    * verify the answer is yes and nothing was ended
    """
    process["open"].return_value = None
    process["last_error"].return_value = process_control.ERROR_INVALID_PARAMETER

    assert process_control.end_process(PID, 2.0)

    process["terminate"].assert_not_called()


def test_a_process_that_will_not_open_is_a_refusal(process: dict[str, MagicMock]) -> None:
    """Access denied to open the process -- an elevated one -- reaches the caller.

    **Test steps:**

    * make opening the process fail with access denied
    * end it, expecting the ``OSError`` for that code
    * verify nothing was ended or closed
    """
    process["open"].return_value = None

    with raises(OSError) as refusal:
        process_control.end_process(PID, 2.0)

    assert refusal.value.winerror == ERROR_ACCESS_DENIED  # pyright: ignore[reportAttributeAccessIssue]
    process["terminate"].assert_not_called()
    process["close"].assert_not_called()


def test_a_refused_end_still_closes_the_handle(process: dict[str, MagicMock]) -> None:
    """A process that opened but would not end is a refusal, and its handle is still closed.

    **Test steps:**

    * make ending the process fail with access denied
    * end it, expecting the ``OSError`` for that code
    * verify the handle was closed and nothing was waited for
    """
    process["terminate"].return_value = False

    with raises(OSError) as refusal:
        process_control.end_process(PID, 2.0)

    assert refusal.value.winerror == ERROR_ACCESS_DENIED  # pyright: ignore[reportAttributeAccessIssue]
    process["wait"].assert_not_called()
    process["close"].assert_called_once_with(HANDLE)
