"""The `multi_choice` leaf field: zero or more values from a fixed set, shown as a `FlowLayout` of
checkboxes ([[plugins#field-toolkit]]).
"""

from collections.abc import Sequence
from typing import Final, override

from borco_pyside.widgets import FlowLayout
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QLabel, QWidget

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets


class MultipleChoiceField(Field[list[str]]):
    """A ``multi_choice`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): zero or
    more values from a fixed ``choices`` set, shown as a `FlowLayout`
    (:class:`~borco_pyside.widgets.FlowLayout`) of checkboxes -- covers ``level``
    ([[field-schema#field-mapping]]), which tc4 could tag with more than one of
    beginner/intermediate/advanced/any at once, so this stays multi-select rather than
    mutually-exclusive.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param choices: the fixed, ordered set of selectable values; defaults empty since the
        registry's uniform ``create(type_, name, label)`` call site can't supply one -- pass the
        real set when constructing this field directly for actual use.
    """

    TYPE = "multi_choice"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        choices: Sequence[str] = (),
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__choices: Final = tuple(choices)

    @override
    def make_viewer(self, binding: FieldBinding[list[str]]) -> FieldViewerWidgets:
        label = QLabel(self.__display(binding.value))
        label.setWordWrap(True)
        binding.changed.connect(lambda value: label.setText(self.__display(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[list[str]]) -> FieldEditorWidgets:
        container = QWidget()
        layout = FlowLayout(container)
        checkboxes: dict[str, QCheckBox] = {}
        for choice in self.__choices:
            checkbox = QCheckBox(choice)
            checkbox.setChecked(choice in binding.value)
            layout.addWidget(checkbox)
            checkboxes[choice] = checkbox
        for checkbox in checkboxes.values():
            checkbox.toggled.connect(lambda _checked: self.__on_toggled(binding, checkboxes))
        binding.changed.connect(lambda value: self.__echo(checkboxes, value))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), container)

    def __on_toggled(self, binding: FieldBinding[list[str]], checkboxes: dict[str, QCheckBox]) -> None:
        """Write the checkboxes' current combined state through to the binding, in ``choices`` order.

        Reads every checkbox's live ``isChecked()`` rather than ``binding.value`` -- the latter is
        the snapshot the binding was resolved with, not a live getter, so it wouldn't see this
        same handler's own prior toggles within one editor.

        :param binding: the binding to write the updated list through.
        :param checkboxes: the choice -> checkbox map to read the current selection from.
        """
        binding.set_value([choice for choice in self.__choices if checkboxes[choice].isChecked()])

    def __display(self, values: list[str]) -> str:
        """Join the selected values for the read-only viewer, in ``choices`` order.

        :param values: the bound list of selected choices.
        :returns: the comma-joined display text.
        """
        selected = set(values)
        return ", ".join(choice for choice in self.__choices if choice in selected)

    @staticmethod
    def __echo(checkboxes: dict[str, QCheckBox], values: list[str]) -> None:
        """Resync every checkbox from a binding change without re-emitting ``toggled`` (echo guard).

        :param checkboxes: the choice -> checkbox map to resync.
        :param values: the new bound list.
        """
        selected = set(values)
        for choice, checkbox in checkboxes.items():
            wanted = choice in selected
            if checkbox.isChecked() != wanted:
                with QSignalBlocker(checkbox):
                    checkbox.setChecked(wanted)
