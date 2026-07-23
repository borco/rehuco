"""The persisted app-wide theme mode (#57), fed to a ``borco_pyside.theming.ThemeModel`` on
launch -- from then on, that model (not this settings object) is the single source of truth both
the toolbar's cycling action and the ``View`` menu's theme entries read/write."""

from dataclasses import dataclass, field
from typing import ClassVar, Final, cast

from PySide6.QtCore import QSettings, Qt

GROUP: Final = "theme"
MODE_KEY: Final = "mode"

DEFAULT_MODE: Final = Qt.ColorScheme.Unknown
"""Qt's own default before any override is ever applied -- also what a fresh install (nothing
persisted yet) falls back to."""


@dataclass
class ThemeSettings:
    """The single persisted theme mode."""

    __VALID_MODE_VALUES: ClassVar[set[int]] = {
        Qt.ColorScheme.Unknown.value,
        Qt.ColorScheme.Light.value,
        Qt.ColorScheme.Dark.value,
    }
    """Every ``int`` a stored mode may legitimately hold. Checked explicitly on load rather than
    relying on ``Qt.ColorScheme(value)`` to raise for an out-of-range ``value`` -- PySide6's enum
    wrapper accepts (and returns) an arbitrary out-of-range int instead of raising ``ValueError``,
    confirmed empirically."""

    mode: Qt.ColorScheme = field(default=DEFAULT_MODE)

    def load(self, settings: QSettings) -> None:
        """Replace the current mode with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        value = cast(int, settings.value(MODE_KEY, DEFAULT_MODE.value, type=int))
        settings.endGroup()
        self.mode = Qt.ColorScheme(value) if value in self.__VALID_MODE_VALUES else DEFAULT_MODE

    def save(self, settings: QSettings) -> None:
        """Save the current mode to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(MODE_KEY, self.mode.value)
        settings.endGroup()
