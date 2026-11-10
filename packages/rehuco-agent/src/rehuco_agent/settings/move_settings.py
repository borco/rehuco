"""How a record moved within its root is moved (#579): the Files page's *Moving records* frame.

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

DEFAULT_REMOVE_EMPTY_FOLDERS: Final = False
"""Whether a fresh install removes the folders a move leaves empty. Off: a move touches nothing but the record unless
asked to."""


@dataclass
class MoveSettings:
    """How a record moved within its root is moved (#579)."""

    remove_empty_folders: bool = DEFAULT_REMOVE_EMPTY_FOLDERS
    """Whether the folders a move leaves behind are removed up to the root, only while each is empty."""

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.remove_empty_folders = cast(
            bool, settings.value(REMOVE_EMPTY_FOLDERS_KEY, DEFAULT_REMOVE_EMPTY_FOLDERS, type=bool)
        )
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(REMOVE_EMPTY_FOLDERS_KEY, self.remove_empty_folders)
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
