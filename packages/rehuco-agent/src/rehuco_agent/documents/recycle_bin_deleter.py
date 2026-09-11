"""Moves a deleted screenshot to the Recycle Bin / Trash instead of unlinking it outright (#291).

The agent's own `rehuco_core.Deleter`: ``send2trash`` is a GUI-facing dependency `rehuco_core` stays
free of, so this is the concrete side of the seam #265 left for it (`RehuDocumentImageOrganizer`).
Where no bin is reachable for a path -- a Windows SMB share, the mounted NAS
([[mounts-and-storage#offline-mounts]]) -- ``send2trash`` raises, and this refuses by raising
`~rehuco_core.NoTrashBinError` rather than falling back to a silent permanent delete: the caller is
the one who gets to offer that, for the one action it was asked for.
"""

from pathlib import Path

from rehuco_core import DEFAULT_DELETER, Deleter, NoTrashBinError
from send2trash import send2trash

from ..settings.screenshot_deletion_settings import shared_screenshot_deletion_settings


class RecycleBinDeleter:  # pylint: disable=too-few-public-methods
    """A `~rehuco_core.Deleter` that moves a file to the Recycle Bin / Trash rather than unlinking it."""

    def delete(self, path: Path) -> None:
        """Move ``path`` to the Recycle Bin / Trash.

        :param path: the file to move.
        :raises FileNotFoundError: ``path`` is already gone -- passed through unwrapped, so a caller
            that tolerates a vanished file for a plain unlink tolerates it here too (#298).
        :raises NoTrashBinError: no bin is reachable for ``path`` -- ``path`` is left untouched.
        """
        try:
            send2trash(str(path))
        except FileNotFoundError:
            raise
        except OSError as error:
            raise NoTrashBinError(f"No Recycle Bin is available for {path.parent}") from error


def configured_deleter() -> Deleter:
    """The `~rehuco_core.Deleter` any in-window delete or discard resolves to absent an explicit
    override, per the **Move deleted images to the Recycle Bin** setting (#291, #298).

    Read live rather than cached, so a page Saved after a caller last asked is still honoured -- the
    same discipline `RehuDocumentImageOrganizer.deletes_to_trash` already followed for the one consumer
    this setting used to have; this is the shared accessor every other caller (convert, both discard
    surfaces) was lifted onto instead of each re-reading the setting its own way.

    :returns: a `RecycleBinDeleter` when the setting is on, otherwise `~rehuco_core.DEFAULT_DELETER`.
    """
    return RecycleBinDeleter() if shared_screenshot_deletion_settings().use_recycle_bin else DEFAULT_DELETER
