"""Tests for SharedRotatingFileHandler (#362)."""

import logging
import logging.handlers
from pathlib import Path
from unittest.mock import MagicMock

from borco_core.logging import SharedRotatingFileHandler
from borco_core.logging.shared_rotating_file_handler import MAX_LINE_LENGTH
from pytest_mock import MockerFixture

FAKE_PATH: str = "/fake/rehuco-agent.log"


def make_record(message: str = "message") -> logging.LogRecord:
    """Build a plain `~logging.LogRecord` to feed a handler directly.

    :param message: the record's message.
    :returns: the record.
    """
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)


def make_stream(*, tell: int = 0) -> MagicMock:
    """A stand-in for the open file object a handler writes to.

    :param tell: what the stream reports its current position as.
    :returns: the stand-in.
    """
    stream = MagicMock()
    stream.tell.return_value = tell
    return stream


# region construction and the non-rotating (forwarder) path


def test_construction_touches_no_file(mocker: MockerFixture) -> None:
    """``delay=True`` means building the handler opens nothing.

    **Test steps:**

    * patch ``_open``
    * construct the handler
    * verify ``_open`` was never called and no stream is held
    """
    open_mock = mocker.patch.object(SharedRotatingFileHandler, "_open")

    handler = SharedRotatingFileHandler(FAKE_PATH)

    open_mock.assert_not_called()
    assert handler.stream is None
    assert handler.rotates is False


def test_non_rotating_emit_opens_and_closes_the_stream(mocker: MockerFixture) -> None:
    """While not rotating (a forwarder), every record opens the file, appends, and closes it again --
    never holding it open, so a primary can always rename it out from under this process.

    **Test steps:**

    * emit two records with a forwarder handler
    * verify the stream was opened and closed once per record, and each record was written
    """
    stream = make_stream()
    open_mock = mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=stream)
    handler = SharedRotatingFileHandler(FAKE_PATH)

    handler.emit(make_record("first"))
    handler.emit(make_record("second"))

    assert open_mock.call_count == 2
    assert stream.close.call_count == 2
    assert handler.stream is None
    assert stream.write.call_count == 2


def test_non_rotating_emit_tolerates_a_record_that_never_opened_the_stream(mocker: MockerFixture) -> None:
    """When the underlying emit could not open the file at all (it reports the error itself and leaves
    no stream), there is nothing to close -- and nothing to raise about.

    **Test steps:**

    * stand in for the base emit with one that opens nothing
    * emit as a forwarder
    * verify nothing raised and no stream is held
    """
    mocker.patch.object(logging.FileHandler, "emit")
    handler = SharedRotatingFileHandler(FAKE_PATH)

    handler.emit(make_record())

    assert handler.stream is None


def test_non_rotating_emit_never_rolls_over(mocker: MockerFixture) -> None:
    """A forwarder never rotates, however small ``maxBytes`` is set -- rotation is the primary's alone.

    **Test steps:**

    * set a tiny ``maxBytes`` on a non-rotating handler
    * emit a record
    * verify ``doRollover`` was never reached
    """
    do_rollover = mocker.patch.object(SharedRotatingFileHandler, "doRollover")
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=make_stream(tell=1_000_000))
    handler = SharedRotatingFileHandler(FAKE_PATH)
    handler.maxBytes = 1

    handler.emit(make_record())

    do_rollover.assert_not_called()


# endregion

# region the rotating (primary) path


def test_rotating_emit_holds_the_stream_open(mocker: MockerFixture) -> None:
    """Once :attr:`rotates` is set, the handler behaves like a plain rotating handler: the stream stays
    open across records instead of being closed after each one.

    **Test steps:**

    * emit two records with ``rotates`` set
    * verify the stream was opened once and never closed
    """
    stream = make_stream()
    open_mock = mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=stream)
    handler = SharedRotatingFileHandler(FAKE_PATH)
    handler.rotates = True

    handler.emit(make_record("first"))
    handler.emit(make_record("second"))

    open_mock.assert_called_once()
    stream.close.assert_not_called()
    assert handler.stream is stream


def test_rotating_rolls_over_past_max_bytes(mocker: MockerFixture) -> None:
    """A record that would push the file past ``maxBytes`` rolls the file over first.

    **Test steps:**

    * make the stream report it is already past the limit
    * emit a record
    * verify the base class's rollover ran
    """
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=make_stream(tell=1_000_000))
    base_rollover = mocker.patch.object(logging.handlers.RotatingFileHandler, "doRollover")
    mocker.patch.object(Path, "exists", return_value=False)  # no extra backups to prune
    handler = SharedRotatingFileHandler(FAKE_PATH)
    handler.rotates = True
    handler.maxBytes = 1

    handler.emit(make_record())

    base_rollover.assert_called_once()


