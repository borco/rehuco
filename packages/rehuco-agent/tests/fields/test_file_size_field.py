"""Tests for FileSizeField: the formatted viewer, the FileSizeEdit-backed editor binding, and the
off-thread measurement behind its compute/apply row.
"""

# the viewer is the same formatted label the field has always shown, so its tests read like the ones
# below the split -- the measure row is where this field and the plain size editor differ
# pylint: disable=duplicate-code

from threading import Event, get_ident

from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import FileSizeEdit

from fields.field_testers import FileSizeFieldTester as FileSizeField
from fields.widgets.test_file_size_edit import (
    internal_apply_button,
    internal_compute_button,
    internal_computed_label,
    internal_spin_box,
    internal_stored_label,
)


def compute(qtbot: QtBot, editor: FileSizeEdit) -> None:
    """Press ``Compute`` and wait for the scan to report back.

    The measurement runs on a worker thread (#223), so the result is not on screen when the click
    returns -- every test that presses Compute goes through here rather than each spelling the wait.

    :param qtbot: the pytest-qt bot driving the event loop while the scan runs.
    :param editor: the row to compute on.
    """
    internal_compute_button(editor).click()
    qtbot.waitUntil(lambda: not editor.busy)


def test_file_size_field_viewer_shows_and_tracks_the_formatted_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer label shows the formatted size and re-renders when the model changes.

    **Test steps:**

    * build an ``original_size`` viewer over a model seeded ``0``
    * verify the label starts empty
    * change ``model.original_size`` and verify the label updates live, formatted
    """
    field = FileSizeField("original_size")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    model.original_size = 5368709120
    assert viewer.text() == "5.0G"


def test_file_size_field_editor_is_a_file_size_edit_seeded_from_the_model(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """The editor is a ``FileSizeEdit`` seeded with the model's current value, with nothing computed yet.

    **Test steps:**

    * seed the model with a size, then build the ``original_size`` editor
    * verify the editor holds that value, shows it formatted, and has an empty computed readout
    """
    model.original_size = 5368709120
    field = FileSizeField("original_size")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    assert editor.value == 5368709120
    assert internal_stored_label(editor).text() == "5.0G"
    assert internal_computed_label(editor).text() == ""


def test_file_size_field_editor_writes_through_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Changing the editor's value writes through to the model.

    **Test steps:**

    * build the editor
    * set the editor's ``value``
    * verify ``model.original_size`` follows
    """
    field = FileSizeField("original_size")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    editor.value = 1073741824

    assert model.original_size == 1073741824


def test_file_size_field_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor.

    **Test steps:**

    * build the editor
    * change ``model.original_size`` directly (as another surface would)
    * verify the editor's ``value`` and its spin box follow
    """
    field = FileSizeField("original_size")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    model.original_size = 2048

    assert editor.value == 2048
    assert internal_spin_box(editor).value == 2048


def test_file_size_field_editor_and_viewer_stay_live_together(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editor -> model -> viewer stays live (live "both").

    **Test steps:**

    * build an editor and a viewer over the same ``original_size`` field and model
    * set the editor's value
    * verify the viewer reflects it, formatted
    """
    field = FileSizeField("original_size")
    editor = field.make_editor(model.bind(field)).editor
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(editor, FileSizeEdit)
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(editor)
    qtbot.addWidget(viewer)

    editor.value = 1073741824

    assert model.original_size == 1073741824
    assert viewer.text() == "1.0G"


