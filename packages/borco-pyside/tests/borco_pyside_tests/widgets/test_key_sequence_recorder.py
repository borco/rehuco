"""Tests for KeySequenceRecorder: what `QKeySequenceEdit` cannot record, a keypad key and a lone Esc."""

from borco_pyside.widgets import KeySequenceRecorder, key_sequence_recorder
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent, QKeyEvent, QKeySequence
from PySide6.QtWidgets import QApplication
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot


@fixture
def recorder(qtbot: QtBot, mocker: MockerFixture) -> KeySequenceRecorder:
    """A recorder that settles after 10 ms instead of a second.

    :param qtbot: the widget-owning fixture.
    :param mocker: patches the settle delay.
    :returns: the recorder, not yet started.
    """
    mocker.patch.object(key_sequence_recorder, "SETTLE_DELAY_MS", 10)
    widget = KeySequenceRecorder()
    qtbot.addWidget(widget)
    return widget


def press(
    recorder: KeySequenceRecorder,
    key: Qt.Key,
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier,
) -> None:
    """Deliver one key press straight to the recorder.

    :param recorder: the receiver.
    :param key: the key.
    :param modifiers: the modifiers held.
    """
    QApplication.sendEvent(recorder, QKeyEvent(QEvent.Type.KeyPress, key, modifiers))


def record(qtbot: QtBot, recorder: KeySequenceRecorder, *chords: tuple[Qt.Key, Qt.KeyboardModifier]) -> QKeySequence:
    """Start a recording, press ``chords`` and wait for it to settle.

    :param qtbot: waits on the signal.
    :param recorder: the recorder.
    :param chords: each chord's key and modifiers.
    :returns: what was recorded.
    """
    recorder.start()
    with qtbot.waitSignal(recorder.recorded, timeout=2000) as blocker:
        for key, modifiers in chords:
            press(recorder, key, modifiers)
    args = blocker.args
    assert args is not None
    sequence: QKeySequence = args[0]
    return sequence


def test_a_keypad_key_is_distinct_from_the_plain_one(qtbot: QtBot, recorder: KeySequenceRecorder) -> None:
    """The keypad modifier is kept, so keypad 5 is not 5.

    **Test steps:**

    * record a plain 5, then a keypad 5
    * verify the sequences differ and the keypad one reads ``Num+5``
    """
    plain = record(qtbot, recorder, (Qt.Key.Key_5, Qt.KeyboardModifier.NoModifier))
    keypad = record(qtbot, recorder, (Qt.Key.Key_5, Qt.KeyboardModifier.KeypadModifier))

    assert plain.toString(QKeySequence.SequenceFormat.PortableText) == "5"
    assert keypad.toString(QKeySequence.SequenceFormat.PortableText) == "Num+5"
    assert keypad != plain


def test_esc_is_recorded_as_a_key(qtbot: QtBot, recorder: KeySequenceRecorder) -> None:
    """Esc records instead of cancelling.

    **Test steps:**

    * record Esc
    * verify the sequence is ``Esc``
    """
    sequence = record(qtbot, recorder, (Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))

    assert sequence.toString(QKeySequence.SequenceFormat.PortableText) == "Esc"


def test_a_bare_modifier_is_ignored(qtbot: QtBot, recorder: KeySequenceRecorder) -> None:
    """A modifier press alone adds no chord, and the next key carries it.

    **Test steps:**

    * press Ctrl alone, then Ctrl+K
    * verify only ``Ctrl+K`` was recorded
    """
    sequence = record(
        qtbot,
        recorder,
        (Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier),
        (Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier),
    )

    assert sequence.toString(QKeySequence.SequenceFormat.PortableText) == "Ctrl+K"


