"""Persistent rotating run log: every run appends to ``rehuco-agent.log``, and how it ended is always
recorded -- an exit code, a logged exception, or, when nothing got the chance to write either, an
unclean-exit sentinel the next start finds (#362, [[appendices.logging#run-log-file]]).
"""

import faulthandler
import logging
import os
import platform
import signal
import socket
import sys
import threading
import time
import traceback
from functools import lru_cache
from pathlib import Path
from types import TracebackType
from typing import Final, TextIO
from uuid import uuid4

import PySide6
from borco_core import atomic_write_text
from borco_core.logging import SharedRotatingFileHandler
from PySide6.QtCore import (
    QMessageLogContext,
    QSocketNotifier,
    QtMsgType,
    qInstallMessageHandler,
    qVersion,
)
from PySide6.QtGui import QGuiApplication

from . import __version__
from .settings.logs_settings import BYTES_PER_MB, LogsSettings, shared_logs_settings
from .settings.persistent_settings import config_folder

LOG: Final = logging.getLogger(__name__)
QT_LOG: Final = logging.getLogger("qt")

LOG_FILE_NAME: Final = "rehuco-agent.log"
SENTINEL_FILE_NAME: Final = "primary.run"

ROLE_UNKNOWN: Final = "?"
ROLE_PRIMARY: Final = "primary"
ROLE_FORWARD: Final = "forward"
"""What a record's ``role`` field says about the process that wrote it: not yet resolved, the one
process that holds the file open and rotates it, or a short-lived launch that forwarded its argv and
is about to exit ([[appendices.logging#run-log-file]])."""

FORMAT: Final = "{asctime} {process} {role} {threadName} {levelname} {name}: {message}"

QUIET_LOGGERS: Final = {
    "selenium.webdriver.remote.remote_connection": logging.INFO,
    "urllib3.connectionpool": logging.INFO,
    "MARKDOWN": logging.INFO,
}
"""Loggers whose DEBUG output is noise rather than a trail worth keeping: every WebDriver command and
response -- including a whole page source -- the local HTTP calls behind them, and a "successfully
loaded extension" line on every markdown render. Raised to INFO here rather than only filtered out of
the file, so the same page source is never cached by the bridge for replay, printed to the console, or
padding an in-app log dock either (#362)."""

REPEAT_REPORT_INTERVAL_S: Final = 60.0
"""How often, at most, a repeating identical exception is mentioned again -- as a count, never the
traceback twice (#362)."""

QT_LOG_LEVELS: Final = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}
"""What each `~PySide6.QtCore.QtMsgType` a Qt message handler receives is logged as."""


class _RoleFilter(logging.Filter):  # pylint: disable=too-few-public-methods
    """Stamps every record with the run log's current role, read live rather than baked into a
    formatter string built once -- :meth:`RunLog.become_primary` changes it mid-run."""

    def __init__(self) -> None:
        super().__init__()
        self.role = ROLE_UNKNOWN

    def filter(self, record: logging.LogRecord) -> bool:
        record.role = self.role  # type: ignore[attr-defined]  # read by FORMAT above
        return True


