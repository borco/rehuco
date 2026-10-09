"""Tests for RunLog: the persistent rotating run log and how a run's end is always recorded (#362)."""

# One object covers the file's roles, every hook, the sentinel, faulthandler, signals and repeat
# suppression; its suite is correspondingly long -- one cohesive module reads better than an arbitrary
# split, so the module-length cap is lifted here rather than fragmenting it (as
# test_rehu_document_model.py does).
# pylint: disable=too-many-lines

import logging
import signal
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from borco_core.logging import SharedRotatingFileHandler
from PySide6.QtCore import QtMsgType
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_agent.run_log import QT_LOG_LEVELS, QUIET_LOGGERS, REPEAT_REPORT_INTERVAL_S, RunLog, shared_run_log
from rehuco_agent.settings.logs_settings import BYTES_PER_MB, DEFAULT_FILE_BACKUPS, DEFAULT_FILE_SIZE_MB, LogsSettings

FAKE_PATH: Path = Path("/fake/rehuco-agent.log")


def build_run_log() -> RunLog:
    """A fresh `RunLog` over a settings object nobody else shares, and a path never touched on disk: the
    autouse :func:`patch_filesystem` stands in for every file the log reads or writes.

    :returns: the run log, not started.
    """
    return RunLog(FAKE_PATH, LogsSettings())


@fixture(autouse=True)
def patch_filesystem(mocker: MockerFixture) -> None:
    """Every test in this file starts a `RunLog` at least once; none of them means to create a real
    directory or write a real record -- the handler's own file is stood in for, the same way
    ``test_shared_rotating_file_handler.py`` stands in for it at the handler level alone.

    The sentinel too, by default (#475): no leftover one is read, writing it does nothing, reopening it for
    ``faulthandler`` fails quietly (so the real ``faulthandler`` is never pointed anywhere), and removing it
    succeeds. A test about one of those patches it again. Before, they reached the disk under ``/fake`` and
    passed only while ``C:\\fake`` did not exist.
    """
    mocker.patch.object(Path, "mkdir")
    stream = mocker.MagicMock()
    stream.tell.return_value = 0  # keeps a rotating handler from ever thinking it's past maxBytes
    mocker.patch.object(SharedRotatingFileHandler, "_open", return_value=stream)
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError)
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch.object(Path, "open", side_effect=OSError)
    mocker.patch.object(Path, "unlink")
    mocker.patch("rehuco_agent.run_log.faulthandler.enable")


# region construction and live limits


def test_applies_the_settings_default_limits_on_construction() -> None:
    """The handler's own ``maxBytes``/``backupCount`` are seeded from the shared settings as soon as
    the `RunLog` is built, before ``start`` ever runs.

    **Test steps:**

    * build a run log
    * verify the handler's limits match the settings' defaults
    """
    log = build_run_log()

    assert log.handler.maxBytes == DEFAULT_FILE_SIZE_MB * BYTES_PER_MB
    assert log.handler.backupCount == DEFAULT_FILE_BACKUPS


def test_follows_a_live_settings_change() -> None:
    """A size or backup count changed after construction reaches the handler at once -- the same
    "settable while running" the in-app log surfaces already offer.

    **Test steps:**

    * build a run log, tied to its own settings object
    * change both settings
    * verify the handler picked up both
    """
    settings = LogsSettings()
    log = RunLog(FAKE_PATH, settings)

    settings.file_size_mb = 5
    settings.file_backups = 7

    assert log.handler.maxBytes == 5 * BYTES_PER_MB
    assert log.handler.backupCount == 7


# endregion


# region start()


def test_start_attaches_the_handler_and_logs_a_banner(caplog: LogCaptureFixture) -> None:
    """Starting attaches the handler to the root logger and records this run's banner: an id, this
    process's pid, and the argv it was launched with.

    **Test steps:**

    * start a run log with a fake argv
    * verify the handler is now on the root logger
    * verify the banner names the argv
    """
    log = build_run_log()

    with caplog.at_level(logging.INFO, logger="rehuco_agent.run_log"):
        log.start(["rehuco-agent", "a.rehu"])

    assert log.handler in logging.getLogger().handlers
    assert any("a.rehu" in record.message for record in caplog.records)


