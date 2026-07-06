"""Per-document viewer/editor surfaces over a nested `CDockManager` ([[plugins#viewer-editor-both]])."""

from typing import Any, Final

import cbor2
import PySide6QtAds as QtAds
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import QMainWindow, QWidget

from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields import build_document_form

STATE_DOCK_MANAGER_KEY: Final = "dock_manager"
STATE_STASHED_SIZES_KEY: Final = "stashed_sizes"

VIEWER_ICON_RESOURCE: Final = ":/icons/document_viewer.svg"
EDITOR_ICON_RESOURCE: Final = ":/icons/document_editor_main.svg"
SAVE_ICON_RESOURCE: Final = ":/icons/document_save.svg"


class DocumentWidget(QMainWindow):
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
    save button/shortcut ([[data-model#write-integrity]]) has no other home in the dock shell.

    :param model: the reactive view-model this document's surfaces bind to.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__stashed_sizes: Final[dict[str, list[int]]] = {}

        form = build_document_form()
        viewer_dock = self.__make_dock("viewer", "Viewer", form.make_viewer(model), QtAds.CenterDockWidgetArea)
        editor_dock = self.__make_dock("editor", "Editor", form.make_editor(model), QtAds.RightDockWidgetArea)

        self.__viewer_action: Final = viewer_dock.toggleViewAction()
        self.__viewer_action.setIcon(QIcon(VIEWER_ICON_RESOURCE))
        self.__editor_action: Final = editor_dock.toggleViewAction()
        self.__editor_action.setIcon(QIcon(EDITOR_ICON_RESOURCE))

        self.__save_action: Final = QAction("&Save", self)
        self.__save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.__save_action.setIcon(QIcon(SAVE_ICON_RESOURCE))
        self.__save_action.triggered.connect(model.save)
        self.addAction(self.__save_action)

        toolbar = self.addToolBar("View")
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
    def viewer_action(self) -> QAction:
        """Toggles the viewer dock's visibility."""
        return self.__viewer_action

    @property
    def editor_action(self) -> QAction:
        """Toggles the editor dock's visibility."""
        return self.__editor_action

    def save_state(self) -> bytes:
        """Serialize this document's dock layout (visible surfaces, splitter sizes) for persistence.

        :returns: cbor2-encoded state, suitable for :meth:`restore_state`
            (:class:`~rehuco_agent.settings.document_session_settings.DocumentSessionSettings.Item.state`).
        """
        return cbor2.dumps(
            {
                STATE_DOCK_MANAGER_KEY: bytes(self.__dock_manager.saveState().data()),
                STATE_STASHED_SIZES_KEY: self.__stashed_sizes,
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
        return bool(self.__dock_manager.restoreState(QByteArray(dock_manager_state)))

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

        :param dock: the dock whose visibility changed.
        :param visible: the dock's new visibility.
        """
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
