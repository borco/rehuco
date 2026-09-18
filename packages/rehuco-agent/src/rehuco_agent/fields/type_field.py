"""The special `type` field: a combo editor for the document's resource type
([[plugins#plugin-blocks]], #83).
"""

from collections.abc import Sequence
from typing import Final, override

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import SingleChoiceComboBox

NO_TYPE_LABEL: Final = "(no type)"
"""Display label for the empty type a brand-new document has ([[plugins#plugin-blocks]]) -- the value
is still ``""``, shown as a readable placeholder rather than a blank row. Only offered when the document
is actually type-less; a typed document's choice list omits it, so a type switch is never an
accidental *un*-set."""


def type_label(key: str) -> str:
    """Readable label for a type key: the empty type's placeholder, else the key title-cased.

    Shared between this field's own editor combo and `DocumentWidget`'s toolbar type badge (#309), which
    labels the same keys from outside this class.

    :param key: the type key (a block key spelling, or ``""`` for no type).
    :returns: :data:`NO_TYPE_LABEL` for ``""``, otherwise the key with ``_`` split and title-cased.
    """
    return NO_TYPE_LABEL if not key else key.replace("_", " ").title()


class TypeField(Field[str]):
    """The special ``type`` field ([[plugins#plugin-blocks]], #83): the key of the one **active**
    plugin block, edited as a combo. Editor-only -- the colored viewer badge this field used to show is
    now `DocumentWidget`'s own toolbar concern (#309), driven straight off the model rather than a field
    binding a form rebuild would destroy.

    Carried from TutCatalog5's ``info_type`` prior art: it is the field the user **selects the current
    file's type** with (so changing it re-resolves the whole form), and it is **never declared in the
    field config** -- the offered type list (``choices``) implies it, which is why its owner constructs it
    out-of-band (like the special ``path`` field), not through the registry from a ``(type, name)`` pair.

    **Editor** -- a single-choice combo listing the offered types (the empty type shown as
    :data:`NO_TYPE_LABEL`), whose value is always a block key, never its display spelling.

    :param name: the field's identifier on its model (``resource_type``).
    :param label: display label; derived from ``name`` when omitted.
    :param choices: the offerable type keys, in display order -- typically the model's
        ``available_types()`` with the current value ensured present. ``""`` is rendered as
        :data:`NO_TYPE_LABEL`, any other key title-cased.
    :param viewer_tab: the surface the (empty) viewer bundle belongs to.
    :param editor_tab: the surface the combo belongs to.
    """

    TYPE = "type"

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
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        # editor-only: an all-``None`` bundle, so the assembler drops the row
        return FieldViewerWidgets(self.viewer_tab, None, None)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        editor = SingleChoiceComboBox([(key, type_label(key)) for key in self.__choices])
        # pyright compares the class-level Signal against the protocol's SignalInstance and rejects the
        # descriptor duality PySide resolves at access time; the wiring is sound (see bind_value_widget).
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
