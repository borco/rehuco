"""One dock per open `.rehu` (or legacy `.tc`) document, with focus-and-reuse-by-path
([[nodes#single-instance]])."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import PySide6QtAds as QtAds
from borco_pyside.logging import LogScope
from borco_pyside.qtads import QtAdsFocusTracker
from PySide6.QtCore import QByteArray, QObject, Qt, Signal
from PySide6.QtWidgets import QMainWindow, QMessageBox, QWidget
from rehuco_core import (
    FINISHED_JOB_STATES,
    INFO_REHU_FILENAME,
    JobStatus,
    LockReasonKind,
    RehuDocument,
    RehuFormatError,
    TaskQueue,
    load_tc,
)

from ..glyphs import TAB_CLOSE_GLYPH
from ..settings.identity_settings import shared_identity_settings
from .confirm_and_save_dirty import confirm_and_save_dirty
from .document_dock import DocumentDock
from .document_widget import DocumentWidget
from .rehu_document_model import UNTITLED_LABEL, RehuDocumentModel
from .save_or_prompt_retry import save_or_prompt_retry

LOG: Final = logging.getLogger(__name__)


class DocumentsDock(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """A dock area holding one :class:`DocumentWidget` per open document, tabbed in the focused area.

    Reopening an already-open path focuses its existing dock rather than opening a second one
    ([[nodes#single-instance]]). Which dock is current -- and the highlight/close-button styling
    that marks it, plus every signal needed to catch a tab switch (tab-bar, tabs-menu, tab-label
    click, real keyboard focus into a split area) -- is delegated to a
    :class:`~borco_pyside.qtads.QtAdsFocusTracker`, the same tracker each nested
    :class:`DocumentWidget` uses for its own viewer/editor surfaces.

    :param parent: optional Qt parent.
    :param stylesheet_host: the widget carrying the dock styling for this whole nest -- normally the
        window's outermost ``CDockManager``, an ancestor of every manager below it. Handed on to this
        dock's own manager and to each :class:`DocumentWidget`'s, so QtAds' default stylesheet is
        evaluated once per repolish instead of once per manager ([[appendices.qt-ads#per-manager-stylesheet]],
        #234, and see
        :class:`~borco_pyside.qtads.QtAdsFocusTracker`). ``None`` leaves every manager styling itself.
    :param task_queue: the engine every open document's ``location`` editor asks whether it may rename
        right now (#240). This dock is the **one** listener for the whole nest -- mirroring
        `TaskQueueStore`/`TaskQueueWidget`'s single-attachment-per-app-lifetime shape rather than one
        listener per document -- and re-checks every open model's answer whenever the set of
        **unfinished job sources** moves (:meth:`__wake_rename_locks`; :meth:`detach` before the queue
        shuts down, the same discipline `TaskQueueWidget.detach` follows). ``None`` (most tests) leaves
        every document's rename never locked by this.
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

    class Marshaller(QObject):
        """Carries "the task queue changed, a rename lock may have moved" across the thread boundary,
        and nothing else (#240) -- the same nested, undocumented-outside-its-class shape
        `TaskQueueModel.Marshaller` uses, for the same reason: a mangled class name is not one Qt or
        the linters will accept, and nothing outside :class:`DocumentsDock` has a reason to build one.
        """

        rename_locks_may_have_changed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        stylesheet_host: QWidget | None = None,
        task_queue: TaskQueue | None = None,
    ) -> None:
        super().__init__(parent)
        self.__stylesheet_host: Final = stylesheet_host
        self.__task_queue: Final = task_queue
        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__document_docks: Final[dict[QtAds.CDockWidget, DocumentWidget]] = {}
        self.__tracker: Final = QtAdsFocusTracker(
            self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH, stylesheet_host=stylesheet_host
        )
        self.__tracker.current_dock_changed.connect(self.__on_current_dock_changed)

        self.__marshaller: Final = DocumentsDock.Marshaller()
        self.__marshaller.rename_locks_may_have_changed.connect(
            self.__refresh_rename_lock_reasons, Qt.ConnectionType.QueuedConnection
        )
        self.__pending_rename_lock_refresh = False
        self.__locking_sources: frozenset[Path] | None = None
        """The last-seen set of unfinished job sources, or ``None`` until the first callback settles it
        (:meth:`__resync_rename_locks`, whose comparison ``None`` never satisfies). Deliberately **not**
        read from the queue here: the worker is already running restored jobs when this dock is built,
        so a job transitioning between that read and ``add_listener`` below would be baked in as a
        permanently missed update -- a stale set a later walk can equal by coincidence, swallowing the
        one wake that mattered. Settling inside a callback instead runs under the queue's own lock,
        serialized with every callback after it. Restored jobs still lock correctly before any callback:
        :meth:`~RehuDocumentModel.rename_lock_reason` reads the queue live, and this set only decides
        when to *re-announce*."""
        if task_queue is not None:
            task_queue.add_listener(self)

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
        close guard (:func:`~rehuco_agent.documents.confirm_and_save_dirty.confirm_and_save_dirty`,
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

        # A refusal -- the dialog cancelled, or a checked document's save failed (an offline mount,
        # [[mounts-and-storage#offline-mounts]]) and its retry/cancel dialog cancelled (#146) -- aborts
        # the batch close before any dock is removed, so no document -- saved, unsaved, or
        # unchecked-and-about-to-be-discarded -- is closed out from under a failed save. Every dirty
        # dock stays open for the user to resolve. With no dirty document there is nothing to confirm
        # and nothing left to remove either: the loop below runs over an already-empty mapping.
        if not confirm_and_save_dirty(self, dirty_models):
            return

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
            Matches saved docks up by each dock's ``objectName()`` (a `DocumentDock`'s own
            path-derived identity), so only meaningful once every document that was part of it has been
            reopened (their docks recreated with the same identifiers) again.
        """
        return bytes(self.__dock_manager.saveState().data())

    def restore_state(self, state: bytes) -> bool:
        """Restore a previously-saved outer layout.

        Must be called only after every document dock that was part of it has already been
        (re-)opened -- ``CDockManager.restoreState()`` repositions currently-registered docks to
        match the saved layout by name; it does not (re-)create any docks itself. The tracker
        re-tracks every rebuilt area itself (it listens on ``stateRestored``), so nothing extra is
        needed here for tab switches to keep updating the current dock after a restore.

        Empty ``state`` (no session saved yet) short-circuits before reaching
        ``CDockManager.restoreState()`` -- it would return ``False`` anyway, but only after Qt's
        ``qUncompress()`` logs a spurious "Input data is corrupted" warning to stderr, since an empty
        buffer isn't a valid ``qCompress`` payload.

        :param state: the raw bytes from a prior :meth:`save_state`.
        :returns: ``True`` if the dock manager's own state was restored successfully; ``False`` if
            ``state`` was empty or not a recognized ``CDockManager`` state.
        """
        if not state:
            return False
        return bool(self.__dock_manager.restoreState(QByteArray(state)))

    def detach(self) -> None:
        """Stop listening to the task queue (#240).

        Called before :meth:`~rehuco_core.TaskQueue.shutdown` (``MainWindow.__shutdown_task_queue``),
        the same discipline :meth:`~rehuco_agent.tasks.task_queue_widget.TaskQueueWidget.detach`
        follows: shutdown synchronously emits ``job_updated`` for each job it cancels, and each would
        otherwise schedule a re-check against document docks already being torn down. A no-op when this
        dock was built with no queue.
        """
        if self.__task_queue is not None:
            self.__task_queue.remove_listener(self)

    # region TaskQueueListener (#240) -- a rename lock is a function of one thing only, the set of
    # unfinished jobs' sources ([[appendices.task-queue#observation]]), so every method here keeps
    # that set current and the GUI is woken only when it genuinely moved
    #
    # Why this is not simply "re-snapshot on every callback", the shape `TaskQueueModel` uses:
    # ``job_updated`` fires once per progress report -- once per *file* for a job hashing a tree --
    # and each needless refresh re-renders every open document's location editor, which for a
    # file-scoped resource is a full directory sweep (measured ~11.5 ms over a thousand siblings, vs
    # ~8 us for a directory-scoped one, which reads no directory at all). Waking on every report was
    # measured at ~175 refreshes per 200 reports once the job does real per-unit work; the wake-up
    # coalescing collapses a burst only while the worker never yields, which an I/O-bound job
    # constantly does. Re-snapshotting to *compare* instead is sound but costs a walk of the whole job
    # list per report -- 2.6 us at one queued job, but 1.57 ms at a thousand, which bulk work
    # (a library-wide checksum run) would reach. So the walk is kept for the rare events and the hot
    # one answers in constant time; see :meth:`job_updated`.

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del status, index
        self.__resync_rename_locks()

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`.

        Answers in **constant time** for everything but a job finishing, which is what keeps a
        progress report free. The reasoning, given that this event concerns exactly one job and so
        can move at most that job's own contribution:

        * **set not settled yet** -- the first callback since attaching; walk
          (:meth:`__resync_rename_locks`), because there is no baseline to reason against.
        * **no source** -- contributes nothing whatever its state; the set cannot have moved.
        * **unfinished, source already held** -- its contribution is already in the set, and no other
          job's changed. This is every progress report, and the whole point of the fast path.
        * **unfinished, source not held** -- the job just became unfinished (a retry, or its first
          run), so the set gains exactly that source; no walk is needed to know it.
        * **finished, source not held** -- contributes nothing, and nothing claimed it. Unchanged.
        * **finished, source held** -- the only ambiguous case: the source leaves the set *unless*
          another unfinished job also names it, which only a walk can say. Once per job outcome, so
          the cost lands where it is affordable.
        """
        held = self.__locking_sources
        if held is None:
            self.__resync_rename_locks()
            return
        source = status.source
        if source is None:
            return
        if status.state not in FINISHED_JOB_STATES:
            if source not in held:
                self.__locking_sources = held | {source}
                self.__wake_rename_locks()
            return
        if source in held:
            self.__resync_rename_locks()

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials
        self.__resync_rename_locks()

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials
        self.__resync_rename_locks()

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused
        self.__resync_rename_locks()

    def __unfinished_sources(self) -> frozenset[Path]:
        """Every unfinished job's ``source`` -- the whole of what a rename lock can be built from.

        Exactly the inputs :meth:`~RehuDocumentModel.rename_lock_reason` reads
        (:data:`~rehuco_core.FINISHED_JOB_STATES`, and a job about no one resource contributing
        nothing), so two equal sets guarantee an unchanged answer for **every** open document,
        whatever their paths and scopes are.

        :returns: the sources, or an empty set when this dock has no queue.
        """
        if self.__task_queue is None:  # pragma: no cover -- callbacks fire only once attached, which needs a queue
            return frozenset()
        return frozenset(
            status.source
            for status in self.__task_queue.jobs()
            if status.source is not None and status.state not in FINISHED_JOB_STATES
        )

    def __resync_rename_locks(self) -> None:
        """Re-read the whole set and wake the GUI only if it actually moved.

        The walk, for the events where it is affordable -- an enqueue, a removal, a job finishing, and
        the two that provably cannot matter (a reorder; a pause/resume toggle, since a paused job is
        unfinished, [[appendices.task-queue#pause-concept]]). Routing those two through the comparison
        rather than making them bare no-ops keeps *that* claim enforced by the code rather than by a
        comment that has to stay true.

        Also how the set is **settled**: the not-yet-settled ``None`` satisfies no comparison here, so
        the first callback of any kind -- whatever it reports -- walks and re-announces unconditionally,
        which is what makes a transition the dock was built too late to see harmless.
        """
        sources = self.__unfinished_sources()
        if sources == self.__locking_sources:
            return
        self.__locking_sources = sources
        self.__wake_rename_locks()

    def __wake_rename_locks(self) -> None:
        """Ask the GUI thread to re-check every open document's rename lock, once per burst.

        Called under the queue's own lock, on whichever thread the change happened on -- so this must
        stay quick and must not touch a widget. Emitted only once per pending batch, the same
        coalescing :class:`~rehuco_agent.tasks.task_queue_model.TaskQueueModel` uses; callers update
        :attr:`__locking_sources` *before* getting here, so a change and a change back within one
        batch are never mistaken for no change at all.
        """
        if self.__pending_rename_lock_refresh:
            return
        self.__pending_rename_lock_refresh = True
        self.__marshaller.rename_locks_may_have_changed.emit()

    def __refresh_rename_lock_reasons(self) -> None:
        """Re-announce every open document's :meth:`~RehuDocumentModel.rename_lock_reason` (#240).

        Runs on the GUI thread (the marshaller's queued connection). Asks every open model to re-emit
        rather than computing an answer itself: the model owns what the answer means, this dock only
        owns knowing *when* to ask again.
        """
        self.__pending_rename_lock_refresh = False
        for widget in self.__document_docks.values():
            widget.model.refresh_rename_lock_reason()

    # endregion

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

        **The read is logged, under this resource's own scope** (#200): this is the one funnel both
        loaders and both failure kinds pass through, so it is the one place that can say *"this file was
        read"* or *"this file could not be"* once rather than per branch. The failure is an **error**, not
        a warning: it is not the shape of the document that is in question, it is that there is no
        document -- the stub stands in for one.

        :param path: the file to load (a ``.rehu``, or a legacy ``.tc``).
        :returns: the loaded document, or a locked stub bound to ``path``.
        """
        settings = shared_identity_settings()
        is_tc = path.suffix.lower() == ".tc"
        username = settings.unknown_username if is_tc else settings.current_username
        with LogScope.open(path):
            try:
                document = load_tc(path, username=username) if is_tc else RehuDocument.load(path, username=username)
            except (OSError, RehuFormatError) as error:
                LOG.error("Could not read %s: %s", path, error)
                return RehuDocument.locked_stub_for_error(path, error, username=username)
            LOG.info("Read %s as %s", path, document.type or "an untyped resource")
            return document

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
            model = RehuDocumentModel.create_new(
                path, username=shared_identity_settings().current_username, task_queue=self.__task_queue
            )
        else:
            model = RehuDocumentModel(self.__load_or_locked(path), task_queue=self.__task_queue)
        # the model is created parentless and handed to the dock, which adopts it -- so the whole
        # document is freed when the dock closes rather than leaking for the session (#148). The dock
        # also owns its own title/identity upkeep; the area only wires the two seams that cross back to
        # it: the field status-message relay and the close request.
        dock = DocumentDock(self.__dock_manager, model, stylesheet_host=self.__stylesheet_host)
        # relay this document's field status messages (the authors viewer's hovered-link URL) up to
        # MainWindow, which routes them to the real status bar (the genuine top-level window)
        dock.document_widget.status_message.connect(self.status_message)
        dock.closeRequested.connect(self.__on_close_dock_widget_requested)
        self.__document_docks[dock] = dock.document_widget  # pylint: disable=unsupported-assignment-operation

        # tab the new document into the current dock's area (a fresh area when nothing is current
        # yet, e.g. the very first document); the tracker adopts it as current from there
        current = self.__tracker.current_dock
        dock_area = current.dockAreaWidget() if current is not None else None
        self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, dock_area)

        return dock

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
        widget = self.__document_docks.get(dock) if dock is not None else None
        if widget is not None:
            # clicking a document's tab makes it current without moving the keyboard anywhere near it
            # (QtAds leaves focus wherever it was), which strands an open image viewer: it covers this
            # document, yet ESC would reach whatever still holds focus elsewhere (#160). Only a document
            # with a viewer up takes the keyboard here; every other document's focus is left as it was.
            widget.take_focus()
        self.document_focus_changed.emit(widget)

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
        # deleting the dock frees the whole document with it: the `DocumentDock` owns its model (parented
        # to it) and widget, so their children -- the NameSuggestionModel, the field bindings' data --
        # go too, ending the session-long per-document leak (#148). The model -> dock title connections
        # are the dock's own bound methods, so Qt severs them here as well -- nothing to disconnect by hand.
        dock.deleteLater()
        self.__document_docks.pop(dock, None)

    def __confirm_close(self, model: RehuDocumentModel) -> bool:
        """Prompt Save/Discard/Cancel for a dirty ``model``, saving it if the answer is Save.

        The prompt names the document by :attr:`~RehuDocumentModel.label`, not the bare filename: every
        folder resource is an `info.rehu` ([[data-model#resource-scoping]]), so two of them open at once
        would otherwise raise two identical prompts naming neither (#177).

        Geometry (size/position) is not yet restored across runs -- deferred to #38. Unlike
        :class:`~rehuco_agent.dialogs.unsaved_changes_dialog.UnsavedChangesDialog`, that's simple
        here: the static ``QMessageBox.warning()`` call
        already blocks until the box closes for any reason (a button, Escape, or the titlebar close
        button), so reading geometry right after it returns would cover every exit path -- no need
        for a `QDialog.done()`-style single hook.

        :param model: the dirty document model about to be closed.
        :returns: ``True`` if the close should proceed (Discard was chosen, or Save was chosen and
            succeeded), ``False`` if it was cancelled -- either at this prompt, or at the retry/cancel
            dialog a failed save raises (#146), so a document whose save fails is never closed out from
            under its unsaved edits.
        """
        buttons = QMessageBox.StandardButton
        name = model.label or UNTITLED_LABEL
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
            return save_or_prompt_retry(self, model)
        return True
