"""Tests for watchdog's ReadDirectoryChangesW emitter made to report a lost buffer and to close its handle once
(#511).

Windows-only, like the module: watchdog's Windows API is loaded at import, so the file skips elsewhere. The directory
handle is real, opened on ``tmp_path``; what the emitter reads is replaced where an overflow or a failing read is what
is asserted.
"""

from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

import pytest
from pytest import raises

pytest.importorskip("msvcrt")  # a Windows-only module stands in for "is this Windows"

# these must follow the skip above, or collection fails off Windows -- hence the suppressions
from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_core.platforms.windows.overflow_reporting_emitter import (  # noqa: E402  # pylint: disable=wrong-import-position
    OverflowReportingEmitter,
)
from watchdog.observers.api import EventQueue, ObservedWatch  # noqa: E402  # pylint: disable=wrong-import-position
from watchdog.observers.winapi import close_directory_handle  # noqa: E402  # pylint: disable=wrong-import-position

MODULE: Final = "rehuco_core.platforms.windows.overflow_reporting_emitter"


def emitter_of(folder: Path) -> OverflowReportingEmitter:
    """An emitter of ``folder``, not started.

    :param folder: the watched folder.
    :returns: the emitter.
    """
    return OverflowReportingEmitter(EventQueue(), ObservedWatch(str(folder), recursive=True))


def test_a_second_stop_closes_nothing(tmp_path: Path, mocker: MockerFixture) -> None:
    """The handle is closed once, however often the emitter is stopped: a second close of the same value could close
    whatever Windows handed it to meanwhile, which ended the process at quit.

    **Test steps:**

    * open the emitter's real handle, and count the closes, still closing for real
    * stop the emitter's thread twice
    * verify the handle was closed exactly once
    """
    close = mocker.patch(f"{MODULE}.close_directory_handle", wraps=close_directory_handle)
    emitter = emitter_of(tmp_path)
    emitter.on_thread_start()

    emitter.on_thread_stop()
    emitter.on_thread_stop()

    close.assert_called_once()


def test_an_empty_read_while_running_is_an_overflow(tmp_path: Path, mocker: MockerFixture) -> None:
    """A read that succeeds with no entries while the emitter is meant to run is the system saying it discarded a
    buffer: the callback hears it. A read with entries, or one with no callback set, is no overflow.

    **Test steps:**

    * open the emitter's handle, and make reads answer nothing
    * read with a callback set, and with none; make reads answer an entry and read again
    * verify the callback was called once, and every read answered what was read
    """
    read = mocker.patch(f"{MODULE}.read_events", return_value=[])
    emitter = emitter_of(tmp_path)
    emitter.on_thread_start()
    on_overflow = MagicMock()

    emitter.on_overflow = on_overflow
    assert emitter._read_events() == []  # pylint: disable=protected-access
    emitter.on_overflow = None
    assert emitter._read_events() == []  # pylint: disable=protected-access
    emitter.on_overflow = on_overflow
    read.return_value = [mocker.sentinel.entry]
    assert emitter._read_events() == [mocker.sentinel.entry]  # pylint: disable=protected-access

    on_overflow.assert_called_once_with()
    emitter.on_thread_stop()


def test_a_read_after_the_handle_was_closed_reads_nothing(tmp_path: Path, mocker: MockerFixture) -> None:
    """With no handle, there is nothing to read and nothing was lost.

    **Test steps:**

    * stop an emitter whose handle was opened, and read
    * verify nothing was read and no overflow reported
    """
    read = mocker.patch(f"{MODULE}.read_events")
    emitter = emitter_of(tmp_path)
    emitter.on_overflow = on_overflow = MagicMock()
    emitter.on_thread_start()
    emitter.stop()

    assert emitter._read_events() == []  # pylint: disable=protected-access

    read.assert_not_called()
    on_overflow.assert_not_called()


def test_a_read_failing_because_of_a_stop_is_nothing_lost(tmp_path: Path, mocker: MockerFixture) -> None:
    """A stop closing the handle under a read makes it fail; that is the stop, not a lost buffer.

    **Test steps:**

    * open the emitter's handle, mark it stopped without closing it, and make the read fail
    * verify the read answers nothing and no overflow is reported
    """
    mocker.patch(f"{MODULE}.read_events", side_effect=OSError(6, "The handle is invalid"))
    emitter = emitter_of(tmp_path)
    emitter.on_overflow = on_overflow = MagicMock()
    emitter.on_thread_start()
    emitter.stopped_event.set()

    assert emitter._read_events() == []  # pylint: disable=protected-access

    on_overflow.assert_not_called()
    emitter.on_thread_stop()


def test_a_read_failing_while_running_is_raised(tmp_path: Path, mocker: MockerFixture) -> None:
    """A read that fails while the emitter is meant to run is a real failure -- the folder went away -- and ends the
    emitter, which the watch reports as failed.

    **Test steps:**

    * open the emitter's handle and make the read fail
    * verify the read raises the error
    """
    mocker.patch(f"{MODULE}.read_events", side_effect=OSError(5, "Access is denied"))
    emitter = emitter_of(tmp_path)
    emitter.on_thread_start()

    with raises(OSError, match="Access is denied"):
        emitter._read_events()  # pylint: disable=protected-access

    emitter.on_thread_stop()
