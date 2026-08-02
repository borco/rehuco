"""Tests for SharedMeasurementEdit's own shape, apart from the sizes built on it: a group whose rows
carry no leading human reading, because their stored editor already is one.
"""

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QGridLayout
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.shared_measurement_edit import (
    EDITOR_COLUMN,
    STORED_COLUMN,
    SharedMeasurementEdit,
    SharedMeasurementRow,
)

COMPUTE_ICON_RESOURCE = ":/icons/measure_duration.svg"
"""Any themed action icon: which one is the concrete group's business, not this base's."""


@fixture
def bare_group(qtbot: QtBot) -> SharedMeasurementEdit:
    """A two-row group whose rows asked for **no** leading readout -- the shape the durations take, since
    `DurationEdit` carries the human reading itself (#233).

    :param qtbot: the pytest-qt bot the widget is registered with.
    :returns: the group.
    """
    rows = []
    for label in ("First", "Second"):
        spin_box = UnboundedSpinBox(value=None, minimum=0)
        rows.append(
            SharedMeasurementRow(
                spin_box,  # type: ignore[arg-type]  # the SimpleProperty descriptor duality
                set_editor_value=spin_box.setValue,
                copy_tooltip=f"Store the computed value in {label}",
            )
        )
    group = SharedMeasurementEdit(
        rows,
        compute_icon=COMPUTE_ICON_RESOURCE,
        compute_tooltip="Measure",
        computed_tooltip="What was measured",
    )
    qtbot.addWidget(group)
    return group


def test_a_row_without_a_format_leaves_its_reading_column_empty(bare_group: SharedMeasurementEdit) -> None:
    """A row whose editor is already a human reading adds no readout -- and leaves the column empty
    rather than filling it with a blank frame that would read as a missing value.

    **Test steps:**

    * build a group whose rows asked for no leading readout
    * verify nothing was placed in the reading column, while the editors are in theirs
    """
    grid = bare_group.layout()
    assert isinstance(grid, QGridLayout)

    for index, row in enumerate(bare_group.rows):
        assert grid.itemAtPosition(index, STORED_COLUMN) is None
        assert grid.itemAtPosition(index, EDITOR_COLUMN) is not None
        del row


def test_a_row_without_a_format_still_echoes_its_value_into_its_editor(bare_group: SharedMeasurementEdit) -> None:
    """Dropping the leading reading changes nothing about the binding: the stored value still lands in
    the editor, which is the one place it lives.

    **Test steps:**

    * set one row's value
    * verify its editor followed and the other row is untouched
    """
    first, second = bare_group.rows

    first.set_value(4096)  # type: ignore[attr-defined]  # the slot SimpleProperty synthesizes

    assert first.value == 4096
    assert second.value is None


def test_a_measurement_still_reaches_every_row(bare_group: SharedMeasurementEdit) -> None:
    """One measurement, every row -- the group's whole reason for existing, independent of what each row
    shows beside its editor.

    **Test steps:**

    * hand the group a measurement
    * verify both rows hold it
    """
    bare_group.show_measurement(2048)

    assert [row.computed for row in bare_group.rows] == [2048, 2048]
