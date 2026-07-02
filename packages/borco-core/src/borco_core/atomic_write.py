"""Crash-safe file writes: write a temp sibling, flush + fsync, then atomically replace.

A reader never sees a half-written file, and a crash mid-write leaves either the
complete old file or the complete new file -- never a torn one. ``os.replace`` is the
cross-platform atomic rename (POSIX ``rename``; Windows ``MoveFileEx``/``ReplaceFile``
semantics), so the same discipline holds on every target platform.
"""

import os
import tempfile
from pathlib import Path
from typing import Final

DEFAULT_ENCODING: Final = "utf-8"
"""Text encoding used by :func:`atomic_write_text` unless overridden."""


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically via a temp sibling and ``os.replace``.

    The temp file is created in the destination's own directory so the final rename
    stays on one filesystem (a cross-device rename is not atomic). On any failure the
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
        os.replace(tmp_path, path)
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
