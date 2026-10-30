"""The tutorial's in-app video player: a Qt Multimedia surface, a transport bar and the player's keys
([[plugins#in-app-player]], #317)."""

from collections.abc import Callable
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Final, cast

from borco_pyside.theming import GlyphActionIconThemeHandler, themed_glyph_icon
from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QImage, QPalette
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoFrame
from PySide6.QtWidgets import QToolButton, QWidget
from rehuco_core import (
    EXTERNAL_TOOLS,
    FFMPEG_LIBRARIES_TOOL,
    VideoFormat,
    content_path,
    read_video_format,
    tutorial_video_keys,
)

from ..commands import (
    PLAYER_BACK,
    PLAYER_FORWARD,
    PLAYER_NEXT,
    PLAYER_PLAY_PAUSE,
    PLAYER_PREVIOUS,
    PLAYER_SPEED_DOWN,
    PLAYER_SPEED_UP,
    PLAYER_TO_END,
    PLAYER_TO_START,
    PLAYER_VOLUME_DOWN,
    PLAYER_VOLUME_UP,
    shared_command_registry,
)
from ..glyphs import (
    PLAYER_BACK_GLYPH,
    PLAYER_FORWARD_GLYPH,
    PLAYER_NEXT_GLYPH,
    PLAYER_PAUSE_GLYPH,
    PLAYER_PLAY_GLYPH,
    PLAYER_PREVIOUS_GLYPH,
)
from ..playback_libraries import shared_playback_libraries
from ..playback_vlc import shared_vlc_library
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.videos_settings import VLC_PLAYER, shared_videos_settings
from .latest_runner import LatestRunner
from .player_notices import AV1_LIBRARIES_HINT, PlayerNotices
from .player_playlist import PlayerPlaylist
from .player_view_ui import Ui_PlayerView
from .rehu_document_model import RehuDocumentModel
from .vlc_media_player import VlcEngineError, VlcMediaPlayer
from .watch_progress_recorder import WatchProgressRecorder

SEEK_STEP_MS: Final = 5000
"""How far the back and forward keys and buttons jump."""

VOLUME_STEP: Final = 0.05
"""How much each press of the volume keys raises or lowers the volume, of a full scale of 1."""

SPEEDS: Final = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
"""The playback speeds the combo offers, and the steps of the speed keys."""

DEFAULT_SPEED: Final = 1.0

NO_FRAME_MS: Final = 1500
"""How long an AV1 video may play without showing a frame before the player says why: Qt decodes AV1 in hardware only,
and a machine without it plays the sound with no picture and no error."""

GRAB_TIMEOUT_MS: Final = 3000
"""How long a video may be held open to take a frame of it: a file that gives none by then is let go of without one."""

FRAME_TOLERANCE_MS: Final = 1000
"""How far from where a video was left a frame may be and still be the one to show it as."""

LIST_TAG: Final = "list"
"""What the runner that lists the tutorial's videos answers under."""

INTERLACED_NOTICE: Final = (
    "This video is interlaced, and this player shows it without deinterlacing: moving edges look combed."
)
AV1_NOTICE: Final = (
    "This video is AV1, and this computer's graphics hardware does not seem to decode it: the sound plays but there "
    "is no picture."
)
VLC_FALLBACK_TEMPLATE: Final = "Playing with Qt: {reason}"
"""What the player says when VLC is chosen on the Videos page and its libvlc could not be used (#319)."""
ERROR_NOTICE: Final = "This video could not be played."
LIST_ERROR_NOTICE: Final = "This tutorial's videos could not be listed."
NO_VIDEOS_NOTICE: Final = "This tutorial has no videos."
MISSING_NOTICE: Final = "That video is no longer in this tutorial."


class Session(Enum):
    """Whether the player holds a video's file, and why."""

    NONE = auto()
    """No source is open: the file is not held, and the OS may rename its folder."""

    GRAB = auto()
    """The file is open, paused, only to take a frame of it and learn its length -- a moment, then it is let go."""

    PLAY = auto()
    """The video is playing, and the file is held for as long as it does."""


