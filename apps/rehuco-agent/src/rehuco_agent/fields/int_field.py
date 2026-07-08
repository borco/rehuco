"""The `int` leaf field: a label viewer and a `QSpinBox` editor ([[plugins#field-toolkit]])."""

from typing import Final, override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QLabel, QSpinBox, QWidget

from rehuco_agent.fields.field import Field, FieldBinding


class IntField(Field[int]):
    """A plain integer field ([[plugins#field-toolkit]], [[field-schema#field-types]]): a label viewer + a
    ``QSpinBox`` editor, live-bound to the binding. Covers ``images_count`` and ``collection_index``.

    The spin box spans the full 32-bit signed range by default, so negatives are allowed -- the schema
    calls ``int`` a *plain* integer ([[field-schema#field-types]]). ``minimum``/``maximum`` narrow that
    range (e.g. :class:`~rehuco_agent.fields.rating_field.RatingField`'s ``-5``/``5`` default); either is
    boxed to :attr:`MINIMUM`/:attr:`MAXIMUM` when omitted or when it would widen past them.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param minimum: the editor's minimum value; defaults to :attr:`MINIMUM`.
    :param maximum: the editor's maximum value; defaults to :attr:`MAXIMUM`.
    """

    TYPE = "int"

    # TODO(#40): remove once IntField uses UnboundedSpinBox instead of QSpinBox's native int32 range.
    MINIMUM: Final = -2_147_483_648
    MAXIMUM: Final = 2_147_483_647

    def __init__(
        self,
        name: str,
        label: str | None = None,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> None:
        super().__init__(name, label)
        self.__min = self.MINIMUM if minimum is None else max(minimum, self.MINIMUM)
        self.__max = self.MAXIMUM if maximum is None else min(maximum, self.MAXIMUM)

    @override
    def make_viewer(self, binding: FieldBinding[int]) -> QWidget:
        label = QLabel(str(binding.value))
        binding.changed.connect(lambda value: label.setText(str(value)))
        return label

    @override
    def make_editors(self, binding: FieldBinding[int]) -> list[QWidget]:
        # TODO(#40): replace with UnboundedSpinBox (arbitrary-precision, not int32-capped).
        spin_box = QSpinBox()
        spin_box.setRange(self.__min, self.__max)
        spin_box.setValue(binding.value)
        spin_box.valueChanged.connect(binding.set_value)
        binding.changed.connect(lambda value: self.__echo(spin_box, value))
        return [spin_box]

    @staticmethod
    def __echo(spin_box: QSpinBox, value: int) -> None:
        """Update the editor from a binding change without re-emitting ``valueChanged`` (echo guard).

        :param spin_box: the editor to update.
        :param value: the new value.
        """
        if spin_box.value() != value:
            with QSignalBlocker(spin_box):
                spin_box.setValue(value)