def test_compute_fills_the_readout_without_touching_the_value_or_dirtying(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """Compute measures and shows, and stops there: the stored size and the document's dirty flag are
    untouched (#223).

    **Test steps:**

    * build the editor over a stored ``1024`` with a measurement that finds ``2048``
    * press Compute
    * verify the readout shows ``2048`` while the model still reads ``1024`` and the document is clean
    """
    model.original_size = 1024
    model.dirty = False
    field = FileSizeField("original_size", measure=lambda: 2048)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == "2048"
    assert model.original_size == 1024
    assert model.dirty is False


def test_compute_measures_afresh_on_every_press(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Each press asks again -- the size is read from disk at that moment, never cached from the last
    press or from form construction.

    **Test steps:**

    * build the editor over a measurement whose answer changes between presses
    * press Compute twice and verify the readout followed the second answer
    """
    answers = iter([2048, 4096])
    field = FileSizeField("original_size", measure=lambda: next(answers))
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "2048"

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "4096"


def test_nothing_is_measured_until_compute_is_pressed(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Building the editor measures nothing: opening a document must not silently rewrite -- or even
    read -- what is on disk (#223).

    **Test steps:**

    * build the editor over a measurement that records each call
    * verify it was never called, and the computed readout is empty
    """
    calls: list[None] = []

    def measure() -> int:
        calls.append(None)
        return 2048

    field = FileSizeField("original_size", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    assert not calls
    assert internal_computed_label(editor).text() == ""


def test_the_scan_runs_off_the_gui_thread(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The measurement runs on a worker thread: a ``stat`` sum over a multi-gigabyte tree on an SMB
    mount takes seconds, and the window must stay responsive for them (#223).

    **Test steps:**

    * build the editor over a measurement that records the thread it ran on
    * press Compute and wait for the result
    * verify it did not run on the thread the test (and the GUI) is on
    """
    gui_thread = get_ident()
    scan_threads: list[int] = []

    def measure() -> int:
        scan_threads.append(get_ident())
        return 2048

    field = FileSizeField("original_size", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert scan_threads and gui_thread not in scan_threads
    assert editor.computed == 2048


def test_compute_is_disabled_while_a_scan_is_in_flight(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A scan already running cannot be started again, nor its half-finished answer applied (#223).

    **Test steps:**

    * build the editor over a measurement that blocks until the test releases it
    * press Compute and verify the row is busy with both buttons disabled while it hangs
    * release the measurement and verify the row comes back with the result
    """
    release = Event()

    def measure() -> int:
        release.wait(timeout=5)
        return 2048

    field = FileSizeField("original_size", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    try:
        internal_compute_button(editor).click()

        assert editor.busy is True
        assert not internal_compute_button(editor).isEnabled()
        assert not internal_apply_button(editor).isEnabled()
    finally:
        release.set()

    qtbot.waitUntil(lambda: not editor.busy)
    assert editor.computed == 2048
    assert internal_compute_button(editor).isEnabled()


def test_a_scan_that_raises_gives_the_row_back(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that blows up reports *nothing measured* rather than stranding the row busy with a
    Compute that can never be pressed again (#223).

    **Test steps:**

    * build the editor over a measurement that raises
    * press Compute and wait
    * verify nothing was computed, the stored size is untouched, and Compute is offered again
    """
    model.original_size = 1024

    def measure() -> int:
        raise OSError("the mount went away mid-scan")

    field = FileSizeField("original_size", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert editor.computed is None
    assert model.original_size == 1024
    assert internal_compute_button(editor).isEnabled()


def test_apply_is_offered_only_when_the_measurement_disagrees(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that agrees with the stored size leaves nothing to apply.

    **Test steps:**

    * build the editor over a stored ``2048`` with a measurement that also finds ``2048``
    * press Compute and verify apply stays disabled
    """
    model.original_size = 2048
    field = FileSizeField("original_size", measure=lambda: 2048)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert not internal_apply_button(editor).isEnabled()


def test_apply_stores_the_measured_size_and_dirties(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Apply is the only path from a measurement into the document -- and it is an ordinary edit.

    **Test steps:**

    * build the editor over a stale stored ``1024``, compute ``2048``, then press Apply
    * verify the model holds ``2048``, the document's core block does too, and the model went dirty
    """
    model.original_size = 1024
    model.dirty = False
    field = FileSizeField("original_size", measure=lambda: 2048)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)
    compute(qtbot, editor)

    internal_apply_button(editor).click()

    assert model.original_size == 2048
    assert model.document.original_size == 2048
    assert model.dirty is True


def test_a_stale_stored_size_stays_until_apply(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Opening a document whose stored size disagrees with the disk changes nothing: the disagreement is
    evidence -- content added or deleted since -- and only the user resolves it (#223).

    **Test steps:**

    * build the editor over a stored ``1024`` with a measurement that finds ``2048``
    * verify the model still reads ``1024`` before and after computing
    * apply, and verify only then does it move
    """
    model.original_size = 1024
    field = FileSizeField("original_size", measure=lambda: 2048)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)
    assert model.original_size == 1024

    compute(qtbot, editor)
    assert model.original_size == 1024

    internal_apply_button(editor).click()
    assert model.original_size == 2048


def test_an_unmeasurable_document_computes_nothing(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that cannot run -- a document with no path yet -- leaves the readout empty and
    offers nothing to apply, rather than reporting a size of zero it never took.

    **Test steps:**

    * build the editor over a measurement returning ``None`` and press Compute
    * verify the readout is empty, apply is disabled, and the stored size is untouched
    """
    model.original_size = 1024
    field = FileSizeField("original_size", measure=lambda: None)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, FileSizeEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == ""
    assert not internal_apply_button(editor).isEnabled()
    assert model.original_size == 1024
