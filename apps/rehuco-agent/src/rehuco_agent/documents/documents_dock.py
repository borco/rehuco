"""One dock per open `.rehu` document, with focus-and-reuse-by-path ([[nodes#single-instance]])."""

import logging
from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFocusTracker, tab_label
from PySide6.QtCore import QByteArray, Signal
from PySide6.QtWidgets import QMainWindow, QMessageBox, QWidget
from rehuco_core import RehuDocument, RehuFormatError

from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import INFO_REHU_FILENAME, RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

DIRTY_DOCK_MARKER: Final = "⬤ "
"""Marker prepended to the title of dirty document tabs."""


class DocumentsDock(QMainWindow):
    """A dock area holding one :class:`DocumentWidget` per open document, tabbed in the focused area.

    Reopening an already-open path focuses its existing dock rather than opening a second one
    ([[nodes#single-instance]]). Which dock is current -- and the highlight/close-button styling
    that marks it, plus every signal needed to catch a tab switch (tab-bar, tabs-menu, tab-label
    click, real keyboard focus into a split area) -- is delegated to a
    :class:`~borco_pyside.qtads.QtAdsFocusTracker`, the same tracker each nested
    :class:`DocumentWidget` uses for its own viewer/editor surfaces.

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
        self.__tracker: Final = QtAdsFocusTracker(self.__dock_manager)
        self.__tracker.current_dock_changed.connect(self.__on_current_dock_changed)

    def open_document(self, path: Path) -> DocumentWidget | None:
        """Open ``path`` in a new dock, or focus its dock if already open.

        :param path: absolute filesystem path to a ``.rehu`` file (``MainWindow.open_file`` resolves it).
        :returns: the document's widget, or ``None`` when the file could not be read (an error
            dialog was shown instead of a dock, #35).
        """
        return self.__activate(self.__find_dock_by_path(path) or self.__make_new_dock(path))

    def open_folder(self, folder: Path) -> DocumentWidget | None:
        """Open the directory-scoped resource in ``folder`` ([[data-model#resource-scoping]]).

        Opens ``folder/info.rehu`` exactly like :meth:`open_document` if it already exists. If it
        doesn't, starts a new document already bound to that path and dirty (:meth:`RehuDocumentModel.create_new`)
        -- nothing is written to disk until the user saves, so discarding it (closing without
        saving) never creates the file.

        :param folder: absolute filesystem path to the directory to open.
        :returns: the document's widget, or ``None`` when `info.rehu` exists but could not be read.
        """
        return self.__open_companion(folder / INFO_REHU_FILENAME)

    def open_archive(self, archive_path: Path) -> DocumentWidget | None:
        """Open the file-scoped resource for ``archive_path`` ([[data-model#resource-scoping]]).

        Opens ``archive_path`` with its suffix replaced by ``.rehu`` (e.g. ``foo.zip`` ->
        ``foo.rehu``) exactly like :meth:`open_document` if that companion already exists. If it
        doesn't, starts a new document already bound to that path and dirty
        (:meth:`RehuDocumentModel.create_new`) -- nothing is written to disk until the user saves.

        :param archive_path: absolute filesystem path to the archive file (e.g. ``foo.zip``).
        :returns: the document's widget, or ``None`` when the companion ``.rehu`` exists but
            could not be read.
        """
        return self.__open_companion(archive_path.with_suffix(".rehu"))

    def __open_companion(self, info_path: Path) -> DocumentWidget | None:
        """Open ``info_path`` if it exists, or start a new document bound to it.

        Shared by :meth:`open_folder` and :meth:`open_archive`, which differ only in how they
        derive ``info_path`` from the path the user actually clicked.

        :param info_path: the resource's own ``.rehu`` path (an ``info.rehu`` under a folder, or a
            same-stem companion of an archive file).
        :returns: the document's widget, or ``None`` when ``info_path`` exists but could not be read.
        """
        if info_path.exists():
            return self.open_document(info_path)
        return self.__activate(self.__find_dock_by_path(info_path) or self.__make_new_dock(info_path, new=True))

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
        current = self.__tracker.current_dock
        if current is None:
            return None
        return self.__document_docks[current].model.path

    def open_document_models(self) -> list[RehuDocumentModel]:
        """The models of every currently open document, in no particular order.

        Used by the whole-app close guard (``MainWindow.closeEvent``) to find dirty documents.
        """
        return [widget.model for widget in self.open_document_widgets()]

    def save_state(self) -> bytes:
        """Serialize this dock's own layout (splits/tabs between currently open documents).

        :returns: the raw ``CDockManager.saveState()`` bytes, suitable for :meth:`restore_state`
            (:class:`~rehuco_agent.settings.document_session_settings.DocumentSessionSettings.docks_state`).
            Matches saved docks up by :meth:`__dock_object_name`, so only meaningful once every
            document that was part of it has been reopened (their docks recreated with the same
            identifiers) again.
        """
        return bytes(self.__dock_manager.saveState().data())

    def restore_state(self, state: bytes) -> bool:
        """Restore a previously-saved outer layout.

        Must be called only after every document dock that was part of it has already been
        (re-)opened -- ``CDockManager.restoreState()`` repositions currently-registered docks to
        match the saved layout by name; it does not (re-)create any docks itself. The tracker
        re-tracks every rebuilt area itself (it listens on ``stateRestored``), so nothing extra is
        needed here for tab switches to keep updating the current dock after a restore.

        :param state: the raw bytes from a prior :meth:`save_state`.
        :returns: ``True`` if the dock manager's own state was restored successfully; ``False`` if
            ``state`` was empty or not a recognized ``CDockManager`` state.
        """
        return bool(self.__dock_manager.restoreState(QByteArray(state)))

    def __activate(self, dock: QtAds.CDockWidget | None) -> DocumentWidget | None:
        """Make ``dock`` the current dock and return its widget, or ``None`` through unchanged.

        :param dock: a dock found or just created by :meth:`open_document`/:meth:`open_folder`.
        :returns: the dock's widget, or ``None`` when ``dock`` is ``None`` (no dock was created).
        """
        if dock is None:
            return None
        self.__tracker.set_current_dock(dock)
        return self.__document_docks[dock]

    def __make_new_dock(self, path: Path, *, new: bool = False) -> QtAds.CDockWidget | None:
        """Load ``path`` and build its document dock, or show an error dialog and return ``None``.

        :param path: absolute filesystem path to the ``.rehu`` file to load, or to create if ``new``.
        :param new: when true, skip loading and start an empty, already-dirty document bound to
            ``path`` instead (:meth:`RehuDocumentModel.create_new`) -- used by :meth:`open_folder`
            when the directory has no `info.rehu` yet; nothing is written to disk until the user saves.
        :returns: the new dock, or ``None`` when the file is missing/unreadable (``OSError``) or
            not valid ``.rehu`` JSON (:class:`RehuFormatError`) -- no dock is created then (#35).
        """
        if new:
            model = RehuDocumentModel.create_new(path, self)
        else:
            try:
                document = RehuDocument.load(path)
            except (OSError, RehuFormatError) as exc:
                QMessageBox.critical(self, "Cannot Open File", f"Could not open {path}:\n\n{exc}")
                return None
            model = RehuDocumentModel(document, self)
        widget = DocumentWidget(model, self)

        dock = QtAds.CDockWidget(self.__dock_manager, "")
        dock.setObjectName(self.__dock_object_name(model.document))
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

        # tab the new document into the current dock's area (a fresh area when nothing is current
        # yet, e.g. the very first document); the tracker adopts it as current from there
        current = self.__tracker.current_dock
        dock_area = current.dockAreaWidget() if current is not None else None
        self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, dock_area)

        return dock

    @staticmethod
    def __dock_object_name(document: RehuDocument) -> str:
        """A stable identifier for ``document``'s dock, surviving across app restarts.

        Needed for :meth:`restore_state` to match a saved layout entry back up to the dock
        recreated for the same document on the next launch (``CDockManager`` matches docks up by
        ``objectName()``).

        :param document: the loaded document to derive an identifier for.
        :returns: the resource's own UUID ([[data-model#stable-identity]]), or its absolute path
            if the UUID is empty (e.g. a not-yet-imported file).
        """
        return document.id or str(document.path)

    def __on_tab_label_double_clicked(self) -> None:
        """Handle a double-click on a document's tab label."""
        # TODO: implement tab label double-clicked functionality -- convert a preview-mode tab
        # into a normal one, once tab preview mode (VSCode-explorer-style: opened-from-explorer
        # tabs start in preview and get replaced by the next preview open, until double-click or
        # an edit promotes them) exists.
        LOG.info("Tab label double-clicked; not implemented yet")

    def __update_dock_title(self, dock: QtAds.CDockWidget) -> None:
        """Set ``dock``'s tab title/tooltip from its document's label, marking it dirty when unsaved.

        The tab title is the document's :attr:`~RehuDocumentModel.label`, with :data:`DIRTY_DOCK_MARKER`
        prepended while unsaved; the tooltip always shows the full path.

        :param dock: the dock whose title to refresh.
        """
        widget = self.__document_docks[dock]
        name = widget.model.label
        dock.setWindowTitle(f"{DIRTY_DOCK_MARKER}{name}" if widget.model.dirty else name)
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

    def __on_current_dock_changed(self, dock: QtAds.CDockWidget | None) -> None:
        """Announce the newly-current document's widget whenever the tracked current dock changes.

        :param dock: the newly-current dock, or ``None`` when focus leaves every document dock (a
            dock the tracker has already forgotten, e.g. one just closed, resolves to ``None`` too).
        """
        self.document_focus_changed.emit(self.__document_docks.get(dock) if dock is not None else None)

    def __on_close_dock_widget_requested(self) -> None:
        """Remove the closed dock (and its widget) from the dock manager and bookkeeping.

        Prompts to Save/Discard/Cancel first if the document is dirty; Cancel leaves the dock open
        and untouched. Removing it from the manager clears the tracker's current dock (which emits
        :attr:`document_focus_changed` with ``None`` when it was the current one).
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

    def __confirm_close(self, model: RehuDocumentModel) -> bool:
        """Prompt Save/Discard/Cancel for a dirty ``model``, saving it if the answer is Save.

        Geometry (size/position) is not yet restored across runs -- deferred to #38. Unlike
        :class:`UnsavedChangesDialog`, that's simple here: the static ``QMessageBox.warning()`` call
        already blocks until the box closes for any reason (a button, Escape, or the titlebar close
        button), so reading geometry right after it returns would cover every exit path -- no need
        for a `QDialog.done()`-style single hook.

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
