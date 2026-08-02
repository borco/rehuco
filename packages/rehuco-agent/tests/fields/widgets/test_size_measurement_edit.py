"""Tests for SizeMeasurementEdit: two stored spin boxes sharing one measurement, a copy per row, and the
grid that lines their columns up.
"""

# the measure/compute/busy contract is the one every measure surface's tests pin; each suite pins it
# through its own surface, which is where a user meets it
# pylint: disable=duplicate-code
# a row's ``value``/``set_value`` are a ``SimpleProperty`` and its synthesized slot, which pylint
# resolves to the descriptor rather than to what an instance exposes -- the same duality every call site
# of one carries a ``# type: ignore`` for
# pylint: disable=no-member

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QGridLayout
from pytest import mark, param
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.shared_measurement_edit import (
    COMPUTE_COLUMN,
    COMPUTED_COLUMN,
    COPY_COLUMN,
    EDITOR_COLUMN,
    SharedMeasurementRow,
)
from rehuco_agent.fields.widgets.size_measurement_edit import COMPUTED_TOOLTIP, STORED_TOOLTIP, SizeMeasurementEdit
from rehuco_agent.fields.widgets.value_readout import ValueReadout

from .shared_measurement_internals import (
    internal_compute_button,
    internal_computed_label,
    internal_copy_button,
    internal_editor,
    internal_stored_label,
)

ROW_LABELS = ("Original Size", "Current Size")
"""The two sizes' labels, as the field composes them -- what each row's copy action is named after."""


def internal_spin_box(row: SharedMeasurementRow) -> UnboundedSpinBox:
    """Return one row's stored-size spin box, named for what this editor puts there.

    :param row: the row to inspect.
    :returns: the internal ``UnboundedSpinBox``.
    """
    return internal_editor(row)


# region format() tests
@mark.parametrize(
    ("size", "expected"),
    [
        param(None, "", id="none-is-empty-unmeasured"),
        param(0, "0B", id="zero-renders-honestly-not-empty"),
        param(1, "1B", id="one-byte"),
        param(300, "300B", id="sub-kilo"),
        param(1024, "1.0K", id="exactly-one-kilo"),
        param(1500000000, "1.4G", id="giga-rounded"),
        param(5368709120, "5.0G", id="five-giga-exact"),
        param(2**50, "1.0P", id="one-peta"),
    ],
)
def test_format(size: int | None, expected: str) -> None:
    """``format`` renders whole bytes GNU ``ls -sh`` style (``humanize.naturalsize(size, gnu=True)``).

    **Test steps:**

    * format each ``size`` value
    * verify it matches ``expected``
    """
    assert SizeMeasurementEdit.format(size) == expected


# endregion


