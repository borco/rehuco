"""The read-only readout a measure row shows a number in ([[plugins#field-toolkit]], #198, #223)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QWidget


class ValueReadout(QLabel):
    """One framed, selectable, read-only number on a measure row -- the computed value beside the stored
    one, and the stored one's human reading beside its spin box.

    **Framed, not bare.** A computed readout is empty until ``Compute`` is pressed, and an unframed empty
    label is invisible: the row reads as missing a widget rather than as waiting for one. The border is
    what makes it an **anchor rather than a gap**, and it frames the row's controls the same way the
    editors around them are framed.

    **A label, not a read-only line edit.** It is a reading of a value, never a second place to enter
    one, and a `QLabel` says so with no ``setReadOnly`` to be undone later. Selectable, so an exact byte
    count can be copied out and pasted somewhere it can be compared.

    Shared by every measure surface -- the single-value rows built on
    :class:`~rehuco_agent.fields.widgets.MeasuredValueEdit`, the size pair's stored readings, and both
    pairs' spanning measurement (:class:`~rehuco_agent.fields.widgets.MeasurementResult`) -- so a change of
    look lands on all of them at once: they sit on the same form, where one framed readout and one bare
    one read as a bug.

    :param tooltip: what this readout shows, in words -- it carries no label of its own.
    :param parent: optional Qt parent.
    """

    def __init__(self, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setToolTip(tooltip)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
