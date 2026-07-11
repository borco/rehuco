"""Per-document viewer/editor docks over a nested `CDockManager` ([[plugins#viewer-editor-both]])."""

from typing import Any, Final

import cbor2
import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFocusTracker
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QWidget

from rehuco_agent.documents.document_fields import build_document_form
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import FieldsTab, StatefulWidget

STATE_VERSION_KEY: Final = "version"
STATE_VERSION: Final = 3
"""Schema version of :meth:`DocumentWidget.save_state`'s blob. The dock layout is keyed by dock
object name, so any change to the docks (names, count, which tabs exist) makes an older blob
incompatible: QtAds's ``restoreState`` would accept it and silently hide the current docks. Bump this
on any such change; :meth:`DocumentWidget.restore_state` ignores a blob whose version differs, keeping
the default (all-visible) layout instead."""

STATE_DOCK_MANAGER_KEY: Final = "dock_manager"
STATE_STASHED_SIZES_KEY: Final = "stashed_sizes"
STATE_CURRENT_DOCK_KEY: Final = "current_dock"
STATE_WIDGET_STATE_KEY: Final = "widget_state"

SAVE_ICON_RESOURCE: Final = ":/icons/document_save.svg"
REVERT_ICON_RESOURCE: Final = ":/icons/document_revert.svg"


