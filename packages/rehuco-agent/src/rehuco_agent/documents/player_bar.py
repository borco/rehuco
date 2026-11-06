"""The player's transport bar: what its slider, clock, play glyph and note button show ([[plugins#in-app-player]],
[[plugins#video-notes-dock]])."""

from typing import Final

from borco_pyside.theming import GlyphActionIconThemeHandler, themed_glyph_icon
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QToolButton, QWidget

from ..commands import (
    PLAYER_ADD_NOTE_AT,
    PLAYER_BACK,
    PLAYER_EDIT_NOTES,
    PLAYER_FORWARD,
    PLAYER_INFO,
    PLAYER_NEXT,
    PLAYER_NOTES,
    PLAYER_PLAY_PAUSE,
    PLAYER_PREVIOUS,
    PLAYER_SPEED_DOWN,
    PLAYER_SPEED_UP,
    PLAYER_SUBTITLE_NEXT,
    PLAYER_SUBTITLE_PREVIOUS,
    PLAYER_SUBTITLE_TOGGLE,
    PLAYER_TO_END,
    PLAYER_TO_START,
    PLAYER_TREE,
    PLAYER_VOLUME_DOWN,
    PLAYER_VOLUME_UP,
    shared_command_registry,
)
from ..glyphs import (
    LIGHTBOX_CLOSE_GLYPH,
    PLAYER_BACK_GLYPH,
    PLAYER_FORWARD_GLYPH,
    PLAYER_NEXT_GLYPH,
    PLAYER_PAUSE_GLYPH,
    PLAYER_PLAY_GLYPH,
    PLAYER_PREVIOUS_GLYPH,
)
from .clock_text import clock_text
from .player_view_ui import Ui_PlayerView

ADD_NOTE_AT_TEMPLATE: Final = "Add note at {clock}"
"""The *Add note at* action's text and tooltip, with the clock of where the video is."""

ADD_NOTE_AT_TOOLTIP: Final = "Add a note to the video at {clock}."

SCRUB_INTERVAL_MS: Final = 250
"""The least time between two of a drag's moves reaching the player: a few seeks a second (#613)."""


def bind_player_actions(ui: Ui_PlayerView, player: QWidget) -> None:
    """Bind the player's actions to their commands and keys.

    :param ui: the player's generated UI.
    :param player: the player, whose subtree the keys are scoped to: every document has a player of its own.
    """
    for action, command in (
        (ui.play_pause_action, PLAYER_PLAY_PAUSE),
        (ui.back_action, PLAYER_BACK),
        (ui.forward_action, PLAYER_FORWARD),
        (ui.previous_action, PLAYER_PREVIOUS),
        (ui.next_action, PLAYER_NEXT),
        (ui.to_start_action, PLAYER_TO_START),
        (ui.to_end_action, PLAYER_TO_END),
        (ui.add_note_at_action, PLAYER_ADD_NOTE_AT),
        (ui.info_action, PLAYER_INFO),
        (ui.tree_action, PLAYER_TREE),
        (ui.notes_action, PLAYER_NOTES),
        (ui.edit_notes_action, PLAYER_EDIT_NOTES),
        (ui.volume_up_action, PLAYER_VOLUME_UP),
        (ui.volume_down_action, PLAYER_VOLUME_DOWN),
        (ui.speed_up_action, PLAYER_SPEED_UP),
        (ui.speed_down_action, PLAYER_SPEED_DOWN),
        (ui.subtitle_next_action, PLAYER_SUBTITLE_NEXT),
        (ui.subtitle_previous_action, PLAYER_SUBTITLE_PREVIOUS),
        (ui.subtitle_toggle_action, PLAYER_SUBTITLE_TOGGLE),
    ):
        shared_command_registry().bind(action, command.id)
        player.addAction(action)


