"""The `int` leaf field: a label viewer and an `UnboundedSpinBox` editor ([[plugins#field-toolkit]])."""

from typing import override

from borco_pyside.widgets import UnboundedSpinBox
from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets


class IntField(Field[int | None]):
    """A plain integer field ([[plugins#field-toolkit]], [[field-schema#field-types]]): a label viewer + an
    ``UnboundedSpinBox`` editor, live-bound to the binding -- ``None`` (unset) renders/edits as empty,
    distinct from a genuine ``0``. Covers ``images_count`` and ``collection_index``.

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

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        minimum: int | None = None,
        maximum: int | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__minimum = minimum
        self.__maximum = maximum

    @override
    def make_viewer(self, binding: FieldBinding[int | None]) -> FieldViewerWidgets:
        label = QLabel(self.__label_text(binding.value))
        self.bind_external(binding.changed, lambda value: label.setText(self.__label_text(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @staticmethod
    def __label_text(value: int | None) -> str:
        """The viewer label's text for ``value``: the plain number, or ``""`` when unset.

        :param value: the field's current value.
        :returns: the display text.
        """
        return str(value) if value is not None else ""

    @override
    def make_editor(self, binding: FieldBinding[int | None]) -> FieldEditorWidgets:
        spin_box = UnboundedSpinBox(value=binding.value, minimum=self.__minimum, maximum=self.__maximum)
        spin_box.value_changed.connect(binding.set_value)  # type: ignore[attr-defined]
        binding.changed.connect(spin_box.setValue)
        return FieldEditorWidgets(self.editor_tab, self.make_label(), spin_box)
