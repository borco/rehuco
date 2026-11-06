"""The player's volume and playback speed ([[plugins#in-app-player]], #317)."""

from typing import Final

from PySide6.QtCore import QObject

from .player_engine import PlayerEngine
from .player_view_ui import Ui_PlayerView

VOLUME_STEP: Final = 0.05
"""How much each press of the volume keys raises or lowers the volume, of a full scale of 1."""

SPEEDS: Final = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
"""The playback speeds the combo offers, and the steps of the speed keys."""

DEFAULT_SPEED: Final = 1.0


class PlayerLevels(QObject):
    """How loud and how fast the player plays: the volume the keys step, and the speed the combo shows.

    The volume is kept here and handed to a new engine as it is built; the speed is the combo's, which reaches the
    engine at each change and, for a new engine, as it is built.

    :param ui: the player's generated UI, whose speed combo this fills and listens to.
    :param engine: the engine the volume and speed are given to.
    :param parent: the Qt parent, which owns this.
    """

    def __init__(self, ui: Ui_PlayerView, engine: PlayerEngine, parent: QObject) -> None:
        super().__init__(parent)
        self.__combo: Final = ui.speed_combo
        self.__engine: Final = engine
        self.__volume = 1.0
        for rate in SPEEDS:
            self.__combo.addItem(f"{rate:g}×", rate)
        self.__combo.setCurrentIndex(SPEEDS.index(DEFAULT_SPEED))
        self.__combo.currentIndexChanged.connect(self.__on_speed_changed)

    @property
    def volume(self) -> float:
        """The volume, 0 to 1."""
        return self.__volume

    @property
    def speed(self) -> float:
        """The playback rate the combo shows."""
        return float(self.__combo.currentData())

    def change_volume(self, delta: float) -> None:
        """Raise or lower the volume one step, within the scale.

        :param delta: the change, of a full scale of 1.
        """
        self.__volume = min(max(self.__volume + delta, 0.0), 1.0)
        self.__engine.set_volume(self.__volume)

    def change_speed(self, delta: int) -> None:
        """Move the speed combo ``delta`` steps, within its range; its change reaches the player.

        :param delta: how many steps faster, or slower when negative.
        """
        self.__combo.setCurrentIndex(min(max(self.__combo.currentIndex() + delta, 0), self.__combo.count() - 1))

    def __on_speed_changed(self) -> None:
        """Play at the speed the combo now shows."""
        if self.__engine.player is not None:
            self.__engine.player.setPlaybackRate(self.speed)
