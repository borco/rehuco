"""The `collections` leaf field: the memberships viewer, and a table to edit them in
([[plugins#field-toolkit]], [[field-schema#sources]]).
"""

from collections.abc import Sequence
from typing import Any, override

from rehuco_core import CollectionEntry, collection_entries

from .field import FieldBinding, FieldEditorWidgets
from .indexed_list_field import IndexedListField
from .widgets import CollectionsEditor


class CollectionsField(IndexedListField[Sequence[dict[str, Any]]]):
    """A ``collections`` field ([[plugins#field-toolkit]], [[field-schema#sources]]): the publisher-defined
    series this resource belongs to, and its position in each.

    Binds the **stored records**, not the display projection, because the editor writes one back merged --
    a title cell that rebuilt its record from the two columns it shows would sever the ``url`` the
    collection owns (#235). The viewer's sorted ``Title [3]`` line is
    :func:`~rehuco_core.collection_entries` applied to the same value, so the two surfaces never disagree
    about what is in the field, only about what they do with it.
    """

    TYPE = "collections"

    @override
    def entries(self, value: Sequence[dict[str, Any]]) -> Sequence[CollectionEntry]:
        return collection_entries(list(value))

    @override
    def make_editor(self, binding: FieldBinding[Sequence[dict[str, Any]]]) -> FieldEditorWidgets:
        editor = CollectionsEditor()
        # the ignore: PySide types a class-level ``Signal`` as ``Signal``, not as the ``SignalInstance``
        # an *instance* actually exposes, so no widget declaring one ever satisfies a protocol naming it
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # value_changed is a class-level Signal
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