class DocumentWidget(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """One open document's **viewer** and **editor**, each in its own dock ([[plugins#viewer-editor-both]]).

    Both docks are built once, from the same :class:`RehuDocumentModel`, and stay live regardless of
    which are currently visible -- toggling a dock only hides/shows it, so an edit in the (possibly
    hidden) editor still reaches the (possibly hidden) viewer through the model's signals, making
    "both" work even when only one is on screen. Carries the closed-dock-size workaround
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
    just how a dirty one discards in-memory edits. The editor docks' content is disabled outright
    while the model is :attr:`~RehuDocumentModel.locked` (A3, [[data-model#schema-version]]) -- a
    ``format_version`` newer than this build understands, so editing isn't safe.

    :param model: the reactive view-model this document's docks bind to.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__tracker: Final = QtAdsFocusTracker(self.__dock_manager)
        self.__stashed_sizes: Final[dict[str, list[int]]] = {}
        self.__restoring_layout = False

        # the whole field composition (location + images + record fields + unknown fallbacks) is
        # authored in document_fields; this widget only hosts the resulting docks
        form = build_document_form(model)
        # one dock per FieldsTab: editor tabs stacked on the left, viewer tabs on the right
        self.__editor_docks: Final = self.__add_docks(form.make_editor(model), "editor", QtAds.LeftDockWidgetArea)
        self.__viewer_docks: Final = self.__add_docks(form.make_viewer(model), "viewer", QtAds.RightDockWidgetArea)

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

        self.__set_editors_locked(model.locked)
        model.locked_changed.connect(self.__on_locked_changed)  # type: ignore[attr-defined]

        toolbar = self.addToolBar("View")
        toolbar.addAction(self.__revert_action)
        toolbar.addAction(self.__save_action)
        for dock in (*self.__viewer_docks.values(), *self.__editor_docks.values()):
            toolbar.addAction(dock.toggleViewAction())

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

    def toggle_action(self, tab: FieldsTab) -> QAction:
        """The visibility-toggle action for ``tab``'s dock -- whichever viewer or editor tab it is.

        :param tab: the tab whose dock to toggle.
        :returns: that dock's checkable toggle action.
        :raises KeyError: if no dock hosts ``tab``.
        """
        dock = self.__viewer_docks.get(tab) or self.__editor_docks.get(tab)
        if dock is None:
            raise KeyError(tab)
        return dock.toggleViewAction()

    def save_state(self) -> bytes:
        """Serialize this document's dock layout (visible docks, splitter sizes) and each persisting
        widget's own state for persistence.

        Widget state (e.g. the path field's expand state) rides along here -- persisted per ``.rehu``
        together with the tab layout, not in a separate global settings section (#25).

        :returns: cbor2-encoded state, suitable for :meth:`restore_state`
            (:class:`~rehuco_agent.settings.document_session_settings.DocumentSessionSettings.Item.state`).
        """
        return cbor2.dumps(
            {
                STATE_VERSION_KEY: STATE_VERSION,
                STATE_DOCK_MANAGER_KEY: bytes(self.__dock_manager.saveState().data()),
                STATE_STASHED_SIZES_KEY: self.__stashed_sizes,
                STATE_CURRENT_DOCK_KEY: self.__tracker.save_state(),
                STATE_WIDGET_STATE_KEY: {
                    name: widget.save_state() for name, widget in self.__stateful_widgets().items()
                },
            }
        )

    def restore_state(self, state: bytes) -> bool:
        """Restore a dock layout previously captured by :meth:`save_state`.

        :param state: the cbor2-encoded state to restore.
        :returns: ``True`` if the dock manager's own state was restored successfully; ``False`` if
            ``state`` was empty, malformed, not in the expected shape, or of an incompatible
            :data:`STATE_VERSION` (in which case the default layout is kept).
        """
        try:
            values: Any = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return False
        if not isinstance(values, dict):
            return False
        # An incompatible (e.g. pre-rename) blob would restore cleanly but hide the current docks,
        # leaving a blank window -- ignore it and keep the default all-visible layout instead.
        if values.get(STATE_VERSION_KEY) != STATE_VERSION:
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
            # re-select the dock that was current -- restoreState above only recovers the current
            # tab within each area, not which of two split (viewer/editor) areas actually had focus
            current_dock_state = values.get(STATE_CURRENT_DOCK_KEY, b"")
            if isinstance(current_dock_state, bytes):
                self.__tracker.restore_state(current_dock_state)

        widget_state = values.get(STATE_WIDGET_STATE_KEY)
        if isinstance(widget_state, dict):
            widgets = self.__stateful_widgets()
            for name, saved in widget_state.items():
                widget = widgets.get(name)
                if widget is not None and isinstance(saved, bytes):
                    widget.restore_state(saved)
        return restored

    def __stateful_widgets(self) -> dict[str, StatefulWidget]:
        """The persisting widgets (`StatefulWidget`) across all docks, keyed by object name.

        Found by protocol rather than by holding references or knowing which field types persist, so
        persistence stays decoupled from the field toolkit's layout and its set of stateful widgets. A
        field names its stateful widget after itself (via ``setObjectName``), which is the key here.

        Enumerated through the manager's dock registry (not ``findChildren``): QtAds detaches the
        content of a dock hidden behind another tab from the widget tree, so ``findChildren`` would
        miss it once a second editor tab (e.g. the description) is present.

        :returns: the stateful widgets, keyed by their object name.
        """
        widgets: dict[str, StatefulWidget] = {}
        for dock in self.__dock_manager.dockWidgetsMap().values():
            content = dock.widget()
            for widget in (content, *content.findChildren(QWidget)):
                name = widget.objectName()
                if name and isinstance(widget, StatefulWidget):
                    widgets[name] = widget
        return widgets

    def __on_dirty_changed(self, dirty: bool) -> None:
        """Enable save only while the model holds unsaved edits -- there is nothing to save otherwise.

        Revert stays enabled regardless: it re-reads the document from disk (#41), which is useful
        even on a clean model, to pick up a change made outside this app.

        :param dirty: the model's new dirty state.
        """
        self.__save_action.setEnabled(dirty)

    def __on_locked_changed(self, locked: bool) -> None:
        """Disable/re-enable the editor docks as :attr:`~RehuDocumentModel.locked` changes (e.g. on revert).

        :param locked: the model's new locked state.
        """
        self.__set_editors_locked(locked)

    def __set_editors_locked(self, locked: bool) -> None:
        """Disable every editor dock's content while ``locked`` -- the document's ``format_version`` is
        newer than this build understands ([[data-model#schema-version]]), so editing it isn't safe.

        Only the content widget is disabled, not the dock itself: the tab/toggle stay usable, so the
        editor is still viewable, just not editable.

        :param locked: whether to disable (``True``) or re-enable (``False``) the editor docks.
        """
        for dock in self.__editor_docks.values():
            dock.widget().setEnabled(not locked)

    def __add_docks(
        self, grids: dict[FieldsTab, QWidget], kind: str, position: QtAds.DockWidgetArea
    ) -> dict[FieldsTab, QtAds.CDockWidget]:
        """Build one dock per tab, stacked together into a single area at ``position``, theming each
        dock's toggle action from the tab's SVG icon.

        :param grids: the ``{tab: grid widget}`` mapping (from `FieldsForm`).
        :param kind: ``"viewer"`` or ``"editor"`` -- namespaces the dock object names.
        :param position: the dock area the first tab opens into; later tabs stack into it.
        :returns: the built docks, keyed by tab.
        """
        docks: dict[FieldsTab, QtAds.CDockWidget] = {}
        area: QtAds.CDockAreaWidget | None = None
        for tab, widget in grids.items():
            dock = self.__make_dock(f"{kind}:{tab.text}", tab.text, widget)
            if area is None:
                area = self.__dock_manager.addDockWidget(position, dock)
            else:
                self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, area)
            ActionIconThemeHandler(dock.toggleViewAction(), tab.icon)
            docks[tab] = dock
        if docks:
            # later tabs open as the current one; make the first (e.g. the main editor) current instead
            next(iter(docks.values())).setAsCurrentTab()
        return docks

    def __make_dock(self, name: str, title: str, widget: QWidget) -> QtAds.CDockWidget:
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
