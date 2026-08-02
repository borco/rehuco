"""Accessors for a measure row's internals -- `MeasuredValueEdit` exposes none by design (#224).

One module rather than a copy per row: the rows built on that base
(:class:`~rehuco_agent.fields.widgets.ContentCountEdit`,
:class:`~rehuco_agent.fields.widgets.MeasuredDurationEdit`) hold their pieces in the *base*'s private
attributes, so each test suite would otherwise spell the same five name-mangled lookups. The shared measurement's
internals live in :mod:`fields.widgets.shared_measurement_internals`, since it is a different widget (#232).
"""

from typing import Any

from PySide6.QtWidgets import QToolButton, QWidget
from rehuco_agent.fields.widgets.measured_value_edit import MeasuredValueEdit
from rehuco_agent.fields.widgets.value_readout import ValueReadout


def internal_editor(edit: MeasuredValueEdit) -> Any:
    """Return the row's stored-value editor -- a spin box or a `DurationEdit`, per the row.

    :param edit: the row to inspect.
    :returns: the internal editor widget, untyped because each row supplies a different one.
    """
    return edit._MeasuredValueEdit__editor  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_computed_label(edit: MeasuredValueEdit) -> ValueReadout:
    """Return the row's computed-value readout.

    :param edit: the row to inspect.
    :returns: the internal ``ValueReadout``.
    """
    return edit._MeasuredValueEdit__computed_label  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_apply_button(edit: MeasuredValueEdit) -> QToolButton:
    """Return the row's apply button.

    :param edit: the row to inspect.
    :returns: the internal ``QToolButton``.
    """
    return edit._MeasuredValueEdit__apply_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_compute_button(edit: MeasuredValueEdit) -> QToolButton:
    """Return the row's compute button.

    :param edit: the row to inspect.
    :returns: the internal ``QToolButton``.
    """
    return edit._MeasuredValueEdit__compute_button  # type: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def internal_row_widgets(edit: MeasuredValueEdit) -> list[QWidget]:
    """Return the row's widgets in layout order -- what a reader actually sees, left to right.

    :param edit: the row to inspect.
    :returns: the laid-out widgets.
    """
    layout = edit.layout()
    assert layout is not None
    widgets = (layout.itemAt(index) for index in range(layout.count()))
    return [widget for item in widgets if item is not None and (widget := item.widget()) is not None]
