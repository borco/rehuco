"""Moving a file to the Recycle Bin / Trash, wrapped behind one call (#300).

The one place ``send2trash`` is imported anywhere in this workspace: everything that needs to move a
file to the Recycle Bin rather than unlink it outright goes through :func:`recycle_bin`, so a future
replacement library, or Windows-specific tuning, changes here and nowhere else.

**Why this narrows, rather than repeats, the bug it replaces.** The deleter this superseded caught every
``OSError`` ``send2trash`` raised and reported it as "no Recycle Bin available" -- so a locked file or an
access-denied one was mislabeled the same way a genuinely bin-less drive was, and offered a
permanent-delete fallback that could not fix the real problem. No Windows error code reliably
distinguishes those cases after the fact (see
:mod:`borco_pyside.platforms.windows.recycle_bin_capability`'s docstring for what was actually tried), so
this checks the drive's capability *before* attempting the move instead: once a drive is known to have a
bin, any ``OSError`` ``send2trash`` then raises is unambiguously a real failure, not a bin problem, and is
left to propagate as itself.
"""

import sys
from functools import lru_cache
from pathlib import Path

from send2trash import send2trash
from send2trash.exceptions import TrashPermissionError


class NoRecycleBinError(OSError):
    """No Recycle Bin / Trash is reachable for a path (#300).

    Raised instead of falling back to a silent permanent delete, so the caller is the one who gets to
    offer that -- for the one action it was asked for.
    """


class RecycleBin:  # pylint: disable=too-few-public-methods
    """Moves files to the Recycle Bin / Trash, or refuses by name when none is reachable."""

    def add(self, path: Path) -> None:
        """Move ``path`` to the Recycle Bin / Trash.

        :param path: the file to move.
        :raises FileNotFoundError: ``path`` is already gone -- passed through unwrapped.
        :raises NoRecycleBinError: no bin is reachable for ``path`` -- ``path`` is left untouched.
        :raises OSError: any other real failure (locked, permission denied, ...), passed through
            unwrapped so the caller reports the actual cause.
        """
        if sys.platform == "win32":
            # pylint: disable-next=import-outside-toplevel
            from .platforms.windows.recycle_bin_capability import has_recycle_bin

            if not has_recycle_bin(path):
                # a file already gone is not a bin problem, whatever its drive -- the same distinction
                # send2trash draws, which never gets to draw it here because it is never called
                if not path.exists():
                    raise FileNotFoundError(path)
                raise NoRecycleBinError(f"No Recycle Bin is available for {path.parent}")
        try:
            send2trash(str(path))
        except TrashPermissionError as error:
            # the one no-bin case send2trash documents on its own (mac/gio/other backends) --
            # never used when permissions prevent removing the file itself, only the trash step
            raise NoRecycleBinError(f"No Recycle Bin is available for {path.parent}") from error


@lru_cache(maxsize=1)
def recycle_bin() -> RecycleBin:
    """The single, process-wide `RecycleBin`.

    :returns: the shared instance.
    """
    return RecycleBin()
