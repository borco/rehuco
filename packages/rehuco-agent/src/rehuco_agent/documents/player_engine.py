"""Which engine the player dock drives: built from the Videos page's choice, rebuilt when it changes
([[plugins#in-app-player]], #317, #319)."""

from collections.abc import Callable
from typing import Final, cast

from PySide6.QtCore import QObject
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QWidget

from ..playback_vlc import shared_vlc_library
from ..settings.videos_settings import VLC_PLAYER, shared_videos_settings
from .vlc_media_player import VlcEngineError, VlcMediaPlayer
from .vlc_surface import VlcSurface

Engine = QMediaPlayer | VlcMediaPlayer
"""What `PlayerView` drives: Qt Multimedia's player, or libvlc speaking its language."""


class PlayerEngine:
    """The engine behind one `PlayerView`, and what it was built for.

    **Qt Multimedia is always there; libvlc when the Videos page chooses VLC and the Tools page's VLC loads.** The
    choice is read each time an engine is asked for, so a change applies to the next video selected, in every open
    document: an engine built for another choice is dropped and the chosen one built in its place. A VLC chosen but
    not usable gives Qt, with :attr:`fallback_reason` for the banner, and is tried again at the next video, since the
    Tools page may have been set up meanwhile.

    **Building is cheap and the view owns the signals**: the view hands :meth:`ensure` the callable that connects a
    new engine's signals, so the view's state machine never knows which engine it drives.

    :param owner: the view, parent of the engines built.
    :param video_widget: the page Qt Multimedia draws on.
    :param vlc_surface: the page libvlc's frames are painted on.
    """

    def __init__(self, owner: QWidget, video_widget: QWidget, vlc_surface: VlcSurface) -> None:
        self.__owner: Final = owner
        self.__pages: Final = (video_widget, vlc_surface)
        """The surface stack's pages: Qt's video widget, and the one libvlc's frames are painted on."""
        self.__player: Engine | None = None
        self.__audio: QAudioOutput | None = None
        self.__vlc = False
        self.__fallback_reason: str | None = None
        self.__built_for: str | None = None
        """The Videos page's choice the engine was built for; another choice rebuilds it at the next selection."""

    @property
    def player(self) -> Engine | None:
        """The engine built, or ``None`` before the first video and after :meth:`drop`."""
        return self.__player

    @property
    def vlc(self) -> bool:
        """Whether the engine built is libvlc, which shows what Qt cannot and whose still is its last frame."""
        return self.__vlc

    @property
    def surface(self) -> QWidget:
        """The page of the surface stack the engine draws on: Qt's video widget, or the one libvlc's frames are painted
        on."""
        return self.__pages[1] if self.__vlc else self.__pages[0]

    @property
    def fallback_reason(self) -> str | None:
        """Why the engine is Qt although VLC was chosen, or ``None``."""
        return self.__fallback_reason

    def ensure(self, volume: float, speed: float, connect: Callable[[Engine], None]) -> Engine:
        """The engine for the choice made now: the one built, or a new one when none is or the choice changed.

        :param volume: the volume a new engine starts at, 0 to 1.
        :param speed: the playback rate a new engine starts at.
        :param connect: what connects a new engine's signals to the view.
        :returns: the engine.
        """
        choice = shared_videos_settings().player
        if self.__player is not None and (choice != self.__built_for or self.__fallback_reason is not None):
            # another choice, or a VLC that could not be used last time and may be set up by now
            self.drop()
        if self.__player is None:
            self.__built_for = choice
            player = self.__build_vlc(volume) if choice == VLC_PLAYER else None
            if player is None:
                player = self.__build_qt(volume)
            player.setPlaybackRate(speed)
            self.__player = player
            connect(player)
        return self.__player

    def drop(self) -> None:
        """Let the engine go, with whatever it was built for: the next :meth:`ensure` builds the one chosen then.

        Called with no file held, so nothing is playing through it. libvlc's own objects are released with it.
        """
        if self.__player is None:
            return
        if self.__vlc:
            cast(VlcMediaPlayer, self.__player).close()
        cast(QObject, self.__player).deleteLater()
        if self.__audio is not None:
            self.__audio.deleteLater()
        self.__player = None
        self.__audio = None
        self.__vlc = False
        self.__fallback_reason = None

    def set_volume(self, volume: float) -> None:
        """Set the volume on whichever engine is built.

        :param volume: 0 to 1.
        """
        if self.__audio is not None:
            self.__audio.setVolume(volume)
        elif self.__vlc and self.__player is not None:
            cast(VlcMediaPlayer, self.__player).setVolume(volume)

    def __build_vlc(self, volume: float) -> VlcMediaPlayer | None:
        """Build the libvlc engine, when the Tools page's VLC loads.

        :param volume: the volume to start at.
        :returns: the engine, or ``None`` with :attr:`fallback_reason` set when VLC cannot be used.
        """
        library = shared_vlc_library()
        try:
            if not library.available:
                raise VlcEngineError(library.reason or "libvlc is not available.")
            player = VlcMediaPlayer(library, self.__pages[1], self.__owner)
        except VlcEngineError as error:
            self.__fallback_reason = str(error)
            return None
        player.setVolume(volume)
        self.__vlc = True
        return player

    def __build_qt(self, volume: float) -> QMediaPlayer:
        """Build the Qt Multimedia engine.

        :param volume: the volume to start at.
        :returns: the player, its audio output kept.
        """
        player = QMediaPlayer(self.__owner)
        audio = QAudioOutput(self.__owner)
        audio.setVolume(volume)
        player.setAudioOutput(audio)
        player.setVideoOutput(self.__pages[0])
        self.__audio = audio
        return player
