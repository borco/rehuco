"""Tests for ContentCountField: the measured count's viewer, the compute/apply row over its editor,
and the off-thread measurement behind it.
"""

from threading import Event, get_ident

# the viewer is deliberately the plain-integer one ``IntField`` gives (a measured count *is* a plain
# number to look at), so its test reads like that field's -- the row below it is where the two differ
# pylint: disable=duplicate-code
from PySide6.QtWidgets import QLabel
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.widgets import ContentCountEdit

from rehuco_agent_tests.fields.field_testers import ContentCountFieldTester as ContentCountField
from rehuco_agent_tests.fields.widgets.test_content_count_edit import (
    internal_apply_button,
    internal_compute_button,
    internal_computed_label,
    internal_spin_box,
)


def compute(qtbot: QtBot, editor: ContentCountEdit) -> None:
    """Press ``Compute`` and wait for the count to report back.

    The measurement runs on a worker thread (#198, #223), so the result is not on screen when the click
    returns -- every test that presses Compute goes through here rather than each spelling the wait.

    :param qtbot: the pytest-qt bot driving the event loop while the count runs.
    :param editor: the row to compute on.
    """
    internal_compute_button(editor).click()
    qtbot.waitUntil(lambda: not editor.busy)


def test_content_count_viewer_shows_and_tracks_the_value(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The viewer shows the stored count and re-renders when the model changes; unset renders empty and a
    genuine ``0`` renders honestly ([[field-schema#deferred-items]]).

    **Test steps:**

    * build a ``current_count`` viewer over a model that has never been scanned
    * verify the label starts empty, then follows a real count and a genuine zero
    """
    field = ContentCountField("current_count")
    viewer = field.make_viewer(model.bind(field)).viewer
    assert isinstance(viewer, QLabel)
    qtbot.addWidget(viewer)

    assert viewer.text() == ""

    model.current_count = 42
    assert viewer.text() == "42"

    model.current_count = 0
    assert viewer.text() == "0"


def test_content_count_editor_seeds_the_stored_count(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The editor's spin box holds the stored count, and nothing is computed until asked.

    **Test steps:**

    * seed the model with a count and build the editor
    * verify the spin box shows it and the computed label is empty
    """
    model.current_count = 7
    field = ContentCountField("current_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    assert internal_spin_box(editor).value == 7
    assert internal_computed_label(editor).text() == ""


def test_content_count_editor_writes_back_to_the_model(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Editing the spin box writes through to the model, exactly like any other value widget.

    **Test steps:**

    * build the editor and set the spin box's value
    * verify the model followed
    """
    field = ContentCountField("current_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    internal_spin_box(editor).setValue(42)

    assert model.current_count == 42


def test_compute_fills_the_label_without_touching_the_value_or_dirtying(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Compute measures and shows, and stops there: the stored count and the document's dirty flag are
    untouched ([[data-model#image-meanings]], #198).

    **Test steps:**

    * build the editor over a stored ``7`` with a measurement that finds ``9``
    * press Compute
    * verify the label shows ``9`` while the model still reads ``7`` and the document is still clean
    """
    model.current_count = 7
    model.dirty = False
    field = ContentCountField("current_count", measure=lambda: 9)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == "9"
    assert model.current_count == 7
    assert model.dirty is False


def test_compute_measures_afresh_on_every_press(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Each press asks again -- the count is read from disk at that moment, never cached from the last
    press or from form construction.

    **Test steps:**

    * build the editor over a measurement whose answer changes between presses
    * press Compute twice and verify the label followed the second answer
    """
    answers = iter([9, 11])
    field = ContentCountField("current_count", measure=lambda: next(answers))
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "9"

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "11"


def test_nothing_is_measured_until_compute_is_pressed(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Building the editor measures nothing: opening a document must not silently rewrite -- or even
    read -- what the archives hold (#198).

    **Test steps:**

    * build the editor over a measurement that records each call
    * verify it was never called, and the computed label is empty
    """
    calls: list[None] = []

    def measure() -> int:
        calls.append(None)
        return 9

    field = ContentCountField("current_count", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    assert not calls
    assert internal_computed_label(editor).text() == ""


def test_computing_zero_content_images_shows_zero(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """An archive holding no content images computes ``0``, not nothing -- and offers to store that ``0``
    over an unset count ([[field-schema#deferred-items]]).

    **Test steps:**

    * build the editor over an unscanned model with a measurement that finds nothing
    * press Compute and verify the label reads ``"0"`` and apply is offered
    """
    field = ContentCountField("current_count", measure=lambda: 0)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == "0"
    assert internal_apply_button(editor).isEnabled()


def test_apply_is_offered_only_when_the_measurement_disagrees(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that agrees with the stored count leaves nothing to apply.

    **Test steps:**

    * build the editor over a stored ``9`` with a measurement that also finds ``9``
    * press Compute and verify apply stays disabled
    """
    model.current_count = 9
    field = ContentCountField("current_count", measure=lambda: 9)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert not internal_apply_button(editor).isEnabled()


def test_apply_stores_the_measured_count_and_dirties(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Apply is the only path from a measurement into the document -- and it is an ordinary edit.

    **Test steps:**

    * build the editor over a stale stored ``7``, compute ``9``, then press Apply
    * verify the model holds ``9``, the document's block does too, and the model went dirty
    """
    model.current_count = 7
    model.dirty = False
    field = ContentCountField("current_count", measure=lambda: 9)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)
    compute(qtbot, editor)

    internal_apply_button(editor).click()

    assert model.current_count == 9
    assert model.document.active_field("current_count") == 9
    assert model.dirty is True


def test_a_stale_stored_count_stays_until_apply(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Opening a document whose stored count disagrees with the archives changes nothing: the
    disagreement is evidence of a refreshed zip, and only the user resolves it (#198).

    **Test steps:**

    * build the editor over a stored ``7`` with a measurement that finds ``9``
    * verify the model still reads ``7`` before and after computing
    * apply, and verify only then does it move
    """
    model.current_count = 7
    field = ContentCountField("current_count", measure=lambda: 9)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)
    assert model.current_count == 7

    compute(qtbot, editor)
    assert model.current_count == 7

    internal_apply_button(editor).click()
    assert model.current_count == 9


def test_an_unmeasurable_document_computes_nothing(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that cannot run -- a document with no path yet -- leaves the label empty and offers
    nothing to apply, rather than reporting a count of zero it never took.

    **Test steps:**

    * build the editor over a measurement returning ``None`` and press Compute
    * verify the label is empty, apply is disabled, and the stored count is untouched
    """
    model.current_count = 7
    field = ContentCountField("current_count", measure=lambda: None)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == ""
    assert not internal_apply_button(editor).isEnabled()
    assert model.current_count == 7


def test_content_count_editor_follows_an_external_model_change(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A model change from elsewhere updates the editor under the echo guard.

    **Test steps:**

    * build the editor, then change ``model.current_count`` directly
    * verify the spin box followed
    """
    field = ContentCountField("current_count")
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    model.current_count = 13

    assert internal_spin_box(editor).value == 13


def test_the_count_runs_off_the_gui_thread(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The measurement runs on a worker thread: opening every archive a pack holds, over an SMB mount,
    takes long enough that the window must stay responsive for it (#223).

    **Test steps:**

    * build the editor over a measurement that records the thread it ran on
    * press Compute and wait for the result
    * verify it did not run on the thread the test (and the GUI) is on
    """
    gui_thread = get_ident()
    count_threads: list[int] = []

    def measure() -> int:
        count_threads.append(get_ident())
        return 9

    field = ContentCountField("current_count", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert count_threads and gui_thread not in count_threads
    assert editor.computed == 9


def test_compute_is_disabled_while_a_count_is_in_flight(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A count already running cannot be started again, nor its half-finished answer applied (#223).

    **Test steps:**

    * build the editor over a measurement that blocks until the test releases it
    * press Compute and verify the row is busy with both buttons disabled while it hangs
    * release the measurement and verify the row comes back with the result
    """
    release = Event()

    def measure() -> int:
        release.wait(timeout=5)
        return 9

    field = ContentCountField("current_count", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    try:
        internal_compute_button(editor).click()

        assert editor.busy is True
        assert not internal_compute_button(editor).isEnabled()
        assert not internal_apply_button(editor).isEnabled()
    finally:
        release.set()

    qtbot.waitUntil(lambda: not editor.busy)
    assert editor.computed == 9
    assert internal_compute_button(editor).isEnabled()


def test_a_count_that_raises_gives_the_row_back(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """A measurement that blows up -- a corrupt archive, a mount that went away -- reports *nothing
    counted* rather than stranding the row busy with a Compute that can never be pressed again (#223).

    **Test steps:**

    * build the editor over a measurement that raises
    * press Compute and wait
    * verify nothing was computed, the stored count is untouched, and Compute is offered again
    """
    model.current_count = 7

    def measure() -> int:
        raise OSError("the mount went away mid-count")

    field = ContentCountField("current_count", measure=measure)
    editor = field.make_editor(model.bind(field)).editor
    assert isinstance(editor, ContentCountEdit)
    qtbot.addWidget(editor)

    compute(qtbot, editor)

    assert editor.computed is None
    assert model.current_count == 7
    assert internal_compute_button(editor).isEnabled()
