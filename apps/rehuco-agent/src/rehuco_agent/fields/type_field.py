"""The special, editor-only `type` field: a combo selecting the document's resource type
([[plugins#plugin-blocks]], A4.3/#83).
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


class TypeField(Field[str]):
    """The special ``type`` field ([[plugins#plugin-blocks]], A4.3/#83): a single-choice combo the user
    selects the document's current type with -- the key of the one **active** plugin block.

    Three design rules carried from TutCatalog5's ``info_type`` prior art:

    - it is the field the user **selects the current file's type** with, so changing it re-resolves the
      whole form (the outgoing block's editors go away, the incoming block's render);
    - it is **never declared in the field config** -- the offered type list (``choices``) implies it,
      which is why its owner constructs it out-of-band (like the special ``path`` field), not through the
      registry from a ``(type, name)`` pair;
    - it is **editor-only** -- shown in the editor, never in the viewer -- so :meth:`make_viewer` returns
      an empty bundle and the assembler drops the row.

    Unlike a ``multi_choice`` toolkit field, the combo's items carry each type's **key** as their value
    and a readable label as their text (the empty type shows as :data:`NO_TYPE_LABEL`), so the bound
    value is always a block key, never its display spelling.

    :param name: the field's identifier on its model (``resource_type``).
    :param label: display label; derived from ``name`` when omitted.
    :param choices: the offerable type keys, in display order -- typically the model's
        ``available_types()`` with the current value ensured present. ``""`` is rendered as
        :data:`NO_TYPE_LABEL`, any other key title-cased.
    :param viewer_tab: the (unused) viewer surface; required by the base, but this field builds no viewer.
    :param editor_tab: the editor surface the combo belongs to.
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
        # editor-only: an all-``None`` bundle, so the assembler drops the row and, with no other type
        # widget on the viewer, keeps the type selector out of the read-only surface entirely
        return FieldViewerWidgets(self.viewer_tab, None, None)

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        editor = SingleChoiceComboBox([(key, self.__label_for(key)) for key in self.__choices])
        # pyright compares the class-level Signal against the protocol's SignalInstance and rejects the
        # descriptor duality PySide resolves at access time; the wiring is sound (see bind_value_widget).
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)

    @staticmethod
    def __label_for(key: str) -> str:
        """Readable label for a type key: the empty type's placeholder, else the key title-cased.

        :param key: the type key (a block key spelling, or ``""`` for no type).
        :returns: :data:`NO_TYPE_LABEL` for ``""``, otherwise the key with ``_`` split and title-cased.
        """
        return NO_TYPE_LABEL if not key else key.replace("_", " ").title()
