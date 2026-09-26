"""A rotating file handler several processes can share, only one of which rotates (#362).

The intended shape: one long-lived *primary* process holds the file open and rotates it, while any
number of short-lived *forwarder* processes open, append one record and close -- never rotating, since a
rename fails on Windows while another process holds the file open. See
[[appendices.logging#run-log-file]].
"""

import logging.handlers
from pathlib import Path
from typing import Final

MAX_LINE_LENGTH: Final = 2000
"""A record's formatted line is cut to this many characters before it is written, **below
:data:`UNCUT_LEVEL` only**. One library logging an entire payload at DEBUG -- a page source, a large
response body -- would otherwise crowd a run's whole earlier history out of a size-bounded file on its
own (#362)."""

UNCUT_LEVEL: Final = logging.WARNING
"""From this level up a record is written whole, however long: a CRITICAL traceback, or the warning
carrying a crashed run's every-thread stack dump, is the record the file exists for, and the noise the
cut guards against is DEBUG."""


class SharedRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A `~logging.handlers.RotatingFileHandler` that only rotates once told to.

    Built with ``delay=True``, so construction touches no file at all -- a process that never emits a
    record never creates one. While :attr:`rotates` is left `False` (the default, for a forwarder), every
    :meth:`emit` opens the file, appends, and closes it again -- the same cycle a plain, non-rotating
    `~logging.FileHandler` would run, and never a rename. Setting :attr:`rotates` to `True` (the primary,
    once confirmed) is the whole of "swapping to the rotating handler": the same instance starts holding
    its stream open between records and rolling over at :attr:`maxBytes`, rather than a second handler
    being added and this one removed -- which would leave a gap, and a handler to tear down.

    :attr:`maxBytes` and :attr:`backupCount` are read fresh by :meth:`shouldRollover`/:meth:`doRollover`
    on every call, so a caller may change either while the handler is running and have it apply to the
    very next record -- there is nothing cached to invalidate.

    :param filename: the log file's path.
    """

    def __init__(self, filename: Path | str) -> None:
        super().__init__(filename, mode="a", maxBytes=0, backupCount=0, encoding="utf-8", delay=True)
        self.rotates: bool = False
        """Whether this process is the primary and so rotates the file; `False` (never rotate, open
        and close per record) until :meth:`~logging.Handler.acquire`'d code sets it, typically once
        the single-instance check confirms this process is primary."""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        if record.levelno >= UNCUT_LEVEL or len(formatted) <= MAX_LINE_LENGTH:
            return formatted
        cut = len(formatted) - MAX_LINE_LENGTH
        return f"{formatted[:MAX_LINE_LENGTH]}… [{cut} chars cut]"

    def emit(self, record: logging.LogRecord) -> None:
        if self.rotates:
            super().emit(record)
            return
        # a forwarder: append this one record and leave nothing open behind it, so a primary can
        # always rename the file out from under it
        logging.FileHandler.emit(self, record)
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def doRollover(self) -> None:  # noqa: N802  (overriding stdlib's camelCase API)
        """Roll the file over, retrying later if another process is holding it.

        A rename can fail with `PermissionError` on Windows while a forwarder has the file open for
        its one record (there being no lock file to wait on, by design -- a crash would leave nothing
        to clean up). Caught here rather than left to propagate: the handler keeps appending to the
        file it already has (``delay=True`` leaves :attr:`stream` unset, so the next :meth:`emit`
        reopens it), and :meth:`shouldRollover` is still `True` on the next record, so the rename is
        retried there. Nothing is logged about the failure from inside a log handler, to avoid
        re-entering ``logging`` from within its own emit path.
        """
        try:
            super().doRollover()
        except PermissionError:
            return
        self.__prune_excess_backups()

    def __prune_excess_backups(self) -> None:
        """Remove any backup numbered above the *current* :attr:`backupCount`.

        Lowering :attr:`backupCount` while running only stops stdlib's own rollover from *creating*
        further backups past the new count -- the ones it already wrote past it are left on disk
        until this runs them off after the next rotation. Missing files are not an error.
        """
        base = Path(self.baseFilename)
        index = self.backupCount + 1
        # stops at the first gap, as log_files() does -- stdlib's own numbering never leaves one
        while (candidate := base.with_name(f"{base.name}.{index}")).exists():
            candidate.unlink(missing_ok=True)
            index += 1

    def log_files(self) -> list[Path]:
        """The base file plus every backup this handler has written, however many currently exist.

        :returns: the base file first, then ``<name>.1``, ``<name>.2``, ... for as long as each one is
            found -- stopping at the first gap, since stdlib's own numbering never leaves one.
        """
        base = Path(self.baseFilename)
        files = [base]
        index = 1
        while (candidate := base.with_name(f"{base.name}.{index}")).exists():
            files.append(candidate)
            index += 1
        return files

    def used_bytes(self) -> int:
        """How many bytes the base file and its backups occupy together right now.

        A file that no longer exists by the time it's `stat`'d (removed concurrently) counts as 0
        rather than failing the whole sum.

        :returns: the total size, in bytes.
        """
        total = 0
        for candidate in self.log_files():
            try:
                total += candidate.stat().st_size
            except OSError:
                continue
        return total

    def clear(self) -> None:
        """Discard everything this handler has written: every backup, and the base file's contents.

        The base file is **truncated in place**, not unlinked -- an unlink can fail on Windows while a
        forwarder holds it open for its one record, the same reason :meth:`doRollover` retries rather
        than raising, while truncating an already-open file is always possible. Held under the
        handler's own lock, so no record from this process is lost mid-clear.

        :raises OSError: if the base file cannot be truncated (a backup that cannot be removed is not
            fatal on its own and is skipped).
        """
        self.acquire()
        try:
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            for backup in self.log_files()[1:]:
                backup.unlink(missing_ok=True)
            with open(self.baseFilename, "w", encoding="utf-8"):
                pass
        finally:
            self.release()
