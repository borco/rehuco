"""The special `type` field: a combo editor and a colored viewer badge for the document's resource type
([[plugins#plugin-blocks]], A4.3/#83).
"""

from collections.abc import Callable, Sequence
from typing import Final, override

from PySide6.QtWidgets import QHBoxLayout, QWidget

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import SingleChoiceComboBox, TypeBadge

NO_TYPE_LABEL: Final = "(no type)"
"""Display label for the empty type a brand-new document has ([[plugins#plugin-blocks]]) -- the value
is still ``""``, shown as a readable placeholder rather than a blank row. Only offered when the document
is actually type-less; a typed document's choice list omits it, so a type switch is never an
accidental *un*-set."""


class TypeField(Field[str]):
    """The special ``type`` field ([[plugins#plugin-blocks]], A4.3/#83): the key of the one **active**
    plugin block, edited as a combo and shown in the viewer as a colored badge.

    Carried from TutCatalog5's ``info_type`` prior art: it is the field the user **selects the current
    file's type** with (so changing it re-resolves the whole form), and it is **never declared in the
    field config** -- the offered type list (``choices``) implies it, which is why its owner constructs it
    out-of-band (like the special ``path`` field), not through the registry from a ``(type, name)`` pair.

    **Editor** -- a single-choice combo listing the offered types (the empty type shown as
    :data:`NO_TYPE_LABEL`), whose value is always a block key, never its display spelling.

    **Viewer** -- a small colored :class:`~rehuco_agent.fields.widgets.type_badge.TypeBadge` in the
    surface's top-right corner, painted with the colors the resource's **plugin declares**
    (:attr:`~rehuco_core.PluginSpec.color` / ``text_color``), resolved through ``colors_for`` and each
    falling back to the theme's selection color when the plugin declares none. tc5 kept the type
    editor-only; here the viewer shows it as a badge (the predecessor's top-right colored rectangle), so
    ``colors_for`` is what turns the viewer badge on -- omit it for a purely editor-only field. The empty
    type shows no badge.

    :param name: the field's identifier on its model (``resource_type``).
    :param label: display label; derived from ``name`` when omitted.
    :param choices: the offerable type keys, in display order -- typically the model's
        ``available_types()`` with the current value ensured present. ``""`` is rendered as
        :data:`NO_TYPE_LABEL`, any other key title-cased.
    :param colors_for: resolves a type key to its badge ``(background, text)`` colors, each a hex string
        or ``None`` to fall back to the theme's selection color (the plugin's declared colors, via the
        registry); omit for an editor-only field with no viewer badge.
    :param viewer_tab: the surface the viewer badge belongs to.
    :param editor_tab: the surface the combo belongs to.
    """

    TYPE = "type"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        choices: Sequence[str] = (),
        colors_for: Callable[[str], tuple[str | None, str | None]] | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__choices: Final = tuple(choices)
        self.__colors_for: Final = colors_for

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        if self.__colors_for is None:
            # editor-only: an all-``None`` bundle, so the assembler drops the row
            return FieldViewerWidgets(self.viewer_tab, None, None)
        badge = TypeBadge(self.__colors_for, self.__label_for)
        badge.on_type(binding.value)
        # bound-method slot, not a lambda: Qt drops this connection when the badge is destroyed (a
        # form rebuild on a type switch), so it never fires into a deleted widget ([[plugins#plugin-blocks]])
        binding.changed.connect(badge.on_type)
        # a full-width row whose leading stretch pushes the badge to the right, so it sits in the
        # surface's top-right corner (this field leads, so its viewer row is the top one)
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        row.addWidget(badge)
        return FieldViewerWidgets(self.viewer_tab, None, container, vertical=True)

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
