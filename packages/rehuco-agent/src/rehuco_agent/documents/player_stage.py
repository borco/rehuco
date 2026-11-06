"""The player's stage -- the picture and the panels beside it -- and what is done to it as a whole: clicked, maximized,
its picture shown, its split remembered ([[plugins#player-maximized]], #574)."""

from typing import Final

import cbor2
from PySide6.QtCore import QByteArray, QObject, QSize, Qt, QTimer
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QWidget
from rehuco_core import SubtitleChoice

from ..fields.widgets.overlay_surface import OverlayMode
from .player_clicks import PlayerClicks
from .player_info import player_info_text
from .player_overlay import PlayerMaximizer
from .player_panels import PlayerPanels
from .player_playlist import PlayerPlaylist
from .player_view_ui import Ui_PlayerView
from .rehu_document_model import RehuDocumentModel

VIDEO_STATE_KEY: Final = "video"
INFO_STATE_KEY: Final = "info"
TREE_STATE_KEY: Final = "tree"
NOTES_STATE_KEY: Final = "notes"
SUBTITLES_STATE_KEY: Final = "subtitles"
"""The rest of the player's entry: the video it is on, and which of the panels beside the picture show (#576)."""

STAGE_STATE_KEY: Final = "stage_split"
"""Where the split of the tree, the picture and the right column is kept in the player's entry of the document's layout.
It was ``stage`` while the splitter held two children; that entry is ignored. The right column's own divider does not
drag, so there is nothing of it to keep."""

FRAME_TOLERANCE_MS: Final = 1000
"""How far from where a video was left a frame may be and still be the one to show it as."""

REVEAL_TIMEOUT_MS: Final = 3000
"""How long Qt's video widget may keep its last frame over a video that plays and gives no frame of where it is: then
every frame is handed on as it comes, as a paused load gives up on its frame after as long."""


