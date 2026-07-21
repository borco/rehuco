"""The generic `unknown` fallback field: an unrecognized field value -- a common top-level key or a
key in the active plugin block the software here doesn't understand -- carried verbatim, with a remove action
in the editor ([[plugins#fallback-editor]], §13.3/§13.4).
"""

from collections.abc import Callable
from typing import Any, Final, override

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from .colors import WARNING_COLOR
from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets

REMOVE_ICON_RESOURCE: Final = ":/icons/document_remove_unknown_field.svg"
"""The editor remove action's theme-aware icon ([[plugins#fallback-editor]])."""

PROVENANCE_NEWER_VERSION: Final = (
    "This field isn't recognized here -- it likely comes from a newer version of the app or one of "
    "its plugins. It is kept as-is; upgrade to edit it."
)
"""Provenance for a field the software here doesn't recognize because it comes from a **newer version**
than what's installed ([[plugins#fallback-editor]]) -- deliberately source-agnostic, since in A2.8 a
newer **common** top-level key and a newer **plugin-block** key are indistinguishable (there's no
core-version/plugin-registry model yet to tell them apart). The plugin-absent provenance still lands
later, with A4.4's real fallback UI ([[plugins#fallback-editor]])."""

PROVENANCE_NOT_CURRENT_TYPE: Final = (
    "This block isn't the one this file's type names, so it isn't editable here. It is kept as-is."
)
"""Provenance for a whole **inactive** plugin block ([[plugins#plugin-blocks]]) -- one this file's
``type`` doesn't name. Distinct from :data:`PROVENANCE_NEWER_VERSION` because the two are different
situations the user resolves differently ([[plugins#fallback-editor]]): a newer-version field wants an
upgrade, whereas an inactive block is simply payload this file is custodian of. Deliberately says
nothing about whether the block's plugin is installed -- that never affects the answer, since only the
type decides what is active.

Worded to stay true of the one case this can't tell apart: an object-valued top-level key added to the
**common core** by a newer build is structurally identical to an uninstalled plugin's block
(:data:`~rehuco_core.COMMON_FIELD_KEYS`), so it classifies as an inactive block here. Saying only that
the file's ``type`` doesn't name it is accurate either way; separating the three real provenances
(newer-plugin / plugin-absent / not-this-type) is A4.4's ([[plugins#fallback-editor]])."""


PROVENANCE_ABANDONED_TYPE: Final = (
    "You switched away from this type this session, so saving will delete this block. Switch back to "
    "this type before saving to keep it."
)
"""Provenance for a **claimed-then-abandoned** inactive block ([[plugins#plugin-blocks]], A4.3/#83) --
one made active this session and then switched away from, so the block persistence invariant (#82)
**drops it on save**. Distinct from :data:`PROVENANCE_NOT_CURRENT_TYPE` (a never-claimed foreign block,
carried verbatim) because the two are exactly the safety-net contrast the spec asks the editor to make
visible: switching to a type merely to preview it arms its deletion, and the wording tells the user the
block will be lost on save and how to keep it -- where a foreign block says only that it is kept as-is."""


