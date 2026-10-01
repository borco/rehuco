"""A key button: shows a key sequence, and records a new one by pressing it -- what `QKeySequenceEdit`
cannot do for a keypad key or a lone Esc."""

from typing import Final, override

from PySide6.QtCore import QEvent, QKeyCombination, Qt, QTimer, Signal
from PySide6.QtGui import QFocusEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QPushButton, QWidget

MODIFIER_KEYS: Final = frozenset(
    {Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_unknown}
)
"""Keys that only change the modifiers of the next press -- never a chord of their own."""

MAX_CHORDS: Final = 4
"""How many chords a sequence holds (`QKeySequence`'s own limit)."""

SETTLE_DELAY_MS: Final = 1000
"""How long after a chord the recording is taken as finished, unless another chord follows."""

NATIVE: Final = QKeySequence.SequenceFormat.NativeText

EMPTY_TEXT: Final = "None"
"""What an idle button with no sequence reads."""

RECORDING_TEXT: Final = "Press keys…"
"""What the button reads while recording, before the first chord."""

RELEVANT_MODIFIERS: Final = (
    Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
    | Qt.KeyboardModifier.MetaModifier
    | Qt.KeyboardModifier.KeypadModifier
)
"""The modifiers a chord keeps. `KeypadModifier` is the one `QKeySequenceEdit` drops: Qt's shortcut map keeps
``Num+5`` and ``5`` apart, so a recorder that loses it records the wrong key."""


class KeySequenceRecorder(QPushButton):
    """A key button: it shows one key sequence, and records a new one when clicked -- up to four chords, Esc
    included.

    Idle, it reads as a push button labelled with :attr:`sequence` (or :data:`EMPTY_TEXT`). A click, or
    :meth:`start`, begins a recording: pressing keys builds the sequence (a bare modifier press is ignored),
    and it settles -- emits :attr:`recorded` -- once no further chord follows within :data:`SETTLE_DELAY_MS`,
    or at once on the fourth. Clicking it again or losing focus ends it with :attr:`cancelled`; Esc cannot,
    since it is a key a user may want to bind. Either way the button goes back to showing :attr:`sequence`:
    what a recording *means* is its owner's to decide, so a recorded sequence is reported, never adopted.

    :param parent: optional Qt parent.
    """

    recorded = Signal(QKeySequence)
    """The recording settled on this sequence."""

    cancelled = Signal()
    """The recording ended without a sequence."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__chords: list[QKeyCombination] = []
        self.__recording = False
        self.__sequence = QKeySequence()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.__settle_timer: Final = QTimer(self)
        self.__settle_timer.setSingleShot(True)
        self.__settle_timer.timeout.connect(self.__settle)
        self.clicked.connect(self.__on_clicked)
        self.__show()

    @property
    def is_recording(self) -> bool:
        """Whether a recording is in progress."""
        return self.__recording

    @property
    def sequence(self) -> QKeySequence:
        """The sequence shown while idle."""
        return self.__sequence

    @sequence.setter
    def sequence(self, sequence: QKeySequence) -> None:
        """Set the sequence shown while idle.

        :param sequence: the sequence; an empty one shows :data:`EMPTY_TEXT`.
        """
        self.__sequence = QKeySequence(sequence)
        self.__show()

    def start(self) -> None:
        """Begin a recording: clear the chords and take focus."""
        self.__chords.clear()
        self.__recording = True
        self.setDown(True)
        self.__show()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def cancel(self) -> None:
        """End a recording in progress on nothing; does nothing while idle."""
        if not self.__recording:
            return
        self.__finish()
        self.cancelled.emit()

    @override
    def event(self, event: QEvent) -> bool:
        if self.__recording and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()  # the app's own shortcuts must not fire on a key being recorded
            return True
        if self.__recording and event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            self.__record(event)
            return True  # before QWidget turns Tab into a focus move, or QPushButton Space into a click
        if self.__recording and event.type() == QEvent.Type.KeyRelease:
            return True
        return super().event(event)

    @override
    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802  (Qt API name)
        super().focusOutEvent(event)
        self.cancel()

    def __on_clicked(self) -> None:
        """Start a recording, or cancel the one in progress."""
        if self.__recording:
            self.cancel()
        else:
            self.start()

    def __record(self, event: QKeyEvent) -> None:
        """Append the chord ``event`` presses, unless it is a bare modifier.

        :param event: the key press.
        """
        event.accept()
        if event.isAutoRepeat() or Qt.Key(event.key()) in MODIFIER_KEYS:
            return
        self.__chords.append(QKeyCombination(event.modifiers() & RELEVANT_MODIFIERS, Qt.Key(event.key())))
        self.__show()
        if len(self.__chords) >= MAX_CHORDS:
            self.__settle()
        else:
            self.__settle_timer.start(SETTLE_DELAY_MS)

    def __show(self) -> None:
        """Show the chords pressed so far while recording, the prompt before any, and the sequence while idle."""
        if self.__recording:
            text = QKeySequence(*self.__chords).toString(NATIVE) if self.__chords else RECORDING_TEXT
        else:
            text = self.__sequence.toString(NATIVE) if not self.__sequence.isEmpty() else EMPTY_TEXT
        self.setText(text)

    def __settle(self) -> None:
        """End the recording on what was pressed; only ever armed by a chord, while recording."""
        sequence = QKeySequence(*self.__chords)
        self.__finish()
        self.recorded.emit(sequence)

    def __finish(self) -> None:
        """Stop recording, and show the idle sequence again."""
        self.__settle_timer.stop()
        self.__recording = False
        self.setDown(False)
        self.__show()
