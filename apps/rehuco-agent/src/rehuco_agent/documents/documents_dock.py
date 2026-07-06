"""One dock per open `.rehu` document, with focus-and-reuse-by-path ([[nodes#single-instance]])."""

import logging
from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMainWindow, QMessageBox, QWidget
from rehuco_core import RehuDocument, RehuFormatError

from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.widgets.qtads_utils import tab_label

LOG: Final = logging.getLogger(__name__)


class DocumentsDock(QMainWindow):
    """A dock area holding one :class:`DocumentWidget` per open document, tabbed in the focused area.

    Reopening an already-open path focuses its existing dock rather than opening a second one
    ([[nodes#single-instance]]). Session persistence across app restarts is deferred (A2.1/#21).

    :param parent: optional Qt parent.
    """

    document_focus_changed: Signal = Signal(object)
    """Emitted with the newly-focused document's widget (a ``DocumentWidget``), or ``None`` when
    focus leaves every document dock. Consumers read ``widget.model.label`` for its display label.
    Typed as plain ``object`` (Python-object marshalling), not ``Signal(DocumentWidget)`` -- the
    latter has Shiboken try to cast the emitted value to a genuine C++ ``DocumentWidget*``, which
    crashes the process outright when a test registers a ``MagicMock`` stand-in dock instead of a
    real one (an established pattern elsewhere in this test suite for isolating dock bookkeeping
    from real ``QtAds`` objects)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__document_docks: Final[dict[QtAds.CDockWidget, DocumentWidget]] = {}
        self.__areas_tracking_current_tab: Final[set[QtAds.CDockAreaWidget]] = set()
        """Every area whose ``currentChanged`` is already connected to :meth:`__on_area_current_changed`
        -- checked by :meth:`__track_current_tab` so a second document joining an already-open
        area (as a new tab, not a new area) doesn't connect that area's signal a second time."""
        self.__current_dock: QtAds.CDockWidget | None = None

    def open_document(self, path: Path) -> DocumentWidget | None:
        """Open ``path`` in a new dock, or focus its dock if already open.

        :param path: absolute filesystem path to a ``.rehu`` file (``MainWindow.open_file`` resolves it).
        :returns: the document's widget, or ``None`` when the file could not be read (an error
            dialog was shown instead of a dock, #35).
        """
        dock = self.__find_dock_by_path(path) or self.__make_new_dock(path)
        if dock is None:
            return None
        widget = self.__document_docks[dock]

        if area := dock.dockAreaWidget():
            area.setCurrentIndex(area.index(dock))
        # set directly rather than relying solely on the area's currentChanged: opening the very
        # first document ever is already index 0, so setCurrentIndex(0) above is a no-op that
        # never fires it, leaving __current_dock as still None and the next dock splitting into
        # its own area instead of tabbing into this one
        self.__set_current_dock(dock)

        return widget

    def open_document_widgets(self) -> list[DocumentWidget]:
        """Every currently open document's widget, in no particular order.

        Used by the session-persistence save (``MainWindow``) to snapshot each open document's
        dock layout.
        """
        return list(self.__document_docks.values())

    def focused_document_path(self) -> Path | None:
        """The path of the currently focused document, or ``None`` if none is focused.

        Used by the session-persistence save (``MainWindow``) to remember which document to
        re-focus on restore.
        """
        if self.__current_dock is None:
            return None
        return self.__document_docks[self.__current_dock].model.path

    def open_document_models(self) -> list[RehuDocumentModel]:
        """The models of every currently open document, in no particular order.

        Used by the whole-app close guard (``MainWindow.closeEvent``) to find dirty documents.
        """
        return [widget.model for widget in self.open_document_widgets()]

    def __make_new_dock(self, path: Path) -> QtAds.CDockWidget | None:
        """Load ``path`` and build its document dock, or show an error dialog and return ``None``.

        :param path: absolute filesystem path to the ``.rehu`` file to load.
        :returns: the new dock, or ``None`` when the file is missing/unreadable (``OSError``) or
            not valid ``.rehu`` JSON (:class:`RehuFormatError`) -- no dock is created then (#35).
        """
        try:
            document = RehuDocument.load(path)
        except (OSError, RehuFormatError) as exc:
            QMessageBox.critical(self, "Cannot Open File", f"Could not open {path}:\n\n{exc}")
            return None
        model = RehuDocumentModel(document, self)
        widget = DocumentWidget(model, self)

        dock = QtAds.CDockWidget(self.__dock_manager, "")
        dock_features = QtAds.CDockWidget.DockWidgetFeature
        dock.setFeatures(
            dock_features.CustomCloseHandling
            | dock_features.DockWidgetClosable
            | dock_features.DockWidgetDeleteOnClose
            | dock_features.DockWidgetFocusable
            | dock_features.DockWidgetForceCloseWithArea
            | dock_features.DockWidgetMovable
        )
        dock.setWidget(widget)
        dock.closeRequested.connect(self.__on_close_dock_widget_requested)
        self.__document_docks[dock] = widget  # pylint: disable=unsupported-assignment-operation

        tab_label(dock).doubleClicked.connect(self.__on_tab_label_double_clicked)

        model.dirty_changed.connect(lambda _: self.__update_dock_title(dock))  # type: ignore[attr-defined]
        self.__update_dock_title(dock)

        dock_area = self.__current_dock.dockAreaWidget() if self.__current_dock is not None else None
        area = self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, dock_area)
        self.__track_current_tab(area)

        return dock

    def __track_current_tab(self, area: QtAds.CDockAreaWidget) -> None:
        """Connect ``area.currentChanged`` to track tab switches, once per distinct area.

        :param area: the dock area to track; a no-op if already tracked (e.g. a new dock joining
            an already-open area, which shares that area's existing connection).
        """
        if area not in self.__areas_tracking_current_tab:
            self.__areas_tracking_current_tab.add(area)
            area.currentChanged.connect(lambda index: self.__on_area_current_changed(area, index))

    def __on_tab_label_double_clicked(self) -> None:
        """Handle a double-click on a document's tab label."""
        # TODO: implement tab label double-clicked functionality -- convert a preview-mode tab
        # into a normal one, once tab preview mode (VSCode-explorer-style: opened-from-explorer
        # tabs start in preview and get replaced by the next preview open, until double-click or
        # an edit promotes them) exists.
        LOG.info("Tab label double-clicked; not implemented yet")

    def __update_dock_title(self, dock: QtAds.CDockWidget) -> None:
        """Set ``dock``'s tab title/tooltip from its document's label, marking it dirty when unsaved.

        The tab title is the document's :attr:`~RehuDocumentModel.label`; the tooltip always shows
        the full path.

        :param dock: the dock whose title to refresh.
        """
        widget = self.__document_docks[dock]
        name = widget.model.label
        dock.setWindowTitle(f"{name}*" if widget.model.dirty else name)
        dock.setTabToolTip(str(widget.model.path) if widget.model.path else "")

    def __find_dock_by_path(self, path: Path) -> QtAds.CDockWidget | None:
        """Return the dock whose document has ``path``, or ``None`` if no such dock is open.

        :param path: absolute filesystem path to look for.
        :returns: the matching dock, if any.
        """
        for dock, widget in self.__document_docks.items():
            if widget.model.path == path:
                return dock
        return None

    def __set_current_dock(self, dock: QtAds.CDockWidget | None) -> None:
        """Track the currently-focused document dock and announce its widget.

        :param dock: the newly-focused dock, or ``None`` when focus leaves every document dock.
        """
        self.__current_dock = dock
        self.document_focus_changed.emit(self.__document_docks[dock] if dock is not None else None)

    def __on_area_current_changed(self, area: QtAds.CDockAreaWidget, index: int) -> None:
        """Track the currently-focused document dock whenever the user switches tabs.

        :param area: the dock area whose current tab changed.
        :param index: the newly-current tab's index within ``area``.
        """
        dock = area.dockWidget(index)
        if dock in self.__document_docks:
            self.__set_current_dock(dock)

    def __on_close_dock_widget_requested(self) -> None:
        """Remove the closed dock (and its widget) from the dock manager and bookkeeping.

        Prompts to Save/Discard/Cancel first if the document is dirty; Cancel leaves the dock open
        and untouched.
        """
        dock = self.sender()
        if not isinstance(dock, QtAds.CDockWidget):
            return

        widget = self.__document_docks[dock]
        if widget.model.dirty and not self.__confirm_close(widget.model):
            return

        self.__dock_manager.removeDockWidget(dock)
        dock.deleteLater()

        self.__document_docks.pop(dock, None)
        if self.__current_dock == dock:
            self.__set_current_dock(None)

    def __confirm_close(self, model: RehuDocumentModel) -> bool:
        """Prompt Save/Discard/Cancel for a dirty ``model``, saving it if the answer is Save.

        Geometry (size/position) is not yet restored across runs -- deferred to #21's settings/
        persistence slice. Unlike :class:`UnsavedChangesDialog`, that's simple here: the static
        ``QMessageBox.warning()`` call already blocks until the box closes for any reason (a
        button, Escape, or the titlebar close button), so reading geometry right after it returns
        would cover every exit path -- no need for a `QDialog.done()`-style single hook.

        :param model: the dirty document model about to be closed.
        :returns: ``True`` if the close should proceed (Save or Discard was chosen), ``False`` if
            it was cancelled.
        """
        buttons = QMessageBox.StandardButton
        name = model.path.name if model.path else "Untitled"
        answer = QMessageBox.warning(
            self,
            "Unsaved Changes",
            f'"{name}" has unsaved changes. Save them before closing?',
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Save,
        )
        if answer == buttons.Cancel:
            return False
        if answer == buttons.Save:
            model.save()
        return True
