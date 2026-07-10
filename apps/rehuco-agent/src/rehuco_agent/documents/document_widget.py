"""Per-document viewer/editor surfaces over a nested `CDockManager` ([[plugins#viewer-editor-both]])."""

from typing import Any, Final

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFocusTracker
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QWidget

from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import PathField, build_document_form
from rehuco_agent.fields.widgets import PathEditor

LOCATION_FIELD_NAME: Final = "location"

STATE_DOCK_MANAGER_KEY: Final = "dock_manager"
STATE_STASHED_SIZES_KEY: Final = "stashed_sizes"
STATE_CURRENT_DOCK_KEY: Final = "current_dock"
STATE_PATH_FIELD_EXPANDED_KEY: Final = "path_field_expanded"

VIEWER_ICON_RESOURCE: Final = ":/icons/document_viewer.svg"
EDITOR_ICON_RESOURCE: Final = ":/icons/document_editor_main.svg"
SAVE_ICON_RESOURCE: Final = ":/icons/document_save.svg"
REVERT_ICON_RESOURCE: Final = ":/icons/document_revert.svg"


class DocumentWidget(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """One open document's **viewer** and **editor** surfaces, each in its own dock ([[plugins#viewer-editor-both]]).

    Both docks are built once, from the same :class:`RehuDocumentModel`, and stay live regardless of
    which are currently visible -- toggling a dock only hides/shows it, so an edit in the (possibly
    hidden) editor still reaches the (possibly hidden) viewer through the model's signals, making
    "both" work even when only one surface is on screen. Carries the closed-dock-size workaround
    ([[packaging-deployment#qml-regression]]): `CDockManager.splitterSizes` are stashed on
    ``viewToggled(False)`` -- confirmed, against this QtAds version, to still fire with the area at
    its pre-hide size, unlike ``closeRequested`` (never emitted by a toggle-hide; that signal is
    for the ``CustomCloseHandling`` close-button flow `DocumentsDock` uses instead) -- and
    re-applied on ``viewToggled(True)``, since QtAds does not otherwise restore a closed dock's size.
    Also carries the save action (the platform save shortcut, e.g. ``Ctrl+S``), since A1's per-file
    save button/shortcut ([[data-model#write-integrity]]) has no other home in the dock shell, and a
    revert action that re-reads the document from disk (#41). Save is enabled only while the model is
    :attr:`~RehuDocumentModel.dirty` -- there is nothing to save otherwise. Revert stays enabled
    unconditionally: it is also how a clean document picks up a change made outside this app, not
    just how a dirty one discards in-memory edits.

    :param model: the reactive view-model this document's surfaces bind to.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__tracker: Final = QtAdsFocusTracker(self.__dock_manager)
        self.__stashed_sizes: Final[dict[str, list[int]]] = {}
        self.__restoring_layout = False

        location_field = PathField(
            LOCATION_FIELD_NAME,
            suggestions=model.name_suggestions,
            on_suggestion_selected=self.__rename_to,
            current_name=lambda: model.current_name,
            suggestions_changed=model.name_suggestions_changed,
        )
        form = build_document_form(leading_fields=[location_field])
        # keep the editor widget so save/restore_state can reach the location field's expand toggle
        self.__editor_widget: Final = form.make_editor(model)
        viewer_dock = self.__make_dock("viewer", "Viewer", form.make_viewer(model), QtAds.CenterDockWidgetArea)
        editor_dock = self.__make_dock("editor", "Editor", self.__editor_widget, QtAds.RightDockWidgetArea)

        self.__viewer_action: Final = viewer_dock.toggleViewAction()
        ActionIconThemeHandler(self.__viewer_action, VIEWER_ICON_RESOURCE)
        self.__editor_action: Final = editor_dock.toggleViewAction()
        ActionIconThemeHandler(self.__editor_action, EDITOR_ICON_RESOURCE)

        self.__save_action: Final = QAction("&Save", self)
        self.__save_action.setShortcut(QKeySequence.StandardKey.Save)
        # WidgetWithChildrenShortcut, not the default WindowShortcut: this widget is a QMainWindow
        # embedded in a dock, not a genuine top-level window, so WindowShortcut resolves to the
        # single real top-level window shared by every open document -- with two dirty documents
        # open, Qt would see two enabled actions on the same key sequence in that shared scope and
        # call it ambiguous, firing neither (#41). Scoping to this widget's own subtree instead
        # means the shortcut only fires whichever document actually has focus.
        self.__save_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        ActionIconThemeHandler(self.__save_action, SAVE_ICON_RESOURCE)
        self.__save_action.triggered.connect(model.save)
        self.addAction(self.__save_action)

        self.__revert_action: Final = QAction("&Revert", self)
        ActionIconThemeHandler(self.__revert_action, REVERT_ICON_RESOURCE)
        self.__revert_action.triggered.connect(model.revert)
        self.addAction(self.__revert_action)

        self.__save_action.setEnabled(model.dirty)
        model.dirty_changed.connect(self.__on_dirty_changed)  # type: ignore[attr-defined]

        toolbar = self.addToolBar("View")
        toolbar.addAction(self.__revert_action)
        toolbar.addAction(self.__save_action)
        toolbar.addAction(self.__viewer_action)
        toolbar.addAction(self.__editor_action)

    @property
    def model(self) -> RehuDocumentModel:
        """The reactive view-model wrapping this document."""
        return self.__model

    @property
    def save_action(self) -> QAction:
        """Saves the document ([[data-model#write-integrity]]); bound to the platform's save shortcut."""
        return self.__save_action

    @property
    def revert_action(self) -> QAction:
        """Discards in-memory edits and reloads the document from disk (#41)."""
        return self.__revert_action

    @property
    def viewer_action(self) -> QAction:
        """Toggles the viewer dock's visibility."""
        return self.__viewer_action

    @property
    def editor_action(self) -> QAction:
        """Toggles the editor dock's visibility."""
        return self.__editor_action

    def save_state(self) -> bytes:
        """Serialize this document's dock layout (visible surfaces, splitter sizes) and each
        `PathField`'s expand state for persistence.

        The path-field expand state rides along here -- persisted per ``.rehu`` together with the tab
        layout, not in a separate global settings section (#25).

        :returns: cbor2-encoded state, suitable for :meth:`restore_state`
            (:class:`~rehuco_agent.settings.document_session_settings.DocumentSessionSettings.Item.state`).
        """
        return cbor2.dumps(
            {
                STATE_DOCK_MANAGER_KEY: bytes(self.__dock_manager.saveState().data()),
                STATE_STASHED_SIZES_KEY: self.__stashed_sizes,
                STATE_CURRENT_DOCK_KEY: self.__tracker.save_state(),
                STATE_PATH_FIELD_EXPANDED_KEY: {
                    editor.objectName(): editor.expanded for editor in self.__path_editors()
                },
            }
        )

    def restore_state(self, state: bytes) -> bool:
        """Restore a dock layout previously captured by :meth:`save_state`.

        :param state: the cbor2-encoded state to restore.
        :returns: ``True`` if the dock manager's own state was restored successfully; ``False`` if
            ``state`` was empty, malformed, or not in the expected shape.
        """
        try:
            values: Any = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return False
        if not isinstance(values, dict):
            return False

        stashed_sizes = values.get(STATE_STASHED_SIZES_KEY)
        if isinstance(stashed_sizes, dict):
            self.__stashed_sizes.clear()
            self.__stashed_sizes.update(stashed_sizes)

        dock_manager_state = values.get(STATE_DOCK_MANAGER_KEY, b"")
        # restoreState() fires viewToggled(True) for every dock it reconstructs, even ones never
        # really hidden/shown in the user-facing sense -- without this guard, __on_view_toggled
        # would re-apply __stashed_sizes (last updated on some earlier, unrelated hide/show toggle,
        # not necessarily reflecting the sizes actually being restored here) right on top of the
        # correct sizes restoreState() itself just set, clobbering them with stale data
        self.__restoring_layout = True
        try:
            restored = bool(self.__dock_manager.restoreState(QByteArray(dock_manager_state)))
        finally:
            self.__restoring_layout = False
        if restored:
            # re-select the surface that was current -- restoreState above only recovers the current
            # tab within each area, not which of two split (viewer/editor) areas actually had focus
            current_dock_state = values.get(STATE_CURRENT_DOCK_KEY, b"")
            if isinstance(current_dock_state, bytes):
                self.__tracker.restore_state(current_dock_state)

        expanded = values.get(STATE_PATH_FIELD_EXPANDED_KEY)
        if isinstance(expanded, dict):
            editors = {editor.objectName(): editor for editor in self.__path_editors()}
            for name, was_expanded in expanded.items():
                editor = editors.get(name)
                if editor is not None:
                    editor.expanded = bool(was_expanded)
        return restored

    def __path_editors(self) -> list[PathEditor]:
        """The editor form's `PathEditor` widgets, each named after its field.

        Found by type rather than by holding references, so this stays decoupled from how
        `FieldsForm` lays the editor out.

        :returns: the `PathEditor` widgets under the editor surface.
        """
        return self.__editor_widget.findChildren(PathEditor)

    def __rename_to(self, new_name: str) -> None:
        """Rename the resource to a clicked suggestion's name (delegated to the model).

        :param new_name: the sanitized suggestion name that was clicked.
        """
        self.__model.rename_location(new_name)

    def __on_dirty_changed(self, dirty: bool) -> None:
        """Enable save only while the model holds unsaved edits -- there is nothing to save otherwise.

        Revert stays enabled regardless: it re-reads the document from disk (#41), which is useful
        even on a clean model, to pick up a change made outside this app.

        :param dirty: the model's new dirty state.
        """
        self.__save_action.setEnabled(dirty)

    def __make_dock(self, name: str, title: str, widget: QWidget, position: QtAds.DockWidgetArea) -> QtAds.CDockWidget:
        dock = QtAds.CDockWidget(self.__dock_manager, title)
        dock.setObjectName(name)
        dock_features = QtAds.CDockWidget.DockWidgetFeature
        dock.setFeatures(
            dock_features.DockWidgetFocusable
            | dock_features.DockWidgetClosable
            | dock_features.DockWidgetForceCloseWithArea
            | dock_features.DockWidgetMovable
        )
        dock.setWidget(widget)
        dock.viewToggled.connect(lambda visible: self.__on_view_toggled(dock, visible))

        self.__dock_manager.addDockWidget(position, dock)
        return dock

    def __on_view_toggled(self, dock: QtAds.CDockWidget, visible: bool) -> None:
        """Stash ``dock``'s splitter sizes as it hides, or restore them as it reappears.

        No-op while :meth:`restore_state` is actively running -- see the comment there.

        :param dock: the dock whose visibility changed.
        :param visible: the dock's new visibility.
        """
        if self.__restoring_layout:
            return
        if visible:
            self.__restore_size(dock)
        else:
            self.__stash_size(dock)

    def __stash_size(self, dock: QtAds.CDockWidget) -> None:
        """Record the containing splitter's size distribution before ``dock`` hides.

        :param dock: the dock about to hide.
        """
        area = dock.dockAreaWidget()
        if area is not None:
            self.__stashed_sizes[dock.objectName()] = (  # pylint: disable=unsupported-assignment-operation
                self.__dock_manager.splitterSizes(area)
            )

    def __restore_size(self, dock: QtAds.CDockWidget) -> None:
        """Re-apply ``dock``'s stashed splitter sizes now that it is visible again.

        :param dock: the dock that just became visible.
        """
        area = dock.dockAreaWidget()
        sizes = self.__stashed_sizes.get(dock.objectName())
        if sizes and area is not None and len(sizes) == len(self.__dock_manager.splitterSizes(area)):
            self.__dock_manager.setSplitterSizes(area, sizes)
