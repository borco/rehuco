"""Whether deleting a screenshot goes through the Recycle Bin / Trash (#291).

A plain ``@dataclass``, like `ReferenceImagesSettings`: this is read once, at the moment a delete is
about to happen -- there is nothing already on screen for an Apply to update, so it earns no
``SimpleProperty`` reactivity.
"""

from dataclasses import dataclass
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "screenshot_deletion"
USE_RECYCLE_BIN_KEY: Final = "use_recycle_bin"

DEFAULT_USE_RECYCLE_BIN: Final = True
"""Whether a fresh install (no ``.ini`` yet) sends a deleted screenshot to the Recycle Bin / Trash. On:
the safer default -- a permanent delete is the deliberate exception (#291), not the everyday case."""


@dataclass
class ScreenshotDeletionSettings:
    """Whether deleting a file this app removes on the user's behalf moves it to the Recycle Bin /
    Trash, or unlinks it outright (#291, #298).

    Named and first written for the images dock's delete alone, but
    `~rehuco_agent.documents.recycle_bin_deleter.configured_deleter` -- the one place
    :attr:`use_recycle_bin` is actually read -- is now also what a legacy-``.tc`` conversion's discarded
    backup and both conversion-backups discard surfaces resolve into a `RecycleBinDeleter` or
    `~rehuco_core.DEFAULT_DELETER`, absent a caller's own explicit choice.
    """

    use_recycle_bin: bool = DEFAULT_USE_RECYCLE_BIN
    """Whether a deleted screenshot goes to the Recycle Bin / Trash rather than being unlinked outright."""

    def load(self, settings: QSettings) -> None:
        """Replace the current choice with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.use_recycle_bin = cast(bool, settings.value(USE_RECYCLE_BIN_KEY, DEFAULT_USE_RECYCLE_BIN, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current choice to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(USE_RECYCLE_BIN_KEY, self.use_recycle_bin)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_screenshot_deletion_settings() -> ScreenshotDeletionSettings:
    """The single, process-wide `ScreenshotDeletionSettings` instance, loaded from persistent storage
    on first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`: the settings page's Save
    must be what the next delete reads, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = ScreenshotDeletionSettings()
    settings.load(persistent_settings())
    return settings
