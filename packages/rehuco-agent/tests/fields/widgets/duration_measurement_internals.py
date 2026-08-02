"""Accessors for the duration editor's internals -- `DurationMeasurementEdit` and `DurationRow` expose
none by design (#233).

Separate from :mod:`fields.widgets.size_measurement_internals` for the reason the widgets are separate: a
duration row is one `DurationEdit` carrying its own human reading where a size row is a readout beside a
spin box, so there is no leading-readout accessor here at all.
"""

from PySide6.QtWidgets import QToolButton
from rehuco_agent.fields.widgets.duration_edit import DurationEdit
from rehuco_agent.fields.widgets.duration_measurement_edit import DurationMeasurementEdit, DurationRow
from rehuco_agent.fields.widgets.value_readout import ValueReadout


def internal_computed_label(edit: DurationMeasurementEdit) -> ValueReadout:
    """Return the editor's one measured readout.

    :param edit: the editor to inspect.
    :returns: the internal ``ValueReadout``.
    """
    return edit._DurationMeasurementEdit__result.label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_compute_button(edit: DurationMeasurementEdit) -> QToolButton:
    """Return the editor's one compute button.

    :param edit: the editor to inspect.
    :returns: the internal ``QToolButton``.
    """
    return edit._DurationMeasurementEdit__result.button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_editor(row: DurationRow) -> DurationEdit:
    """Return one row's stored-duration editor.

    :param row: the row to inspect.
    :returns: the internal ``DurationEdit``.
    """
    return row._DurationRow__editor  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_copy_button(row: DurationRow) -> QToolButton:
    """Return one row's copy button.

    :param row: the row to inspect.
    :returns: the internal ``QToolButton``.
    """
    return row._DurationRow__copy_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
