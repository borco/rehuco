"""Tests for DurationMeasurementEdit: two stored `DurationEdit`s sharing one measurement, a copy per row,
and the grid that lines their columns up.
"""

# the measure/compute/busy contract is the one every measure surface's tests pin; each suite pins it
# through its own surface, which is where a user meets it
# pylint: disable=duplicate-code
# a row's ``value``/``set_value`` are a ``SimpleProperty`` and its synthesized slot, which pylint
# resolves to the descriptor rather than to what an instance exposes -- the same duality every call site
# of one carries a ``# type: ignore`` for
# pylint: disable=no-member

from PySide6.QtWidgets import QGridLayout
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.duration_edit import DurationEdit
from rehuco_agent.fields.widgets.duration_measurement_edit import (
    COMPUTE_COLUMN,
    COMPUTED_COLUMN,
    COMPUTED_TOOLTIP,
    COPY_COLUMN,
    EDITOR_COLUMN,
    EDITOR_COLUMN_SPAN,
    DurationMeasurementEdit,
    DurationRow,
)
from rehuco_agent.fields.widgets.value_readout import ValueReadout

from .duration_measurement_internals import (
    internal_compute_button,
    internal_computed_label,
    internal_copy_button,
    internal_editor,
)

ROW_LABELS = ("Original Duration", "Current Duration")
"""The two durations' labels, as the field composes them -- what each row's copy action is named after."""


def internal_duration_edit(row: DurationRow) -> DurationEdit:
    """Return one row's stored-duration editor, named for what this editor puts there.

    :param row: the row to inspect.
    :returns: the internal ``DurationEdit``.
    """
    return internal_editor(row)