class PlayerStage(QObject):  # pylint: disable=too-many-instance-attributes
    """The part of `PlayerView` that moves when it is maximized, and the panels it holds.

    It counts the clicks on the picture (`PlayerClicks`), lifts the stage and the bar over the chosen surface
    (`PlayerMaximizer`), and keeps the info panel beside the picture: hidden until ``I``, then the picture shrinks to
    make room. The panel is told the video's state as it changes and shows the latest whenever it is shown.

    **What the picture shows** is its too. libvlc's surface is shown the moment a video plays, since it resumes on the
    frame it paused on, and a pause shows the still, which is that frame drawn the same way.

    **Qt's frames reach its video widget through here** (:meth:`offer_frame`): the player decodes into the view's own
    sink, and the stage hands each frame on, or holds the last. A pause stops handing them on and lets the widget keep
    its last frame, drawn by the same renderer -- swapping to a still painted by Qt's own scaling shifted the picture by
    about a pixel and flashed as the native window went (seen by the owner, #574). A resume opens the file again,
    which takes about 200 ms, and hands frames on again only from one of where the video is: stamped within
    :data:`FRAME_TOLERANCE_MS` of the position asked for, or any frame once the player has reported that position, for
    a file whose frame times run on another clock than its positions (an MPEG-TS stream's do), or every frame
    :data:`REVEAL_TIMEOUT_MS` after play, for a file that gives neither.

    :param ui: the player's generated UI.
    :param model: the document, read for the pixel size a Measure recorded.
    :param document: the open document the player belongs to.
    :param click_ms: how long a click waits for a second one; the system's when ``None``.
    :param parent: the player, which owns this.
    """

    def __init__(
        self,
        ui: Ui_PlayerView,
        model: RehuDocumentModel,
        document: QWidget,
        click_ms: int | None,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.__ui: Final = ui
        self.__model: Final = model
        self.__state: tuple[PlayerPlaylist | None, int, int, bool] = (None, 0, 0, False)
        """The latest video state :meth:`show_info` was given: the playlist, the length, the position, and whether
        libvlc draws."""
        self.__measured: tuple[str, QSize | None] | None = None
        """The pixel size a Measure recorded for a video, read once as the video is selected: the record's ``videos``
        map is parsed whole at each read, the panel is refreshed at every position, and a size is the file's -- once a
        frame shows, the frame says it, and a file that changed is loaded again (owner)."""
        self.__awaited_ms: int | None = None
        """The position Qt's video widget is to show a frame of before it is shown, or ``None`` while nothing waits."""
        self.__reported_ms: int | None = None
        """The position the player reported last since the wait began, or ``None`` for none yet."""
        self.__forwarding = False
        """Whether Qt's frames are handed on to its video widget as they come."""
        self.__latest: QVideoFrame | None = None
        """The newest of Qt's frames offered since the video was selected, handed on or not."""
        self.__player: Final = parent
        self.panels: Final = PlayerPanels(ui, parent.actions, self.focus_player, self)
        self.clicks: Final = PlayerClicks((ui.video_widget, ui.vlc_surface, ui.still_widget), click_ms, self)
        self.maximizer: Final = PlayerMaximizer(
            ui.main_layout, (ui.stage_splitter, ui.controls_bar), ui.restore_button, document, parent
        )
        self.__reveal_timer: Final = QTimer(self)
        self.__reveal_timer.setObjectName("reveal_timer")
        self.__reveal_timer.setSingleShot(True)
        self.__reveal_timer.setInterval(REVEAL_TIMEOUT_MS)
        self.__reveal_timer.timeout.connect(self.__reveal)
        ui.side_splitter.hide()
        ui.info_panel.hide()
        ui.info_action.toggled.connect(self.__on_info_toggled)
        ui.restore_action.triggered.connect(self.maximizer.restore)

    @property
    def mode(self) -> OverlayMode | None:
        """The surface the player is maximized over, or ``None`` while it is in its dock."""
        return self.maximizer.mode

    def focus_player(self) -> None:
        """Put the keyboard on the player, or on the overlay it is maximized in: where its keys answer."""
        overlay = self.maximizer.overlay
        (overlay if overlay is not None else self.__player).setFocus(Qt.FocusReason.OtherFocusReason)

    # region The picture

    def show_still(self) -> None:
        """Show the still, hand no frame on, and take the video widget's frame away: another video's must never come up
        as this one's picture."""
        self.hold()
        self.__latest = None
        self.__ui.video_widget.videoSink().setVideoFrame(QVideoFrame())
        self.__ui.surface_stack.setCurrentWidget(self.__ui.still_widget)

    def hold(self) -> None:
        """Hand no more of Qt's frames on: its video widget keeps the last it was given, as a pause under Qt shows.

        A widget given nothing yet -- paused before a frame of the position arrived -- shows the newest frame decoded
        instead, from wherever in the video it is: a picture over none.
        """
        self.__forwarding = False
        self.__awaited_ms = None
        self.__reveal_timer.stop()
        if self.__latest is not None and not self.__ui.video_widget.videoSink().videoFrame().isValid():
            self.__ui.video_widget.videoSink().setVideoFrame(self.__latest)
            self.__ui.surface_stack.setCurrentWidget(self.__ui.video_widget)

    def show_frame(self, frame: QVideoFrame) -> None:
        """Show one of Qt's frames and hold it -- the frame a paused load opened the file for.

        :param frame: the frame.
        """
        self.hold()
        self.__ui.video_widget.videoSink().setVideoFrame(frame)
        self.__ui.surface_stack.setCurrentWidget(self.__ui.video_widget)

    def show_engine(self, surface: QWidget, vlc: bool, position_ms: int) -> None:
        """Show the engine's surface as a video starts to play: libvlc's at once; Qt's frames handed on from one of
        where the video is (:meth:`offer_frame`, :meth:`note_position`), what the picture shows held until then.

        :param surface: the page the engine draws on.
        :param vlc: whether the engine is libvlc.
        :param position_ms: where the video plays from.
        """
        if vlc:
            self.__ui.surface_stack.setCurrentWidget(surface)
            return
        self.__forwarding = False
        self.__awaited_ms = position_ms
        self.__reported_ms = None
        self.__reveal_timer.start()

    def offer_frame(self, frame: QVideoFrame) -> None:
        """Hand a frame of Qt's on to its video widget while frames are handed on, or when it is the one waited for.

        :param frame: a valid frame of the ready video.
        """
        self.__latest = frame
        awaited, reported = self.__awaited_ms, self.__reported_ms
        if awaited is not None:
            landed = reported is not None and abs(reported - awaited) <= FRAME_TOLERANCE_MS
            if self.at_position(frame, awaited) or landed:
                self.__reveal()
        if self.__forwarding:
            self.__ui.video_widget.videoSink().setVideoFrame(frame)

    def note_position(self, position_ms: int) -> None:
        """Take the position the player reports: while a frame is waited for, one at the position asked for means the
        seek has landed and the next frame is of it, whatever time it carries.

        Not the report of the position asked for itself: Qt reports a seek's target the moment it is asked, 110 ms
        before any frame of it (measured), and a frame from before the seek could still come meanwhile. What playback
        then reports drifts off the exact target.

        :param position_ms: where the player says it is.
        """
        if position_ms != self.__awaited_ms:
            self.__reported_ms = position_ms

    @staticmethod
    def at_position(frame: QVideoFrame, position_ms: int) -> bool:
        """Whether a frame is of a position, rather than one from before a seek to it took hold.

        :param frame: a valid frame.
        :param position_ms: the position.
        :returns: ``True`` within :data:`FRAME_TOLERANCE_MS` of it, or for a frame with no time.
        """
        start_ms = frame.startTime() / 1000
        return start_ms < 0 or abs(start_ms - position_ms) <= FRAME_TOLERANCE_MS

    def __reveal(self) -> None:
        """Hand Qt's frames on to its video widget from now, and show it."""
        self.__awaited_ms = None
        self.__reveal_timer.stop()
        self.__forwarding = True
        self.__ui.surface_stack.setCurrentWidget(self.__ui.video_widget)

    # endregion

    # region The info panel

    def show_info(self, playlist: PlayerPlaylist | None, length_ms: int, position_ms: int, vlc: bool) -> None:
        """Take the video's state, and show it in the info panel when the panel is shown.

        :param playlist: the playlist on the video loaded, or ``None`` when none is.
        :param length_ms: the video's length; ``0`` when it is not known.
        :param position_ms: where the video is.
        :param vlc: whether libvlc draws the picture, whose frame then gives its size.
        """
        self.__state = (playlist, length_ms, position_ms, vlc)
        if self.__ui.info_panel.isHidden():
            return
        self.__ui.info_panel.setText(
            player_info_text(playlist, self.__pixel_size(playlist, vlc), length_ms, position_ms)
            if playlist is not None
            else ""
        )
        # a longer key can wrap to another line
        self.panels.fit_info()

    def __pixel_size(self, playlist: PlayerPlaylist, vlc: bool) -> QSize | None:
        """The picture's size: what a Measure recorded, read once as the video is selected, else the frame the engine
        shows.

        :param playlist: the playlist on the video loaded.
        :param vlc: whether libvlc draws the picture.
        :returns: the size, or ``None`` when neither knows it.
        """
        key = playlist.current.key
        if self.__measured is None or self.__measured[0] != key:
            facts = self.__model.measured_videos().get(key)
            size = QSize(facts.width, facts.height) if facts is not None and facts.width and facts.height else None
            self.__measured = (key, size)
        if self.__measured[1] is not None:
            return self.__measured[1]
        if vlc:
            frame = self.__ui.vlc_surface.frame
            return frame.size() if frame is not None else None
        return self.__ui.video_widget.videoSink().videoSize()

    def __on_info_toggled(self, shown: bool) -> None:
        """Show or hide the info beside the picture, which shrinks or grows to fit.

        :param shown: whether it is shown.
        """
        self.__ui.info_panel.setVisible(shown)
        self.panels.update_side()
        self.show_info(*self.__state)

    # endregion

    def save_state(self, video: str | None, subtitles: SubtitleChoice | None = None) -> bytes:
        """Encode where the stage splits between the picture and the panels beside it, which of them show, the
        video the player is on, and what the reader chose of the subtitles (#618).

        :param video: the video's content key, or ``None`` for none.
        :param subtitles: the choice, or ``None`` while none was made, which the settings' default stands for.
        :returns: the state, restorable by :meth:`restore_state`.
        """
        ui = self.__ui
        state: dict[str, object] = {
            STAGE_STATE_KEY: bytes(ui.stage_splitter.saveState().data()),
            VIDEO_STATE_KEY: video,
            INFO_STATE_KEY: ui.info_action.isChecked(),
            TREE_STATE_KEY: ui.tree_action.isChecked(),
            NOTES_STATE_KEY: ui.notes_action.isChecked(),
        }
        if subtitles is not None:
            state[SUBTITLES_STATE_KEY] = subtitles.to_state()
        return cbor2.dumps(state)

    @staticmethod
    def subtitles_in(state: bytes) -> SubtitleChoice | None:
        """The subtitle choice :meth:`save_state` encoded.

        :param state: the blob.
        :returns: the choice, or ``None`` when there is none or the blob cannot be read.
        """
        try:
            loaded = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return None
        return SubtitleChoice.from_state(loaded.get(SUBTITLES_STATE_KEY)) if isinstance(loaded, dict) else None

    def restore_state(self, state: bytes) -> str | None:
        """Restore what :meth:`save_state` encoded: the panels first, since a splitter gives sizes only to what shows.

        :param state: the blob; one that cannot be read leaves everything as it is, and each value costs only itself.
        :returns: the video the player was on, or ``None`` for none.
        """
        try:
            loaded = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return None
        if not isinstance(loaded, dict):
            return None
        ui = self.__ui
        for key, action in (
            (INFO_STATE_KEY, ui.info_action),
            (TREE_STATE_KEY, ui.tree_action),
            (NOTES_STATE_KEY, ui.notes_action),
        ):
            shown = loaded.get(key)
            if isinstance(shown, bool):
                action.setChecked(shown)
        stage = loaded.get(STAGE_STATE_KEY)
        if isinstance(stage, bytes):
            ui.stage_splitter.restoreState(QByteArray(stage))
        video = loaded.get(VIDEO_STATE_KEY)
        return video if isinstance(video, str) and video else None