class PlayerBar(QObject):
    """The bar under the player's picture, drawn from the player's state and asking it for nothing but a seek.

    The slider follows the position unless the reader holds it; a click on its groove, a turn of the wheel or the
    release of a handle that did not move asks for a seek (:attr:`seek_requested`). **A dragged handle** reports where
    it is at most once per :data:`SCRUB_INTERVAL_MS` (:attr:`scrub_moved`), and where it was let go
    (:attr:`scrub_finished`), so a press with no move opens nothing. The clock reads the position over the length, the
    play action the glyph of what pressing it does, the other transport actions and the restore one their glyphs, and
    the *Add note at* action the clock it would add a note at.

    :param ui: the player's generated UI, whose slider, clock and actions this shows.
    :param parent: the Qt parent, which owns this.
    """

    seek_requested = Signal(int)
    """The reader moved the slider: the position to seek to, in milliseconds."""

    scrub_moved = Signal(int)
    """The reader is dragging the handle: where it is now, in milliseconds, throttled."""

    scrub_finished = Signal(int)
    """The reader let go of a handle they had dragged: where, in milliseconds."""

    def __init__(self, ui: Ui_PlayerView, parent: QObject) -> None:
        super().__init__(parent)
        self.__ui: Final = ui
        self.__scrubbing = False
        self.__moved = False
        """Whether the handle held has moved since it was pressed."""
        self.__kept_ms: int | None = None
        """Where the handle went since the last move reported, while the interval runs."""
        self.__scrub_timer: Final = QTimer(self)
        self.__scrub_timer.setObjectName("scrub_timer")
        self.__scrub_timer.setSingleShot(True)
        self.__scrub_timer.setInterval(SCRUB_INTERVAL_MS)
        self.__scrub_timer.timeout.connect(self.__on_scrub_interval)
        self.__duration_ms = 0
        self.__note_clock = ""
        ui.position_slider.sliderPressed.connect(self.__on_slider_pressed)
        ui.position_slider.sliderMoved.connect(self.__on_slider_moved)
        ui.position_slider.sliderReleased.connect(self.__on_slider_released)
        ui.position_slider.actionTriggered.connect(self.__on_slider_action)
        for action, glyph in (
            (ui.previous_action, PLAYER_PREVIOUS_GLYPH),
            (ui.back_action, PLAYER_BACK_GLYPH),
            (ui.forward_action, PLAYER_FORWARD_GLYPH),
            (ui.next_action, PLAYER_NEXT_GLYPH),
            (ui.restore_action, LIGHTBOX_CLOSE_GLYPH),
        ):
            GlyphActionIconThemeHandler(action, glyph.codepoint, glyph.family)
        for button, action in (
            (ui.previous_button, ui.previous_action),
            (ui.back_button, ui.back_action),
            (ui.play_pause_button, ui.play_pause_action),
            (ui.forward_button, ui.forward_action),
            (ui.next_button, ui.next_action),
            (ui.add_note_button, ui.add_note_at_action),
            (ui.restore_button, ui.restore_action),
        ):
            self.__mirror(button, action)

    @property
    def duration_ms(self) -> int:
        """The video's length as the bar shows it; ``0`` while it is not known."""
        return self.__duration_ms

    def set_duration(self, duration_ms: int) -> None:
        """Fit the slider to the video's length.

        :param duration_ms: the length; ``0`` when it is not known.
        """
        self.__duration_ms = duration_ms
        self.__ui.position_slider.setRange(0, duration_ms)

    def show_bookmarks(self, seconds: list[float]) -> None:
        """Mark the video's bookmarks on the slider.

        :param seconds: the time of each bookmark.
        """
        self.__ui.position_slider.set_marks([round(second * 1000) for second in seconds])

    def show_playing(self, playing: bool) -> None:
        """Give the play button the glyph of what pressing it does.

        :param playing: whether a video plays now.
        """
        glyph = PLAYER_PAUSE_GLYPH if playing else PLAYER_PLAY_GLYPH
        action = self.__ui.play_pause_action
        action.setIcon(themed_glyph_icon(glyph.codepoint, glyph.family, QPalette.ColorRole.Text))
        action.setText("Pause" if playing else "Play")

    def show_position(self, position_ms: int) -> None:
        """Show where the video is on the slider and the clock.

        :param position_ms: the position.
        """
        if not self.__scrubbing:
            self.__ui.position_slider.setValue(position_ms)
        self.show_time(position_ms)

    def show_time(self, position_ms: int) -> None:
        """Show the position, and the length where it is known, as a clock, and name it on the note action.

        :param position_ms: where the video is.
        """
        clock = clock_text(position_ms)
        if clock != self.__note_clock:
            self.__note_clock = clock
            action = self.__ui.add_note_at_action
            action.setText(ADD_NOTE_AT_TEMPLATE.format(clock=clock))
            # the tooltip rides the command's binding, so a plain setToolTip would be undone by the next keymap change
            shared_command_registry().bind(
                action, PLAYER_ADD_NOTE_AT.id, tooltip=ADD_NOTE_AT_TOOLTIP.format(clock=clock)
            )
        if self.__duration_ms > 0:
            clock = f"{clock} / {clock_text(self.__duration_ms)}"
        self.__ui.time_label.setText(clock)

    def update_actions(self, *, selected: bool, has_previous: bool, has_next: bool) -> None:
        """Enable the actions a selected video allows: none while nothing is, and no step past either end.

        :param selected: whether a video is selected.
        :param has_previous: whether there is a video before it.
        :param has_next: whether there is a video after it.
        """
        ui = self.__ui
        for action in (
            ui.play_pause_action,
            ui.back_action,
            ui.forward_action,
            ui.to_start_action,
            ui.to_end_action,
            ui.add_note_at_action,
        ):
            action.setEnabled(selected)
        ui.previous_action.setEnabled(has_previous)
        ui.next_action.setEnabled(has_next)

    @staticmethod
    def __mirror(button: QToolButton, action: QAction) -> None:
        """Make a button press an action and show it, without making it the button's default action.

        A default action is applied to its button again, with a fresh signal connection, every time it changes, and
        the play glyph changes as the player lets go of a video -- the moment Qt Multimedia destroys its renderer on a
        thread of its own, which waits for the GIL while holding a signal-slot mutex. A connection made then, on the GUI
        thread, under the GIL, can need that same mutex: the app hung that way. Here the button is connected once, and
        what changes is only copied.

        :param button: the button.
        :param action: the action it presses and shows.
        """

        def show() -> None:
            """Show the action's icon, text, tooltip and whether it is enabled on the button."""
            button.setIcon(action.icon())
            button.setText(action.text())
            button.setToolTip(action.toolTip())
            button.setEnabled(action.isEnabled())

        button.clicked.connect(action.trigger)
        action.changed.connect(show)
        show()

    def __on_slider_pressed(self) -> None:
        """Stop the slider following the video while the reader holds it."""
        self.__scrubbing = True

    def __on_slider_moved(self, position_ms: int) -> None:
        """Report where the handle is, or keep it for when the interval runs out.

        :param position_ms: where the handle is.
        """
        self.__moved = True
        if self.__scrub_timer.isActive():
            self.__kept_ms = position_ms
        else:
            self.__report_scrub(position_ms)

    def __on_scrub_interval(self) -> None:
        """Report where the handle went during the interval, if it went anywhere."""
        if self.__kept_ms is not None:
            self.__report_scrub(self.__kept_ms)

    def __report_scrub(self, position_ms: int) -> None:
        """Report where the handle is, and start the interval until the next report.

        :param position_ms: where the handle is.
        """
        self.__kept_ms = None
        self.__scrub_timer.start()
        self.scrub_moved.emit(position_ms)

    def __on_slider_released(self) -> None:
        """Say where the reader let go of the slider: the end of a drag, or a seek for a handle that did not move."""
        moved, self.__moved = self.__moved, False
        self.__scrubbing = False
        self.__kept_ms = None
        self.__scrub_timer.stop()
        (self.scrub_finished if moved else self.seek_requested).emit(self.__ui.position_slider.value())

    def __on_slider_action(self) -> None:
        """Ask for a seek to where a click on the slider's groove or a turn of the wheel took it -- not while the
        handle is held, when every move is an action too and the drag reports its own."""
        if not self.__scrubbing:
            self.seek_requested.emit(self.__ui.position_slider.sliderPosition())