# region layout tests
def test_one_row_is_built_per_label(qtbot: QtBot) -> None:
    """The widget's shape is the document's answer, not its own: one row per bound size.

    **Test steps:**

    * build a two-label editor and a one-label one
    * verify each holds that many rows
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    lone = SizeMeasurementEdit(("Current Size",))
    qtbot.addWidget(edit)
    qtbot.addWidget(lone)

    assert len(edit.rows) == 2
    assert len(lone.rows) == 1


def test_the_rows_share_one_grid_so_their_columns_line_up(qtbot: QtBot) -> None:
    """Both rows' cells are placed in the **editor's own** grid, column for column -- the reason this is one
    widget rather than two row bundles, which would each distribute their width alone (#232).

    **Test steps:**

    * build the editor
    * verify each row's spin box and copy button sit in the same grid columns, one grid row apart
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    grid = edit.layout()
    assert isinstance(grid, QGridLayout)

    for index, row in enumerate(edit.rows):
        editor = grid.indexOf(internal_spin_box(row))
        copy = grid.indexOf(internal_copy_button(row))
        assert grid.getItemPosition(editor) == (index, EDITOR_COLUMN, 1, 1)
        assert grid.getItemPosition(copy) == (index, COPY_COLUMN, 1, 1)


def test_the_measurement_spans_every_row(qtbot: QtBot) -> None:
    """The measured readout and the compute action span all the rows, because the measurement belongs to
    the whole group rather than to whichever row happened to host it (#232).

    **Test steps:**

    * build the editor
    * verify the readout and the compute button each span both rows in their own column
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    grid = edit.layout()
    assert isinstance(grid, QGridLayout)

    computed = grid.indexOf(internal_computed_label(edit))
    compute = grid.indexOf(internal_compute_button(edit))
    assert grid.getItemPosition(computed) == (0, COMPUTED_COLUMN, 2, 1)
    assert grid.getItemPosition(compute) == (0, COMPUTE_COLUMN, 2, 1)


def test_the_rows_take_equal_bands_of_the_editors_height(qtbot: QtBot) -> None:
    """The rows split the widget's height evenly, which is what a stacked label column beside it -- laid
    out with the same rule by `equal_height_column` -- lines itself up against.

    **Test steps:**

    * build and show the editor at a height neither row would ask for
    * verify both grid rows came out the same height
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
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
    """A fresh editor holds no stored size on any row, shows no measured one, and offers nothing to copy.

    **Test steps:**

    * build the widget
    * verify every value is unset, every readout empty, both copies disabled and compute offered
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    assert edit.computed is None
    assert edit.busy is False
    assert internal_computed_label(edit).text() == ""
    assert internal_compute_button(edit).isEnabled()
    for row in edit.rows:
        assert row.value is None
        assert internal_stored_label(row).text() == ""
        assert not internal_copy_button(row).isEnabled()


def test_each_rows_copy_names_the_field_it_stores_into(qtbot: QtBot) -> None:
    """The two copy buttons are icon-only and identical, so the tooltip is what says which size each one
    stores -- pressing the wrong one overwrites the denominator of *how much is left*.

    **Test steps:**

    * build the editor
    * verify each row's copy tooltip names that row's label
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    tooltips = [internal_copy_button(row).toolTip() for row in edit.rows]

    assert tooltips == ["Store the computed size in Original Size", "Store the computed size in Current Size"]


def test_every_spin_box_has_no_upper_bound(qtbot: QtBot) -> None:
    """Each row's spin box has a zero minimum (sizes are never negative) and no maximum -- a
    multi-terabyte resource overflows the C++ int32 ceiling by orders of magnitude (#40).

    **Test steps:**

    * build the widget
    * verify both spin boxes' ``minimum()``/``maximum()``
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    for row in edit.rows:
        assert internal_spin_box(row).minimum() == 0
        assert internal_spin_box(row).maximum() is None


@mark.parametrize(
    "readout",
    [
        param(lambda edit: internal_stored_label(edit.rows[0]), id="human-readable-readout"),
        param(internal_computed_label, id="computed-readout"),
    ],
)
def test_the_readouts_are_the_shared_read_only_readout(qtbot: QtBot, readout: object) -> None:
    """Every readout is the surface-agnostic `ValueReadout` -- framed, selectable, read-only -- rather
    than something this editor styles for itself, so the count row beside it cannot end up looking
    different. What that widget guarantees is pinned by its own tests.

    **Test steps:**

    * build the widget
    * verify the readout is a ``ValueReadout`` and names what it shows
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    label = readout(edit)  # type: ignore[operator]  # a parametrized accessor from this module

    assert isinstance(label, ValueReadout)
    assert label.toolTip() in (STORED_TOOLTIP, COMPUTED_TOOLTIP)


def test_editing_a_spin_box_writes_that_rows_value_through(qtbot: QtBot) -> None:
    """Each spin box is its own row's value: typing in one moves that row's ``value`` and no other.

    **Test steps:**

    * build the widget and set the second row's spin box
    * verify only that row's ``value`` followed
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    internal_spin_box(edit.rows[1]).setValue(5368709120)

    assert edit.rows[1].value == 5368709120
    assert edit.rows[0].value is None


def test_setting_a_rows_value_echoes_into_its_spin_box_and_human_reading(qtbot: QtBot) -> None:
    """A value set from outside (the model, or a copy) shows up in that row's spin box and in the readout
    beside it, with no feedback loop.

    **Test steps:**

    * build the widget and set the first row's ``value`` directly, as a bound model change would
    * verify its spin box holds the bytes, its readout shows them formatted, and the value survived
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    row = edit.rows[0]

    row.set_value(5368709120)  # type: ignore[attr-defined]  # the slot SimpleProperty synthesizes

    assert internal_spin_box(row).value == 5368709120
    assert internal_stored_label(row).text() == "5.0G"
    assert row.value == 5368709120


def test_a_stored_zero_reads_honestly_where_unmeasured_reads_empty(qtbot: QtBot) -> None:
    """The human readout keeps the absent/zero distinction the value itself carries
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * set a genuine ``0`` and verify the readout shows ``"0B"``
    * set ``None`` and verify it goes blank
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    row = edit.rows[0]

    row.set_value(0)  # type: ignore[attr-defined]
    assert internal_stored_label(row).text() == "0B"

    row.set_value(None)  # type: ignore[attr-defined]
    assert internal_stored_label(row).text() == ""


def test_a_value_beyond_int32_is_held_exactly(qtbot: QtBot) -> None:
    """A size far past the C++ int32 ceiling round-trips exactly through the spin box (the point of #40).

    **Test steps:**

    * set a petabyte-scale value
    * verify the value and the spin box hold it exactly, and the readout formats it
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    row = edit.rows[0]

    row.set_value(2**50)  # type: ignore[attr-defined]

    assert row.value == 2**50
    assert internal_spin_box(row).value == 2**50
    assert internal_stored_label(row).text() == "1.0P"


def test_compute_asks_the_owner_rather_than_measuring(qtbot: QtBot) -> None:
    """Pressing ``Compute`` only emits -- the widget knows nothing about files, paths, or settings.

    **Test steps:**

    * build the widget and press ``Compute``
    * verify ``compute_requested`` fired and no value changed
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    with qtbot.waitSignal(edit.compute_requested):
        internal_compute_button(edit).click()

    assert edit.computed is None
    assert [row.value for row in edit.rows] == [None, None]


def test_compute_makes_every_row_busy_and_disables_every_action(qtbot: QtBot) -> None:
    """A scan in flight disables everything on the edit: one scan answers both rows, so both wait for it
    and neither a second scan nor a copy of a half-finished answer may be pressed (#223, #232).

    **Test steps:**

    * build the editor over stored sizes with a stale measurement already showing, so both copies are offered
    * press ``Compute``
    * verify the editor and every row are busy, with all three buttons disabled
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    for row in edit.rows:
        row.set_value(1024)  # type: ignore[attr-defined]
    edit.computed = 2048
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
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(2048)

    assert edit.busy is False
    assert edit.computed == 2048
    assert internal_computed_label(edit).text() == "2048"
    assert internal_compute_button(edit).isEnabled()
    for row in edit.rows:
        assert row.computed == 2048
        assert internal_copy_button(row).isEnabled()


def test_a_failed_measurement_leaves_both_rows_empty_rather_than_half_a_state(qtbot: QtBot) -> None:
    """A scan that measured nothing still hands back an answer, and it reaches **every** row -- one
    measurement cannot leave one row showing a result and the other not (#232).

    **Test steps:**

    * press ``Compute``, then hand the widget ``None``
    * verify it is no longer busy, the readout is empty, no copy is offered, and compute is offered again
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    internal_compute_button(edit).click()

    edit.show_measurement(None)

    assert edit.busy is False
    assert internal_computed_label(edit).text() == ""
    assert internal_compute_button(edit).isEnabled()
    for row in edit.rows:
        assert row.computed is None
        assert not internal_copy_button(row).isEnabled()


def test_a_computed_size_is_shown_exactly_without_touching_any_value(qtbot: QtBot) -> None:
    """A measurement fills the one readout and leaves both stored sizes alone -- the disagreement is
    information, not something to silently resolve (#223).

    It is shown as an **exact byte count**, so it can be compared against either spin box digit for digit
    rather than through a rounded ``1.4G`` two different sizes would share.

    **Test steps:**

    * build the editor over stored sizes and hand it a computed ``5368709120``
    * verify the readout shows the exact bytes while both rows still read what they held
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    edit.rows[0].set_value(8192)  # type: ignore[attr-defined]
    edit.rows[1].set_value(1024)  # type: ignore[attr-defined]

    edit.computed = 5368709120

    assert internal_computed_label(edit).text() == "5368709120"
    assert [row.value for row in edit.rows] == [8192, 1024]


def test_a_computed_zero_shows_as_zero_not_as_nothing(qtbot: QtBot) -> None:
    """A measured ``0`` renders honestly, distinct from the empty "never measured" readout
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * hand the widget a computed ``0``
    * verify the readout reads ``"0"``
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)

    edit.computed = 0

    assert internal_computed_label(edit).text() == "0"


def test_each_rows_copy_is_offered_only_while_that_row_differs(qtbot: QtBot) -> None:
    """A copy enables exactly when the measurement disagrees with **that row's** stored size -- one scan,
    two independent answers to the question *is this one stale*.

    **Test steps:**

    * store two different sizes and compute one of them
    * verify only the disagreeing row offers a copy
    * bring that row into agreement and verify it stops offering one
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    original, current = edit.rows
    original.set_value(2048)  # type: ignore[attr-defined]
    current.set_value(1024)  # type: ignore[attr-defined]

    edit.computed = 2048

    assert not internal_copy_button(original).isEnabled()
    assert internal_copy_button(current).isEnabled()

    current.set_value(2048)  # type: ignore[attr-defined]
    assert not internal_copy_button(current).isEnabled()


def test_a_copy_stores_the_measurement_into_that_row_alone(qtbot: QtBot) -> None:
    """A copy is the one action here that changes a value -- and it changes exactly one:
    ``original_size`` is the denominator for *how much is left* ([[field-schema#duration-size]]).

    **Test steps:**

    * build the editor over two stale sizes with a measurement showing
    * press the second row's copy and verify its ``value_changed`` fired with the measured size
    * verify its spin box and human readout followed, and the first row is untouched
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    original, current = edit.rows
    original.set_value(8192)  # type: ignore[attr-defined]
    current.set_value(1024)  # type: ignore[attr-defined]
    edit.computed = 2048

    with qtbot.waitSignal(current.value_changed) as blocker:  # type: ignore[attr-defined]
        internal_copy_button(current).click()

    assert blocker.args == [2048]
    assert current.value == 2048
    assert internal_spin_box(current).value == 2048
    assert internal_stored_label(current).text() == "2.0K"
    assert not internal_copy_button(current).isEnabled()
    assert original.value == 8192


def test_an_unmeasurable_size_shows_nothing_and_copies_nothing(qtbot: QtBot) -> None:
    """A measurement that could not run (``None`` -- e.g. a document with no path yet) leaves the readout
    empty and every copy disabled, rather than offering to store "no size".

    **Test steps:**

    * build the editor over stored sizes and hand it a computed ``None``
    * verify the readout is empty and neither copy is offered
    """
    edit = SizeMeasurementEdit(ROW_LABELS)
    qtbot.addWidget(edit)
    for row in edit.rows:
        row.set_value(1024)  # type: ignore[attr-defined]

    edit.computed = None

    assert internal_computed_label(edit).text() == ""
    assert not any(internal_copy_button(row).isEnabled() for row in edit.rows)


# endregion