# region layout tests
def test_one_row_is_built_per_label(qtbot: QtBot) -> None:
    """The widget's shape is the document's answer, not its own: one row per bound duration.

    **Test steps:**

    * build a two-label editor and a one-label one
    * verify each holds that many rows
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    lone = DurationMeasurementEdit(("Current Duration",))
    qtbot.addWidget(edit)
    qtbot.addWidget(lone)

    assert len(edit.rows) == 2
    assert len(lone.rows) == 1


def test_the_rows_share_one_grid_so_their_columns_line_up(qtbot: QtBot) -> None:
    """Both rows' cells are placed in the **editor's own** grid, column for column -- the reason this is
    one widget rather than two row bundles, which would each distribute their width alone (#233).

    **Test steps:**

    * build the editor
    * verify each row's duration editor and copy button sit in the same grid columns, one grid row apart
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    grid = edit.layout()
    assert isinstance(grid, QGridLayout)

    for index, row in enumerate(edit.rows):
        editor = grid.indexOf(internal_duration_edit(row))
        copy = grid.indexOf(internal_copy_button(row))
        assert grid.getItemPosition(editor) == (index, EDITOR_COLUMN, 1, EDITOR_COLUMN_SPAN)
        assert grid.getItemPosition(copy) == (index, COPY_COLUMN, 1, 1)


def test_the_measurement_spans_every_row(qtbot: QtBot) -> None:
    """The measured readout and the compute action span all the rows, because the measurement belongs to
    the whole group rather than to whichever row happened to host it (#233).

    **Test steps:**

    * build the editor
    * verify the readout and the compute button each span both rows in their own column
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    grid = edit.layout()
    assert isinstance(grid, QGridLayout)

    computed = grid.indexOf(internal_computed_label(edit))
    compute = grid.indexOf(internal_compute_button(edit))
    assert grid.getItemPosition(computed) == (0, COMPUTED_COLUMN, 2, 1)
    assert grid.getItemPosition(compute) == (0, COMPUTE_COLUMN, 2, 1)


def test_the_column_stretches_match_the_size_editors(qtbot: QtBot) -> None:
    """Five columns stretched ``1, 1, 0, 1, 0`` -- the same geometry
    :class:`~rehuco_agent.fields.widgets.SizeMeasurementEdit` uses, so a form showing both pairs lines all
    four rows up rather than leaving each editor to divide the width its own way (#233).

    **Test steps:**

    * build the editor
    * verify each of the five columns' stretch
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    grid = edit.layout()
    assert isinstance(grid, QGridLayout)

    assert [grid.columnStretch(column) for column in range(grid.columnCount())] == [1, 1, 0, 1, 0]


def test_the_duration_editor_spans_both_content_columns(qtbot: QtBot) -> None:
    """`DurationEdit` covers columns 0-1 as one widget: it is already two boxes splitting its own width
    evenly, so spanning both puts that split exactly where the size rows put theirs (#233).

    **Test steps:**

    * build the editor
    * verify each row's editor occupies the first two columns, with the copy button after them
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    grid = edit.layout()
    assert isinstance(grid, QGridLayout)

    for index, row in enumerate(edit.rows):
        editor = grid.indexOf(internal_duration_edit(row))
        assert grid.getItemPosition(editor) == (index, EDITOR_COLUMN, 1, EDITOR_COLUMN_SPAN)


def test_the_rows_take_equal_bands_of_the_editors_height(qtbot: QtBot) -> None:
    """The rows split the widget's height evenly, which is what a stacked label column beside it -- laid
    out with the same rule by `equal_height_column` -- lines itself up against.

    **Test steps:**

    * build and show the editor at a height neither row would ask for
    * verify both grid rows came out the same height
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    edit.resize(600, 120)
    edit.show()
    qtbot.waitExposed(edit)
    grid = edit.layout()
    assert isinstance(grid, QGridLayout)

    first, second = grid.cellRect(0, EDITOR_COLUMN), grid.cellRect(1, EDITOR_COLUMN)

    assert first.height() == second.height()


# endregion


# region widget tests
def test_a_fresh_editor_starts_unmeasured_with_nothing_to_copy(qtbot: QtBot) -> None:
    """A fresh editor holds no stored duration on any row, shows no measured one, and offers nothing to
    copy.

    **Test steps:**

    * build the widget
    * verify every value is unset, the measured readout is empty, both copies disabled, compute offered
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    assert edit.computed is None
    assert edit.busy is False
    assert internal_computed_label(edit).text() == ""
    assert internal_compute_button(edit).isEnabled()
    for row in edit.rows:
        assert row.value is None
        assert not internal_copy_button(row).isEnabled()


def test_each_rows_copy_names_the_field_it_stores_into(qtbot: QtBot) -> None:
    """The two copy buttons are icon-only and identical, so the tooltip is what says which duration each
    one stores -- pressing the wrong one overwrites the denominator of *how much is left*.

    **Test steps:**

    * build the editor
    * verify each row's copy tooltip names that row's label
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    tooltips = [internal_copy_button(row).toolTip() for row in edit.rows]

    assert tooltips == [
        "Store the computed duration in Original Duration",
        "Store the computed duration in Current Duration",
    ]


def test_the_computed_readout_is_the_shared_read_only_readout(qtbot: QtBot) -> None:
    """The measured readout is the surface-agnostic `ValueReadout` -- framed, selectable, read-only --
    rather than something this editor styles for itself, so a form showing it beside the size pair's
    readout cannot end up looking different.

    **Test steps:**

    * build the widget
    * verify the readout is a ``ValueReadout`` naming what it shows
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    label = internal_computed_label(edit)

    assert isinstance(label, ValueReadout)
    assert label.toolTip() == COMPUTED_TOOLTIP


def test_editing_a_duration_editor_writes_that_rows_value_through(qtbot: QtBot) -> None:
    """Each `DurationEdit` is its own row's value: typing in one moves that row's ``value`` and no other.

    **Test steps:**

    * build the widget and set the second row's duration editor
    * verify only that row's ``value`` followed
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    internal_duration_edit(edit.rows[1]).value = 8100

    assert edit.rows[1].value == 8100
    assert edit.rows[0].value is None


def test_setting_a_rows_value_echoes_into_its_duration_editor(qtbot: QtBot) -> None:
    """A value set from outside (the model, or a copy) shows up in that row's duration editor, with no
    feedback loop.

    **Test steps:**

    * build the widget and set the first row's ``value`` directly, as a bound model change would
    * verify its duration editor holds the seconds and the value survived
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    row = edit.rows[0]

    row.set_value(8100)  # type: ignore[attr-defined]  # the slot SimpleProperty synthesizes

    assert internal_duration_edit(row).value == 8100
    assert row.value == 8100


def test_compute_asks_the_owner_rather_than_measuring(qtbot: QtBot) -> None:
    """Pressing ``Compute`` only emits -- the widget knows nothing about files, probes, or settings.

    **Test steps:**

    * build the widget and press ``Compute``
    * verify ``compute_requested`` fired and no value changed
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    with qtbot.waitSignal(edit.compute_requested):
        internal_compute_button(edit).click()

    assert edit.computed is None
    assert [row.value for row in edit.rows] == [None, None]


def test_compute_makes_every_row_busy_and_disables_every_action(qtbot: QtBot) -> None:
    """A scan in flight disables everything on the edit: one scan answers both rows, so both wait for it
    and neither a second scan nor a copy of a half-finished answer may be pressed (#233).

    **Test steps:**

    * build the editor over stored durations with a stale measurement already showing, so both copies are
      offered
    * press ``Compute``
    * verify the editor and every row are busy, with all three buttons disabled
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    for row in edit.rows:
        row.set_value(4050)  # type: ignore[attr-defined]
    edit.computed = 8100
    assert all(internal_copy_button(row).isEnabled() for row in edit.rows)

    internal_compute_button(edit).click()

    assert edit.busy is True
    assert not internal_compute_button(edit).isEnabled()
    for row in edit.rows:
        assert row.busy is True
        assert not internal_copy_button(row).isEnabled()


def test_showing_a_measurement_leaves_the_busy_state(qtbot: QtBot) -> None:
    """The owner's answer is what ends the scan: every button comes back and the one result is on screen.

    **Test steps:**

    * press ``Compute``, then hand the widget a result
    * verify it is no longer busy, the readout shows the result, and every button is offered again
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(8100)

    assert edit.busy is False
    assert edit.computed == 8100
    assert internal_computed_label(edit).text() == "8100"
    assert internal_compute_button(edit).isEnabled()
    for row in edit.rows:
        assert row.computed == 8100
        assert internal_copy_button(row).isEnabled()


def test_a_failed_measurement_leaves_both_rows_empty_rather_than_half_a_state(qtbot: QtBot) -> None:
    """A scan that measured nothing still hands back an answer, and it reaches **every** row -- one
    measurement cannot leave one row showing a result and the other not (#233).

    **Test steps:**

    * press ``Compute``, then hand the widget ``None``
    * verify it is no longer busy, the readout is empty, no copy is offered, and compute is offered again
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(None)

    assert edit.busy is False
    assert internal_computed_label(edit).text() == ""
    assert internal_compute_button(edit).isEnabled()
    for row in edit.rows:
        assert row.computed is None
        assert not internal_copy_button(row).isEnabled()


def test_a_computed_duration_is_shown_exactly_without_touching_any_value(qtbot: QtBot) -> None:
    """A measurement fills the one readout and leaves both stored durations alone -- the disagreement is
    information, not something to silently resolve (#224).

    It is shown as an **exact second count**, so it can be compared against either duration editor digit
    for digit rather than through a rounded ``2h 15m`` two different durations would share.

    **Test steps:**

    * build the editor over stored durations and hand it a computed ``8137``
    * verify the readout shows the exact seconds while both rows still read what they held
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    edit.rows[0].set_value(8100)  # type: ignore[attr-defined]
    edit.rows[1].set_value(4050)  # type: ignore[attr-defined]

    edit.computed = 8137

    assert internal_computed_label(edit).text() == "8137"
    assert [row.value for row in edit.rows] == [8100, 4050]


def test_a_computed_zero_shows_as_zero_not_as_nothing(qtbot: QtBot) -> None:
    """A tutorial holding no video measures a genuine ``0``, which reads differently from never having
    measured ([[field-schema#deferred-items]]).

    **Test steps:**

    * hand the widget a computed ``0``
    * verify the readout reads ``"0"``
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    edit.computed = 0

    assert internal_computed_label(edit).text() == "0"


def test_each_rows_copy_is_offered_only_while_that_row_differs(qtbot: QtBot) -> None:
    """A copy enables exactly when the measurement disagrees with **that row's** stored duration -- one
    scan, two independent answers to the question *is this one stale*.

    **Test steps:**

    * store two different durations and compute one of them
    * verify only the disagreeing row offers a copy
    * bring that row into agreement and verify it stops offering one
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    original, current = edit.rows
    original.set_value(8100)  # type: ignore[attr-defined]
    current.set_value(4050)  # type: ignore[attr-defined]

    edit.computed = 8100

    assert not internal_copy_button(original).isEnabled()
    assert internal_copy_button(current).isEnabled()

    current.set_value(8100)  # type: ignore[attr-defined]
    assert not internal_copy_button(current).isEnabled()


def test_a_copy_stores_the_measurement_into_that_row_alone(qtbot: QtBot) -> None:
    """A copy is the one action here that changes a value -- and it changes exactly one:
    ``original_duration`` is the denominator for *how much is left* ([[field-schema#duration-size]]).

    **Test steps:**

    * build the editor over two stale durations with a measurement showing
    * press the second row's copy and verify its ``value_changed`` fired with the measured seconds
    * verify its duration editor followed, and the first row is untouched
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    original, current = edit.rows
    original.set_value(8100)  # type: ignore[attr-defined]
    current.set_value(4050)  # type: ignore[attr-defined]
    edit.computed = 7000

    with qtbot.waitSignal(current.value_changed) as blocker:  # type: ignore[attr-defined]
        internal_copy_button(current).click()

    assert blocker.args == [7000]
    assert current.value == 7000
    assert internal_duration_edit(current).value == 7000
    assert not internal_copy_button(current).isEnabled()
    assert original.value == 8100


def test_an_unmeasurable_duration_shows_nothing_and_copies_nothing(qtbot: QtBot) -> None:
    """A measurement that could not run (``None`` -- a document with no path yet, or a probe backend that
    cannot run here at all) leaves the readout empty and every copy disabled, rather than offering to
    store "no duration".

    **Test steps:**

    * build the editor over stored durations and hand it a computed ``None``
    * verify the readout is empty and neither copy is offered
    """
    edit = DurationMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    for row in edit.rows:
        row.set_value(4050)  # type: ignore[attr-defined]

    edit.computed = None

    assert internal_computed_label(edit).text() == ""
    assert not any(internal_copy_button(row).isEnabled() for row in edit.rows)


# endregion
