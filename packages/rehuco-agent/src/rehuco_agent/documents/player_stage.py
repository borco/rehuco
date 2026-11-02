"""The player's stage -- the picture and the panels beside it -- and what is done to it as a whole: clicked, maximized,
its picture shown, its split remembered ([[plugins#player-maximized]], #574)."""

from typing import Final

import cbor2
from PySide6.QtCore import QByteArray, QObject, QSize, QTimer
from PySide6.QtMultimedia import QVideoFrame
from PySide6.QtWidgets import QWidget

from ..fields.widgets.overlay_surface import OverlayMode
from .player_clicks import PlayerClicks
from .player_info import player_info_text
from .player_overlay import PlayerMaximizer
from .player_playlist import PlayerPlaylist
from .player_view_ui import Ui_PlayerView
from .rehu_document_model import RehuDocumentModel

STAGE_STATE_KEY: Final = "stage"
"""Where the stage's split is kept in the player's entry of the document's layout."""

FRAME_TOLERANCE_MS: Final = 1000
"""How far from where a video was left a frame may be and still be the one to show it as."""

REVEAL_TIMEOUT_MS: Final = 3000
"""How long the still may stay up over a video that plays and gives no frame of where it is: then the picture is shown
as it is, as a paused load gives up on its frame after as long."""


class PlayerStage(QObject):  # pylint: disable=too-many-instance-attributes
    """The part of `PlayerView` that moves when it is maximized, and the panels it holds.

    It counts the clicks on the picture (`PlayerClicks`), lifts the stage and the bar over the chosen surface
    (`PlayerMaximizer`), and keeps the info panel beside the picture: hidden until ``I``, then the picture shrinks to
    make room. The panel is told the video's state as it changes and shows the latest whenever it is shown.

    **Which page the picture shows** is its too. libvlc's surface is shown the moment a video plays, since it resumes
    on the frame it paused on. Qt's video widget is black until its first frame -- a paused video's file was let go,
    and opening it again takes about 200 ms (measured, #574) -- so the still stays up until the widget has a frame
    of where the video is: one Qt stamps within :data:`FRAME_TOLERANCE_MS` of the position asked for, or any frame
    once the player has reported that position, for a file whose frame times run on another clock than its
    positions (an MPEG-TS stream's do), or :data:`REVEAL_TIMEOUT_MS` after play for a file that gives neither.

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
        """The pixel size a Measure recorded for a video, read once per video: the record's ``videos`` map is parsed
        whole at each read, and the panel is refreshed at every position."""
        self.__awaited_ms: int | None = None
        """The position Qt's video widget is to show a frame of before it is shown, or ``None`` while nothing waits."""
        self.__reported_ms: int | None = None
        """The position the player reported last since the wait began, or ``None`` for none yet."""
        self.clicks: Final = PlayerClicks((ui.video_widget, ui.vlc_surface, ui.still_widget), click_ms, self)
        self.maximizer: Final = PlayerMaximizer(
            ui.main_layout, (ui.stage_splitter, ui.controls_bar), ui.restore_button, document, parent
        )
        self.clicks.double_clicked.connect(self.maximizer.toggle)
        self.__reveal_timer: Final = QTimer(self)
        self.__reveal_timer.setObjectName("reveal_timer")
        self.__reveal_timer.setSingleShot(True)
        self.__reveal_timer.setInterval(REVEAL_TIMEOUT_MS)
        self.__reveal_timer.timeout.connect(self.__reveal)
        ui.side_splitter.hide()
        ui.info_action.toggled.connect(self.__on_info_toggled)
        ui.restore_action.triggered.connect(self.maximizer.restore)

    @property
    def mode(self) -> OverlayMode | None:
        """The surface the player is maximized over, or ``None`` while it is in its dock."""
        return self.maximizer.mode

    # region The picture

    def show_still(self) -> None:
        """Show the still, and wait for no frame."""
        self.__awaited_ms = None
        self.__reveal_timer.stop()
        self.__ui.surface_stack.setCurrentWidget(self.__ui.still_widget)

    def show_engine(self, surface: QWidget, vlc: bool, position_ms: int) -> None:
        """Show the engine's surface as a video starts to play: libvlc's at once, Qt's once it has a frame of where the
        video is (:meth:`offer_frame`, :meth:`note_position`), the still up until then.

        :param surface: the page the engine draws on.
        :param vlc: whether the engine is libvlc.
        :param position_ms: where the video plays from.
        """
        if vlc:
            self.__ui.surface_stack.setCurrentWidget(surface)
            return
        self.__awaited_ms = position_ms
        self.__reported_ms = None
        self.__reveal_timer.start()

    def offer_frame(self, frame: QVideoFrame) -> None:
        """Show Qt's video widget, when a frame of the video playing is the one waited for.

        :param frame: a valid frame of the ready video.
        """
        awaited, reported = self.__awaited_ms, self.__reported_ms
        if awaited is None:
            return
        start_ms = frame.startTime() / 1000
        landed = reported is not None and abs(reported - awaited) <= FRAME_TOLERANCE_MS
        if start_ms < 0 or abs(start_ms - awaited) <= FRAME_TOLERANCE_MS or landed:
            self.__reveal()

    def note_position(self, position_ms: int) -> None:
        """Take the position the player reports: while a frame is waited for, one at the position asked for means the
        seek has landed and the next frame is of it, whatever time it carries.

        :param position_ms: where the player says it is.
        """
        self.__reported_ms = position_ms

    def __reveal(self) -> None:
        """Show Qt's video widget, and wait for no frame."""
        self.__awaited_ms = None
        self.__reveal_timer.stop()
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
        if self.__ui.side_splitter.isHidden():
            return
        if playlist is None:
            self.__ui.info_panel.setText("")
            return
        self.__ui.info_panel.setText(
            player_info_text(playlist, self.__pixel_size(playlist, vlc), length_ms, position_ms)
        )

    def __pixel_size(self, playlist: PlayerPlaylist, vlc: bool) -> QSize | None:
        """The picture's size: what a Measure recorded, read once per video, else the frame the engine shows.

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
        self.__ui.side_splitter.setVisible(shown)
        self.show_info(*self.__state)

    # endregion

    def save_state(self) -> bytes:
        """Encode where the stage splits between the picture and the panels beside it.

        :returns: the state, restorable by :meth:`restore_state`.
        """
        return cbor2.dumps({STAGE_STATE_KEY: bytes(self.__ui.stage_splitter.saveState().data())})

    def restore_state(self, state: bytes) -> None:
        """Restore the split :meth:`save_state` encoded.

        :param state: the blob; one that cannot be read, or holds no split, leaves the split as it is.
        """
        try:
            loaded = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return
        stage = loaded.get(STAGE_STATE_KEY) if isinstance(loaded, dict) else None
        if isinstance(stage, bytes):
            self.__ui.stage_splitter.restoreState(QByteArray(stage))
