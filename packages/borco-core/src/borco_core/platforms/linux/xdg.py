"""Shared per-user XDG data-directory file and cache-refresh helpers.

Every desktop integration on Linux reduces to the same handful of low-level operations -- writing a
file under the user's data home, reading it back to check it is still exactly what was written,
removing it, and telling the desktop's caches to refresh. This is the Linux counterpart of
:mod:`borco_core.platforms.windows.hkcu_registry`, and per-user in the same way: everything lands
under ``$XDG_DATA_HOME`` (``~/.local/share`` by default), so nothing here ever needs root.

Content is handled as ``bytes`` rather than ``str`` throughout: the callers' "is this already
registered?" question is *byte-for-byte identical to what we would write*, and an icon is binary
while a desktop entry is text -- one primitive answers both.
"""

import logging
import os
import shutil
import subprocess  # nosec B404  # only ever runs the two XDG cache-refresh commands resolved below
from pathlib import Path
from typing import Final

LOG: Final = logging.getLogger(__name__)

DATA_HOME_VARIABLE: Final = "XDG_DATA_HOME"
"""Environment variable overriding where per-user data files live."""

DEFAULT_DATA_HOME: Final = ".local/share"
"""Path relative to the user's home directory used when :data:`DATA_HOME_VARIABLE` is unset."""


def data_home() -> Path:
    """The directory per-user data files (desktop entries, MIME packages, icons) belong under.

    A set-but-empty ``XDG_DATA_HOME`` is treated as unset, per the XDG base-directory spec. A
    *relative* value is not rejected, unlike the spec's advice: ``Path.is_absolute()`` is itself
    platform-dependent (a POSIX path like ``/home/me/.local/share`` is not "absolute" to a Windows
    ``Path``, having no drive), so enforcing it here would misfire wherever the tests run rather
    than where the code runs.

    :returns: ``$XDG_DATA_HOME`` when set, else ``~/.local/share``.
    """
    override = os.environ.get(DATA_HOME_VARIABLE)
    return Path(override) if override else Path.home() / DEFAULT_DATA_HOME


def write_file(path: Path, data: bytes) -> None:
    """Create ``path``'s parent directories and write ``data`` to it, replacing any existing file.

    :param path: the file to write.
    :param data: its full contents.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    LOG.debug("wrote %s (%d bytes)", path, len(data))


def read_file(path: Path) -> bytes | None:
    """Read ``path``, or ``None`` if it doesn't exist or can't be read.

    The read-back counterpart to :func:`write_file`, for verifying a registration is (still)
    exactly what it should be -- e.g. a "Check registration" settings-page button.

    :param path: the file to read.
    :returns: its full contents, or ``None`` if it is missing or unreadable.
    """
    try:
        return path.read_bytes()
    except OSError:
        return None


def remove_file(path: Path) -> None:
    """Delete ``path``, leaving its directory in place.

    A no-op (not an error) when ``path`` doesn't exist -- unregister callers use this to clean up
    state that may already be gone. Any other failure is logged rather than swallowed silently, so
    a partial removal leaves a trace instead of being reported as success -- but it is not
    re-raised: unregistration is best-effort cleanup and must not crash the caller. The same
    contract as :func:`~borco_core.platforms.windows.hkcu_registry.delete_key_tree`.

    :param path: the file to delete.
    """
    try:
        path.unlink()
        LOG.debug("removed %s", path)
    except FileNotFoundError:
        pass  # already gone
    except OSError:
        LOG.warning("failed to remove %s", path, exc_info=True)


def run_update_command(command: str, *arguments: str) -> None:
    """Run one of the desktop's cache-refresh commands, tolerating its absence.

    ``update-desktop-database`` and ``update-mime-database`` ship with ``desktop-file-utils`` and
    ``shared-mime-info``, neither of which is guaranteed present -- and a desktop that lacks them
    generally rescans the directories itself, so a missing command means "nothing to refresh"
    rather than "the registration failed". A command that runs and *fails* is logged and likewise
    not re-raised: the files are already written, which is the part that matters.

    :param command: the executable's name, resolved on ``PATH``.
    :param arguments: arguments to pass it, typically the directory to rescan.
    """
    executable = shutil.which(command)
    if executable is None:
        LOG.info("%s not found -- skipping its cache refresh", command)
        return
    try:
        subprocess.run([executable, *arguments], check=True, capture_output=True)  # nosec B603  # resolved by which()
        LOG.debug("ran %s %s", command, " ".join(arguments))
    except OSError, subprocess.SubprocessError:
        LOG.warning("%s failed", command, exc_info=True)
