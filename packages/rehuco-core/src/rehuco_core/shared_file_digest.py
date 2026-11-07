"""What a save of a shared file compares the file on disk with: the SHA-256 of its text
([[mounts-and-storage#rehuco-scope]], #514, #577).

A ``.rehuco`` and a ``.rehuroot`` are saved the same way: under the file's lock, and only if the file is still what
this machine last read or wrote. The two share these steps; each raises its own error when they differ.
"""

import hashlib
from pathlib import Path


def text_digest(text: str) -> str:
    """What a save compares a file by.

    :param text: the file's text.
    :returns: its SHA-256, in hex.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def disk_digest(path: Path) -> str | None:
    """The digest of a file as it is on disk now.

    :param path: the file.
    :returns: its :func:`text_digest`, or ``None`` when it is gone or not text -- either way not what was last read.
    :raises OSError: the file exists and could not be read.
    """
    try:
        return text_digest(path.read_text(encoding="utf-8"))
    except FileNotFoundError, UnicodeDecodeError:
        return None
