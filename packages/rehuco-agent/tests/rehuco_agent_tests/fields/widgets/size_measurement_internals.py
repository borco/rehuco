"""Accessors for the size editor's internals -- `SizeMeasurementEdit` and `SizeRow` expose none by
design (#232).

Separate from :mod:`fields.widgets.duration_measurement_internals` for the reason the widgets are
separate: a size row is a human reading beside a byte spin box where a duration row is one editor, so the
two carry different pieces under different name-mangled attributes.
"""

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QToolButton
from rehuco_agent.fields.widgets.size_measurement_edit import SizeMeasurementEdit, SizeRow
from rehuco_agent.fields.widgets.value_readout import ValueReadout


def internal_computed_label(edit: SizeMeasurementEdit) -> ValueReadout:
    """Return the editor's one measured readout.

    :param edit: the editor to inspect.
    :returns: the internal ``ValueReadout``.
    """
    return edit._SizeMeasurementEdit__result.label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_compute_button(edit: SizeMeasurementEdit) -> QToolButton:
    """Return the editor's one compute button.

    :param edit: the editor to inspect.
    :returns: the internal ``QToolButton``.
    """
    return edit._SizeMeasurementEdit__result.button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_editor(row: SizeRow) -> UnboundedSpinBox:
    """Return one row's stored-size spin box.

    :param row: the row to inspect.
    :returns: the internal ``UnboundedSpinBox``.
    """
    return row._SizeRow__editor  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_stored_label(row: SizeRow) -> ValueReadout:
    """Return one row's leading human-readable readout.

    :param row: the row to inspect.
    :returns: the internal ``ValueReadout``.
    """
    return row._SizeRow__stored_label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_copy_button(row: SizeRow) -> QToolButton:
    """Return one row's copy button.

    :param row: the row to inspect.
    :returns: the internal ``QToolButton``.
    """
    return row._SizeRow__copy_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
