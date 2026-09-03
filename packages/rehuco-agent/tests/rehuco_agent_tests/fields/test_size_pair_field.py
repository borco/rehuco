"""Tests for SizePairField: two model fields bound by one field, two formatted viewer rows, one
off-thread measurement behind one Compute, and the alignment that lets the stacked labels sit against
the editor's rows.
"""

# the viewer half is the same formatted label the sizes have always shown, so its tests read like the
# other formatted viewers' -- the pair is where this field and a plain measured field differ
# pylint: disable=duplicate-code
# a row's ``value``/``set_value`` are a ``SimpleProperty`` and its synthesized slot, which pylint
# resolves to the descriptor rather than to what an instance exposes -- the same duality every call site
# of one carries a ``# type: ignore`` for
# pylint: disable=no-member

from collections.abc import Callable
from threading import Event, get_ident

from PySide6.QtWidgets import QGridLayout, QLabel, QWidget
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.fields_form import CONTENT_COLUMN, LABEL_COLUMN, FieldsForm
from rehuco_agent.fields.widgets import SizeMeasurementEdit

from rehuco_agent_tests.fields.field_testers import TEST_EDITOR_TAB, TEST_VIEWER_TAB, TextFieldTester
from rehuco_agent_tests.fields.field_testers import SizePairFieldTester as SizePairField
from rehuco_agent_tests.fields.widgets.size_measurement_internals import (
    internal_compute_button,
    internal_computed_label,
    internal_copy_button,
    internal_editor,
)


@fixture
def build_editor(qtbot: QtBot, model: RehuDocumentModel) -> Callable[[SizePairField], SizeMeasurementEdit]:
    """Return a builder for a field's editor over the shared model, resolving both of its bindings the
    way `FieldsForm` does.

    A pair binds two model names, so a test cannot hand it one binding the way a single-value field's
    tests do -- going through the form is what keeps this suite honest about that. The **surface** each
    build produces is kept alive by this fixture rather than by ``qtbot``, whose registry holds only a
    weak reference: collected, it takes the C++ half of the very rows the test is about, and every
    property on them silently reads back as its descriptor.

    :param qtbot: the pytest-qt bot each surface is registered with.
    :param model: the view-model to bind against.
    :returns: a callable taking the field and returning its pair editor.
    """
    surfaces: list[QWidget] = []

    def build(field: SizePairField) -> SizeMeasurementEdit:
        grid = FieldsForm([field]).make_editor(model)[TEST_EDITOR_TAB]
        qtbot.addWidget(grid)
        surfaces.append(grid)
        editor = grid.findChild(SizeMeasurementEdit)
        assert isinstance(editor, SizeMeasurementEdit)
        return editor

    return build


def compute(qtbot: QtBot, editor: SizeMeasurementEdit) -> None:
    """Press the pair's ``Compute`` and wait for the scan to report back.

    The measurement runs on a worker thread (#223), so the result is not on screen when the click
    returns -- every test that computes goes through here rather than each spelling the wait.

    :param qtbot: the pytest-qt bot driving the event loop while the scan runs.
    :param editor: the pair to compute on.
    """
    internal_compute_button(editor).click()
    qtbot.waitUntil(lambda: not editor.busy)