class UnknownField(Field[Any]):
    """The generic fallback for an unrecognized field -- a common top-level key, a key in the active
    plugin block the software here doesn't understand, or a whole inactive block
    ([[plugins#fallback-editor]], §13.3/§13.4).

    Source-agnostic: the field never inspects where its value lives; its owner supplies the
    ``current_value``/``is_present``/``on_remove`` callbacks, so the same class serves a common field
    and a plugin-block field alike.

    Flagged by **provenance** (why it's unrecognized) and **carried verbatim by default** -- the value
    is shown but not edited (migrate-to-known-field is deferred, §13.3). The viewer marks it so it
    stands out; the editor adds a **remove** action (in the row's middle/misc column) that drops the
    field via ``on_remove``. An
    unremoved unknown field is preserved untouched on round-trip ([[data-model#schema-version]]).

    **Reactive to the block's live state.** When ``is_present``/``current_value`` are supplied, the
    field's whole row (on *both* the editor and the viewer -- this same instance builds both) shows or
    hides and re-reads its value on every ``binding.changed`` (the model's ``unknown_fields_changed``).
    So removing it hides both rows at once, and a **revert** that restores the key brings both rows
    back with the value re-read from disk. Without those callbacks it is static (built once, no live
    tracking) -- the shape a viewer-only presentation uses.

    Constructed out-of-band by its owner (the document field composition), one per unknown key, not
    resolved generically through the registry -- the registry has no class for an unknown ``type`` and
    the provenance/remove wiring is owner-supplied, the same shape as the special ``path`` field.

    :param name: the unknown key (a common top-level key, a key in the active plugin block, or an
        inactive block's own key).
    :param label: display label; derived from ``name`` when omitted.
    :param provenance: the human-readable reason this field is flagged (e.g.
        :data:`PROVENANCE_NEWER_VERSION`); shown as the value's tooltip.
    :param on_remove: called with no arguments when the editor's remove button is clicked, to drop
        the field; omit for a viewer-only, non-removable presentation.
    :param is_present: called with no arguments for whether the key still exists; drives the row's
        visibility on every change. Omit for a static (non-reactive) field.
    :param current_value: called with no arguments for the key's current raw value, re-read into the
        value labels on every change (e.g. after a revert restores it). Omit to keep the initial value.
    :param viewer_tab: the surface this field's viewer belongs to.
    :param editor_tab: the surface this field's editor belongs to.
    """

    TYPE = "unknown"

    WARNING_STYLESHEET: Final = f'QLabel[unknown="true"] {{ color: {WARNING_COLOR}; }}'
    """Paints the flagged value in the warning color so an unknown field stands out ([[plugins#fallback-editor]])."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        *,
        provenance: str = PROVENANCE_NEWER_VERSION,
        on_remove: Callable[[], None] | None = None,
        is_present: Callable[[], bool] | None = None,
        current_value: Callable[[], Any] | None = None,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__provenance: Final = provenance
        self.__on_remove: Final = on_remove
        self.__is_present: Final = is_present
        self.__current_value: Final = current_value
        # every widget this field puts on either surface, so a removal (or a revert) can hide/show its
        # whole row on *both* the editor and the viewer at once (this same instance builds both)
        self.__row_widgets: Final[list[QWidget]] = []
        # just the value labels, refreshed with the re-read value when the block changes
        self.__value_labels: Final[list[QLabel]] = []

    @override
    def make_viewer(self, binding: FieldBinding[Any]) -> FieldViewerWidgets:
        label = self.make_label()
        value = self.__make_value_label(binding.value)
        self.__track(binding, label, value)
        return FieldViewerWidgets(self.viewer_tab, label, value)

    @override
    def make_editor(self, binding: FieldBinding[Any]) -> FieldEditorWidgets:
        value = self.__make_value_label(binding.value)
        button: QToolButton | None = None
        on_remove = self.__on_remove
        if on_remove is not None:
            button = QToolButton()
            remove_action = QAction(button)
            remove_action.setToolTip("Drop this unrecognized field from the file")
            ActionIconThemeHandler(remove_action, REMOVE_ICON_RESOURCE)
            remove_action.triggered.connect(lambda: self.__remove(on_remove))
            button.setDefaultAction(remove_action)
        label = self.make_label()
        self.__track(binding, label, button, value)
        return FieldEditorWidgets(self.editor_tab, label, value, misc=button)

    def __make_value_label(self, value: Any) -> QLabel:
        """Build the flagged, verbatim value label, tooltip-marked with the provenance.

        :param value: the unknown field's raw stored value, rendered as text.
        :returns: a warning-colored, word-wrapping `QLabel` showing the value.
        """
        label = QLabel(str(value))
        label.setWordWrap(True)
        label.setProperty("unknown", True)
        label.setStyleSheet(self.WARNING_STYLESHEET)
        label.setToolTip(self.__provenance)
        self.__value_labels.append(label)
        return label

    def __track(self, binding: FieldBinding[Any], *widgets: QWidget | None) -> None:
        """Record a row's widgets and, when reactive, wire its refresh to the block-change signal.

        :param binding: the field binding, whose ``changed`` signal (the model's
            ``unknown_fields_changed``) drives the row's live show/hide + value refresh.
        :param widgets: the row's widgets (label, value, container); ``None`` slots are skipped.
        """
        self.__row_widgets.extend(widget for widget in widgets if widget is not None)
        if self.__is_present is not None:
            binding.changed.connect(lambda *_: self.__refresh())

    def __remove(self, on_remove: Callable[[], None]) -> None:
        """Drop the field via ``on_remove``, then reconcile its rows to the block's new state.

        :meth:`__refresh` hides the whole row on both surfaces once the key is gone (an absent key,
        or a non-reactive field with no ``is_present``, reads as not-present -> hidden).

        :param on_remove: the owner callback that drops the field from the document.
        """
        on_remove()
        self.__refresh()

    def __refresh(self) -> None:
        """Show or hide the row on both surfaces per the key's live presence, re-reading its value.

        Hiding every cell of a grid row collapses it (the row takes no height); showing them again
        restores it -- so a revert that brings the key back reinstates both rows with the value
        re-read from disk.
        """
        present = self.__is_present() if self.__is_present is not None else False
        for widget in self.__row_widgets:
            widget.setVisible(present)
        if present and self.__current_value is not None:
            text = str(self.__current_value())
            for label in self.__value_labels:
                label.setText(text)
