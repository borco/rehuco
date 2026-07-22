"""Crash-safe file writes: write a temp sibling, flush + fsync, then atomically replace.

A reader never sees a half-written file, and a crash mid-write leaves either the
complete old file or the complete new file -- never a torn one. ``os.replace`` is the
cross-platform atomic rename (POSIX ``rename``; Windows ``MoveFileEx``/``ReplaceFile``
semantics), so the same discipline holds on every target platform.
"""

import logging
import os
import stat
import sys
import tempfile
from pathlib import Path
from typing import Final

DEFAULT_ENCODING: Final = "utf-8"
"""Text encoding used by :func:`atomic_write_text` unless overridden."""

LOG: Final = logging.getLogger(__name__)


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via a temp sibling and ``os.replace``.

    The temp file is created in the destination's own directory so the final rename
    stays on one filesystem (a cross-device rename is not atomic). Before the replace,
    the temp file's mode is set to match the existing destination (or umask-respecting
    defaults for a new file) so ``os.replace`` never narrows an existing file's
    permissions down to the temp file's owner-only mode; on POSIX its owner/group are
    restored the same way, best-effort (a failure there -- e.g. lacking the privilege
    to ``chown`` to another user, or the destination directory not being fsync-able
    at all on Windows -- is logged and does not abort the write). On any failure the
    temp file is removed and the original ``path`` is left untouched.

    :param path: destination file path; overwritten atomically if it already exists.
    :param data: bytes to write.
    :raises OSError: if the temp file cannot be written or the replace fails.
    """
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            dest_stat = path.stat()
        except FileNotFoundError:
            dest_stat = None
        if dest_stat is None:
            # os.umask has no "peek" mode -- setting it is the only way to read it, so
            # restore the previous value immediately.
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        else:
            mode = stat.S_IMODE(dest_stat.st_mode)
        os.chmod(tmp_path, mode)
        if dest_stat is not None and hasattr(os, "chown"):
            # os.chown is POSIX-only (absent from the os module on Windows) and even
            # there requires a privilege an unprivileged process may lack.
            try:
                os.chown(tmp_path, dest_stat.st_uid, dest_stat.st_gid)  # pylint: disable=no-member
            except OSError:
                LOG.warning("Could not restore owner/group on %s", path, exc_info=True)
        os.replace(tmp_path, path)
        # The rename itself is atomic, but the directory entry recording it still needs
        # its own fsync to survive a crash right after the replace. Opening a directory
        # this way isn't supported on Windows, so it's skipped there entirely rather
        # than attempted and warned about on every single save.
        #
        # Deliberately sys.platform, not os.name: pathlib checks os.name on every
        # Path(...) call to pick WindowsPath/PosixPath, and PosixPath's __new__ has a
        # hard "cannot instantiate on your system" guard baked in from os.name at
        # interpreter start. Mocking os.name in a test makes pathlib crash on the very
        # next path.parent access; sys.platform isn't consulted by pathlib at all, so
        # it's the only one of the two that can be mocked here safely.
        if sys.platform != "win32":
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY)
            except OSError:
                LOG.warning("Could not open directory %s to fsync it", path.parent, exc_info=True)
            else:
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def atomic_write_text(path: Path | str, text: str, *, encoding: str = DEFAULT_ENCODING) -> None:
    """Encode ``text`` and write it to ``path`` atomically.

    :param path: destination file path; overwritten atomically if it already exists.
    :param text: text to write.
    :param encoding: text encoding; defaults to :data:`DEFAULT_ENCODING`.
    :raises OSError: if the temp file cannot be written or the replace fails.
    """
    atomic_write_bytes(path, text.encode(encoding))
