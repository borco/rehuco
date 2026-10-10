"""Versioned JSON files for the agent's bulky state, beside the ``.ini`` (#404).

The ``.ini`` keeps preferences. What is large or grows with use -- the document session, the window and dock layout
blobs -- lives in a file of its own under :func:`~.persistent_settings.config_folder`, written atomically, the way
``task-queue.json`` and ``catalogs/<id>.json`` are. Each file is read once at startup and rewritten whole, so a plain
file is enough; nothing here needs queries or a second writer.

**Lenient on read, silent on write**: this is view state, so a file that is missing, unreadable, of another version or
hand-damaged reads as absent and is logged, and a write that fails is logged, never raised, because losing a layout
must not block closing. A file that existed but read as absent is moved aside as ``<name>.bak`` by the next write to
it, so a transient read error never costs the good file (#478).
"""

import base64
import binascii
import json
import logging
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

LOG: Final = logging.getLogger(__name__)


#: Files that exist but read as absent. The next write to one moves it aside first (see :func:`set_aside_unread`).
UNREAD: Final[set[Path]] = set()


def read_json_file(path: Path, what: str = "saved state") -> Any | None:
    """Read one JSON file, leniently.

    A file that is missing, cannot be opened, is not UTF-8 or is not JSON reads as ``None`` and is logged (a missing
    one is not). One that exists is remembered, so that :func:`set_aside_unread` can keep it when it is next written.

    :param path: the file.
    :param what: what the file is, for the log.
    :returns: what it holds, or ``None`` when there is nothing that can be read.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError, UnicodeDecodeError:
        LOG.exception("The %s %s could not be read.", what, path)
        UNREAD.add(path)
        return None
    try:
        return json.loads(text)
    except ValueError:
        LOG.error("The %s %s is not readable JSON; it is ignored.", what, path)
        UNREAD.add(path)
        return None


def set_aside_unread(path: Path) -> None:
    """Keep a file that read as absent, before it is overwritten.

    A read that fails is not always the file's fault (a virus scanner's lock, a newer build's version), and the load
    that followed it started from empty state, whose save would otherwise replace the good file. The file is renamed
    to ``<name>.bak`` -- replacing an older one -- so the user can recover it by hand. A no-op for a file that read
    fine or was never read.

    :param path: the file about to be written.
    """
    if path not in UNREAD:
        return
    backup = path.with_name(path.name + ".bak")
    try:
        path.replace(backup)
    except OSError:
        # still remembered: the lock that failed the read may be the one failing this, and the write that follows
        # fails on it too, so the next save gets another go at keeping the file
        LOG.exception("The unreadable state %s could not be set aside as %s.", path, backup)
    else:
        UNREAD.discard(path)
        LOG.warning("The unreadable state %s was kept as %s before being replaced.", path, backup)


def read_state_file(path: Path, version: int) -> dict[str, Any] | None:
    """Read one state file.

    :param path: the file.
    :param version: the schema version this build reads; a file of another one reads as absent.
    :returns: the file's values (``version`` included), or ``None`` when there is none that can be read.
    """
    values = read_json_file(path)
    if values is None:
        return None
    if not isinstance(values, dict) or values.get("version") != version:
        LOG.warning("The saved state %s is not in a shape this build reads; it is ignored.", path)
        UNREAD.add(path)
        return None
    return values


def write_state_file(path: Path, version: int, values: dict[str, Any]) -> None:
    """Write one state file atomically.

    :param path: the file; its folder is made if it is missing.
    :param version: the schema version to stamp it with.
    :param values: what to keep, JSON-ready (see :func:`encode_bytes`).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        set_aside_unread(path)
        atomic_write_text(path, json.dumps({"version": version, **values}, indent=2) + "\n")
    except OSError:
        LOG.exception("The state could not be saved to %s.", path)


def encode_bytes(value: bytes) -> str:
    """Spell a binary blob so JSON can hold it.

    :param value: the blob.
    :returns: its base64 text.
    """
    return base64.b64encode(value).decode("ascii")


def decode_bytes(value: object) -> bytes:
    """Read a blob back, or nothing for a missing or damaged one.

    :param value: what the file holds.
    :returns: the bytes.
    """
    if not isinstance(value, str):
        return b""
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except binascii.Error, ValueError:
        return b""
