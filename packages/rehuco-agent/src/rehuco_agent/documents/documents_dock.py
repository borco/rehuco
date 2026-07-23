"""One dock per open `.rehu` (or legacy `.tc`) document, with focus-and-reuse-by-path
([[nodes#single-instance]])."""

import logging
from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.qtads import QtAdsFocusTracker, tab_label
from PySide6.QtCore import QByteArray, Signal
from PySide6.QtWidgets import QDialog, QMainWindow, QMessageBox, QWidget
from rehuco_core import LockReasonKind, RehuDocument, RehuFormatError, load_tc

from ..dialogs.unsaved_changes_dialog import UnsavedChangesDialog
from ..glyphs import TAB_CLOSE_GLYPH
from ..settings.identity_settings import shared_identity_settings
from .document_widget import DocumentWidget
from .rehu_document_model import INFO_REHU_FILENAME, RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

DIRTY_DOCK_MARKER: Final = "⬤ "
"""Marker prepended to the title of dirty document tabs."""

LOCKED_DOCK_MARKER: Final = "⚿ "
"""Marker prepended to the title of locked document tabs ([[data-model#schema-version]]); takes
precedence over :data:`DIRTY_DOCK_MARKER` -- a locked document's editors are disabled, so it can never
actually be dirty too. A plain Unicode symbol (Miscellaneous Symbols, not an emoji-presentation
codepoint), same as :data:`DIRTY_DOCK_MARKER` -- renders in the tab's own text color with no font
wiring, unlike a Phosphor glyph, which would need the tab label's font swapped mid-string (unverified
whether ``CElidingLabel``'s own eliding logic tolerates that) and can't be a ``CDockWidget.setIcon()``
icon either, since that single shared property also backs the tabs-menu entry, which has no notion of
"is this the current tab" for a state-dependent color to key off (confirmed the hard way)."""


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

    status_message: Signal = Signal(str)
    """Relays a document field's transient status message (an ``authors`` viewer's hovered-link URL, a
    `StatusReporter`) up from each :class:`DocumentWidget` -- an empty string clears the bar. Like the
    widget below it, this dock is a `QMainWindow` embedded in a dock and can't safely own a status bar
    (the ``.window()`` trap), so it bubbles the message on to the genuine top-level window, which routes
    it to the real bar. The relay mirrors :attr:`document_focus_changed`'s own ``DocumentsDock`` ->
    ``MainWindow`` hop."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__document_docks: Final[dict[QtAds.CDockWidget, DocumentWidget]] = {}
        self.__tracker: Final = QtAdsFocusTracker(self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH)
        self.__tracker.current_dock_changed.connect(self.__on_current_dock_changed)

    def open_document(self, path: Path) -> DocumentWidget:
        """Open ``path`` in a new dock, or focus its dock if already open.

        :param path: absolute filesystem path to a ``.rehu`` file, or a legacy ``.tc`` file
            ([[acquisition-tooling#tc-to-rehu]], opened locked and read-only) -- ``MainWindow.open_file``
            resolves it.
        :returns: the document's widget. A file that cannot be read opens as an empty **locked** dock
            standing in for it ([[data-model#write-integrity]]).
        """
        return self.__activate(self.__find_dock_by_path(path) or self.__make_new_dock(path))

    def open_folder(self, folder: Path) -> DocumentWidget:
        """Open the directory-scoped resource in ``folder`` ([[data-model#resource-scoping]]).

        Opens ``folder/info.rehu`` exactly like :meth:`open_document` if it already exists; falls
        back to a legacy ``folder/info.tc`` if it doesn't ([[acquisition-tooling#tc-to-rehu]]).
        If neither exists, starts a new document already bound to the ``.rehu`` path and dirty
        (:meth:`RehuDocumentModel.create_new`) -- nothing is written to disk until the user saves, so
        discarding it (closing without saving) never creates the file.

        :param folder: absolute filesystem path to the directory to open.
        :returns: the document's widget (an empty **locked** dock when `info.rehu`/`info.tc` exists but
            could not be read, [[data-model#write-integrity]]).
        """
        return self.__open_companion(folder / INFO_REHU_FILENAME)

    def open_archive(self, archive_path: Path) -> DocumentWidget:
        """Open the file-scoped resource for ``archive_path`` ([[data-model#resource-scoping]]).

        Opens ``archive_path`` with its suffix replaced by ``.rehu`` (e.g. ``foo.zip`` ->
        ``foo.rehu``) exactly like :meth:`open_document` if that companion already exists; falls
        back to a legacy ``foo.tc`` if it doesn't ([[acquisition-tooling#tc-to-rehu]]).
        If neither exists, starts a new document already bound to the ``.rehu`` path and dirty
        (:meth:`RehuDocumentModel.create_new`) -- nothing is written to disk until the user saves.

        :param archive_path: absolute filesystem path to the archive file (e.g. ``foo.zip``).
        :returns: the document's widget (an empty **locked** dock when the companion ``.rehu``/``.tc``
            exists but could not be read, [[data-model#write-integrity]]).
        """
        return self.__open_companion(archive_path.with_suffix(".rehu"))

    def __open_companion(self, info_path: Path) -> DocumentWidget:
        """Open ``info_path`` if it exists, its legacy ``.tc`` sibling if that exists instead, or
        start a new document bound to ``info_path``.

        Shared by :meth:`open_folder` and :meth:`open_archive`, which differ only in how they
        derive ``info_path`` from the path the user actually clicked. The ``.tc`` fallback
        ([[acquisition-tooling#tc-to-rehu]]) makes the locked, read-only ``.tc``
        view reachable through normal folder/archive open, not just direct loading.

        :param info_path: the resource's own ``.rehu`` path (an ``info.rehu`` under a folder, or a
            same-stem companion of an archive file).
        :returns: the document's widget (an empty **locked** dock when ``info_path`` or its ``.tc``
            sibling exists but could not be read, [[data-model#write-integrity]]).
        """
        if info_path.exists():
            return self.open_document(info_path)
        tc_path = info_path.with_suffix(".tc")
        if tc_path.exists():
            return self.open_document(tc_path)
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

    def close_all(self) -> None:
        """Close every open document at once, via the same batch confirmation as the whole-app
        close guard (:class:`~rehuco_agent.dialogs.unsaved_changes_dialog.UnsavedChangesDialog`,
        #96) -- not the sequential per-document guard :meth:`__close_dock` uses for a single tab's
        own close button.

        Every clean document closes immediately, with no dialog and unconditionally -- even if the
        dialog for the dirty ones is about to be cancelled. Only if any document is dirty does a
        single dialog appear, listing them with a checkbox each, exactly like
        :meth:`MainWindow.closeEvent`. Cancelling it leaves every dirty document open and nothing
        saved (the already-closed clean documents stay closed regardless). Otherwise the checked
        documents are saved, and every remaining (dirty) document closes; an unchecked one's edits
        are discarded along with the close, same as a whole-app quit.
        """
        dirty_models: list[RehuDocumentModel] = []
        for dock, widget in list(self.__document_docks.items()):
            if widget.model.dirty:
                dirty_models.append(widget.model)
            else:
                self.__remove_dock(dock)

        if not dirty_models:
            return

        dialog = UnsavedChangesDialog(dirty_models, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        for model in dialog.selected_models():
            model.save()
        for dock in list(self.__document_docks):
            self.__remove_dock(dock)

    def close_missing(self) -> None:
        """Close every open document locked with the ``MISSING`` reason (#93, #96).

        Never closes an ``INVALID_FILE`` dock, whose file the user may be mid-hand-fix on. A
        ``MISSING`` document is locked and so can never be dirty, so this never prompts.
        """
        for dock, widget in list(self.__document_docks.items()):
            if self.__is_missing(widget):
                self.__remove_dock(dock)

    def has_missing_documents(self) -> bool:
        """Whether any open document is locked with the ``MISSING`` reason (#93).

        Drives the ``View`` menu's "Close Missing Files" enabled state (#96) -- shares the same
        predicate :meth:`close_missing` itself filters by, so "what counts as missing" lives in
        one place.
        """
        return any(self.__is_missing(widget) for widget in self.__document_docks.values())

    @staticmethod
    def __is_missing(widget: DocumentWidget) -> bool:
        """Whether ``widget``'s document is locked with the ``MISSING`` reason (#93)."""
        return any(reason.kind == LockReasonKind.MISSING for reason in widget.model.lock_reasons)

    def focus_document(self, widget: DocumentWidget) -> None:
        """Make ``widget``'s dock the current one, raising/focusing it.

        Used by the ``View`` menu's open-documents list (#61) to jump to an already-open document
        by widget identity rather than path, since a not-yet-saved document has no path (yet) for
        :meth:`open_document` to look up.

        :param widget: an already-open document's widget (one returned by
            :meth:`open_document_widgets`).
        """
        dock = next(dock for dock, w in self.__document_docks.items() if w is widget)
        self.__activate(dock)

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

    def __activate(self, dock: QtAds.CDockWidget) -> DocumentWidget:
        """Make ``dock`` the current dock and return its widget.

        Always a real dock now -- :meth:`__make_new_dock` yields one for every open attempt (a locked
        stub when the file cannot be read, [[data-model#write-integrity]]), so there is no "no dock was
        created" case to pass through.

        :param dock: a dock found or just created by :meth:`open_document`/:meth:`open_folder`.
        :returns: the dock's widget.
        """
        self.__tracker.set_current_dock(dock)
        return self.__document_docks[dock]

    @staticmethod
    def __load_or_locked(path: Path) -> RehuDocument:
        """Load ``path``, or an empty locked stub bound to it when the file cannot be read.

        Routes a ``.tc`` through :func:`rehuco_core.load_tc` and everything else through
        :meth:`RehuDocument.load`, but funnels *both* loaders' failures through the one seam that draws
        the missing-vs-unparseable line (:meth:`RehuDocument.locked_stub_for_error`) -- so the dock is
        built around a locked, never-savable stub instead of the caller seeing an exception
        ([[data-model#write-integrity]]). Each branch is handed the identity that matches its provenance
        (:func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`, #109), read here at
        open time -- the document keeps it for its whole life, so a later identity-setting change
        affects only documents opened afterwards. A ``.tc`` import files its per-user state under the
        **unknown** user, since a flag carried in from the file was not set by this install's identity; a
        ``.rehu`` (whose per-user writes this UI makes) is opened under the **current** user. A locked stub
        adopts whichever name its branch would have used, so a hand-fix-and-revert retries under the same
        identity the open was asked for.

        :param path: the file to load (a ``.rehu``, or a legacy ``.tc``).
        :returns: the loaded document, or a locked stub bound to ``path``.
        """
        settings = shared_identity_settings()
        is_tc = path.suffix.lower() == ".tc"
        username = settings.unknown_username if is_tc else settings.current_username
        try:
            if is_tc:
                return load_tc(path, username=username)
            return RehuDocument.load(path, username=username)
        except (OSError, RehuFormatError) as error:
            return RehuDocument.locked_stub_for_error(path, error, username=username)

    def __make_new_dock(self, path: Path, *, new: bool = False) -> QtAds.CDockWidget:
        """Load ``path`` and build its document dock -- **always** a dock, never an error dialog.

        Every open attempt yields a document view ([[data-model#write-integrity]]): a file that is
        missing, unparseable, or refused opens as an **empty, locked** dock bound to the path
        (:meth:`RehuDocument.open_or_locked` / :meth:`~RehuDocument.locked_stub_for_error`) whose lock
        reason names the failure, rather than a modal box the user dismisses with nowhere left to fix the
        file. Hand-fixing it and reverting retries in place (:meth:`RehuDocumentModel.revert`).

        :param path: absolute filesystem path to the ``.rehu`` file to load, or to create if ``new``;
            a ``.tc`` suffix loads through :func:`rehuco_core.load_tc` instead
            ([[acquisition-tooling#tc-to-rehu]]), producing a locked, read-only document.
        :param new: when true, skip loading and start an empty, already-dirty document bound to
            ``path`` instead (:meth:`RehuDocumentModel.create_new`) -- used by :meth:`open_folder`
            when the directory has no `info.rehu` yet; nothing is written to disk until the user saves.
            Kept strictly distinct from the empty **locked** stub a failed load produces: a new document
            is empty **and editable and dirty**, a document about to be written.
        :returns: the new dock (created for a successful load, a new document, or a locked stub alike).
        """
        if new:
            model = RehuDocumentModel.create_new(path, self, username=shared_identity_settings().current_username)
        else:
            model = RehuDocumentModel(self.__load_or_locked(path), self)
        widget = DocumentWidget(model, self)
        # relay this document's field status messages (the authors viewer's hovered-link URL) up to
        # MainWindow, which routes them to the real status bar (the genuine top-level window)
        widget.status_message.connect(self.status_message)

        dock = QtAds.CDockWidget(self.__dock_manager, "")
        dock.setObjectName(self.__dock_object_name(model.path))
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
        model.lock_reasons_changed.connect(lambda _: self.__update_dock_title(dock))  # type: ignore[attr-defined]
        model.path_changed.connect(  # type: ignore[attr-defined]
            lambda path: dock.setObjectName(self.__dock_object_name(path))
        )
        self.__update_dock_title(dock)

        # tab the new document into the current dock's area (a fresh area when nothing is current
        # yet, e.g. the very first document); the tracker adopts it as current from there
        current = self.__tracker.current_dock
        dock_area = current.dockAreaWidget() if current is not None else None
        self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, dock_area)

        return dock

    @staticmethod
    def __dock_object_name(path: Path | None) -> str:
        """A stable identifier for a document's dock, used only for :meth:`restore_state` to match
        a saved layout entry back up to the dock recreated for the same document on the next launch
        (``CDockManager`` matches docks up by ``objectName()``).

        Just the path itself, not the resource's UUID ([[data-model#stable-identity]]) -- a
        ``.tc``-backed document has no UUID until a live :meth:`~RehuDocumentModel.convert` mints
        one partway through an already-open dock's lifetime. Renaming an already-registered dock's
        ``objectName()`` is itself safe and propagates correctly (confirmed empirically:
        ``CDockManager.saveState()`` reads ``objectName()`` fresh, not from a stale add-time cache),
        so :meth:`__make_new_dock` resyncs it on every :attr:`~RehuDocumentModel.path_changed`
        instead of needing this identifier to be transition-immune by construction.

        :param path: the document's current path.
        :returns: the path as a string, or a placeholder if it has no path yet (every real call
            site here already has a concrete path in hand).
        """
        return str(path) if path is not None else "untitled"

    def __on_tab_label_double_clicked(self) -> None:
        """Handle a double-click on a document's tab label."""
        # TODO: implement tab label double-clicked functionality -- convert a preview-mode tab
        # into a normal one, once tab preview mode (VSCode-explorer-style: opened-from-explorer
        # tabs start in preview and get replaced by the next preview open, until double-click or
        # an edit promotes them) exists.
        LOG.info("Tab label double-clicked; not implemented yet")

    def __update_dock_title(self, dock: QtAds.CDockWidget) -> None:
        """Set ``dock``'s tab title/tooltip from its document's label, marking it locked or dirty.

        The tab title is the document's :attr:`~RehuDocumentModel.label`, with
        :data:`LOCKED_DOCK_MARKER` prepended while locked ([[data-model#schema-version]]) or
        :data:`DIRTY_DOCK_MARKER` while unsaved -- locked takes precedence, since a locked document's
        disabled editors mean it can never be dirty too. The tooltip always shows the full path.

        :param dock: the dock whose title to refresh.
        """
        widget = self.__document_docks[dock]
        name = widget.model.label
        if widget.model.locked:
            title = f"{LOCKED_DOCK_MARKER}{name}"
        elif widget.model.dirty:
            title = f"{DIRTY_DOCK_MARKER}{name}"
        else:
            title = name
        dock.setWindowTitle(title)
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
        self.__close_dock(dock)

    def __close_dock(self, dock: QtAds.CDockWidget) -> bool:
        """Close ``dock``, prompting first if its document is dirty.

        The close-button handler's own guard -- a single document's dirty state decides whether to
        prompt for it alone. :meth:`close_missing` reuses it (a ``MISSING`` document is locked and
        so can never actually prompt); :meth:`close_all` does not, since it confirms every dirty
        document at once through a single batch dialog instead (#96).

        :param dock: the dock to close.
        :returns: ``True`` if the dock was actually closed (clean, or dirty and Save/Discard was
            chosen); ``False`` if a dirty prompt was cancelled, leaving the dock untouched.
        """
        widget = self.__document_docks[dock]
        if widget.model.dirty and not self.__confirm_close(widget.model):
            return False

        self.__remove_dock(dock)
        return True

    def __remove_dock(self, dock: QtAds.CDockWidget) -> None:
        """Unconditionally remove ``dock`` from the manager and bookkeeping -- no dirty guard.

        Shared by :meth:`__close_dock`, once its own guard has passed, and :meth:`close_all`/
        :meth:`close_missing` (#96), which have already resolved (or ruled out) any dirty
        confirmation before ever reaching here.

        :param dock: the dock to remove. Removing it from the manager clears the tracker's current
            dock (which emits :attr:`document_focus_changed` with ``None`` when it was the current
            one).
        """
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
