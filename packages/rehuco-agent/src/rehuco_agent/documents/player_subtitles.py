"""The player's subtitle keys, which only libvlc answers ([[plugins#in-app-player]], #618)."""

from collections.abc import Callable
from typing import Final, cast

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QPalette
from rehuco_core import SubtitleChoice

from ..settings.videos_settings import shared_videos_settings
from .player_engine import Engine, PlayerEngine
from .player_view_ui import Ui_PlayerView
from .vlc_media_player import VlcMediaPlayer

PENDING_TEXT: Final = "Subs: …"
"""What the subtitle menu reads while libvlc has not listed the video's tracks."""


class PlayerSubtitles(QObject):
    """Moves the video's subtitles along with the player's keys: ``V`` to the next track, ``Alt+V`` to the previous
    one, ``Shift+V`` on or off, and remembers what the reader chose.

    **Only libvlc has subtitles**: it shows a subtitle file beside the video, blended into the frames, and lists its
    tracks. Under Qt Multimedia the three actions are disabled, and the keys do nothing. The change showing is the
    feedback, and a menu on the transport bar says which one is on (``Subs: English``) and picks another, since a
    silent stretch of a video shows none. A paused video has a still on screen, and the engine's refreshed frame
    (:attr:`VlcMediaPlayer.still_refreshed`) replaces it, so a change shows at once.

    **Which tracks the keys visit** is the Videos page's list of languages (:class:`~rehuco_core.SubtitlePreferences`);
    **what shows when a video starts** is this rehu's :attr:`choice`, which travels with the player's layout, or the
    page's default (on or off) for a rehu that has none. Both are handed to the engine before each video
    (:meth:`prepare`), which applies the choice when libvlc has listed the tracks.

    :param ui: the player's generated UI, whose three subtitle actions this connects.
    :param engine: the engine the keys drive.
    :param parent: the Qt parent, which owns this.
    """

    def __init__(self, ui: Ui_PlayerView, engine: PlayerEngine, parent: QObject) -> None:
        super().__init__(parent)
        self.__ui: Final = ui
        self.__engine: Final = engine
        self.choice: SubtitleChoice | None = None
        """What the reader chose of the subtitles in this rehu, or ``None`` while nothing was chosen."""
        ui.subtitle_next_action.triggered.connect(lambda: self.__libvlc(lambda player: player.next_subtitle()))
        ui.subtitle_previous_action.triggered.connect(lambda: self.__libvlc(lambda player: player.previous_subtitle()))
        ui.subtitle_toggle_action.triggered.connect(lambda: self.__libvlc(lambda player: player.toggle_subtitles()))
        ui.subtitle_combo.activated.connect(self.__on_picked)
        self.update_actions()

    def connect_engine(self, player: Engine) -> None:
        """Listen to a new engine, and enable the actions when it is libvlc.

        :param player: the engine just built.
        """
        if self.__engine.vlc:
            vlc = cast(VlcMediaPlayer, player)
            vlc.still_refreshed.connect(self.__ui.still_widget.set_image)
            vlc.subtitle_chosen.connect(self.__on_chosen)
            vlc.subtitle_menu_changed.connect(self.__show_menu)
        self.update_actions()

    def prepare(self) -> None:
        """Hand the engine the languages to visit and the choice to apply, as a video is about to open."""
        player = self.__engine.player
        if not self.__engine.vlc or player is None:
            return
        settings = shared_videos_settings()
        vlc = cast(VlcMediaPlayer, player)
        vlc.set_subtitle_preferences(settings.subtitle_preferences)
        vlc.set_subtitle_choice(self.choice if self.choice is not None else SubtitleChoice(shown=settings.subtitles_on))

    def update_actions(self) -> None:
        """Enable the actions while the engine is libvlc, and show the menu only then."""
        ui = self.__ui
        for action in (ui.subtitle_next_action, ui.subtitle_previous_action, ui.subtitle_toggle_action):
            action.setEnabled(self.__engine.vlc)
        self.__show_menu([], 0, 0)

    def __show_menu(self, labels: object, index: int, visited: int) -> None:
        """Fill the subtitle menu on the transport bar and select the entry that is on. Under libvlc it is always
        there: libvlc lists a video's tracks only while its file is open, so until then it reads :data:`PENDING_TEXT`,
        disabled; under Qt it is hidden. The tracks the keys skip are in the disabled colour, and the reader can still
        pick them.

        :param labels: the entries, a list of strings, empty for none.
        :param index: the entry that is on.
        :param visited: how many of the entries after *none* the keys visit.
        """
        combo = self.__ui.subtitle_combo
        entries = [str(label) for label in labels] if isinstance(labels, list) else []
        combo.clear()
        combo.addItems(entries or ([PENDING_TEXT] if self.__engine.vlc else []))
        skipped = combo.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        for row in range(1 + visited, len(entries)):
            combo.setItemData(row, skipped, Qt.ItemDataRole.ForegroundRole)
        combo.setCurrentIndex(index if combo.count() else -1)
        combo.setVisible(combo.count() > 0)
        combo.setEnabled(len(entries) > 1)

    def __on_picked(self, index: int) -> None:
        """Show the entry the reader picked.

        :param index: its position in the menu.
        """
        self.__libvlc(lambda player: player.select_subtitle(index))

    def __on_chosen(self, choice: object) -> None:
        """Keep what the reader chose.

        :param choice: the :class:`~rehuco_core.SubtitleChoice` the engine says was made.
        """
        if isinstance(choice, SubtitleChoice):
            self.choice = choice

    def __libvlc(self, call: Callable[[VlcMediaPlayer], None]) -> None:
        """Make a call on the engine. The actions are enabled only while it is libvlc, so a trigger finds it there.

        :param call: the engine's method.
        """
        call(cast(VlcMediaPlayer, self.__engine.player))
