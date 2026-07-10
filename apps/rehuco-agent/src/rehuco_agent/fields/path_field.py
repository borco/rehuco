"""The special `path` field: a native-path link viewer and a `PathEditor` for its editor
([[plugins#field-toolkit]]).
"""

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import override

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QUrl, SignalInstance

from rehuco_agent.fields.field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from rehuco_agent.fields.widgets import ExpandToggleButton, PathEditor


class PathField(Field[str]):
    """The special ``path`` field ([[plugins#field-toolkit]], [[field-schema#field-mapping]]): a
    file's location, common to every ``.rehu`` and unlike the record fields in that its editor is
    driven by *other* fields' values (rename suggestions built from title/publisher/etc). It is
    therefore constructed directly by its owner (`DocumentWidget`) with model-aware callbacks, not
    resolved generically through the field list.

    **Viewer** -- a ``file://`` hyperlink whose text is the value rendered with the OS-native path
    separators (backslashes on Windows), even though the bound value itself is stored posix-style.

    **Editor** -- a :class:`~rehuco_agent.fields.widgets.PathEditor` (current name + collapsible
    clickable rename suggestions). ``suggestions`` and ``current_name`` are pushed into it on build,
    on every bound-value change, and whenever ``suggestions_changed`` fires -- so editing a field a
    suggestion is built from (title/authors/publisher/released) updates the list live. A clicked
    suggestion is forwarded to ``on_suggestion_selected``; this field never touches the filesystem.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param suggestions: called with no arguments for the current raw candidate names; omit for a
        read-only editor (viewer-style label, no rename panel).
    :param on_suggestion_selected: called with a suggestion's sanitized name when it is clicked.
    :param current_name: called with no arguments for the resource's current name.
    :param suggestions_changed: fires when a field the suggestions are built from changes, to
        re-pull ``suggestions``/``current_name`` live.
    :param expanded: the suggestions panel's starting expand state.
    """

    TYPE = "path"

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        name: str,
        label: str | None = None,
        suggestions: Callable[[], Sequence[str]] | None = None,
        on_suggestion_selected: Callable[[str], None] | None = None,
        current_name: Callable[[], str] | None = None,
        suggestions_changed: SignalInstance | None = None,
        expanded: bool = False,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__suggestions = suggestions
        self.__on_suggestion_selected = on_suggestion_selected
        self.__current_name = current_name
        self.__suggestions_changed = suggestions_changed
        self.__expanded = expanded

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), self.__make_link_label(binding))

    @override
    def make_editor(self, binding: FieldBinding[str]) -> FieldEditorWidgets:
        if self.__suggestions is None:
            # read-only variant: the same native-path link as the viewer, no rename panel or toggle
            return FieldEditorWidgets(self.editor_tab, self.make_label(), self.__make_link_label(binding))

        editor = PathEditor()
        editor.setObjectName(self.name)
        editor.expanded = self.__expanded
        if self.__on_suggestion_selected is not None:
            editor.suggestion_selected.connect(self.__on_suggestion_selected)

        self.__refresh(editor)
        binding.changed.connect(lambda _value: self.__refresh(editor))
        if self.__suggestions_changed is not None:
            self.__suggestions_changed.connect(lambda *_: self.__refresh(editor))

        # expand/collapse toggle for the middle column, two-way bound to the editor's expand state
        toggle = ExpandToggleButton()
        toggle.setChecked(editor.expanded)
        toggle.toggled.connect(lambda checked: setattr(editor, "expanded", checked))
        editor.expanded_changed.connect(toggle.setChecked)
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor, toggle)

    def __make_link_label(self, binding: FieldBinding[str]) -> ElidedLabel:
        """Build the ``file://`` native-path link label bound to ``binding`` -- the viewer, and the
        read-only (no-suggestions) editor variant.

        :param binding: the value/signal to bind.
        :returns: an `ElidedLabel` that re-renders the link on every change.
        """
        label = ElidedLabel()
        label.setOpenExternalLinks(True)
        self.__render_link(label, binding.value)
        binding.changed.connect(lambda value: self.__render_link(label, value))
        return label

    def __refresh(self, editor: PathEditor) -> None:
        """Re-pull the current name and raw suggestions into the editor.

        :param editor: the editor to update.
        """
        editor.set_current_name(self.__current_name() if self.__current_name is not None else "")
        editor.set_suggestions(self.__suggestions() if self.__suggestions is not None else [])

    @staticmethod
    def __render_link(label: ElidedLabel, value: str) -> None:
        """Show ``value`` as a middle-elided ``file://`` hyperlink with native-separator display text,
        or nothing when empty.

        :param label: the viewer label to update.
        :param value: the new path (stored posix-style; displayed OS-native).
        """
        if not value:
            label.set_text("")
            return
        label.set_text(str(Path(value)), href=QUrl.fromLocalFile(value).toString())