class RunLog:  # pylint: disable=too-many-instance-attributes
    """This process's run, from the first record worth keeping to how it ends.

    Built once per process ( :func:`shared_run_log` ) and started as early as possible -- before the
    settings read, the singleton check, or anything else that could go wrong during startup, all of
    which are then in the file even if nothing after them ever runs. Not installed anywhere at
    construction, so building one is harmless in tests and in the settings page, which only reads
    :attr:`handler`.

    :param path: where the run log file lives.
    :param settings: the shared `LogsSettings`, followed live for the file's size and backup count.
    """

    def __init__(self, path: Path, settings: LogsSettings) -> None:
        self.__path: Final = path
        self.__settings: Final = settings
        self.__run_id: Final = uuid4().hex[:12]
        self.__role_filter: Final = _RoleFilter()
        self.handler: Final = SharedRotatingFileHandler(path)
        self.handler.setLevel(logging.DEBUG)
        self.handler.addFilter(self.__role_filter)
        self.handler.setFormatter(logging.Formatter(FORMAT, style="{"))
        self.__apply_limits()
        settings.file_size_mb_changed.connect(self.__apply_limits)  # type: ignore[attr-defined]
        settings.file_backups_changed.connect(self.__apply_limits)  # type: ignore[attr-defined]
        self.__started = False
        self.__is_primary = False
        self.__previous_excepthook: Final = sys.excepthook
        self.__previous_threading_excepthook: Final = threading.excepthook
        self.__previous_unraisablehook: Final = sys.unraisablehook
        self.__last_logged_exception: BaseException | None = None
        self.__last_traceback = ""
        self.__repeat_count = 0
        self.__last_repeat_report = 0.0
        # never read back -- both exist purely to keep the notifier and the socket pair alive for the
        # rest of the process, once __watch_posix_signals sets them
        self.__signal_notifier: QSocketNotifier | None = None  # pylint: disable=unused-private-member
        self.__signal_sockets: tuple[socket.socket, socket.socket] | None = None  # pylint: disable=unused-private-member
        self.__fault_file: TextIO | None = None

    def __apply_limits(self) -> None:
        """Read the live size/backup-count settings onto the handler."""
        self.handler.maxBytes = self.__settings.file_size_mb * BYTES_PER_MB
        self.handler.backupCount = self.__settings.file_backups

    def start(self, argv: list[str]) -> None:
        """Start writing this run's records: the folder, the handler, the banner, and every hook.

        Safe to call at most once; a second call would double-install every hook. Staying console-only
        (a warning, not a raise) when the folder cannot be created is deliberate -- a run whose log
        cannot be written is still a run worth starting (#361 already treats a failed
        :func:`~rehuco_agent.settings.persistent_settings.config_folder` write the same way).

        :param argv: this process's argv, recorded in the banner.
        """
        for name, level in QUIET_LOGGERS.items():
            logging.getLogger(name).setLevel(level)
        try:
            self.__path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            LOG.warning("Could not create %s; the run log will not be written", self.__path.parent, exc_info=True)
            return
        logging.getLogger().addHandler(self.handler)
        self.__started = True
        LOG.info(
            "Run %s starting: pid=%s argv=%s rehuco-agent=%s %s python=%s qt=%s pyside=%s",
            self.__run_id,
            os.getpid(),
            argv,
            __version__,
            platform.platform(),
            sys.version.split()[0],
            qVersion(),
            PySide6.__version__,
        )
        self.__install_hooks()

    def __install_hooks(self) -> None:
        """Route every uncaught Python exception and every Qt message into this log."""
        sys.excepthook = self.__excepthook
        threading.excepthook = self.__threading_excepthook
        sys.unraisablehook = self.__unraisablehook
        qInstallMessageHandler(self.__qt_message_handler)

    def __excepthook(self, exc_type: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
        """Log an uncaught exception CRITICAL, including one PySide re-raises from inside a Qt slot,
        then chain to whatever hook was installed before this one."""
        self.log_exception(value, "sys.excepthook")
        self.__previous_excepthook(exc_type, value, tb)

    def __threading_excepthook(self, args: threading.ExceptHookArgs) -> None:
        """Log an exception uncaught on a non-main thread, then chain to the previous hook."""
        if args.exc_value is not None:
            self.log_exception(args.exc_value, f"thread {args.thread.name if args.thread else '?'!r}")
        self.__previous_threading_excepthook(args)

    def __unraisablehook(self, args: sys.UnraisableHookArgs) -> None:
        """Log an exception that could not be raised anywhere (e.g. from ``__del__``), then chain."""
        if args.exc_value is not None:
            self.log_exception(args.exc_value, "sys.unraisablehook")
        self.__previous_unraisablehook(args)

    def __qt_message_handler(self, msg_type: QtMsgType, context: QMessageLogContext, message: str) -> None:
        """Route a Qt log message to the ``qt`` logger, and flush every handler before a fatal abort.

        :param msg_type: the message's severity.
        :param context: where in Qt the message came from; only its ``category`` is used.
        :param message: the message text.
        """
        category = context.category
        text = message if not category or category == "default" else f"[{category}] {message}"
        QT_LOG.log(QT_LOG_LEVELS.get(msg_type, logging.INFO), text)
        if msg_type == QtMsgType.QtFatalMsg:
            for handler in logging.getLogger().handlers:
                handler.flush()

    def become_forwarder(self) -> None:
        """Mark this run as a forwarder: it never rotates the file and never touches the sentinel --
        both are the primary's alone (#362)."""
        self.__role_filter.role = ROLE_FORWARD

    def become_primary(self) -> None:
        """Mark this run as the primary: it starts rotating the file, and takes over the sentinel.

        A sentinel found here names a run that ended without ever reaching :meth:`finish` -- a native
        crash, End Task, or power loss, none of which leave anything else behind.
        """
        self.__role_filter.role = ROLE_PRIMARY
        self.__is_primary = True
        self.handler.rotates = True
        self.__warn_about_a_leftover_sentinel()
        if self.__write_sentinel():
            self.__enable_faulthandler()

    def __sentinel_path(self) -> Path:
        return self.__path.parent / SENTINEL_FILE_NAME

    def __warn_about_a_leftover_sentinel(self) -> None:
        sentinel = self.__sentinel_path()
        try:
            content = sentinel.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError:
            LOG.warning("A previous run's sentinel could not be read; it likely ended without exiting cleanly")
            return
        LOG.warning("A previous run (%s) ended without exiting cleanly -- no exit line follows it above", content)

    def __write_sentinel(self) -> bool:
        """Write the sentinel naming this run, so a still-open handle can be kept on it for
        :meth:`__enable_faulthandler`.

        :returns: whether the write succeeded.
        """
        try:
            atomic_write_text(self.__sentinel_path(), f"run={self.__run_id} pid={os.getpid()}\n")
        except OSError:
            LOG.warning("Could not write the unclean-exit sentinel", exc_info=True)
            return False
        return True

    def __enable_faulthandler(self) -> None:
        """Dump every thread's Python stack into the sentinel file the instant a fatal signal reaches
        this process -- a native crash, or ``abort()`` -- so the one detail a native crash otherwise
        leaves nothing about (which slot, which line) survives into the next start's warning.

        Appended after the sentinel's own ``run=`` line: on an unclean exit, :meth:`__warn_about_a_leftover_sentinel`
        reads the whole file back, so the dump rides along with the warning it produces rather than
        needing a file of its own. Skipped -- quietly, there being nothing more useful to say -- if the
        sentinel itself could not be opened for append right after being written.
        """
        try:
            self.__fault_file = self.__sentinel_path().open("a", encoding="utf-8")
        except OSError:
            return
        faulthandler.enable(file=self.__fault_file, all_threads=True)

    def __disable_faulthandler(self) -> None:
        """Undo :meth:`__enable_faulthandler`, closing its handle before the sentinel is removed --
        an open handle would otherwise make that removal fail on Windows."""
        if self.__fault_file is None:
            return
        faulthandler.disable()
        try:
            self.__fault_file.close()
        except OSError:
            pass
        self.__fault_file = None

    def watch(self, app: QGuiApplication) -> None:
        """Log how this run's app shuts down, and translate SIGTERM/SIGINT into an orderly
        `~PySide6.QtCore.QCoreApplication.exit`. Primary only.

        POSIX only. On Windows the packaged GUI build receives no console signals at all, and
        ``TerminateProcess`` cannot be caught from inside the process it kills -- the sentinel written
        by :meth:`become_primary` is what covers those there instead.

        :param app: the primary's `~PySide6.QtGui.QGuiApplication` (in practice the
            `~rehuco_agent.app.Application`).
        """
        app.aboutToQuit.connect(lambda: LOG.info("aboutToQuit"))
        app.commitDataRequest.connect(lambda _session_manager: LOG.info("commitDataRequest"))
        if sys.platform == "win32":
            return
        self.__watch_posix_signals(app)

    def __watch_posix_signals(self, app: QGuiApplication) -> None:
        """Wire SIGTERM/SIGINT to `~PySide6.QtCore.QCoreApplication.exit` through a self-pipe -- the
        one way a Unix signal (delivered on an arbitrary OS thread) can safely reach Qt's event loop."""
        reader, writer = socket.socketpair()
        reader.setblocking(False)
        writer.setblocking(False)
        signal.set_wakeup_fd(writer.fileno())

        def handle_signal(_signum: int, _frame: object) -> None:
            pass  # the wakeup fd write (below) already carries which signal fired

        signal.signal(signal.SIGTERM, handle_signal)
        signal.signal(signal.SIGINT, handle_signal)

        notifier = QSocketNotifier(reader.fileno(), QSocketNotifier.Type.Read, app)

        def on_activated() -> None:
            try:
                signum = reader.recv(1)[0]
            except BlockingIOError, IndexError:
                return
            LOG.warning("Received signal %d; exiting", signum)
            app.exit(128 + signum)

        notifier.activated.connect(on_activated)
        # kept alive on this (process-wide, process-lifetime) instance -- nothing else holds the
        # notifier or this closure's socket pair, and either being garbage-collected would silently
        # stop signals being handled
        self.__signal_notifier = notifier  # pylint: disable=unused-private-member
        self.__signal_sockets = (reader, writer)  # pylint: disable=unused-private-member

    def log_exception(self, error: BaseException, where: str) -> None:
        """Log ``error`` CRITICAL with its traceback, unless it was already logged.

        The same exception can reach here more than once -- once from `sys.excepthook`, again from
        whatever wrapped ``main()`` or ``app.exec()`` and re-raised it on its way out -- and a reader
        should see it once, not once per layer that saw it go by. A no-op before :meth:`start` (or if
        the folder could not be created): nothing installed anywhere is listening yet.

        :param error: the exception to log.
        :param where: what was running when it happened, for the message.
        """
        if not self.__started or error is self.__last_logged_exception:
            return
        self.__last_logged_exception = error
        text = "".join(traceback.format_exception(type(error), error, error.__traceback__)).rstrip()
        if text == self.__last_traceback:
            self.__report_repeat(where)
            return
        self.__flush_repeats()
        self.__last_traceback = text
        self.__last_repeat_report = time.monotonic()  # the full record starts the interval
        LOG.critical("Unhandled exception in %s: %s", where, text)

    def __report_repeat(self, where: str) -> None:
        """Count one more occurrence of the exception logged last, and say so at most once per
        :data:`REPEAT_REPORT_INTERVAL_S` -- an exception raised by a slot on every repaint recurs
        several times a second, and written in full each time it would rotate the whole file away
        within the hour while saying nothing new.

        :param where: what was running this time, for the summary.
        """
        self.__repeat_count += 1
        now = time.monotonic()
        if now - self.__last_repeat_report < REPEAT_REPORT_INTERVAL_S:
            return
        LOG.critical("The previous exception repeated %d more times (last in %s)", self.__repeat_count, where)
        self.__repeat_count = 0
        self.__last_repeat_report = now

    def __flush_repeats(self) -> None:
        """Write out any repeats not yet reported, before a different exception takes their place."""
        if self.__repeat_count:
            LOG.critical("The previous exception repeated %d more times", self.__repeat_count)
        self.__repeat_count = 0
        self.__last_repeat_report = 0.0

    def finish(self, exit_code: int | None) -> None:
        """Record how this run ended, and clean up after :meth:`become_primary`.

        :param exit_code: the process's exit code, or ``None`` when the run ended by an exception that
            never produced one (already logged separately by :meth:`log_exception`).
        """
        if not self.__started:
            return
        if exit_code is None:
            LOG.info("Run %s ended by an exception", self.__run_id)
        else:
            LOG.info("Run %s exited with code %d", self.__run_id, exit_code)
        if self.__is_primary:
            # closes the faulthandler file handle first -- an open handle on Windows would otherwise
            # make the unlink below fail
            self.__disable_faulthandler()
            try:
                self.__sentinel_path().unlink()
            except FileNotFoundError:
                pass
            except OSError:
                LOG.warning("Could not remove the unclean-exit sentinel", exc_info=True)
        self.handler.flush()


@lru_cache(maxsize=1)
def shared_run_log() -> RunLog:
    """The single, process-wide `RunLog`.

    An ``lru_cache`` accessor for the same reason :func:`~rehuco_agent.app_logging.shared_log_bridge`
    and :func:`~rehuco_agent.settings.persistent_settings.persistent_settings` are: no layer between
    ``run()`` and here has any other reason to know about logging.

    :returns: the shared instance, not yet started.
    """
    return RunLog(config_folder() / LOG_FILE_NAME, shared_logs_settings())