def test_rotating_reads_live_limits(mocker: MockerFixture) -> None:
    """``maxBytes``/``backupCount`` are read fresh on every record, so a setting changed while running
    applies to the very next one -- there is nothing cached to invalidate.

    **Test steps:**

    * emit under a generous limit, then lower it and emit again
    * verify rollover ran only for the second record
    """
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=make_stream(tell=1_000))
    base_rollover = mocker.patch.object(logging.handlers.RotatingFileHandler, "doRollover")
    mocker.patch.object(Path, "exists", return_value=False)
    handler = SharedRotatingFileHandler(FAKE_PATH)
    handler.rotates = True
    handler.maxBytes = 1_000_000

    handler.emit(make_record())
    base_rollover.assert_not_called()

    handler.maxBytes = 1
    handler.emit(make_record())
    base_rollover.assert_called_once()


def test_a_permission_error_during_rollover_keeps_appending_and_retries(mocker: MockerFixture) -> None:
    """A rename that fails with `PermissionError` -- another process holding the file open, on Windows
    -- is swallowed: the handler keeps appending to what it already has, and the next record over the
    limit tries the rename again rather than this one raising.

    **Test steps:**

    * make the base class's rollover raise ``PermissionError``
    * emit a record over the limit
    * verify nothing raised, the record was still written, and rollover was attempted
    """
    stream = make_stream(tell=1_000_000)
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=stream)
    base_rollover = mocker.patch.object(logging.handlers.RotatingFileHandler, "doRollover", side_effect=PermissionError)
    handler = SharedRotatingFileHandler(FAKE_PATH)
    handler.rotates = True
    handler.maxBytes = 1

    handler.emit(make_record())

    base_rollover.assert_called_once()
    stream.write.assert_called_once()


def test_lowering_backup_count_prunes_existing_extra_backups(mocker: MockerFixture) -> None:
    """A rotation run after ``backupCount`` was lowered removes the backups that are now past it,
    so lowering the setting actually frees the space rather than only stopping further growth.

    **Test steps:**

    * simulate three existing numbered backups with ``backupCount`` set to one
    * roll over
    * verify only the two past the live count were removed
    """
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=make_stream())
    mocker.patch.object(logging.handlers.RotatingFileHandler, "doRollover")
    unlink = mocker.patch.object(Path, "unlink")
    handler = SharedRotatingFileHandler(FAKE_PATH)
    handler.backupCount = 1

    def exists_side_effect(path_self: Path) -> bool:
        return path_self.name.rsplit(".", 1)[-1] in {"2", "3"}

    mocker.patch.object(Path, "exists", exists_side_effect, autospec=False)

    handler.doRollover()

    unlink.assert_any_call(missing_ok=True)
    assert unlink.call_count == 2


# endregion

# region the per-line length cap


def test_a_short_line_is_left_alone() -> None:
    """Nothing under the cap is touched.

    **Test steps:**

    * format an ordinary record
    * verify it comes back exactly as `~logging.Formatter` would produce it
    """
    handler = SharedRotatingFileHandler(FAKE_PATH)
    record = make_record("short")

    assert handler.format(record) == logging.Formatter().format(record)


def test_a_long_line_is_cut_and_says_by_how_much() -> None:
    """A record whose formatted line would exceed the cap -- a whole page source at DEBUG, in
    practice -- is cut to it, with a trailing note naming how much was dropped.

    **Test steps:**

    * format a record long enough to exceed the cap
    * verify the result is exactly at the cap plus the note, and the note's count matches what a
      full, uncut format would have been
    """
    handler = SharedRotatingFileHandler(FAKE_PATH)
    record = make_record("x" * (MAX_LINE_LENGTH * 2))
    full_length = len(logging.Formatter().format(record))

    formatted = handler.format(record)

    cut = full_length - MAX_LINE_LENGTH
    assert formatted == f"{'x' * MAX_LINE_LENGTH}… [{cut} chars cut]"


def test_a_warning_or_worse_is_never_cut() -> None:
    """A CRITICAL traceback, or the warning carrying a crashed run's stack dump, is written whole
    however long -- the cut guards against DEBUG noise, not against the record the file exists for.

    **Test steps:**

    * format a WARNING and a CRITICAL record both far over the cap
    * verify neither was cut
    """
    handler = SharedRotatingFileHandler(FAKE_PATH)
    for level in (logging.WARNING, logging.CRITICAL):
        record = logging.LogRecord("test", level, __file__, 1, "x" * (MAX_LINE_LENGTH * 2), None, None)

        formatted = handler.format(record)

        assert len(formatted) > MAX_LINE_LENGTH
        assert "cut" not in formatted


