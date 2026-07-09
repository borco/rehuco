"""The `int` leaf field: a label viewer and an `UnboundedSpinBox` editor ([[plugins#field-toolkit]])."""

from typing import override

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QLabel, QWidget

from rehuco_agent.fields.field import Field, FieldBinding


class IntField(Field[int]):
    """A plain integer field ([[plugins#field-toolkit]], [[field-schema#field-types]]): a label viewer + an
    ``UnboundedSpinBox`` editor, live-bound to the binding. Covers ``images_count`` and ``collection_index``.

    No default range -- the schema calls ``int`` a *plain* integer ([[field-schema#field-types]]) with no
    stated ceiling, and ``UnboundedSpinBox`` (#40) has none of ``QSpinBox``'s int32 cap to box into
    either. ``minimum``/``maximum`` narrow it for a field whose real domain is bounded (e.g.
    :class:`~rehuco_agent.fields.rating_field.RatingField`'s ``-5``/``5`` -- though that field uses a
    slider, not this one, since ``rating`` is its own type, not ``int``).

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param minimum: the editor's minimum value; ``None`` (default) for no lower bound.
    :param maximum: the editor's maximum value; ``None`` (default) for no upper bound.
    """

    TYPE = "int"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> None:
        super().__init__(name, label)
        self.__minimum = minimum
        self.__maximum = maximum

    @override
    def make_viewer(self, binding: FieldBinding[int]) -> QWidget:
        label = QLabel(str(binding.value))
        binding.changed.connect(lambda value: label.setText(str(value)))
        return label

    @override
    def make_editors(self, binding: FieldBinding[int]) -> list[QWidget]:
        spin_box = UnboundedSpinBox(value=binding.value, minimum=self.__minimum, maximum=self.__maximum)
        spin_box.value_changed.connect(binding.set_value)  # type: ignore[attr-defined]
        binding.changed.connect(spin_box.setValue)
        return [spin_box]
