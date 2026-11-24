"""A size in whole bytes: the bytes in a spin box and a human reading of them beside it ([[plugins#field-toolkit]],
#678)."""

from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QHBoxLayout, QWidget
from rehuco_core import MAX_STORED_INTEGER

from .size_measurement_edit import SizeMeasurementEdit
from .value_readout import ValueReadout

READOUT_TOOLTIP: Final = "The size, human-readable"
"""What the readout shows, in words -- it carries no label of its own."""

SPIN_BOX_TOOLTIP: Final = "The size, in bytes"
"""What the spin box holds."""


class SizeEdit(QWidget):
    """One size a person states -- an advertised download size -- as ``[human reading] [byte spin box]``.

    The single-value counterpart of :class:`~.size_measurement_edit.SizeMeasurementEdit`'s rows, with nothing to
    measure: no scan of the disk says what a store's download weighs. ``None`` is unknown, distinct from a genuine
    ``0``, and the spin box stops at the largest size the cache can hold.

    :param parent: optional Qt parent.
    """

    value = SimpleProperty[int | None](None)
    """The size in whole bytes, or ``None`` when unknown -- the value-widget contract's property
    ([[plugins#field-toolkit]]); ``set_value`` is its slot. The spin box follows it rather than holding it, so a value
    set from anywhere lands in one place."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__readout: Final = ValueReadout(READOUT_TOOLTIP)
        self.__spin_box: Final = UnboundedSpinBox(value=None, minimum=0, maximum=MAX_STORED_INTEGER)
        self.__spin_box.setToolTip(SPIN_BOX_TOOLTIP)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__readout, 1)
        layout.addWidget(self.__spin_box, 1)
        self.__spin_box.value_changed.connect(self.set_value)  # type: ignore[attr-defined]
        self.value_changed.connect(self.__render)  # type: ignore[attr-defined]
        self.__render(None)

    def __render(self, value: int | None) -> None:
        """Echo a change into the spin box and the readout.

        The guard is a compare against what the spin box already holds: its own edit reaches :attr:`value` through
        the connection this echoes back over, and writing the value it holds is where that stops.

        :param value: the new size.
        """
        if self.__spin_box.value != value:
            self.__spin_box.setValue(value)
        self.__readout.setText(SizeMeasurementEdit.format(value))
