"""How a record is moved (#579, #339): the Files page's *Moving records* frame -- the folders it leaves, and which of
its moves verify its checksums.

A plain ``@dataclass``, like `DeletionSettings`: it is read when a move lands, so nothing on screen renders from it and
an Apply has nothing to update.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "moves"
REMOVE_EMPTY_FOLDERS_KEY: Final = "remove_empty_folders"
VERIFY_RENAMED_LOCAL_KEY: Final = "verify_renamed_local"
VERIFY_RENAMED_NETWORK_KEY: Final = "verify_renamed_network"
VERIFY_ORIGINAL_BEFORE_COPY_KEY: Final = "verify_original_before_copy"

DEFAULT_REMOVE_EMPTY_FOLDERS: Final = False
"""Whether a fresh install removes the folders a move leaves empty. Off: a move touches nothing but the record unless
asked to."""

DEFAULT_VERIFY_RENAMED_LOCAL: Final = False
"""Whether a record renamed in place on a local disk is verified before and after. Off: a local rename rewrites no
bytes, and is instant."""

DEFAULT_VERIFY_RENAMED_NETWORK: Final = True
"""Whether a record renamed in place on a network share is verified before and after. On: the server does the rename,
out of this machine's sight."""

DEFAULT_VERIFY_ORIGINAL_BEFORE_COPY: Final = True
"""Whether a record copied to another disk or share is verified before the copy. On: a copy checked against a record
the original no longer matches proves nothing."""


@dataclass
class MoveSettings:
    """How a record is moved (#579, #339). The copy is always checked before the original is removed: that is the hard
    rule ([[mounts-and-storage#safe-move-rename]]), never a setting."""

    remove_empty_folders: bool = DEFAULT_REMOVE_EMPTY_FOLDERS
    """Whether the folders a move leaves behind are removed up to the root, only while each is empty."""

    verify_renamed_local: bool = DEFAULT_VERIFY_RENAMED_LOCAL
    """Whether a rename on a local, removable or disc volume verifies before and after."""

    verify_renamed_network: bool = DEFAULT_VERIFY_RENAMED_NETWORK
    """Whether a rename on a network share verifies before and after."""

    verify_original_before_copy: bool = DEFAULT_VERIFY_ORIGINAL_BEFORE_COPY
    """Whether a copy to another disk or share verifies the original first."""

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.remove_empty_folders = cast(
            bool, settings.value(REMOVE_EMPTY_FOLDERS_KEY, DEFAULT_REMOVE_EMPTY_FOLDERS, type=bool)
        )
        self.verify_renamed_local = cast(
            bool, settings.value(VERIFY_RENAMED_LOCAL_KEY, DEFAULT_VERIFY_RENAMED_LOCAL, type=bool)
        )
        self.verify_renamed_network = cast(
            bool, settings.value(VERIFY_RENAMED_NETWORK_KEY, DEFAULT_VERIFY_RENAMED_NETWORK, type=bool)
        )
        self.verify_original_before_copy = cast(
            bool, settings.value(VERIFY_ORIGINAL_BEFORE_COPY_KEY, DEFAULT_VERIFY_ORIGINAL_BEFORE_COPY, type=bool)
        )
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(REMOVE_EMPTY_FOLDERS_KEY, self.remove_empty_folders)
        settings.setValue(VERIFY_RENAMED_LOCAL_KEY, self.verify_renamed_local)
        settings.setValue(VERIFY_RENAMED_NETWORK_KEY, self.verify_renamed_network)
        settings.setValue(VERIFY_ORIGINAL_BEFORE_COPY_KEY, self.verify_original_before_copy)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_move_settings() -> MoveSettings:
    """The single, process-wide `MoveSettings` instance, loaded from persistent storage on first call, so the Files
    page's Save is what the next move reads.

    :returns: the shared instance.
    """
    settings = MoveSettings()
    settings.load(persistent_settings())
    return settings