def test_the_fourth_chord_settles_at_once(qtbot: QtBot, recorder: KeySequenceRecorder, mocker: MockerFixture) -> None:
    """A full sequence does not wait for the settle delay.

    **Test steps:**

    * make the settle delay far longer than the test waits
    * press four chords
    * verify the recording was emitted anyway, holding all four
    """
    mocker.patch.object(key_sequence_recorder, "SETTLE_DELAY_MS", 60_000)
    recorder.start()
    with qtbot.waitSignal(recorder.recorded, timeout=500) as blocker:
        for key in (Qt.Key.Key_A, Qt.Key.Key_B, Qt.Key.Key_C, Qt.Key.Key_D):
            press(recorder, key)

    args = blocker.args
    assert args is not None
    recorded: QKeySequence = args[0]
    assert recorded.count() == 4
    assert not recorder.is_recording


def test_a_second_click_cancels_and_shows_the_sequence_again(qtbot: QtBot, recorder: KeySequenceRecorder) -> None:
    """Clicking a recording button cancels it, and the button reads its own sequence again.

    **Test steps:**

    * give the button a sequence, click it, press a key, click it again
    * verify ``cancelled`` fired, ``recorded`` never did, and the text is the sequence's
    """
    recorded: list[QKeySequence] = []
    recorder.recorded.connect(recorded.append)
    recorder.sequence = QKeySequence("Ctrl+O")
    recorder.click()
    assert recorder.is_recording
    press(recorder, Qt.Key.Key_A)

    with qtbot.waitSignal(recorder.cancelled, timeout=500):
        recorder.click()
    qtbot.wait(50)

    assert not recorded
    assert not recorder.is_recording
    assert recorder.text() == QKeySequence("Ctrl+O").toString(QKeySequence.SequenceFormat.NativeText)


def test_a_recording_is_reported_not_adopted(qtbot: QtBot, recorder: KeySequenceRecorder) -> None:
    """What was pressed is emitted, and the button keeps showing its own sequence until its owner sets one.

    **Test steps:**

    * give the button a sequence and record another
    * verify the recorded one was emitted and ``sequence`` is unchanged
    """
    recorder.sequence = QKeySequence("Ctrl+O")

    sequence = record(qtbot, recorder, (Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier))

    assert sequence == QKeySequence("Ctrl+P")
    assert recorder.sequence == QKeySequence("Ctrl+O")


def test_an_empty_button_reads_none(recorder: KeySequenceRecorder) -> None:
    """With no sequence the button says so.

    **Test steps:**

    * read a fresh button's text
    """
    assert recorder.text() == "None"


def test_losing_focus_cancels(qtbot: QtBot, recorder: KeySequenceRecorder) -> None:
    """Focus-out ends the recording like Cancel.

    **Test steps:**

    * start, then send a focus-out
    * verify ``cancelled`` fired
    """
    recorder.start()

    with qtbot.waitSignal(recorder.cancelled, timeout=500):
        QApplication.sendEvent(recorder, QFocusEvent(QEvent.Type.FocusOut, Qt.FocusReason.OtherFocusReason))


def test_a_shortcut_override_is_accepted_while_recording(recorder: KeySequenceRecorder) -> None:
    """The app's shortcuts are kept from stealing a key being recorded.

    **Test steps:**

    * send a ``ShortcutOverride`` while idle, then while recording
    * verify it is accepted only while recording
    """
    idle = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    idle.ignore()
    recorder.event(idle)
    assert not idle.isAccepted()

    recorder.start()
    recording = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    recording.ignore()
    recorder.event(recording)

    assert recording.isAccepted()


def test_cancelling_an_idle_button_does_nothing(recorder: KeySequenceRecorder) -> None:
    """``cancel`` is for a recording in progress; idle it emits nothing.

    **Test steps:**

    * cancel a button that is not recording
    * verify no ``cancelled`` signal and it is still idle
    """
    cancelled: list[bool] = []
    recorder.cancelled.connect(lambda: cancelled.append(True))

    recorder.cancel()

    assert not cancelled
    assert not recorder.is_recording


def test_a_key_release_while_recording_is_swallowed(recorder: KeySequenceRecorder) -> None:
    """The release that follows a recorded press must not reach the button, where Space would click it.

    **Test steps:**

    * start recording and send a Space release
    * verify the event was consumed and the button is still recording
    """
    recorder.start()

    consumed = recorder.event(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))

    assert consumed
    assert recorder.is_recording
