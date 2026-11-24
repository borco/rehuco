"""The `string_map` leaf field: a table of keys and the values they map to ([[plugins#field-toolkit]], #678)."""

from typing import Final, override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import StringMapValueEditor


class StringMapField(Field[dict[str, str]]):
    """A map of text to text ([[plugins#field-toolkit]], [[field-schema#field-types]]): a label of one ``key: value``
    line per entry and a two-column :class:`~rehuco_agent.fields.widgets.StringMapValueEditor`. Covers an asset's
    ``compatibility``, what it works with and in which versions ([[assets#block]]).

    A row with no key, or a key an earlier row has, is flagged in the table and left out of the value; a row still
    waiting for its key is kept while the rest is written.

    :param name: the model field this binds.
    :param label: the row's caption; derived from ``name`` when omitted.
    :param key_title: the key column's header.
    :param value_title: the value column's header.
    """

    TYPE = "string_map"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        key_title: str = "Key",
        value_title: str = "Value",
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__key_title: Final = key_title
        self.__value_title: Final = value_title

    @override
    def make_viewer(self, binding: FieldBinding[dict[str, str]]) -> FieldViewerWidgets:
        label = QLabel(self.__lines(binding.value))
        label.setWordWrap(True)
        self.bind_external(binding.changed, lambda value: label.setText(self.__lines(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[dict[str, str]]) -> FieldEditorWidgets:
        editor = StringMapValueEditor()
        editor.set_titles(self.__key_title, self.__value_title)
        # the ignore: PySide types a class-level ``Signal`` as ``Signal``, not as the ``SignalInstance`` an
        # *instance* exposes, so no widget declaring one ever satisfies the protocol statically
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # value_changed is a class-level Signal
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)

    @staticmethod
    def __lines(value: dict[str, str]) -> str:
        """One ``key: value`` line per entry, in the map's order.

        :param value: the map.
        :returns: the text; empty for an empty map.
        """
        return "\n".join(f"{key}: {text}" for key, text in value.items())
