"""Versioned JSON files for the agent's bulky state, beside the ``.ini`` (#404).

The ``.ini`` keeps preferences. What is large or grows with use -- the document session, the window and dock layout
blobs -- lives in a file of its own under :func:`~.persistent_settings.config_folder`, written atomically, the way
``task-queue.json`` and ``catalogs/<id>.json`` are. Each file is read once at startup and rewritten whole, so a plain
file is enough; nothing here needs queries or a second writer.

**Lenient on read, silent on write**: this is view state, so a file that is missing, unreadable, of another version or
hand-damaged reads as absent and is logged, and a write that fails is logged, never raised, because losing a layout
must not block closing.
"""

import base64
import binascii
import json
import logging
from pathlib import Path
from typing import Any, Final

from borco_core import atomic_write_text

LOG: Final = logging.getLogger(__name__)


def read_state_file(path: Path, version: int) -> dict[str, Any] | None:
    """Read one state file.

    :param path: the file.
    :param version: the schema version this build reads; a file of another one reads as absent.
    :returns: the file's values (``version`` included), or ``None`` when there is none that can be read.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        LOG.exception("The saved state %s could not be read.", path)
        return None
    try:
        values: Any = json.loads(text)
    except ValueError:
        LOG.error("The saved state %s is not readable JSON; it is ignored.", path)
        return None
    if not isinstance(values, dict) or values.get("version") != version:
        LOG.warning("The saved state %s is not in a shape this build reads; it is ignored.", path)
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