def test_a_line_exactly_at_the_cap_is_left_alone() -> None:
    """The boundary itself is not cut -- only a line strictly longer than the cap is.

    **Test steps:**

    * format a record whose formatted line is exactly `MAX_LINE_LENGTH` long
    * verify it comes back unchanged
    """
    handler = SharedRotatingFileHandler(FAKE_PATH)
    overhead = len(logging.Formatter().format(make_record("")))
    record = make_record("x" * (MAX_LINE_LENGTH - overhead))

    formatted = handler.format(record)

    assert len(formatted) == MAX_LINE_LENGTH
    assert "cut" not in formatted


# endregion

# region log_files / used_bytes / clear


def test_log_files_lists_the_base_and_existing_backups(mocker: MockerFixture) -> None:
    """The base file is always first; numbered backups follow for as long as each one exists, stopping
    at the first gap.

    **Test steps:**

    * simulate two existing backups
    * verify the three paths come back in order
    """
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=make_stream())
    handler = SharedRotatingFileHandler(FAKE_PATH)

    def exists_side_effect(path_self: Path) -> bool:
        return path_self.name in {"rehuco-agent.log.1", "rehuco-agent.log.2"}

    mocker.patch.object(Path, "exists", exists_side_effect, autospec=False)

    files = handler.log_files()

    assert [path.name for path in files] == ["rehuco-agent.log", "rehuco-agent.log.1", "rehuco-agent.log.2"]


def test_used_bytes_sums_existing_files_and_skips_missing_ones(mocker: MockerFixture) -> None:
    """A file that vanishes between listing and `stat`-ing counts as zero rather than failing the sum.

    **Test steps:**

    * list two files, one of which raises on ``stat``
    * verify the total counts only the one that could be stat'd
    """
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=make_stream())
    handler = SharedRotatingFileHandler(FAKE_PATH)
    base = Path(FAKE_PATH)
    backup = base.with_name(f"{base.name}.1")
    mocker.patch.object(SharedRotatingFileHandler, "log_files", return_value=[base, backup])

    def stat_side_effect(path_self: Path) -> MagicMock:
        if path_self == backup:
            raise FileNotFoundError
        return MagicMock(st_size=123)

    mocker.patch.object(Path, "stat", stat_side_effect, autospec=False)

    assert handler.used_bytes() == 123


def test_clear_with_no_open_stream_still_truncates_and_removes_backups(mocker: MockerFixture) -> None:
    """A forwarder-shaped handler (nothing held open between records) clears the same way -- there
    is just no stream to close first.

    **Test steps:**

    * clear a handler that never opened its file, with one backup simulated
    * verify the backup was removed and the base file was truncated
    """
    handler = SharedRotatingFileHandler(FAKE_PATH)
    base = Path(FAKE_PATH)
    mocker.patch.object(SharedRotatingFileHandler, "log_files", return_value=[base, base.with_name(f"{base.name}.1")])
    unlink = mocker.patch.object(Path, "unlink")
    open_mock = mocker.patch("builtins.open", mocker.mock_open())

    handler.clear()

    assert handler.stream is None
    unlink.assert_called_once_with(missing_ok=True)
    open_mock.assert_called_once_with(handler.baseFilename, "w", encoding="utf-8")


def test_clear_closes_the_stream_truncates_the_base_and_removes_backups(mocker: MockerFixture) -> None:
    """Clearing discards every backup and empties the base file in place -- truncated, not unlinked,
    since an unlink can fail while a forwarder holds the file open, while truncating an already-open
    file always succeeds.

    **Test steps:**

    * hold an open stream and simulate one backup
    * clear
    * verify the stream was closed, the backup was removed, and the base file was opened for
      truncating write
    """
    stream = make_stream()
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=stream)
    handler = SharedRotatingFileHandler(FAKE_PATH)
    handler.stream = stream  # simulate a primary holding the file open

    base = Path(FAKE_PATH)
    backup = base.with_name(f"{base.name}.1")
    mocker.patch.object(SharedRotatingFileHandler, "log_files", return_value=[base, backup])
    unlink = mocker.patch.object(Path, "unlink")
    open_mock = mocker.patch("builtins.open", mocker.mock_open())

    handler.clear()

    stream.close.assert_called_once()
    assert handler.stream is None
    unlink.assert_called_once_with(missing_ok=True)
    open_mock.assert_called_once_with(handler.baseFilename, "w", encoding="utf-8")
