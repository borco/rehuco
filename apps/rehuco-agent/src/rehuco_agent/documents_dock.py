"""One dock per open `.rehu` document, with focus-and-reuse-by-path ([[nodes#single-instance]])."""

from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from PySide6.QtWidgets import QMainWindow, QMessageBox, QWidget
from rehuco_core import RehuDocument, RehuFormatError

from rehuco_agent.document_widget import DocumentWidget
from rehuco_agent.rehu_document_model import RehuDocumentModel


class DocumentsDock(QMainWindow):
    """A dock area holding one :class:`DocumentWidget` per open document, tabbed in the focused area.

    Reopening an already-open path focuses its existing dock rather than opening a second one
    ([[nodes#single-instance]]). Session persistence across app restarts is deferred (A2.1/#21).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__document_docks: Final[dict[QtAds.CDockWidget, DocumentWidget]] = {}
        self.__current_dock: QtAds.CDockWidget | None = None

        self.__dock_manager.focusedDockWidgetChanged.connect(self.__on_focused_dock_widget_changed)

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
        self.__dock_manager.setDockWidgetFocused(dock)
        # set directly rather than relying solely on focusedDockWidgetChanged: setDockWidgetFocused()
        # does not synchronously emit it in this QtAds version (verified against 5.0.0), so without
        # this, every dock after the first would read __current_dock as still None and split into
        # its own area instead of tabbing into the currently open one
        self.__current_dock = dock

        return widget

    def open_document_models(self) -> list[RehuDocumentModel]:
        """The models of every currently open document, in no particular order.

        Used by the whole-app close guard (``MainWindow.closeEvent``) to find dirty documents.
        """
        return [widget.model for widget in self.__document_docks.values()]

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

        model.dirty_changed.connect(lambda _: self.__update_dock_title(dock))  # type: ignore[attr-defined]
        self.__update_dock_title(dock)

        dock_area = self.__current_dock.dockAreaWidget() if self.__current_dock is not None else None
        self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, dock_area)

        return dock

    def __update_dock_title(self, dock: QtAds.CDockWidget) -> None:
        """Set ``dock``'s tab title from its document's path, marking it dirty when unsaved.

        :param dock: the dock whose title to refresh.
        """
        widget = self.__document_docks[dock]
        name = path.name if (path := widget.model.path) else ""
        dock.setWindowTitle(f"{name}*" if widget.model.dirty else name)

    def __find_dock_by_path(self, path: Path) -> QtAds.CDockWidget | None:
        """Return the dock whose document has ``path``, or ``None`` if no such dock is open.

        :param path: absolute filesystem path to look for.
        :returns: the matching dock, if any.
        """
        for dock, widget in self.__document_docks.items():
            if widget.model.path == path:
                return dock
        return None

    def __on_focused_dock_widget_changed(self, _: QtAds.CDockWidget, now: QtAds.CDockWidget) -> None:
        """Track the currently-focused document dock, so new docks join its area.

        :param now: the newly-focused dock, or ``None`` when focus left every document dock.
        """
        if now is None or now in self.__document_docks:
            self.__current_dock = now

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
            self.__current_dock = None

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
