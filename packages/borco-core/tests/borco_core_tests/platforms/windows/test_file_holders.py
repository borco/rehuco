"""Tests for the Restart Manager binding (#355).

Windows-only, like the module: ``rstrtmgr.dll`` is loaded at import, so the whole file skips off
Windows the same way the registry tests beside it do. What the Restart Manager actually reports is
measured in ``tests/test_file_holders.py``'s ``disk`` test; this covers the calls -- the session's
life, the buffer that grows to fit, and each refusal.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock

import pytest
from pytest import fixture, raises

pytest.importorskip("msvcrt")  # a Windows-only module stands in for "is this Windows" -- see the docstring

# these must follow the skip above, or collection fails off Windows -- hence the suppressions
from borco_core import FileHolder  # noqa: E402  # pylint: disable=wrong-import-position
from borco_core.platforms.windows import file_holders  # noqa: E402  # pylint: disable=wrong-import-position
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "borco_core.platforms.windows.file_holders"
"""Where the Restart Manager calls are patched -- every one of them funnels through this module."""

SESSION: Final = 42
"""A stand-in for the session handle ``RmStartSession`` writes back."""

PATHS: Final = (Path("C:/fake/pack/pack.zip"), Path("C:/fake/pack/info00.jpg"))

ERROR_ACCESS_DENIED: Final = 5
"""What ``RmGetList`` answers for a registered directory, among other refusals."""


def holding(*holders: tuple[int, str]) -> Callable[..., int]:
    """An ``RmGetList`` stand-in reporting ``holders``: ``ERROR_MORE_DATA`` with the count needed until
    it is handed a buffer that fits, then the holders written into it.

    :param holders: ``(pid, name)`` per process.
    :returns: the side effect.
    """

    def get_list(_session: Any, needed: Any, count: Any, infos: Any, _reasons: Any) -> int:
        needed._obj.value = len(holders)  # pylint: disable=protected-access
        if count._obj.value < len(holders):  # pylint: disable=protected-access
            return file_holders.ERROR_MORE_DATA
        for info, (pid, name) in zip(infos, holders, strict=False):
            info.Process.dwProcessId = pid
            info.strAppName = name
        count._obj.value = len(holders)  # pylint: disable=protected-access
        return file_holders.ERROR_SUCCESS

    return get_list


@fixture(name="calls")
def fixture_calls(mocker: MockerFixture) -> dict[str, MagicMock]:
    """Patch all four Restart Manager calls to succeed, with a session that starts as :data:`SESSION`
    and a list with nobody on it.

    :param mocker: pytest-mock fixture.
    :returns: the stand-ins, by call name.
    """

    def start(session: Any, _flags: Any, _key: Any) -> int:
        session._obj.value = SESSION  # pylint: disable=protected-access
        return file_holders.ERROR_SUCCESS

    return {
        "start": mocker.patch(f"{MODULE}.RM_START_SESSION", side_effect=start),
        "register": mocker.patch(f"{MODULE}.RM_REGISTER_RESOURCES", return_value=file_holders.ERROR_SUCCESS),
        "list": mocker.patch(f"{MODULE}.RM_GET_LIST", side_effect=holding()),
        "end": mocker.patch(f"{MODULE}.RM_END_SESSION", return_value=file_holders.ERROR_SUCCESS),
    }


def test_the_files_are_registered_and_their_holders_listed(calls: dict[str, MagicMock]) -> None:
    """Every path is registered in one session, and every process holding one comes back once.

    **Test steps:**

    * make the list report two processes, one of them twice
    * ask about two files
    * verify both paths were registered, the holders came back deduplicated, and the session ended
    """
    calls["list"].side_effect = holding((7, "Windows Explorer"), (9, "Rehuco"), (7, "Windows Explorer"))

    assert file_holders.file_holders(PATHS) == (FileHolder(7, "Windows Explorer"), FileHolder(9, "Rehuco"))

    registered = calls["register"].call_args.args
    assert registered[1] == len(PATHS)
    assert list(registered[2]) == [str(path) for path in PATHS]
    calls["end"].assert_called_once()
    assert calls["end"].call_args.args[0].value == SESSION


def test_nobody_holding_is_an_empty_answer(calls: dict[str, MagicMock]) -> None:
    """A list with nobody on it is not a refusal.

    **Test steps:**

    * ask about files nobody holds
    * verify the answer is empty and the list was asked once
    """
    assert not file_holders.file_holders(PATHS)
    calls["list"].assert_called_once()


def test_no_files_asks_nothing(calls: dict[str, MagicMock]) -> None:
    """With nothing to ask about, no session is started at all.

    **Test steps:**

    * ask about no files
    * verify the answer is empty and the Restart Manager was never called
    """
    assert not file_holders.file_holders(())
    calls["start"].assert_not_called()


def test_a_session_that_will_not_start_is_a_refusal(calls: dict[str, MagicMock]) -> None:
    """With no session there is nothing to end, and the caller hears why.

    **Test steps:**

    * make starting the session fail
    * ask, expecting the ``OSError`` for its code
    * verify nothing was registered and no session was ended
    """
    calls["start"].side_effect = None
    calls["start"].return_value = ERROR_ACCESS_DENIED

    with raises(OSError) as refusal:
        file_holders.file_holders(PATHS)

    assert refusal.value.winerror == ERROR_ACCESS_DENIED  # pyright: ignore[reportAttributeAccessIssue]
    calls["register"].assert_not_called()
    calls["end"].assert_not_called()


def test_a_refused_registration_still_ends_the_session(calls: dict[str, MagicMock]) -> None:
    """A session left open counts against a small per-user limit, so it ends on every path.

    **Test steps:**

    * make registering the files fail
    * ask, expecting the ``OSError`` for its code
    * verify the session was ended anyway
    """
    calls["register"].return_value = ERROR_ACCESS_DENIED

    with raises(OSError):
        file_holders.file_holders(PATHS)

    calls["end"].assert_called_once()


def test_a_refused_list_still_ends_the_session(calls: dict[str, MagicMock]) -> None:
    """Listing is refused for a registered directory, measured -- and the session still ends.

    **Test steps:**

    * make the list fail outright
    * ask, expecting the ``OSError`` for its code
    * verify the session was ended anyway
    """
    calls["list"].side_effect = None
    calls["list"].return_value = ERROR_ACCESS_DENIED

    with raises(OSError):
        file_holders.file_holders(PATHS)

    calls["end"].assert_called_once()


def test_a_list_that_keeps_growing_gives_up(calls: dict[str, MagicMock]) -> None:
    """A buffer that never fits -- processes joining faster than it grows -- is a bounded refusal.

    **Test steps:**

    * make the list always ask for more room than it was given
    * ask, expecting an ``OSError``
    * verify the list was tried the bounded number of times and the session ended
    """

    def always_more(_session: Any, needed: Any, count: Any, _infos: Any, _reasons: Any) -> int:
        needed._obj.value = count._obj.value + 1  # pylint: disable=protected-access
        return file_holders.ERROR_MORE_DATA

    calls["list"].side_effect = always_more

    with raises(OSError):
        file_holders.file_holders(PATHS)

    assert calls["list"].call_count == file_holders.LIST_ATTEMPTS
    calls["end"].assert_called_once()
