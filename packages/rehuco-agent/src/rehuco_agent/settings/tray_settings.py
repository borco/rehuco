"""Whether the tray icon is on -- close-to-tray with an explicit Quit (#205, [[nodes#single-instance]])."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "tray"
ENABLED_KEY: Final = "enabled"


class TraySettings(QObject):
    """Whether tray mode is on: closing the window minimizes to tray instead of quitting, and Quit
    becomes explicit (tray menu / window menu, #205).

    A reactive ``QObject`` (``SimpleProperty``), following `ImageViewerSettings` rather than the
    plain dataclass most of this app's settings sections use: toggling this on the settings page has
    to reach the tray icon `MainWindow` already owns -- creating or tearing it down live -- not just
    change what the next launch does. :func:`shared_tray_settings` is the single, process-wide
    instance `TrayPage` writes and `MainWindow` follows.

    :param parent: optional Qt parent.
    """

    enabled = SimpleProperty(False)
    """Off by default (#205): closing the window is a decision to quit until this is turned on --
    otherwise the window's own close button would silently start doing something else."""

    def load(self, settings: QSettings) -> None:
        """Replace the current value with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.enabled = cast(bool, settings.value(ENABLED_KEY, False, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current value to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(ENABLED_KEY, self.enabled)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_tray_settings() -> TraySettings:
    """The single, process-wide `TraySettings` instance, loaded from persistent storage on first call.

    :returns: the shared instance.
    """
    settings = TraySettings()
    settings.load(persistent_settings())
    return settings