def test_a_folder_that_cannot_be_created_leaves_the_run_console_only(
    mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A run whose log folder cannot be created still starts -- it just stays console-only, the same
    fail-safe #361 already gives a failed :func:`~rehuco_agent.settings.persistent_settings.config_folder`
    write.

    **Test steps:**

    * make the folder creation fail
    * start
    * verify the handler was never attached, and a warning was logged instead of a banner
    """
    mocker.patch.object(Path, "mkdir", side_effect=OSError("no such device"))
    log = build_run_log()

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.run_log"):
        log.start(["rehuco-agent"])

    assert log.handler not in logging.getLogger().handlers
    assert any("will not be written" in record.message for record in caplog.records)


def test_start_quiets_the_noisy_third_party_loggers() -> None:
    """Selenium's WebDriver traffic (including whole page sources), the local HTTP calls behind it, and
    markdown's per-render extension notices are raised to INFO for every surface, not only the file --
    so the same page source is never cached by the bridge for replay, printed to the console, or
    padding an in-app log dock either (#362).

    Restores each logger's level afterward -- they are process-wide, not this test's to leave behind.

    **Test steps:**

    * lower each of them back to DEBUG, then start
    * verify each was raised to its configured level
    """
    originals = {name: logging.getLogger(name).level for name in QUIET_LOGGERS}
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)

    try:
        build_run_log().start(["rehuco-agent"])
        for name, level in QUIET_LOGGERS.items():
            assert logging.getLogger(name).level == level
    finally:
        for name, level in originals.items():
            logging.getLogger(name).setLevel(level)


def test_the_format_includes_the_thread_name() -> None:
    """A crash's own native stack dump shows every thread's frames but not which one mattered -- the
    thread name is what a Python-level record can add that the dump alone cannot (#362).

    **Test steps:**

    * start, then format a record built on this (the calling) thread
    * verify the formatted line names it
    """
    log = build_run_log()
    log.start(["rehuco-agent"])
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "message", None, None)
    record.role = "?"  # type: ignore[attr-defined]  # ordinarily stamped by the handler's own filter

    assert threading.current_thread().name in log.handler.format(record)


def test_log_exception_and_finish_are_quiet_when_the_folder_could_not_be_created(mocker: MockerFixture) -> None:
    """Neither ``log_exception`` nor ``finish`` does anything for a run that never really started --
    there is nothing installed anywhere for them to reach.

    **Test steps:**

    * make the folder creation fail, then start
    * call ``log_exception`` and ``finish``
    * verify neither touched the sentinel
    """
    mocker.patch.object(Path, "mkdir", side_effect=OSError)
    unlink = mocker.patch.object(Path, "unlink")
    log = build_run_log()
    log.start(["rehuco-agent"])

    log.log_exception(ValueError("boom"), "somewhere")
    log.become_primary()
    log.finish(0)

    unlink.assert_not_called()


# endregion


# region uncaught exceptions and Qt messages


def test_excepthook_logs_critical_and_chains(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """An uncaught exception -- including one PySide re-raises from a Qt slot -- is logged CRITICAL
    with its traceback, then handed to whatever hook was installed before this one.

    **Test steps:**

    * install a mock as the previous excepthook, then start a run log
    * call ``sys.excepthook``
    * verify the exception was logged (naming its source plainly, not "in an uncaught exception") and
      the previous hook still ran
    """
    previous = mocker.MagicMock()
    mocker.patch.object(sys, "excepthook", previous)
    log = build_run_log()
    log.start(["rehuco-agent"])
    error = ValueError("boom")

    with caplog.at_level(logging.CRITICAL, logger="rehuco_agent.run_log"):
        sys.excepthook(ValueError, error, None)

    assert any("boom" in record.message and "sys.excepthook" in record.message for record in caplog.records)
    previous.assert_called_once_with(ValueError, error, None)


def test_threading_excepthook_logs_and_chains(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """Same for an exception uncaught on a background thread.

    **Test steps:**

    * install a mock as the previous threading excepthook, then start a run log
    * call ``threading.excepthook``
    * verify the exception was logged and the previous hook still ran
    """
    previous = mocker.MagicMock()
    mocker.patch.object(threading, "excepthook", previous)
    log = build_run_log()
    log.start(["rehuco-agent"])
    args = threading.ExceptHookArgs((ValueError, ValueError("boom"), None, threading.current_thread()))

    with caplog.at_level(logging.CRITICAL, logger="rehuco_agent.run_log"):
        threading.excepthook(args)

    assert any("boom" in record.message for record in caplog.records)
    previous.assert_called_once_with(args)


def test_threading_excepthook_with_no_exception_value_still_chains(mocker: MockerFixture) -> None:
    """A hook args carrying no exception value (some interpreter shutdown paths) is chained without
    trying to log it.

    **Test steps:**

    * call ``threading.excepthook`` with ``exc_value=None``
    * verify the previous hook still ran and nothing raised
    """
    previous = mocker.MagicMock()
    mocker.patch.object(threading, "excepthook", previous)
    log = build_run_log()
    log.start(["rehuco-agent"])
    args = threading.ExceptHookArgs((SystemExit, None, None, None))

    threading.excepthook(args)

    previous.assert_called_once_with(args)


def test_unraisablehook_logs_and_chains(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """Same for an exception that could not be raised anywhere (e.g. from ``__del__``).

    **Test steps:**

    * install a mock as the previous unraisable hook, then start a run log
    * call ``sys.unraisablehook``
    * verify the exception was logged and the previous hook still ran
    """
    previous = mocker.MagicMock()
    mocker.patch.object(sys, "unraisablehook", previous)
    log = build_run_log()
    log.start(["rehuco-agent"])
    args = SimpleNamespace(exc_type=ValueError, exc_value=ValueError("boom"), exc_traceback=None, object=None)

    with caplog.at_level(logging.CRITICAL, logger="rehuco_agent.run_log"):
        sys.unraisablehook(args)  # type: ignore[arg-type]  # duck-typed stand-in for UnraisableHookArgs

    assert any("boom" in record.message and "sys.unraisablehook" in record.message for record in caplog.records)
    previous.assert_called_once_with(args)


def test_unraisablehook_with_no_exception_value_still_chains(mocker: MockerFixture) -> None:
    """Same guard as the threading hook's: nothing to log, but the previous hook still runs.

    **Test steps:**

    * call ``sys.unraisablehook`` with ``exc_value=None``
    * verify the previous hook still ran and nothing raised
    """
    previous = mocker.MagicMock()
    mocker.patch.object(sys, "unraisablehook", previous)
    log = build_run_log()
    log.start(["rehuco-agent"])
    args = SimpleNamespace(exc_type=None, exc_value=None, exc_traceback=None, object=None)

    sys.unraisablehook(args)  # type: ignore[arg-type]  # duck-typed stand-in for UnraisableHookArgs

    previous.assert_called_once_with(args)


def test_qt_log_levels_cover_every_message_type() -> None:
    """Every `~PySide6.QtCore.QtMsgType` Qt can hand a message handler maps to a logging level.

    **Test steps:**

    * verify the mapping's keys are exactly the four Qt message types
    """
    assert set(QT_LOG_LEVELS) == {
        QtMsgType.QtDebugMsg,
        QtMsgType.QtInfoMsg,
        QtMsgType.QtWarningMsg,
        QtMsgType.QtCriticalMsg,
        QtMsgType.QtFatalMsg,
    }


def test_qt_message_handler_routes_a_plain_message(caplog: LogCaptureFixture) -> None:
    """A message with no named category (Qt's own ``"default"``) is routed to the ``qt`` logger as-is.

    Reached through the name-mangled attribute, the same way ``test_logs_page.py`` reaches a page's
    own ``__ui`` -- there is no other seam to call it through, since it is installed with
    `~PySide6.QtCore.qInstallMessageHandler` rather than kept as anything public.

    **Test steps:**

    * call the handler directly with a "default"-category context
    * verify the ``qt`` logger got the plain message at the mapped level
    """
    log = build_run_log()
    context = SimpleNamespace(category="default")

    with caplog.at_level(logging.WARNING, logger="qt"):
        log._RunLog__qt_message_handler(QtMsgType.QtWarningMsg, context, "boom")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    # no-member: a false positive from the same PySide6-import/astroid interaction conftest.py's
    # FakeSettings notes -- caplog.records holds plain logging.LogRecord instances
    assert caplog.records[-1].message == "boom"  # pylint: disable=no-member
    assert caplog.records[-1].levelno == logging.WARNING  # pylint: disable=no-member


def test_qt_message_handler_prefixes_a_named_category(caplog: LogCaptureFixture) -> None:
    """A named category is kept, since it is the only clue as to which part of Qt logged the message.

    **Test steps:**

    * call the handler with a named category
    * verify it prefixes the message
    """
    log = build_run_log()
    context = SimpleNamespace(category="qt.qpa.xcb")

    with caplog.at_level(logging.INFO, logger="qt"):
        log._RunLog__qt_message_handler(QtMsgType.QtInfoMsg, context, "boom")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert caplog.records[-1].message == "[qt.qpa.xcb] boom"  # pylint: disable=no-member


def test_a_fatal_qt_message_flushes_every_root_handler(mocker: MockerFixture) -> None:
    """`qFatal` aborts right after the handler returns, so every handler is flushed first or the
    record it just wrote may never reach disk.

    **Test steps:**

    * stand in for the root logger's handlers
    * call the handler with a fatal message
    * verify every one of them was flushed
    """
    log = build_run_log()
    handlers = [mocker.MagicMock(level=0), mocker.MagicMock(level=0)]
    mocker.patch.object(logging.getLogger(), "handlers", handlers)
    context = SimpleNamespace(category="default")

    log._RunLog__qt_message_handler(QtMsgType.QtFatalMsg, context, "dead")  # type: ignore[attr-defined]  # pylint: disable=protected-access

    for handler in handlers:
        handler.flush.assert_called_once()


# endregion


# region roles and the sentinel


def test_become_forwarder_never_rotates_or_touches_the_sentinel(mocker: MockerFixture) -> None:
    """A forwarder is exactly what it started as: neither rotating nor holding the sentinel.

    **Test steps:**

    * become a forwarder
    * verify the handler still does not rotate, and nothing was written
    """
    write = mocker.patch("rehuco_agent.run_log.atomic_write_text")
    log = build_run_log()
    log.start(["rehuco-agent"])

    enable = mocker.patch("rehuco_agent.run_log.faulthandler.enable")

    log.become_forwarder()

    assert log.handler.rotates is False
    write.assert_not_called()
    enable.assert_not_called()


def test_become_primary_starts_rotating_and_writes_the_sentinel(mocker: MockerFixture) -> None:
    """Becoming primary is what turns rotation on, and is when the sentinel naming this run is written.

    **Test steps:**

    * become primary
    * verify the handler now rotates, and the sentinel was written under this run's own path
    """
    write = mocker.patch("rehuco_agent.run_log.atomic_write_text")
    log = build_run_log()
    log.start(["rehuco-agent"])

    log.become_primary()

    assert log.handler.rotates is True
    write.assert_called_once()
    written_path, written_text = write.call_args[0]
    assert written_path == FAKE_PATH.parent / "primary.run"
    assert "pid=" in written_text


def test_a_sentinel_write_failure_is_logged_not_raised(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """A sentinel that cannot be written is a warning, not a reason to refuse becoming primary.

    **Test steps:**

    * make the write fail
    * become primary
    * verify nothing raised and a warning was logged
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text", side_effect=OSError)
    log = build_run_log()
    log.start(["rehuco-agent"])

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.run_log"):
        log.become_primary()

    assert any("sentinel" in record.message for record in caplog.records)


def test_no_leftover_sentinel_stays_quiet(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """The ordinary case -- the last run exited cleanly and removed its own sentinel -- says nothing.

    :func:`patch_filesystem` reads no sentinel: the read fails with ``FileNotFoundError``.

    **Test steps:**

    * become primary
    * verify no "ended without exiting cleanly" warning was logged
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    log = build_run_log()
    log.start(["rehuco-agent"])

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.run_log"):
        log.become_primary()

    assert not any("ended without exiting cleanly" in record.message for record in caplog.records)


def test_a_present_sentinel_warns_with_its_contents(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """A sentinel still on disk at the next start names a run that never reached ``finish`` -- a
    native crash, End Task, or power loss.

    **Test steps:**

    * simulate a readable leftover sentinel
    * become primary
    * verify the warning names what the sentinel held
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch.object(Path, "read_text", return_value="run=abc123 pid=999")
    log = build_run_log()
    log.start(["rehuco-agent"])

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.run_log"):
        log.become_primary()

    assert any("abc123" in record.message and "999" in record.message for record in caplog.records)


def test_an_unreadable_sentinel_still_warns(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """A sentinel that exists but cannot be read (permissions, a half-written file) is treated the
    same as a present one, rather than silently ignored.

    **Test steps:**

    * make reading the sentinel fail with something other than "missing"
    * become primary
    * verify a warning was still logged
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch.object(Path, "read_text", side_effect=PermissionError)
    log = build_run_log()
    log.start(["rehuco-agent"])

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.run_log"):
        log.become_primary()

    assert any("could not be read" in record.message for record in caplog.records)


def test_become_primary_enables_faulthandler_on_the_sentinel_file(mocker: MockerFixture) -> None:
    """A native crash's own stack dump shows every thread's frames but never a line of Python, so
    `faulthandler` is what recovers that -- into the sentinel, appended after its own ``run=`` line, so
    the next start's leftover-sentinel warning carries the dump along with it (#362).

    **Test steps:**

    * become primary with the sentinel reopenable
    * verify faulthandler was enabled on that same (reopened) file, watching every thread
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    fake_file = mocker.MagicMock()
    # also what the leftover-sentinel check's own read_text() opens the path with -- "a" mode is the
    # call this test is about, not necessarily the only one Path.open sees
    open_mock = mocker.patch.object(Path, "open", return_value=fake_file)
    enable = mocker.patch("rehuco_agent.run_log.faulthandler.enable")
    log = build_run_log()
    log.start(["rehuco-agent"])

    log.become_primary()

    assert mocker.call("a", encoding="utf-8") in open_mock.call_args_list
    enable.assert_called_once_with(file=fake_file, all_threads=True)


def test_a_sentinel_that_cannot_be_reopened_skips_faulthandler_quietly(mocker: MockerFixture) -> None:
    """Nothing more useful can be said than the write failure `__write_sentinel` already warned about.

    **Test steps:**

    * make reopening the sentinel fail
    * become primary
    * verify faulthandler was never enabled, and nothing raised
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch.object(Path, "open", side_effect=OSError)
    enable = mocker.patch("rehuco_agent.run_log.faulthandler.enable")
    log = build_run_log()
    log.start(["rehuco-agent"])

    log.become_primary()

    enable.assert_not_called()


def test_a_failed_sentinel_write_never_enables_faulthandler(mocker: MockerFixture) -> None:
    """There is no sentinel to append the dump to when the write itself already failed.

    **Test steps:**

    * make the sentinel write fail
    * become primary
    * verify faulthandler was never enabled
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text", side_effect=OSError)
    enable = mocker.patch("rehuco_agent.run_log.faulthandler.enable")
    log = build_run_log()
    log.start(["rehuco-agent"])

    log.become_primary()

    enable.assert_not_called()


# endregion


# region finish()


def test_finish_logs_the_exit_code(caplog: LogCaptureFixture) -> None:
    """The ordinary case: an exit code, said plainly.

    **Test steps:**

    * start, then finish with a code
    * verify it was logged
    """
    log = build_run_log()
    log.start(["rehuco-agent"])

    with caplog.at_level(logging.INFO, logger="rehuco_agent.run_log"):
        log.finish(3)

    assert any("exited with code 3" in record.message for record in caplog.records)


def test_finish_with_no_code_says_an_exception_ended_it(caplog: LogCaptureFixture) -> None:
    """No exit code means the run ended by an exception rather than returning one -- said as such,
    since ``log_exception`` has already recorded the exception itself.

    **Test steps:**

    * start, then finish with ``None``
    * verify it was logged that way
    """
    log = build_run_log()
    log.start(["rehuco-agent"])

    with caplog.at_level(logging.INFO, logger="rehuco_agent.run_log"):
        log.finish(None)

    assert any("ended by an exception" in record.message for record in caplog.records)


def test_finish_removes_the_sentinel_for_the_primary(mocker: MockerFixture) -> None:
    """Only the primary wrote the sentinel, so only the primary removes it on a clean exit.

    **Test steps:**

    * become primary, then finish
    * verify the sentinel was removed
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    unlink = mocker.patch.object(Path, "unlink")
    log = build_run_log()
    log.start(["rehuco-agent"])
    log.become_primary()

    log.finish(0)

    unlink.assert_called_once()


def test_finish_does_not_touch_the_sentinel_for_a_forwarder(mocker: MockerFixture) -> None:
    """A forwarder never held the sentinel, so it does not try to remove it either.

    **Test steps:**

    * become a forwarder, then finish
    * verify nothing was removed
    """
    unlink = mocker.patch.object(Path, "unlink")
    log = build_run_log()
    log.start(["rehuco-agent"])
    log.become_forwarder()

    log.finish(0)

    unlink.assert_not_called()


def test_finish_closes_the_fault_file_before_unlinking_the_sentinel(mocker: MockerFixture) -> None:
    """The faulthandler file handle from :meth:`become_primary` is closed *before* the sentinel is
    removed -- an open handle would otherwise make that removal fail on Windows (#362).

    **Test steps:**

    * become primary with a reopenable sentinel, recording the order ``close``/``unlink`` happen in
    * finish
    * verify the file was closed strictly before the sentinel was unlinked
    """
    order: list[str] = []
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch("rehuco_agent.run_log.faulthandler.enable")
    mocker.patch("rehuco_agent.run_log.faulthandler.disable")
    fake_file = mocker.MagicMock()
    fake_file.close.side_effect = lambda: order.append("close")
    mocker.patch.object(Path, "open", return_value=fake_file)
    mocker.patch.object(Path, "unlink", side_effect=lambda *args, **kwargs: order.append("unlink"))
    log = build_run_log()
    log.start(["rehuco-agent"])
    log.become_primary()

    log.finish(0)

    assert order == ["close", "unlink"]


def test_a_fault_file_that_fails_to_close_still_lets_the_sentinel_go(mocker: MockerFixture) -> None:
    """A close that raises is swallowed: the handle is dropped either way, and the sentinel's removal
    -- the thing that actually says the run ended cleanly -- is not held hostage to it.

    **Test steps:**

    * become primary with a reopenable sentinel whose handle fails to close
    * finish
    * verify nothing raised and the sentinel was still removed
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch("rehuco_agent.run_log.faulthandler.enable")
    mocker.patch("rehuco_agent.run_log.faulthandler.disable")
    fake_file = mocker.MagicMock()
    fake_file.close.side_effect = OSError("already gone")
    mocker.patch.object(Path, "open", return_value=fake_file)
    unlink = mocker.patch.object(Path, "unlink")
    log = build_run_log()
    log.start(["rehuco-agent"])
    log.become_primary()

    log.finish(0)

    unlink.assert_called_once()


def test_an_already_missing_sentinel_is_not_an_error_on_finish(
    mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A sentinel already gone by ``finish`` (cleared by hand, or by the Logs page) is the outcome
    ``finish`` wanted anyway -- no warning.

    **Test steps:**

    * become primary, then make the unlink report the file missing
    * finish
    * verify no warning was logged
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch.object(Path, "unlink", side_effect=FileNotFoundError)
    log = build_run_log()
    log.start(["rehuco-agent"])
    log.become_primary()

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.run_log"):
        log.finish(0)

    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_a_sentinel_removal_failure_is_logged_not_raised(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """A sentinel that cannot be removed (in practice, vanishingly rare next to a missing one) is a
    warning, not a reason for ``finish`` to raise.

    **Test steps:**

    * make removing it fail with something other than "missing"
    * finish as primary
    * verify a warning was logged instead of raising
    """
    mocker.patch("rehuco_agent.run_log.atomic_write_text")
    mocker.patch.object(Path, "unlink", side_effect=PermissionError)
    log = build_run_log()
    log.start(["rehuco-agent"])
    log.become_primary()

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.run_log"):
        log.finish(0)

    assert any("sentinel" in record.message for record in caplog.records)


# endregion


# region log_exception()


def test_log_exception_is_quiet_before_start(caplog: LogCaptureFixture) -> None:
    """Nothing is installed anywhere before ``start``, so there is nothing worth logging to yet.

    **Test steps:**

    * log an exception without ever starting
    * verify nothing was logged
    """
    log = build_run_log()

    with caplog.at_level(logging.CRITICAL):
        log.log_exception(ValueError("boom"), "somewhere")

    assert caplog.records == []


def test_log_exception_logs_once_per_distinct_error(caplog: LogCaptureFixture) -> None:
    """The same exception can reach here from more than one layer on its way out -- ``sys.excepthook``,
    then whatever wrapped ``main()``/``app.exec()`` and re-raised it -- and a reader should see it once.

    **Test steps:**

    * log the same exception object from two different places
    * verify only one record was written
    """
    log = build_run_log()
    log.start(["rehuco-agent"])
    error = ValueError("boom")

    with caplog.at_level(logging.CRITICAL, logger="rehuco_agent.run_log"):
        log.log_exception(error, "app.exec()")
        log.log_exception(error, "main()")

    assert len(caplog.records) == 1


def test_an_identical_exception_repeating_is_counted_not_rewritten(
    mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A slot raising the same exception on every repaint recurs several times a second; the file
    gets the traceback once, then a count at most once per interval -- never the traceback again.

    **Test steps:**

    * log the same-shaped exception five times within one interval, with the clock pinned
    * verify one full record was written and nothing more
    * move the clock past the interval and log it once more
    * verify one summary naming five repeats was written
    """
    clock = mocker.patch("rehuco_agent.run_log.time.monotonic", return_value=100.0)
    log = build_run_log()
    log.start(["rehuco-agent"])

    def raise_it() -> None:
        raise ValueError("same every time")

    def caught() -> ValueError:
        try:
            raise_it()
        except ValueError as error:
            return error
        raise AssertionError  # pragma: no cover

    with caplog.at_level(logging.CRITICAL, logger="rehuco_agent.run_log"):
        for _ in range(6):
            log.log_exception(caught(), "a slot")
        assert [record.message for record in caplog.records if "same every time" in record.message] != []
        assert len(caplog.records) == 1

        clock.return_value = 100.0 + REPEAT_REPORT_INTERVAL_S
        log.log_exception(caught(), "a slot")

    messages = [record.message for record in caplog.records]
    assert len(messages) == 2
    assert "repeated 6 more times" in messages[1]
    assert "same every time" not in messages[1]


def test_unreported_repeats_are_flushed_before_a_different_exception(caplog: LogCaptureFixture) -> None:
    """The count is never lost: a different exception arriving first writes the pending count out
    ahead of itself.

    **Test steps:**

    * log one exception twice, then a different one
    * verify the middle record is the repeat count and the last is the new exception in full
    """
    log = build_run_log()
    log.start(["rehuco-agent"])

    def caught(message: str) -> ValueError:
        try:
            raise ValueError(message)
        except ValueError as error:
            return error
        raise AssertionError  # pragma: no cover

    with caplog.at_level(logging.CRITICAL, logger="rehuco_agent.run_log"):
        log.log_exception(caught("first"), "here")
        log.log_exception(caught("first"), "here")
        log.log_exception(caught("second"), "there")

    messages = [record.message for record in caplog.records]
    assert len(messages) == 3
    assert "repeated 1 more time" in messages[1]
    assert "second" in messages[2]


def test_log_exception_logs_a_different_error_again(caplog: LogCaptureFixture) -> None:
    """A genuinely different exception is not deduplicated against the last one.

    **Test steps:**

    * log two distinct exceptions
    * verify both were recorded
    """
    log = build_run_log()
    log.start(["rehuco-agent"])

    with caplog.at_level(logging.CRITICAL, logger="rehuco_agent.run_log"):
        log.log_exception(ValueError("first"), "somewhere")
        log.log_exception(ValueError("second"), "somewhere else")

    assert len(caplog.records) == 2


# endregion


# region watch()


def test_watch_logs_about_to_quit_and_commit_data_request(mocker: MockerFixture, caplog: LogCaptureFixture) -> None:
    """Both of a `QGuiApplication`'s own shutdown signals are logged, wherever they land in the
    platform-specific wiring below.

    **Test steps:**

    * watch a mocked app
    * fire both signals' connected callbacks
    * verify both were logged
    """
    mocker.patch.object(sys, "platform", "win32")  # skip the POSIX wiring; not what this test is about
    log = build_run_log()
    log.start(["rehuco-agent"])
    app = mocker.MagicMock()

    log.watch(app)
    about_to_quit = app.aboutToQuit.connect.call_args[0][0]
    commit_data_request = app.commitDataRequest.connect.call_args[0][0]

    # not-callable: the same PySide6-import/astroid false positive noted above -- both are plain
    # closures captured off a mocked ``connect``, not a real bound signal
    with caplog.at_level(logging.INFO, logger="rehuco_agent.run_log"):
        about_to_quit()  # pylint: disable=not-callable
        commit_data_request(mocker.MagicMock())  # pylint: disable=not-callable

    messages = [record.message for record in caplog.records]
    assert "aboutToQuit" in messages
    assert "commitDataRequest" in messages


def test_watch_on_windows_wires_no_signal_handling(mocker: MockerFixture) -> None:
    """The GUI build gets no console signals on Windows, and ``TerminateProcess`` cannot be caught
    from inside the process it kills -- the sentinel covers that instead, so nothing is wired here.

    **Test steps:**

    * watch on a Windows-like platform
    * verify no socket notifier was built
    """
    mocker.patch.object(sys, "platform", "win32")
    notifier_cls = mocker.patch("rehuco_agent.run_log.QSocketNotifier")
    log = build_run_log()
    log.start(["rehuco-agent"])

    log.watch(mocker.MagicMock())

    notifier_cls.assert_not_called()


def test_watch_on_posix_wires_a_socket_notifier_that_exits_on_a_signal(mocker: MockerFixture) -> None:
    """POSIX: SIGTERM/SIGINT reach the event loop through a self-pipe and an orderly ``app.exit``.

    **Test steps:**

    * fake the socket pair and the notifier class, and watch on a POSIX-like platform
    * fire the notifier's connected callback as if SIGTERM had arrived
    * verify the app was told to exit with 128 + the signal number
    """
    mocker.patch.object(sys, "platform", "linux")
    mocker.patch("rehuco_agent.run_log.signal.set_wakeup_fd")
    signal_signal = mocker.patch("rehuco_agent.run_log.signal.signal")
    reader, writer = mocker.MagicMock(), mocker.MagicMock()
    reader.fileno.return_value = 7
    mocker.patch("rehuco_agent.run_log.socket.socketpair", return_value=(reader, writer))
    notifier_cls = mocker.patch("rehuco_agent.run_log.QSocketNotifier")
    log = build_run_log()
    log.start(["rehuco-agent"])
    app = mocker.MagicMock()

    log.watch(app)

    # QSocketNotifier is itself patched below, so production code's own ``QSocketNotifier.Type.Read``
    # resolves through that same mock, not the real enum -- compared against itself, not against
    # ``QSocketNotifier`` imported directly above
    notifier_cls.assert_called_once_with(7, notifier_cls.Type.Read, app)
    assert signal_signal.call_count == 2
    # the Python-level handler installed for both signals is deliberately a no-op: the wakeup fd
    # write is what carries the signal, so calling it must do nothing and raise nothing
    installed_handler = signal_signal.call_args[0][1]
    # not-callable: the same PySide6-import/astroid false positive as the on_activated() call below
    installed_handler(signal.SIGTERM, None)  # pylint: disable=not-callable
    on_activated = notifier_cls.return_value.activated.connect.call_args[0][0]
    reader.recv.return_value = bytes([signal.SIGTERM])

    # not-callable: the same PySide6-import/astroid false positive noted above
    on_activated()  # pylint: disable=not-callable

    app.exit.assert_called_once_with(128 + signal.SIGTERM)


def test_watch_on_posix_ignores_a_read_that_would_block(mocker: MockerFixture) -> None:
    """A notifier can fire with nothing actually readable yet; that is not a signal to act on.

    **Test steps:**

    * make the read raise ``BlockingIOError``
    * fire the notifier's callback
    * verify the app was not told to exit
    """
    mocker.patch.object(sys, "platform", "linux")
    mocker.patch("rehuco_agent.run_log.signal.set_wakeup_fd")
    mocker.patch("rehuco_agent.run_log.signal.signal")
    reader, writer = mocker.MagicMock(), mocker.MagicMock()
    reader.fileno.return_value = 7
    reader.recv.side_effect = BlockingIOError
    mocker.patch("rehuco_agent.run_log.socket.socketpair", return_value=(reader, writer))
    notifier_cls = mocker.patch("rehuco_agent.run_log.QSocketNotifier")
    log = build_run_log()
    log.start(["rehuco-agent"])
    app = mocker.MagicMock()

    log.watch(app)
    on_activated = notifier_cls.return_value.activated.connect.call_args[0][0]

    # not-callable: the same PySide6-import/astroid false positive noted above
    on_activated()  # pylint: disable=not-callable

    app.exit.assert_not_called()


# endregion


# region shared_run_log()


def test_shared_run_log_is_a_process_wide_singleton() -> None:
    """Every caller reaches the same instance -- the same shape as
    :func:`~rehuco_agent.app_logging.shared_log_bridge`.

    **Test steps:**

    * call the accessor twice
    * verify both calls returned the same object
    """
    assert shared_run_log() is shared_run_log()


# endregion