# region binding tests
def test_the_field_binds_both_names(
    model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """The pair is one field over two model fields: it names both, and the form resolves a binding each.

    **Test steps:**

    * seed both sizes on the model and build the editor
    * verify ``names`` carries both and each row was seeded from its own model field
    """
    model.original_size = 8192
    model.current_size = 1024
    field = SizePairField("original_size")

    editor = build_editor(field)

    assert field.names == ("original_size", "current_size")
    assert [row.value for row in editor.rows] == [8192, 1024]


def test_each_row_writes_through_to_its_own_model_field(
    model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """Editing one row writes to that model field and leaves the other alone.

    **Test steps:**

    * build the editor and set the second row's value
    * verify ``model.current_size`` followed and ``model.original_size`` did not
    """
    editor = build_editor(SizePairField("original_size"))

    editor.rows[1].value = 1073741824

    assert model.current_size == 1073741824
    assert model.original_size is None


def test_each_row_follows_its_own_external_model_change(
    model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """A model change from elsewhere updates the row bound to that field, and only it.

    **Test steps:**

    * build the editor
    * change ``model.original_size`` directly (as another surface would)
    * verify the first row's value and spin box followed, and the second stayed unmeasured
    """
    editor = build_editor(SizePairField("original_size"))

    model.original_size = 2048

    assert editor.rows[0].value == 2048
    assert internal_editor(editor.rows[0]).value == 2048
    assert editor.rows[1].value is None


def test_a_lone_declared_name_composes_a_single_row(
    model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """A field built without a partner is a coherent one-row editor rather than a refusal -- the rule
    `composed_field_specs` narrows a partly-declared pair down to (#232).

    **Test steps:**

    * build the field with no ``partner_name`` over a seeded ``current_size``
    * verify it names one field, renders one row and one viewer row, and is bound to it
    """
    model.current_size = 4096
    field = SizePairField("current_size", partner_name=None)

    editor = build_editor(field)

    assert field.names == ("current_size",)
    assert len(editor.rows) == 1
    assert editor.rows[0].value == 4096


# endregion


# region viewer tests
def column_texts(layout: QGridLayout, column: int, rows: int) -> list[str]:
    """Return the text of the labels in one of a viewer grid's columns, top to bottom.

    :param layout: the viewer grid.
    :param column: the column to read.
    :param rows: how many rows to read.
    :returns: each cell's text, in row order.
    """
    texts: list[str] = []
    for row in range(rows):
        item = layout.itemAtPosition(row, column)
        assert item is not None
        cell = item.widget()
        assert isinstance(cell, QLabel)
        texts.append(cell.text())
    return texts


def test_the_viewer_stays_one_formatted_row_per_size(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Merging the editors left the viewer alone: each size keeps its own labeled, formatted row (#232).

    **Test steps:**

    * seed both sizes and build the viewer surface
    * verify it holds two rows, labeled and formatted separately
    """
    model.original_size = 5368709120
    model.current_size = 1024
    field = SizePairField("original_size")
    grid = FieldsForm([field]).make_viewer(model)[TEST_VIEWER_TAB]
    qtbot.addWidget(grid)
    layout = grid.layout()
    assert isinstance(layout, QGridLayout)

    assert column_texts(layout, LABEL_COLUMN, 2) == ["Original Size", "Current Size"]
    assert column_texts(layout, CONTENT_COLUMN, 2) == ["5.0G", "1.0K"]


def test_each_viewer_row_tracks_its_own_model_field(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Both viewer rows are live, each on its own binding.

    **Test steps:**

    * build the viewer surface, then change one size on the model
    * verify only that row re-rendered, formatted
    """
    field = SizePairField("original_size")
    grid = FieldsForm([field]).make_viewer(model)[TEST_VIEWER_TAB]
    qtbot.addWidget(grid)
    layout = grid.layout()
    assert isinstance(layout, QGridLayout)

    model.current_size = 5368709120

    assert column_texts(layout, CONTENT_COLUMN, 2) == ["", "5.0G"]


# endregion


# region measurement tests
def test_one_press_runs_the_scan_once_for_the_pair(
    qtbot: QtBot, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """The whole point of the merge: one Compute, one walk of the tree, one answer both rows read
    (#232). Two rows each with a Compute meant running the identical scan twice.

    **Test steps:**

    * build the editor over a measurement that counts its calls
    * press Compute
    * verify it ran exactly once and both rows hold the same measurement
    """
    calls: list[None] = []

    def measure() -> int:
        calls.append(None)
        return 2048

    editor = build_editor(SizePairField("original_size", measure=measure))

    compute(qtbot, editor)

    assert len(calls) == 1
    assert internal_computed_label(editor).text() == "2048"
    assert [row.computed for row in editor.rows] == [2048, 2048]


def test_compute_fills_the_readout_without_touching_a_value_or_dirtying(
    qtbot: QtBot, model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """Compute measures and shows, and stops there: both stored sizes and the document's dirty flag are
    untouched (#223).

    **Test steps:**

    * build the editor over stored sizes with a measurement that finds a third number
    * press Compute
    * verify the readout shows it while the model still reads what it held, and the document is clean
    """
    model.original_size = 8192
    model.current_size = 1024
    model.dirty = False
    editor = build_editor(SizePairField("original_size", measure=lambda: 2048))

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == "2048"
    assert model.original_size == 8192
    assert model.current_size == 1024
    assert model.dirty is False


def test_compute_measures_afresh_on_every_press(
    qtbot: QtBot, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """Each press asks again -- the size is read from disk at that moment, never cached from the last
    press or from form construction.

    **Test steps:**

    * build the editor over a measurement whose answer changes between presses
    * press Compute twice and verify the readout followed the second answer
    """
    answers = iter([2048, 4096])
    editor = build_editor(SizePairField("original_size", measure=lambda: next(answers)))

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "2048"

    compute(qtbot, editor)
    assert internal_computed_label(editor).text() == "4096"


def test_nothing_is_measured_until_compute_is_pressed(
    build_editor: Callable[[SizePairField], SizeMeasurementEdit],
) -> None:
    """Building the editor measures nothing: opening a document must not silently rewrite -- or even
    read -- what is on disk (#223).

    **Test steps:**

    * build the editor over a measurement that records each call
    * verify it was never called, and the readout is empty
    """
    calls: list[None] = []

    def measure() -> int:
        calls.append(None)
        return 2048

    editor = build_editor(SizePairField("original_size", measure=measure))

    assert not calls
    assert internal_computed_label(editor).text() == ""


def test_the_scan_runs_off_the_gui_thread(
    qtbot: QtBot, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
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

    editor = build_editor(SizePairField("original_size", measure=measure))

    compute(qtbot, editor)

    assert scan_threads and gui_thread not in scan_threads
    assert editor.computed == 2048


def test_both_rows_are_busy_while_a_scan_is_in_flight(
    qtbot: QtBot, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """One scan answers both rows, so both wait for it: while it runs neither can be re-scanned nor have
    a half-finished answer copied (#223, #232).

    **Test steps:**

    * build the editor over a measurement that blocks until the test releases it
    * press Compute and verify the pair and both rows are busy with every button disabled
    * release the measurement and verify the pair comes back with the result
    """
    release = Event()

    def measure() -> int:
        release.wait(timeout=5)
        return 2048

    editor = build_editor(SizePairField("original_size", measure=measure))

    try:
        internal_compute_button(editor).click()

        assert editor.busy is True
        assert not internal_compute_button(editor).isEnabled()
        for row in editor.rows:
            assert row.busy is True
            assert not internal_copy_button(row).isEnabled()
    finally:
        release.set()

    qtbot.waitUntil(lambda: not editor.busy)
    assert editor.computed == 2048
    assert internal_compute_button(editor).isEnabled()


def test_a_scan_that_raises_gives_both_rows_back(
    qtbot: QtBot, model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """A measurement that blows up reports *nothing measured* to every row rather than stranding the pair
    busy with a Compute that can never be pressed again (#223).

    **Test steps:**

    * build the editor over a measurement that raises
    * press Compute and wait
    * verify nothing was computed, both stored sizes are untouched, no copy is offered, and Compute is
      offered again
    """
    model.original_size = 8192
    model.current_size = 1024

    def measure() -> int:
        raise OSError("the mount went away mid-scan")

    editor = build_editor(SizePairField("original_size", measure=measure))

    compute(qtbot, editor)

    assert editor.computed is None
    assert internal_computed_label(editor).text() == ""
    assert (model.original_size, model.current_size) == (8192, 1024)
    assert not any(internal_copy_button(row).isEnabled() for row in editor.rows)
    assert internal_compute_button(editor).isEnabled()


def test_a_copy_is_offered_only_where_the_measurement_disagrees(
    qtbot: QtBot, model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """One measurement, two independent verdicts: the row it agrees with has nothing to copy.

    **Test steps:**

    * store two sizes, one of which the measurement will match
    * press Compute
    * verify only the disagreeing row offers a copy
    """
    model.original_size = 2048
    model.current_size = 1024
    editor = build_editor(SizePairField("original_size", measure=lambda: 2048))

    compute(qtbot, editor)

    assert not internal_copy_button(editor.rows[0]).isEnabled()
    assert internal_copy_button(editor.rows[1]).isEnabled()


def test_a_copy_stores_into_its_own_field_and_dirties(
    qtbot: QtBot, model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """A copy is the only path from a measurement into the document -- and it is an ordinary edit on one
    field: ``original_size`` is the denominator for *how much is left*
    ([[field-schema#duration-size]]), so accepting into ``current_size`` must leave it alone.

    **Test steps:**

    * build the editor over two stale sizes, compute a third, then press the second row's copy
    * verify the model and the document's core block hold it, ``original_size`` is untouched, and the
      model went dirty
    """
    model.original_size = 8192
    model.current_size = 1024
    model.dirty = False
    editor = build_editor(SizePairField("original_size", measure=lambda: 2048))
    compute(qtbot, editor)

    internal_copy_button(editor.rows[1]).click()

    assert model.current_size == 2048
    assert model.document.current_size == 2048
    assert model.original_size == 8192
    assert model.dirty is True


def test_a_stale_stored_size_stays_until_it_is_copied(
    qtbot: QtBot, model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """Opening a document whose stored sizes disagree with the disk changes nothing: the disagreement is
    evidence -- content added or deleted since -- and only the user resolves it (#223).

    **Test steps:**

    * build the editor over a stored ``1024`` with a measurement that finds ``2048``
    * verify the model still reads ``1024`` before and after computing
    * copy, and verify only then does it move
    """
    model.original_size = 1024
    editor = build_editor(SizePairField("original_size", measure=lambda: 2048))
    assert model.original_size == 1024

    compute(qtbot, editor)
    assert model.original_size == 1024

    internal_copy_button(editor.rows[0]).click()
    assert model.original_size == 2048


def test_an_unmeasurable_document_computes_nothing(
    qtbot: QtBot, model: RehuDocumentModel, build_editor: Callable[[SizePairField], SizeMeasurementEdit]
) -> None:
    """A measurement that cannot run -- a document with no path yet -- leaves the readout empty and offers
    nothing to copy, rather than reporting a size of zero it never took.

    **Test steps:**

    * build the editor over a measurement returning ``None`` and press Compute
    * verify the readout is empty, no copy is offered, and the stored sizes are untouched
    """
    model.original_size = 1024
    editor = build_editor(SizePairField("original_size", measure=lambda: None))

    compute(qtbot, editor)

    assert internal_computed_label(editor).text() == ""
    assert not any(internal_copy_button(row).isEnabled() for row in editor.rows)
    assert model.original_size == 1024


# endregion


# region alignment tests
def shown_editor_grid(qtbot: QtBot, model: RehuDocumentModel) -> QWidget:
    """Build and show an editor surface holding a plain field and the size pair, wide enough to lay out.

    Geometry is the assertion in this region, so the grid has to be real: laid out, exposed, and at a
    size the rows are not being squeezed into.

    :param qtbot: the pytest-qt bot to register and expose the widget with.
    :param model: the view-model the fields bind to.
    :returns: the shown editor grid.
    """
    form = FieldsForm([TextFieldTester("title"), SizePairField("original_size")])
    grid = form.make_editor(model)[TEST_EDITOR_TAB]
    qtbot.addWidget(grid)
    grid.resize(800, 300)
    grid.show()
    qtbot.waitExposed(grid)
    return grid


def test_the_stacked_labels_line_up_with_the_editor_rows(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Each stacked name sits against the row it names, asserted on geometry rather than by eye -- the
    whole reason the labels are stacked with `equal_height_column` and the rows given equal stretch
    (#232).

    **Test steps:**

    * show an editor surface carrying the pair
    * verify each label's vertical center matches its row's spin box's, in the grid's own coordinates
    """
    grid = shown_editor_grid(qtbot, model)
    editor = grid.findChild(SizeMeasurementEdit)
    assert isinstance(editor, SizeMeasurementEdit)
    labels = [label for label in grid.findChildren(QLabel) if label.text() in ("Original Size", "Current Size")]

    centers = [label.mapTo(grid, label.rect().center()).y() for label in labels]
    rows = [internal_editor(row) for row in editor.rows]
    row_centers = [row.mapTo(grid, row.rect().center()).y() for row in rows]

    assert len(centers) == 2
    assert all(abs(label - row) <= 1 for label, row in zip(centers, row_centers, strict=True))


def test_the_pairs_label_column_lines_up_with_the_plain_fields(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The pair's label cell is an ordinary label-column cell, so its names start where every other
    field's does -- a stacked cell must not read as an indented sub-form.

    **Test steps:**

    * show an editor surface carrying a plain text field above the pair
    * verify the pair's labels share the plain field's left edge, in the grid's own coordinates
    """
    grid = shown_editor_grid(qtbot, model)
    labels = {label.text(): label for label in grid.findChildren(QLabel)}

    lefts = {
        text: labels[text].mapTo(grid, labels[text].rect().topLeft()).x()
        for text in ("Title", "Original Size", "Current Size")
    }

    assert lefts["Original Size"] == lefts["Title"]
    assert lefts["Current Size"] == lefts["Title"]


# endregion
