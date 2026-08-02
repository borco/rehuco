"""Accessors for a shared measurement's internals -- `SharedMeasurementEdit` and
`SharedMeasurementRow` expose none by design (#232).

The counterpart of :mod:`fields.widgets.measure_row_internals`, and separate from it for the reason
the widgets are separate: the pieces sit on two different classes, the group owning the one measurement
and each row owning its own stored value and copy action.
"""

from typing import Any

from PySide6.QtWidgets import QToolButton
from rehuco_agent.fields.widgets.shared_measurement_edit import SharedMeasurementEdit, SharedMeasurementRow
from rehuco_agent.fields.widgets.value_readout import ValueReadout


def internal_computed_label(edit: SharedMeasurementEdit) -> ValueReadout:
    """Return the group's one measured readout.

    :param edit: the group to inspect.
    :returns: the internal ``ValueReadout``.
    """
    return edit._SharedMeasurementEdit__computed_label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_compute_button(edit: SharedMeasurementEdit) -> QToolButton:
    """Return the group's one compute button.

    :param edit: the group to inspect.
    :returns: the internal ``QToolButton``.
    """
    return edit._SharedMeasurementEdit__compute_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_editor(row: SharedMeasurementRow) -> Any:
    """Return one row's stored-value editor -- a spin box or a `DurationEdit`, per the group.

    :param row: the row to inspect.
    :returns: the internal editor widget, untyped because each group supplies a different one.
    """
    return row._SharedMeasurementRow__editor  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_stored_label(row: SharedMeasurementRow) -> ValueReadout:
    """Return one row's leading human-readable readout.

    :param row: the row to inspect.
    :returns: the internal ``ValueReadout``; ``None`` on a group whose rows asked for none.
    """
    return row._SharedMeasurementRow__stored_label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_copy_button(row: SharedMeasurementRow) -> QToolButton:
    """Return one row's copy button.

    :param row: the row to inspect.
    :returns: the internal ``QToolButton``.
    """
    return row._SharedMeasurementRow__copy_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
