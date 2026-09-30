"""The `sources` leaf field: an editor of every source as a card, and no viewer of its own
([[plugins#field-toolkit]], [[field-schema#sources]]).
"""

from collections.abc import Sequence
from typing import Any, override

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .widgets import SourcesEditor


class SourcesField(Field[Sequence[dict[str, Any]]]):
    """A ``sources`` field ([[plugins#field-toolkit]], [[field-schema#sources]]): every place this resource is
    published, one card each, the top card being the primary.

    **Editor only.** The viewer keeps its Title, Publisher and URL rows, showing the primary source, so this
    field's viewer is an all-``None`` bundle the assembler drops (the ``TypeField`` idiom); those three are
    :class:`~rehuco_agent.fields.text_field.TextField` / :class:`~rehuco_agent.fields.url_field.UrlField`
    fields declared ``viewer_only``.

    Binds the model's ``sources`` (#386): the records as stored, top first and without the ``primary`` key, so
    an edit of one card writes back merged and the top one is the primary. Every source shows, always: there is
    no expand toggle in the row's misc column.
    """

    TYPE = "sources"

    @override
    def make_viewer(self, binding: FieldBinding[Sequence[dict[str, Any]]]) -> FieldViewerWidgets:
        return FieldViewerWidgets(self.viewer_tab, None, None)

    @override
    def make_editor(self, binding: FieldBinding[Sequence[dict[str, Any]]]) -> FieldEditorWidgets:
        editor = SourcesEditor()
        # the ignore: PySide types a class-level ``Signal`` as ``Signal``, not as the ``SignalInstance``
        # an *instance* actually exposes, so no widget declaring one ever satisfies a protocol naming it
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # value_changed is a class-level Signal
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
