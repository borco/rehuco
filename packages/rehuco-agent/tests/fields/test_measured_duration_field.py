"""Tests for MeasuredDurationField: the formatted viewer, the MeasuredDurationEdit-backed editor
binding, and the off-thread measurement behind its compute/apply row (#224).
"""

# the viewer is the same formatted label the plain duration field shows, and the measure half is the
# contract the size field's tests also pin -- the two rows are one `MeasuredValueEdit`
# pylint: disable=duplicate-code

from threading import Event, get_ident

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import MeasuredDurationEdit

from fields.field_testers import MeasuredDurationFieldTester as MeasuredDurationField
from fields.widgets.measure_row_internals import (
    internal_apply_button,
    internal_compute_button,
    internal_computed_label,
    internal_editor,
)


def compute(qtbot: QtBot, editor: MeasuredDurationEdit) -> None:
    """Press ``Compute`` and wait for the scan to report back.

    The measurement runs on a worker thread (#224), so the result is not on screen when the click
    returns -- every test that presses Compute goes through here rather than each spelling the wait.

    :param qtbot: the pytest-qt bot driving the event loop while the scan runs.
    :param editor: the row to compute on.
    """
    internal_compute_button(editor).click()
    qtbot.waitUntil(lambda: not editor.busy)


def test_the_viewer_shows_and_tracks_the_formatted_duration(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer is the formatted label the plain duration field gives -- measuring changes the editor,
    never how a duration reads ([[field-schema#duration-format]]).

    **Test steps:**

    * build an ``original_duration`` viewer over an unset model
    * verify the label starts empty
    * change ``model.original_duration`` and verify the label updates live, formatted
    """
    field = MeasuredDurationField("original_duration")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    model.original_duration = 8100
    assert viewer.text() == "2h 15m"


def test_the_editor_is_a_measure_row_seeded_from_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor is a ``MeasuredDurationEdit`` seeded with the model's current value, with nothing
    computed yet.

    **Test steps:**

    * seed the model with a duration, then build the ``original_duration`` editor
    * verify the editor holds that value and has an empty computed readout
    """
    model.original_duration = 8100
    field = MeasuredDurationField("original_duration")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    assert editor.value == 8100
    assert internal_editor(editor).value == 8100
    assert internal_computed_label(editor).text() == ""


def test_the_editor_writes_through_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Changing the editor's value writes through to the model.

    **Test steps:**

    * build the editor and set its ``value``
    * verify ``model.original_duration`` follows
    """
    field = MeasuredDurationField("original_duration")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    editor.value = 4050

    assert model.original_duration == 4050


def test_the_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor.

    **Test steps:**

    * build the editor
    * change ``model.original_duration`` directly (as another surface would)
    * verify the editor's ``value`` and its duration editor follow
    """
    field = MeasuredDurationField("original_duration")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    model.original_duration = 4050

    assert editor.value == 4050
    assert internal_editor(editor).value == 4050


def test_compute_fills_the_readout_without_touching_the_value_or_dirtying(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Compute measures and shows, and stops there: the stored duration and the document's dirty flag
    are untouched (#224).

    **Test steps:**

    * build the editor over a stored ``8100`` with a measurement that finds ``4050``
    * press Compute
    * verify the readout shows ``4050`` while the model still reads ``8100`` and the document is clean
    """
    model.original_duration = 8100
    model.dirty = False
    field = MeasuredDurationField("original_duration", measure=lambda: 4050)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == "4050"
    assert model.original_duration == 8100
    assert model.dirty is False


def test_nothing_is_measured_until_compute_is_pressed(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Building the editor measures nothing: opening a document must not silently rewrite -- or even
    read -- what is on disk. It matters most on ``original_duration``, whose stored value is the
    denominator for *how much is left* ([[field-schema#duration-size]]).

    **Test steps:**

    * build the editor over a measurement that records each call
    * verify it was never called, and the computed readout is empty
    """
    calls: list[None] = []

    def measure() -> int:
        calls.append(None)
        return 4050

    field = MeasuredDurationField("original_duration", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    assert not calls
    assert internal_computed_label(editor).text() == ""


def test_compute_measures_afresh_on_every_press(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Each press asks again -- the duration is read from disk at that moment, never cached from the
    last press or from form construction.

    **Test steps:**

    * build the editor over a measurement whose answer changes between presses
    * press Compute twice and verify the readout followed the second answer
    """
    answers = iter([4050, 8100])
    field = MeasuredDurationField("original_duration", measure=lambda: next(answers))
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "4050"

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "8100"


def test_the_scan_runs_off_the_gui_thread(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The measurement runs on a worker thread: a header read per video over hundreds of files on an SMB
    mount -- or a subprocess per file with the external backend -- takes seconds, and the window must
    stay responsive for them (#224).

    **Test steps:**

    * build the editor over a measurement that records the thread it ran on
    * press Compute and wait for the result
    * verify it did not run on the thread the test (and the GUI) is on
    """
    gui_thread = get_ident()
    scan_threads: list[int] = []

    def measure() -> int:
        scan_threads.append(get_ident())
        return 4050

    field = MeasuredDurationField("original_duration", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert scan_threads and gui_thread not in scan_threads
    assert editor.computed == 4050


def test_compute_is_disabled_while_a_scan_is_in_flight(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A scan already running cannot be started again, nor its half-finished answer applied (#224).

    **Test steps:**

    * build the editor over a measurement that blocks until the test releases it
    * press Compute and verify the row is busy with both buttons disabled while it hangs
    * release the measurement and verify the row comes back with the result
    """
    release = Event()

    def measure() -> int:
        release.wait(timeout=5)
        return 4050

    field = MeasuredDurationField("original_duration", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    try:
        internal_compute_button(editor).click()

        assert editor.busy is True
        assert not internal_compute_button(editor).isEnabled()
        assert not internal_apply_button(editor).isEnabled()
    finally:
        release.set()

    qtbot.waitUntil(lambda: not editor.busy)
    assert editor.computed == 4050
    assert internal_compute_button(editor).isEnabled()


def test_a_scan_that_raises_gives_the_row_back(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that blows up reports *nothing measured* rather than stranding the row busy with a
    Compute that can never be pressed again.

    **Test steps:**

    * build the editor over a measurement that raises
    * press Compute and wait
    * verify nothing was computed, the stored duration is untouched, and Compute is offered again
    """
    model.original_duration = 8100

    def measure() -> int:
        raise OSError("the mount went away mid-scan")

    field = MeasuredDurationField("original_duration", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert editor.computed is None
    assert model.original_duration == 8100
    assert internal_compute_button(editor).isEnabled()


def test_apply_is_offered_only_when_the_measurement_disagrees(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that agrees with the stored duration leaves nothing to apply.

    **Test steps:**

    * build the editor over a stored ``8100`` with a measurement that also finds ``8100``
    * press Compute and verify apply stays disabled
    """
    model.original_duration = 8100
    field = MeasuredDurationField("original_duration", measure=lambda: 8100)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert not internal_apply_button(editor).isEnabled()


def test_apply_stores_the_measured_duration_and_dirties(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Apply is the only path from a measurement into the document -- and it is an ordinary edit.

    **Test steps:**

    * build the editor over a stale stored ``8100``, compute ``4050``, then press Apply
    * verify the model holds ``4050``, the document's block does too, and the model went dirty
    """
    model.original_duration = 8100
    model.dirty = False
    field = MeasuredDurationField("original_duration", measure=lambda: 4050)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)
    compute(qtbot, editor)

    internal_apply_button(editor).click()

    assert model.original_duration == 4050
    assert model.document.active_field("original_duration") == 4050
    assert model.dirty is True


def test_a_stale_stored_duration_stays_until_apply(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Opening a document whose stored duration disagrees with the disk changes nothing: the
    disagreement is evidence -- videos deleted as they were watched, the very method the ``current_*``
    axis exists for ([[field-schema#duration-size]]) -- and only the user resolves it.

    **Test steps:**

    * build the editor over a stored ``8100`` with a measurement that finds ``4050``
    * verify the model still reads ``8100`` before and after computing
    * apply, and verify only then does it move
    """
    model.original_duration = 8100
    field = MeasuredDurationField("original_duration", measure=lambda: 4050)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)
    assert model.original_duration == 8100

    compute(qtbot, editor)
    assert model.original_duration == 8100

    internal_apply_button(editor).click()
    assert model.original_duration == 4050


def test_an_unmeasurable_document_computes_nothing(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that cannot run -- a document with no path yet, or a probe backend that cannot run
    here at all -- leaves the readout empty and offers nothing to apply, rather than reporting a
    duration of zero it never took.

    **Test steps:**

    * build the editor over a measurement returning ``None`` and press Compute
    * verify the readout is empty, apply is disabled, and the stored duration is untouched
    """
    model.original_duration = 8100
    field = MeasuredDurationField("original_duration", measure=lambda: None)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, MeasuredDurationEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == ""
    assert not internal_apply_button(editor).isEnabled()
    assert model.original_duration == 8100