class PlayerView(QWidget):  # pylint: disable=too-many-instance-attributes
    """One document's video player: a surface, a transport bar, and the keys that drive them, recording where the
    reader is through the document's :class:`~rehuco_agent.documents.watch_progress_recorder.WatchProgressRecorder`.

    **It holds a video's file only while the video plays.** A loaded or paused video is the view's own state -- which
    video, where, and a still of it -- with no source open in the Qt player, because the OS refuses to rename a folder
    with a video open in it and renaming a resource's folder is something the app does. Pausing records where the video
    is, keeps a frame of it on the surface, and lets go; playing opens it again at that position. A rename that begins
    while one plays pauses it first (:meth:`__on_before_rename`). Loading a video to show -- the dock opened, previous,
    next -- opens it for a moment (:attr:`Session.GRAB`) to take a frame and its length, and lets go.

    **One player per document** ([[plugins#in-app-player]]) over **the whole tutorial's videos**, in every folder, in
    natural path order. Showing the dock loads the one watched last, paused where it was left (:meth:`load_last`);
    :meth:`jump` -- a double-click in the Files dock -- plays one at once. Previous and next load the neighbour paused:
    at its recorded position when partly watched, at the start when never watched or watched to the end. The engine is
    built on the first video, so opening a tutorial loads neither FFmpeg nor libvlc.

    **Two engines** ([[plugins#in-app-player]]). Qt Multimedia, always there; or the user's own libvlc, when the Videos
    page chooses VLC and the Tools page has one with its library (:class:`VlcMediaPlayer`, which speaks
    ``QMediaPlayer``'s language so nothing below cares which). The choice is read as the engine is built, so it
    applies to the next document opened; a VLC chosen but not usable plays through Qt, and the banner says why.
    libvlc deinterlaces and decodes AV1 in software, so neither notice below is made under it.

    **Where it records.** Every position the player reports while a video plays goes to the recorder, which writes about
    every five seconds; the moments that matter are flushed at once -- pause, a seek, switching video, :meth:`stop`.
    Nothing is recorded for a video that was only loaded, so stepping through a tutorial leaves its progress, and the
    video watched last, as they were. Reaching the end records the full length, which is what marks the video viewed
    (:func:`~rehuco_core.reached_end`), and loads the next.

    **What it explains, under Qt.** Qt shows interlaced video combed, and plays AV1 with sound and no picture where
    the graphics hardware has no AV1 decoder, raising no error. The file's codec and scan type are read off the GUI
    thread; an interlaced file is noted at once, an AV1 one when no frame has shown within :data:`NO_FRAME_MS` of
    playing.

    **Keys** are the catalog's ``document.player.*`` commands, armed while focus is anywhere inside this widget; the
    seek slider, the speed combo and the buttons take no focus, so the arrows are never theirs.

    :param model: the document, read for the progress each video resumes from and the video watched last.
    :param recorder: where the playing video's position goes.
    :param parent: optional Qt parent.
    :param no_frame_ms: how long an AV1 video may show no frame before the notice.
    :param grab_ms: how long a video may be held open to take a frame of it.
    """

    tools_requested = Signal()
    """The user asked to set up the FFmpeg libraries an AV1 video needs; the window above opens the Tools page."""

    def __init__(
        self,
        model: RehuDocumentModel,
        recorder: WatchProgressRecorder,
        parent: QWidget | None = None,
        no_frame_ms: int = NO_FRAME_MS,
        grab_ms: int = GRAB_TIMEOUT_MS,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__recorder: Final = recorder
        self.__player: QMediaPlayer | VlcMediaPlayer | None = None
        self.__vlc = False
        """Whether the engine built is libvlc, which shows what Qt cannot and takes its stills by snapshot."""
        self.__fallback_reason: str | None = None
        """Why the engine is Qt although VLC was chosen, or ``None``."""
        self.__audio: QAudioOutput | None = None
        self.__volume = 1.0
        self.__videos: list[tuple[str, Path]] | None = None
        """The tutorial's videos as ``(content key, path)`` in play order, once listed; ``None`` before."""
        self.__intent: tuple[str | None, bool] | None = None
        """What to do with the list being read: the video to select (``None`` for the one watched last) and whether to
        play it. Replaced by a later request, so a double-click overrides a dock still listing."""
        self.__playlist: PlayerPlaylist | None = None
        self.__key: str | None = None
        """The content key of the video selected: what its positions are recorded under. Not the playlist's current
        one, which a step has already moved on by the time the video it left is recorded."""
        self.__session = Session.NONE
        self.__state = QMediaPlayer.PlaybackState.StoppedState
        self.__ready = False
        """Whether the video in the player has buffered: before that the player reports a position of 0 that is no
        one's progress, and a status left over from the video it replaced."""
        self.__played = False
        """Whether the selected video has played since it was selected, and so is one whose seeks are progress."""
        self.__position_ms = 0
        """Where the video selected is: where it was left, until it plays, and where it plays from."""
        self.__duration_ms = 0
        """The selected video's length, from what is known of it before it opens, and from the player once it does."""
        self.__scrubbing = False
        self.__frame_seen = False
        self.__av1 = False
        self.__listening = False

        self.__ui: Final = Ui_PlayerView()
        self.__ui.setupUi(self)
        self.__surface: QWidget = self.__ui.video_widget
        """The page of the surface stack the engine draws on: Qt's video widget, or libvlc's native window."""
        self.__notices: Final = PlayerNotices(self.__ui.notice_banner, self)
        self.__notices.tools_requested.connect(self.tools_requested)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.__format_runner: Final = LatestRunner(self)
        self.__format_runner.setObjectName("format_runner")
        self.__format_runner.read.connect(self.__on_format_read)
        self.__list_runner: Final = LatestRunner(self)
        self.__list_runner.setObjectName("list_runner")
        self.__list_runner.read.connect(self.__on_listed)
        self.__no_frame_timer: Final = self.__single_shot(no_frame_ms, self.__on_no_frame)
        self.__grab_timer: Final = self.__single_shot(grab_ms, self.__on_grab_timeout)
        self.__ui.video_widget.videoSink().videoFrameChanged.connect(self.__on_frame)

        self.__setup_actions()
        self.__setup_bar()

    # region What the dock calls

    def load_last(self) -> None:
        """Load the video watched last, paused where it was left -- what showing the dock does when nothing is loaded.

        The tutorial's first video when none was watched or the one watched is gone. Nothing happens while a video is
        loaded or the videos are being listed for one, so a dock shown again does not lose its place.
        """
        if self.__key is not None or self.__intent is not None:
            return
        self.__request(None, play=False)

    def jump(self, key: str) -> None:
        """Play a video of the tutorial from where it was left, and take the keyboard -- what a double-click in the
        Files dock does.

        :param key: the video's content key.
        """
        self.__request(key, play=True)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def stop(self) -> None:
        """Stop playing, recording where it stopped, let go of the video's file, and show nothing.

        What closing the dock does, and what closing the document does first, so nothing plays on, or is written, after
        it. Showing the dock again loads the video watched last, which is this one when it played.
        """
        self.__format_runner.discard()
        self.__list_runner.discard()
        self.__intent = None
        self.__no_frame_timer.stop()
        self.__flush()
        self.__release()
        self.__close_video()

    # endregion

    # region Setup

    def __single_shot(self, interval_ms: int, slot: Callable[[], None]) -> QTimer:
        """A stopped single-shot timer of this widget's.

        :param interval_ms: how long it runs once started.
        :param slot: what it calls.
        :returns: the timer.
        """
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval_ms)
        timer.timeout.connect(slot)
        return timer

    def __setup_actions(self) -> None:
        """Bind the player's actions to its commands and put the transport ones on their buttons."""
        ui = self.__ui
        for action, glyph in (
            (ui.previous_action, PLAYER_PREVIOUS_GLYPH),
            (ui.back_action, PLAYER_BACK_GLYPH),
            (ui.forward_action, PLAYER_FORWARD_GLYPH),
            (ui.next_action, PLAYER_NEXT_GLYPH),
        ):
            GlyphActionIconThemeHandler(action, glyph.codepoint, glyph.family)
        for action, command in (
            (ui.play_pause_action, PLAYER_PLAY_PAUSE),
            (ui.back_action, PLAYER_BACK),
            (ui.forward_action, PLAYER_FORWARD),
            (ui.previous_action, PLAYER_PREVIOUS),
            (ui.next_action, PLAYER_NEXT),
            (ui.to_start_action, PLAYER_TO_START),
            (ui.to_end_action, PLAYER_TO_END),
            (ui.volume_up_action, PLAYER_VOLUME_UP),
            (ui.volume_down_action, PLAYER_VOLUME_DOWN),
            (ui.speed_up_action, PLAYER_SPEED_UP),
            (ui.speed_down_action, PLAYER_SPEED_DOWN),
        ):
            shared_command_registry().bind(action, command.id)
            # added to this widget, whose subtree the keys are scoped to: every document has a player of its own
            self.addAction(action)
        ui.play_pause_action.triggered.connect(self.__toggle_playback)
        ui.back_action.triggered.connect(lambda: self.__seek_by(-SEEK_STEP_MS))
        ui.forward_action.triggered.connect(lambda: self.__seek_by(SEEK_STEP_MS))
        ui.previous_action.triggered.connect(lambda: self.__step(-1))
        ui.next_action.triggered.connect(lambda: self.__step(1))
        ui.to_start_action.triggered.connect(lambda: self.__seek_to(0))
        ui.to_end_action.triggered.connect(self.__finish_video)
        ui.volume_up_action.triggered.connect(lambda: self.__change_volume(VOLUME_STEP))
        ui.volume_down_action.triggered.connect(lambda: self.__change_volume(-VOLUME_STEP))
        ui.speed_up_action.triggered.connect(lambda: self.__change_speed(1))
        ui.speed_down_action.triggered.connect(lambda: self.__change_speed(-1))
        buttons: tuple[tuple[QToolButton, QAction], ...] = (
            (ui.previous_button, ui.previous_action),
            (ui.back_button, ui.back_action),
            (ui.play_pause_button, ui.play_pause_action),
            (ui.forward_button, ui.forward_action),
            (ui.next_button, ui.next_action),
        )
        for button, action in buttons:
            button.setDefaultAction(action)

    def __setup_bar(self) -> None:
        """Fill the speed combo, wire the slider and the combo, and show the bar as it is with nothing selected."""
        ui = self.__ui
        for rate in SPEEDS:
            ui.speed_combo.addItem(f"{rate:g}×", rate)
        ui.speed_combo.setCurrentIndex(SPEEDS.index(DEFAULT_SPEED))
        ui.position_slider.sliderPressed.connect(self.__on_slider_pressed)
        ui.position_slider.sliderReleased.connect(self.__on_slider_released)
        ui.position_slider.actionTriggered.connect(self.__on_slider_action)
        ui.speed_combo.currentIndexChanged.connect(self.__on_speed_changed)
        ui.surface_stack.setCurrentWidget(ui.still_widget)
        self.__show_playing(False)
        self.__show_time(0)
        self.__update_actions()

    def __ensure_player(self) -> QMediaPlayer | VlcMediaPlayer:
        """Build the engine on first use: libvlc when chosen and usable, else Qt Multimedia.

        :returns: the player.
        """
        if self.__player is None:
            player = self.__build_vlc_player() or self.__build_qt_player()
            player.setPlaybackRate(self.__speed())
            player.positionChanged.connect(self.__on_position_changed)
            player.durationChanged.connect(self.__on_duration_changed)
            player.playbackStateChanged.connect(self.__on_state_changed)
            player.mediaStatusChanged.connect(self.__on_status_changed)
            player.errorOccurred.connect(self.__on_error)
            self.__player = player
        return self.__player

    def __build_vlc_player(self) -> VlcMediaPlayer | None:
        """Build the libvlc engine, when the Videos page chooses VLC and the Tools page's VLC loads.

        :returns: the player, or ``None`` with :attr:`__fallback_reason` set when VLC is chosen but cannot be used,
            and ``None`` with none when it is not chosen.
        """
        if shared_videos_settings().player != VLC_PLAYER:
            return None
        library = shared_vlc_library()
        try:
            if not library.available:
                raise VlcEngineError(library.reason or "libvlc is not available.")
            player = VlcMediaPlayer(library, self.__ui.vlc_surface, self)
        except VlcEngineError as error:
            self.__fallback_reason = str(error)
            return None
        player.setVolume(self.__volume)
        player.still_ready.connect(self.__on_still)
        self.__vlc = True
        self.__surface = self.__ui.vlc_surface
        return player

    def __build_qt_player(self) -> QMediaPlayer:
        """Build the Qt Multimedia engine.

        :returns: the player, its audio output kept in :attr:`__audio`.
        """
        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        audio.setVolume(self.__volume)
        player.setAudioOutput(audio)
        player.setVideoOutput(self.__ui.video_widget)
        self.__audio = audio
        return player

    # endregion

    # region Choosing a video

    def __request(self, key: str | None, *, play: bool) -> None:
        """Select a video of the tutorial, listing its videos first unless they are known to hold it.

        :param key: the video's content key, or ``None`` for the one watched last.
        :param play: whether to play it, rather than load it paused.
        """
        path = self.__model.path
        if path is None:
            return
        if self.__videos is not None and (key is None or any(known == key for known, _ in self.__videos)):
            self.__select_from(self.__videos, key, play)
            return
        self.__intent = (key, play)
        settings = shared_videos_settings()
        self.__list_runner.start(
            LIST_TAG,
            partial(
                tutorial_video_keys,
                path,
                video_extensions=settings.video_extensions,
                excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            ),
        )

    def __on_listed(self, _tag: str, result: object) -> None:
        """Select the video asked for, now the tutorial's videos are listed.

        :param _tag: what the list was for.
        :param result: the videos' content keys, or the error listing them ended in.
        """
        intent, self.__intent = self.__intent, None
        path = self.__model.path
        if isinstance(result, Exception):
            self.__notices.add(f"{LIST_ERROR_NOTICE} {result}")
            return
        keys = cast(list[str], result)
        self.__videos = [(key, content_path(path, key)) for key in keys] if path is not None else []
        if not self.__videos:
            self.__notices.add(NO_VIDEOS_NOTICE)
        elif intent is not None:
            self.__select_from(self.__videos, *intent)

    def __select_from(self, videos: list[tuple[str, Path]], key: str | None, play: bool) -> None:
        """Select a video of the list.

        :param videos: the tutorial's videos.
        :param key: the video's content key, or ``None`` for the one watched last, else the first.
        :param play: whether to play it, rather than load it paused.
        """
        keys = [known for known, _ in videos]
        if key is None:
            last = self.__model.last_video()
            key = last if last in keys else keys[0]
        elif key not in keys:
            self.__notices.add(MISSING_NOTICE)
            return
        self.__select(PlayerPlaylist(videos, key), play)

    def __select(self, playlist: PlayerPlaylist, play: bool) -> None:
        """Make the playlist's current video the one selected, leaving the one before with its position recorded.

        It starts where it was left, or at the beginning when never watched or watched to the end, and the bar shows
        that at once, before anything opens. Played at once or loaded paused, it opens the file; paused, only to take
        a frame of it.

        :param playlist: the playlist, positioned on the video to select.
        :param play: whether to play it, rather than load it paused.
        """
        self.__leave()
        video = playlist.current
        self.__playlist = playlist
        self.__key = video.key
        self.__played = False
        self.__frame_seen = False
        self.__av1 = False
        self.__no_frame_timer.stop()
        entry = self.__model.progress_of(video.key)
        measured = self.__model.measured_videos().get(video.key)
        length = measured.duration if measured is not None else (entry.duration if entry is not None else None)
        self.__duration_ms = round(length * 1000) if length else 0
        self.__position_ms = round(PlayerPlaylist.start_position(entry, length) * 1000)
        self.__ui.position_slider.setRange(0, self.__duration_ms)
        self.__show_position(self.__position_ms)
        self.__ui.title_label.set_text(video.key)
        self.__notices.clear()
        self.__ui.still_widget.set_image(None)
        self.__ui.surface_stack.setCurrentWidget(self.__ui.still_widget)
        # the engine before the format is read: whether a format needs explaining depends on which engine shows it
        self.__ensure_player()
        self.__format_runner.start(video.key, partial(read_video_format, video.path))
        self.__open(Session.PLAY if play else Session.GRAB)
        if self.__fallback_reason is not None:
            self.__notices.add(VLC_FALLBACK_TEMPLATE.format(reason=self.__fallback_reason))
        self.__update_actions()

    def __step(self, delta: int) -> bool:
        """Load the video ``delta`` places on in the playlist, paused, unless that is past either end.

        :param delta: how many videos forward, or back when negative.
        :returns: whether there was a video there.
        """
        if self.__playlist is None or self.__playlist.step(delta) is None:
            return False
        self.__select(self.__playlist, play=False)
        return True

    def __close_video(self) -> None:
        """Return to showing nothing: no video, no playlist, an empty bar -- what stopping leaves."""
        self.__videos = None
        self.__playlist = None
        self.__key = None
        self.__played = False
        self.__position_ms = 0
        self.__duration_ms = 0
        self.__ui.position_slider.setRange(0, 0)
        self.__ui.position_slider.setValue(0)
        self.__show_time(0)
        self.__ui.title_label.set_text("")
        self.__ui.still_widget.set_image(None)
        self.__ui.surface_stack.setCurrentWidget(self.__ui.still_widget)
        self.__notices.clear()
        self.__show_playing(False)
        self.__update_actions()

    # endregion

    # region Holding the file

    def __open(self, session: Session) -> None:
        """Open the selected video's file in the player, to play it or to take a frame of it.

        :param session: why it is opened.
        """
        player = self.__ensure_player()
        assert self.__playlist is not None  # nosec B101  (a video is selected before it is opened)
        self.__session = session
        self.__ready = False
        self.__listen()
        # from where the record is now, not where the playlist saw the video: a rename moves the folder under a video
        # that is paused, and pressing play opens it at its new place
        record_path = self.__model.path
        video = self.__playlist.current
        path = content_path(record_path, video.key) if record_path is not None else video.path
        player.setSource(QUrl.fromLocalFile(str(path)))
        if session is Session.PLAY:
            self.__ui.surface_stack.setCurrentWidget(self.__surface)
            player.play()
        else:
            player.pause()
            self.__grab_timer.start()

    def __release(self) -> None:
        """Let go of the video's file: the player is stopped and its source cleared."""
        self.__grab_timer.stop()
        held = self.__session is not Session.NONE
        # before the player is told: it reports the position it resets to (0) ahead of the state it ends in, and a
        # position reported while this still said *playing* would be recorded as where the reader got to
        self.__session = Session.NONE
        self.__ready = False
        self.__state = QMediaPlayer.PlaybackState.StoppedState
        if held and self.__player is not None:
            self.__player.stop()
            self.__player.setSource(QUrl())
        self.__stop_listening()

    def __leave(self) -> None:
        """Let go of the video in the player, recording where it was."""
        self.__flush()
        self.__release()

    def __listen(self) -> None:
        """Ask to be told of a rename of this resource, for as long as its file is held."""
        coordinator = self.__model.rename_coordinator
        if coordinator is not None and not self.__listening:
            coordinator.add_before_rename_listener(self.__on_before_rename)
            self.__listening = True

    def __stop_listening(self) -> None:
        """Stop asking to be told of renames, now the file is not held."""
        coordinator = self.__model.rename_coordinator
        if coordinator is not None and self.__listening:
            coordinator.remove_before_rename_listener(self.__on_before_rename)
        self.__listening = False

    def __on_before_rename(self, record_path: Path) -> None:
        """Let go of the video's file before this resource is renamed: pause a video that plays, drop one that is only
        being held for a frame.

        The OS refuses to rename a folder with a video open in it; this is how the rename gets past a video playing.
        Only this resource's own rename: another's has nothing to do with this player.

        :param record_path: the ``.rehu`` file of the resource about to be renamed.
        """
        if record_path != self.__model.path:
            return
        if self.__session is Session.PLAY:
            self.__pause()
        elif self.__session is Session.GRAB:
            self.__release()

    # endregion

    # region Playing

    def __toggle_playback(self) -> None:
        """Pause a video that plays, and play one that does not."""
        if self.__key is None:  # pragma: no cover  (the action is disabled until a video is selected)
            return
        if self.__session is Session.PLAY:
            self.__pause()
        else:
            self.__play_selected()

    def __play_selected(self) -> None:
        """Play the selected video from where it is."""
        if self.__session is Session.GRAB and self.__player is not None:
            # already open to take a frame: carry on from there, the seek to where it is made as it buffers
            self.__grab_timer.stop()
            self.__session = Session.PLAY
            self.__ui.surface_stack.setCurrentWidget(self.__surface)
            self.__player.play()
            if self.__ready:
                self.__played = True
                self.__arm_no_frame_timer()
        else:
            self.__open(Session.PLAY)

    def __pause(self) -> None:
        """Pause a video by letting go of it: where it is is recorded, a frame of it is kept on the surface, and its
        file is released, so the folder can be renamed while it is paused."""
        player = self.__player
        if player is not None and self.__ready:
            self.__position_ms = player.position()
        self.__flush()
        self.__ui.still_widget.set_image(self.__still_now())
        self.__release()
        self.__ui.surface_stack.setCurrentWidget(self.__ui.still_widget)
        self.__show_position(self.__position_ms)
        self.__show_playing(False)

    def __finish_video(self) -> None:
        """Record the whole video as watched, then load the next; after the last, stop and let go of its file.

        What the end of a video does, and what the key for it does to one not at its end."""
        if self.__key is None:  # pragma: no cover  (the action is disabled until a video is selected)
            return
        length = self.__duration_seconds()
        if length is not None:
            self.__recorder.position(self.__key, length, length)
        self.__recorder.flush()
        # it has ended: there is no position left to record, and the reset the stop reports is no progress
        self.__state = QMediaPlayer.PlaybackState.StoppedState
        if not self.__step(1):
            self.stop()

    def __seek_by(self, delta_ms: int) -> None:
        """Jump ``delta_ms`` from where the video is, within the video.

        :param delta_ms: how far forward, or back when negative.
        """
        playing = self.__player is not None and self.__session is Session.PLAY and self.__ready
        position = self.__player.position() if playing and self.__player is not None else self.__position_ms
        self.__seek_to(position + delta_ms)

    def __seek_to(self, position_ms: int) -> None:
        """Move to ``position_ms``, recording it at once when the video has played, so a seek is never lost to the
        writes' pace. A video not playing opens nothing: the bar moves, and playing starts from there.

        :param position_ms: where to go; held within the video when its length is known.
        """
        if self.__key is None:
            return
        target = max(position_ms, 0)
        if self.__duration_ms > 0:
            target = min(target, self.__duration_ms)
        self.__position_ms = target
        self.__show_position(target)
        if self.__player is not None and self.__session is not Session.NONE and self.__ready:
            self.__player.setPosition(target)
        if self.__session is Session.PLAY or self.__played:
            self.__recorder.position(self.__key, target / 1000, self.__duration_seconds())
            self.__recorder.flush()

    def __change_volume(self, delta: float) -> None:
        """Raise or lower the volume one step, within the scale.

        :param delta: the change, of a full scale of 1.
        """
        self.__volume = min(max(self.__volume + delta, 0.0), 1.0)
        if self.__audio is not None:
            self.__audio.setVolume(self.__volume)
        elif self.__vlc and self.__player is not None:
            cast(VlcMediaPlayer, self.__player).setVolume(self.__volume)

    def __change_speed(self, delta: int) -> None:
        """Move the speed combo ``delta`` steps, within its range; its change reaches the player.

        :param delta: how many steps faster, or slower when negative.
        """
        combo = self.__ui.speed_combo
        combo.setCurrentIndex(min(max(combo.currentIndex() + delta, 0), combo.count() - 1))

    def __speed(self) -> float:
        """The speed the combo shows.

        :returns: the playback rate.
        """
        return float(self.__ui.speed_combo.currentData())

    def __on_speed_changed(self) -> None:
        """Play at the speed the combo now shows."""
        if self.__player is not None:
            self.__player.setPlaybackRate(self.__speed())

    # endregion

    # region What the player reports

    def __on_position_changed(self, position_ms: int) -> None:
        """Follow the position on the slider and the clock, and note it for the recorder.

        :param position_ms: where playback is.
        """
        # a video held only for a frame shows where playback will start, whatever the player reports meanwhile
        if self.__session is not Session.PLAY or not self.__ready:
            return
        self.__position_ms = position_ms
        self.__show_position(position_ms)
        if self.__key is not None and self.__state != QMediaPlayer.PlaybackState.StoppedState:
            self.__recorder.position(self.__key, position_ms / 1000, self.__duration_seconds())

    def __on_duration_changed(self, duration_ms: int) -> None:
        """Fit the slider to the video's length.

        :param duration_ms: the video's length.
        """
        if self.__session is Session.NONE:
            return
        self.__duration_ms = duration_ms
        self.__ui.position_slider.setRange(0, duration_ms)
        self.__show_position(self.__position_ms)

    def __on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        """Show whether the video plays, and record where it is the moment it does not.

        :param state: the player's new state.
        """
        self.__state = state
        playing = self.__session is Session.PLAY and state == QMediaPlayer.PlaybackState.PlayingState
        self.__show_playing(playing)
        if self.__session is Session.PLAY and not playing:
            self.__flush()

    def __on_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Resume the video once it has buffered, and move on when it ends.

        **Buffered, not loaded.** Replacing a source makes the player report ``LoadedMedia`` from inside ``setSource``,
        for the video it is replacing, ahead of the new one's own; a seek made then, or straight after ``play()``, is
        lost (measured on a real clip: the video started at 0 whatever it recorded). ``BufferedMedia`` is the first
        status the video itself reports once it plays or is paused, and a seek made there holds.

        The length is read then too, not only from ``durationChanged``: the player reports no change for a source as
        long as the one before it, so a video opened again, or after one of its own length, would otherwise be recorded
        with no length at all.

        :param status: the player's new media status.
        """
        player = self.__player
        if (
            status == QMediaPlayer.MediaStatus.BufferedMedia
            and not self.__ready
            and player is not None
            and self.__session is not Session.NONE
        ):
            self.__ready = True
            if player.duration() > 0:
                self.__on_duration_changed(player.duration())
            if self.__position_ms > 0:
                player.setPosition(self.__position_ms)
            if self.__session is Session.PLAY:
                self.__played = True
                self.__arm_no_frame_timer()
        elif status == QMediaPlayer.MediaStatus.EndOfMedia and self.__session is Session.PLAY:
            self.__finish_video()

    def __on_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        """Say what stopped the video.

        :param _error: the kind of error.
        :param message: Qt's description of it.
        """
        self.__notices.add(f"{ERROR_NOTICE} {message}".rstrip())

    def __on_frame(self, frame: QVideoFrame) -> None:
        """Take the picture the video shows: the frame a paused load was opened for, or proof an AV1 video is no silent
        one.

        Only a valid frame is one, and only once the video is ready: the sink also reports an empty frame each time it
        is cleared, as a source is replaced, and the last frame of the video being replaced can arrive after it. An AV1
        video that cannot be decoded gets nothing else, so counting either hid exactly the video this exists to explain
        (found by playing one with hardware decoding off, after another video).

        :param frame: what the sink was given.
        """
        if not self.__ready or not frame.isValid():
            return
        if self.__session is Session.GRAB:
            start_ms = frame.startTime() / 1000
            if start_ms < 0 or abs(start_ms - self.__position_ms) <= FRAME_TOLERANCE_MS:
                self.__ui.still_widget.set_image(frame.toImage())
                self.__release()
        elif self.__session is Session.PLAY and not self.__frame_seen:
            self.__frame_seen = True
            self.__no_frame_timer.stop()

    def __on_still(self, image: QImage) -> None:
        """Take the picture libvlc made of a paused load, and let the file go -- what a frame from Qt's sink does.

        :param image: the still at the position the video was opened at.
        """
        if self.__session is Session.GRAB:
            self.__ui.still_widget.set_image(image)
            self.__release()

    def __still_now(self) -> QImage | None:
        """The picture the surface shows, as a video is paused: Qt's last frame, or a libvlc snapshot taken while the
        file is still held.

        :returns: the image, or ``None`` when there is none to take.
        """
        if self.__vlc and self.__player is not None:
            return cast(VlcMediaPlayer, self.__player).grab_still() if self.__ready else None
        return self.__ui.video_widget.videoSink().videoFrame().toImage()

    def __on_grab_timeout(self) -> None:
        """Let go of a video that gave no frame to show, without one. The timer runs for a paused load alone: playing
        or letting go stops it."""
        self.__release()

    def __arm_no_frame_timer(self) -> None:
        """Start waiting for a picture from an AV1 video that plays."""
        if self.__av1 and self.__session is Session.PLAY and self.__ready and not self.__frame_seen:
            self.__no_frame_timer.start()

    def __on_no_frame(self) -> None:
        """Say why an AV1 video that plays shows nothing."""
        if not self.__frame_seen and self.__state == QMediaPlayer.PlaybackState.PlayingState:
            self.__notices.add(AV1_NOTICE + (AV1_LIBRARIES_HINT if self.__offers_libraries() else ""))

    def __on_format_read(self, key: str, result: object) -> None:
        """Explain what Qt cannot show well about the video, once its format is known.

        :param key: the video the format is of.
        :param result: its format, or ``None``, or the error reading it ended in -- the file could not be read.
        """
        if key != self.__key or not isinstance(result, VideoFormat) or self.__vlc:
            return
        if result.interlaced:
            self.__notices.add(INTERLACED_NOTICE)
        self.__av1 = result.is_av1
        self.__arm_no_frame_timer()

    # endregion

    # region The slider

    def __on_slider_pressed(self) -> None:
        """Stop the slider following the video while the reader holds it."""
        self.__scrubbing = True

    def __on_slider_released(self) -> None:
        """Seek to where the reader let go of the slider."""
        self.__scrubbing = False
        self.__seek_to(self.__ui.position_slider.value())

    def __on_slider_action(self) -> None:
        """Seek to where a click on the slider's groove or a turn of the wheel took it -- not while the handle is held,
        when every move is an action too and the seek waits for the release."""
        if not self.__scrubbing:
            self.__seek_to(self.__ui.position_slider.sliderPosition())

    # endregion

    # region What it shows

    def __flush(self) -> None:
        """Record where a video that plays is, and write at once what is waiting for the recorder."""
        player, key = self.__player, self.__key
        if (
            self.__session is Session.PLAY
            and player is not None
            and key is not None
            and self.__ready
            and self.__state != QMediaPlayer.PlaybackState.StoppedState
        ):
            self.__recorder.position(key, player.position() / 1000, self.__duration_seconds())
        self.__recorder.flush()

    def __duration_seconds(self) -> float | None:
        """The video's length.

        :returns: the length in seconds, or ``None`` while it is not known.
        """
        return self.__duration_ms / 1000 if self.__duration_ms > 0 else None

    @staticmethod
    def __offers_libraries() -> bool:
        """Whether an external FFmpeg's libraries could still be set up for this run.

        :returns: ``True`` where the tool exists and this run is not already using it.
        """
        return FFMPEG_LIBRARIES_TOOL.ID in EXTERNAL_TOOLS and shared_playback_libraries().loaded_from is None

    def __show_playing(self, playing: bool) -> None:
        """Give the play button the glyph of what pressing it does.

        :param playing: whether a video plays now.
        """
        glyph = PLAYER_PAUSE_GLYPH if playing else PLAYER_PLAY_GLYPH
        action = self.__ui.play_pause_action
        action.setIcon(themed_glyph_icon(glyph.codepoint, glyph.family, QPalette.ColorRole.Text))
        action.setText("Pause" if playing else "Play")

    def __show_position(self, position_ms: int) -> None:
        """Show where the video is on the slider and the clock.

        :param position_ms: the position.
        """
        if not self.__scrubbing:
            self.__ui.position_slider.setValue(position_ms)
        self.__show_time(position_ms)

    def __show_time(self, position_ms: int) -> None:
        """Show the position, and the length where it is known, as a clock.

        :param position_ms: where the video is.
        """
        clock = self.__clock(position_ms)
        if self.__duration_ms > 0:
            clock = f"{clock} / {self.__clock(self.__duration_ms)}"
        self.__ui.time_label.setText(clock)

    @staticmethod
    def __clock(milliseconds: int) -> str:
        """Spell a time as ``m:ss``, or ``h:mm:ss`` from an hour on.

        :param milliseconds: the time.
        :returns: the clock text.
        """
        minutes, seconds = divmod(max(milliseconds, 0) // 1000, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"

    def __update_actions(self) -> None:
        """Enable the actions a selected video allows: none while nothing is, and no step past either end."""
        ui = self.__ui
        playlist = self.__playlist
        selected = self.__key is not None
        for action in (ui.play_pause_action, ui.back_action, ui.forward_action, ui.to_start_action, ui.to_end_action):
            action.setEnabled(selected)
        ui.previous_action.setEnabled(playlist is not None and playlist.has_previous)
        ui.next_action.setEnabled(playlist is not None and playlist.has_next)

    # endregion
