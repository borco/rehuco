"""The `bool` leaf field: a Yes/No label viewer and a `QCheckBox` editor ([[plugins#field-toolkit]])."""

from typing import Final, override

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QLabel

from .colors import WARNING_COLOR
from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets


class BooleanField(Field[bool]):
    """A boolean field ([[plugins#field-toolkit]], [[field-schema#boolean-flags]]): a Yes/No label viewer + a
    ``QCheckBox`` editor, live-bound to the binding.

    Covers the tc4 boolean flags ``complete`` / ``online`` / ``viewed`` / ``todo`` / ``keep`` and the new
    ``favorite`` ([[field-schema#boolean-flags]]). A field named in :attr:`WARN_WHEN_FALSE` (``complete``,
    "not all files present") paints its viewer in the warning color when false ([[field-schema#field-types]]).
    """

    TYPE = "bool"

    WARN_WHEN_FALSE: Final = frozenset({"complete"})
    """Field names whose viewer warns when false ([[field-schema#field-types]])."""

    WARNING_STYLESHEET: Final = f'QLabel[warning="true"] {{ color: {WARNING_COLOR}; }}'

    @override
    def make_viewer(self, binding: FieldBinding[bool]) -> FieldViewerWidgets:
        label = QLabel()
        if self.name in self.WARN_WHEN_FALSE:
            label.setStyleSheet(self.WARNING_STYLESHEET)
        self.__render(label, binding.value)
        self.bind_external(binding.changed, lambda value: self.__render(label, value))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[bool]) -> FieldEditorWidgets:
        checkbox = QCheckBox()
        checkbox.setChecked(binding.value)
        checkbox.toggled.connect(binding.set_value)
        self.bind_external(binding.changed, lambda value: self.__echo(checkbox, value))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), checkbox)

    def __render(self, label: QLabel, value: bool) -> None:
        """Show ``Yes``/``No`` and flag the warning state so the stylesheet can repaint it.

        :param label: the viewer label to update.
        :param value: the new boolean value.
        """
        label.setText("Yes" if value else "No")
        warning = self.name in self.WARN_WHEN_FALSE and not value
        if label.property("warning") != warning:
            label.setProperty("warning", warning)
            # re-polish so the ``[warning]`` property selector re-applies after the property flips
            style = label.style()
            style.unpolish(label)
            style.polish(label)

    @staticmethod
    def __echo(checkbox: QCheckBox, value: bool) -> None:
        """Update the editor from a binding change without re-emitting ``toggled`` (echo guard).

        :param checkbox: the editor to update.
        :param value: the new value.
        """
        if checkbox.isChecked() != value:
            with QSignalBlocker(checkbox):
                checkbox.setChecked(value)
