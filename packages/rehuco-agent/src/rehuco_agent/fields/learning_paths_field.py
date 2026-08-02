"""The `learning_paths` leaf field: the viewer's resolved line, and the cross-scope table that edits it
([[plugins#field-toolkit]], [[field-schema#learning-path-ownership]]).
"""

from collections.abc import Callable, Sequence
from typing import Any, Final, override

from PySide6.QtCore import QSignalBlocker
from rehuco_core import DEFAULT_CURRENT_USERNAME, DEFAULT_UNKNOWN_USERNAME, LearningPathEntry, visible_learning_paths

from .field import FieldBinding, FieldEditorWidgets, FieldsTab
from .indexed_list_field import IndexedListField
from .widgets import ExpandToggleButton, LearningPathsEditor
from .widgets.memberships_editor import ALL_SCOPES_TOOLTIP

type ScopedRecords = dict[str, list[dict[str, Any]]]
"""The field's value: every scope's learning-path records, as stored
([[field-schema#learning-path-ownership]])."""


class LearningPathsField(IndexedListField[ScopedRecords]):
    """A ``learning_paths`` field ([[plugins#field-toolkit]],
    [[field-schema#learning-path-ownership]]): whose paths this resource is in.

    Binds every scope's **stored records**, which is more than the viewer shows and exactly what the
    editor needs: the viewer answers *what am I in* (:func:`~rehuco_core.visible_learning_paths`, resolved
    for this document's identity) while the editor can also answer *what is in this file*, which is where
    another identity's private paths become subscribable. One value, two questions.

    The row's ``misc`` column carries the toggle between the editor's two views, the same place the
    ``authors`` field puts its own mode switch -- a view choice belongs beside the row it re-renders, not
    inside the table as a control competing with the memberships.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param username: the current identity -- whose rows are editable, whose view the editor opens in, and
        who a subscription is written for. Supplied by the assembler from the document
        (:attr:`~rehuco_core.RehuDocument.username`), since the toolkit has no identity of its own.
    :param next_ref: hands back the next free **file-scoped** slot for a minted path
        (:meth:`~rehuco_core.RehuDocument.next_learning_path_ref`); a runtime callback for the same reason
        every measurement is one -- uniqueness spans the whole file, which is more than a field can see.
    :param unknown_username: the identity a deleted-but-subscribed path is reparented to
        ([[field-schema#learning-path-ownership]]).
    :param viewer_tab: the surface this field's viewer belongs to.
    :param editor_tab: the surface this field's editor belongs to.
    """

    TYPE = "learning_paths"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        *,
        username: str = DEFAULT_CURRENT_USERNAME,
        next_ref: Callable[[], int] = lambda: 1,
        unknown_username: str = DEFAULT_UNKNOWN_USERNAME,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__username: Final = username
        self.__next_ref: Final = next_ref
        self.__unknown_username: Final = unknown_username

    @override
    def entries(self, value: ScopedRecords) -> Sequence[LearningPathEntry]:
        return visible_learning_paths(
            {scope: list(records) for scope, records in value.items()}, username=self.__username
        )

    @override
    def make_editor(self, binding: FieldBinding[ScopedRecords]) -> FieldEditorWidgets:
        editor = LearningPathsEditor(self.__username, self.__next_ref, self.__unknown_username)
        # the view is a state of this document, restored per ``.rehu`` (`StatefulWidget`), and the owner
        # collects those by object name
        editor.setObjectName(self.name)
        # the ignore: PySide types a class-level ``Signal`` as ``Signal``, not as the ``SignalInstance``
        # an *instance* actually exposes, so no widget declaring one ever satisfies a protocol naming it
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # value_changed is a class-level Signal

        toggle = ExpandToggleButton()
        toggle.defaultAction().setToolTip(ALL_SCOPES_TOOLTIP)
        toggle.toggled.connect(editor.set_all_scopes)
        editor.all_scopes_changed.connect(lambda shown: self.__sync_toggle(toggle, shown))
        self.__sync_toggle(toggle, editor.all_scopes)
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor, toggle)

    @staticmethod
    def __sync_toggle(toggle: ExpandToggleButton, all_scopes: bool) -> None:
        """Show the editor's current view on the toggle.

        Blocked while it is written: the editor's own state reaching the toggle must not read back as a
        click and be applied a second time -- and the session-restored view (`restore_state`) arrives
        exactly this way, after the toggle was built.

        :param toggle: the row's misc-column toggle.
        :param all_scopes: whether every identity's paths are being shown.
        """
        with QSignalBlocker(toggle):
            toggle.setChecked(all_scopes)
