"""Moves a deleted screenshot to the Recycle Bin / Trash instead of unlinking it outright (#291).

The agent's own `rehuco_core.Deleter`: ``send2trash`` is a GUI-facing dependency `rehuco_core` stays
free of, so this is the concrete side of the seam #265 left for it (`RehuDocumentImageOrganizer`).
Where no bin is reachable for a path -- a Windows SMB share, the mounted NAS
([[mounts-and-storage#offline-mounts]]) -- ``send2trash`` raises, and this refuses by raising
`~rehuco_core.NoTrashBinError` rather than falling back to a silent permanent delete: the caller is
the one who gets to offer that, for the one action it was asked for.
"""

from pathlib import Path

from rehuco_core import NoTrashBinError
from send2trash import send2trash


class RecycleBinDeleter:  # pylint: disable=too-few-public-methods
    """A `~rehuco_core.Deleter` that moves a file to the Recycle Bin / Trash rather than unlinking it."""

    def delete(self, path: Path) -> None:
        """Move ``path`` to the Recycle Bin / Trash.

        :param path: the file to move.
        :raises NoTrashBinError: no bin is reachable for ``path`` -- ``path`` is left untouched.
        """
        try:
            send2trash(str(path))
        except OSError as error:
            raise NoTrashBinError(f"No Recycle Bin is available for {path.parent}") from error
