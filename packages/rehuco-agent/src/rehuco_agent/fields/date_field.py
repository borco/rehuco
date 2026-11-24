"""The `date` leaf field: partial-precision (Y / Y-M / Y-M-D) text, edited via an opaque `DateEdit`
([[plugins#field-toolkit]]).
"""

from typing import Final, override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .local_time import local_time_text
from .widgets import DateEdit


class DateField(Field[str | None]):
    """A ``date`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): **partial-precision**
    -- stored and edited as the ``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD`` ISO-prefix string it is on
    disk ([[field-schema#deferred-items]]), never parsed into (or held as) a full calendar date --
    edited via :class:`~rehuco_agent.fields.widgets.DateEdit`. The viewer is a plain label showing
    the stored string as-is, or nothing when unreleased/unknown (``None``). Covers ``released`` and an asset's
    ``source_updated``.

    **Or a UTC time** (``with_time``, #678): an asset's ``acquired`` is a time where the store gives one. The editor
    keeps the stored time through every keystroke, and the viewer shows it in local time, as the browser's columns do
    (#623); a plain date is shown as stored.

    :param name: the model field this binds.
    :param label: the row's caption; derived from ``name`` when omitted.
    :param with_time: whether a stored UTC time is kept and shown in local time.
    """

    TYPE = "date"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        with_time: bool = False,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__with_time: Final = with_time

    @override
    def make_viewer(self, binding: FieldBinding[str | None]) -> FieldViewerWidgets:
        label = QLabel(self.__text(binding.value))
        self.bind_external(binding.changed, lambda value: label.setText(self.__text(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    def __text(self, value: str | None) -> str:
        """What the viewer shows for a stored value.

        :param value: the stored date or time, or ``None``.
        :returns: the date as stored, a time in local time, or nothing.
        """
        if not value:
            return ""
        return (local_time_text(value) if self.__with_time else None) or value

    @override
    def make_editor(self, binding: FieldBinding[str | None]) -> FieldEditorWidgets:
        editor = DateEdit(with_time=self.__with_time)
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
