"""The player's transport bar: what its slider, clock, play glyph and note button show ([[plugins#in-app-player]],
[[plugins#video-notes-dock]])."""

from typing import Final

from borco_pyside.theming import themed_glyph_icon
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QToolButton

from ..commands import PLAYER_ADD_NOTE_AT, shared_command_registry
from ..glyphs import PLAYER_PAUSE_GLYPH, PLAYER_PLAY_GLYPH
from .clock_text import clock_text
from .player_view_ui import Ui_PlayerView

ADD_NOTE_AT_TEMPLATE: Final = "Add note at {clock}"
"""The *Add note at* action's text and tooltip, with the clock of where the video is."""

ADD_NOTE_AT_TOOLTIP: Final = "Add a note to the video at {clock}."


class PlayerBar(QObject):
    """The bar under the player's picture, drawn from the player's state and asking it for nothing but a seek.

    The slider follows the position unless the reader holds it; a click on its groove, a turn of the wheel or the
    release of the handle asks for a seek (:attr:`seek_requested`). The clock reads the position over the length, the
    play action the glyph of what pressing it does, and the *Add note at* action the clock it would add a note at.

    :param ui: the player's generated UI, whose slider, clock and actions this shows.
    :param parent: the Qt parent, which owns this.
    """

    seek_requested = Signal(int)
    """The reader moved the slider: the position to seek to, in milliseconds."""

    def __init__(self, ui: Ui_PlayerView, parent: QObject) -> None:
        super().__init__(parent)
        self.__ui: Final = ui
        self.__scrubbing = False
        self.__duration_ms = 0
        self.__note_clock = ""
        ui.position_slider.sliderPressed.connect(self.__on_slider_pressed)
        ui.position_slider.sliderReleased.connect(self.__on_slider_released)
        ui.position_slider.actionTriggered.connect(self.__on_slider_action)
        for button, action in (
            (ui.previous_button, ui.previous_action),
            (ui.back_button, ui.back_action),
            (ui.play_pause_button, ui.play_pause_action),
            (ui.forward_button, ui.forward_action),
            (ui.next_button, ui.next_action),
            (ui.add_note_button, ui.add_note_at_action),
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

    def __on_slider_released(self) -> None:
        """Ask for a seek to where the reader let go of the slider."""
        self.__scrubbing = False
        self.seek_requested.emit(self.__ui.position_slider.value())

    def __on_slider_action(self) -> None:
        """Ask for a seek to where a click on the slider's groove or a turn of the wheel took it -- not while the
        handle is held, when every move is an action too and the seek waits for the release."""
        if not self.__scrubbing:
            self.seek_requested.emit(self.__ui.position_slider.sliderPosition())
