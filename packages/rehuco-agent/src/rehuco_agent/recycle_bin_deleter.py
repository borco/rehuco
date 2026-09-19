"""Moves a deleted screenshot to the Recycle Bin / Trash instead of unlinking it outright (#291).

The agent's own `rehuco_core.Deleter`: `~borco_pyside.recycle_bin.RecycleBin` -- a GUI-facing dependency
`rehuco_core` stays free of -- carries the actual `send2trash` mechanics; this is the concrete side of the
seam #265 left for it (`RehuDocumentImageOrganizer`), translating
`~borco_pyside.recycle_bin.NoRecycleBinError` into the vocabulary `rehuco_core` shares with every other
`Deleter` consumer (#300).

Top-level rather than under ``documents``: the images dock (``fields/widgets``) needs it too (#301), and
the field toolkit may not import ``documents`` ([[plugins#field-toolkit]]).
"""

from pathlib import Path

from borco_pyside.recycle_bin import NoRecycleBinError, recycle_bin
from rehuco_core import DEFAULT_DELETER, Deleter, NoTrashBinError

from .settings.deletion_settings import shared_deletion_settings


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
            recycle_bin().add(path)
        except NoRecycleBinError as error:
            raise NoTrashBinError(str(error)) from error


def configured_deleter() -> Deleter:
    """The `~rehuco_core.Deleter` any in-window delete or discard resolves to absent an explicit
    override, per the **Move deleted files to the Recycle Bin, if possible** setting (#291, #298, #312).

    Read live rather than cached, so a page Saved after a caller last asked is still honoured; this is
    the shared accessor every caller (the images dock, convert, both discard surfaces) was lifted onto
    instead of each re-reading the setting its own way.

    :returns: a `RecycleBinDeleter` when the setting is on, otherwise `~rehuco_core.DEFAULT_DELETER`.
    """
    return RecycleBinDeleter() if shared_deletion_settings().use_recycle_bin else DEFAULT_DELETER
