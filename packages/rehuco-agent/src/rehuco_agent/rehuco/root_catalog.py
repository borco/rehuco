"""The open Root Catalog: one ``.rehuco``, its cache, the jobs that scan into it (#377, #461,
[[plugins#rehuco-dock]], [[data-model#cache-schema]]).
"""

import itertools
import logging
import threading
from collections.abc import Hashable, Iterable, Sequence
from pathlib import Path
from typing import Final
from uuid import UUID

from borco_core.logging import LogScope
from PySide6.QtCore import QObject, Qt, QThreadPool, Signal
from rehuco_core import (
    DEFAULT_RENAME_COORDINATOR,
    FINISHED_JOB_STATES,
    CatalogQuery,
    CatalogRow,
    JobStatus,
    RecordCheck,
    RecordsChecked,
    RehucoFile,
    RehucoFileError,
    RehucoRoot,
    RemoveCatalogRootJob,
    RenameCoordinator,
    ScanCatalogRootJob,
    TaskJob,
    TaskQueue,
    check_records,
    rehudb_path,
)
from rehuco_core.access import (
    AccessRouter,
    CatalogSession,
    CatalogUnreadable,
    KeyRelocation,
    LocalAccess,
    LocalKey,
    NodeUnreachable,
    ResourceKey,
)

from ..resource_events import ResourceEvents
from ..settings.persistent_settings import cache_folder

LOG: Final = logging.getLogger(__name__)


# the public surface is the file operations, the reads the two docks make and the queue listener's callbacks
class RootCatalog(QObject):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """The one open ``.rehuco`` and its ``.rehudb`` cache, which the **Root Catalog** dock (its roots,
    :class:`~.roots_panel.RootsPanel`) and the **Browsers** dock (the resources the cache lists,
    :class:`~.browsers_dock.BrowsersDock`) both read (#461). Neither dock owns the file: each hears from here
    when it changed and reads what it shows.

    **The ``.rehuco`` is the source of truth for the roots, the cache for everything under them.** An open
    reconciles the cache's roots to the file's, so the two cannot disagree for longer than it takes to save; what
    is *found* under a root only ever arrives from a scan.

    **The cache itself is the access seam's** (#417, [[nodes#access-seam]]): this holds no connection, and reads
    and keeps the cache current through :class:`~rehuco_core.LocalCatalog`, which opens one per call on whichever
    thread asks (SQLite's one connection per thread, [[data-model#cache-schema]]). **A scan is a queue job per
    root**, never run here: each opens its own on the worker. This is a queue listener only to learn when one of its
    own jobs has finished, and then says the catalog :attr:`refreshed` -- the same marshalling the checksum actions
    use ([[appendices.task-queue#observation]]).

    **A file newer than this build opens read-only**: its :attr:`~rehuco_core.RehucoFile.lock_reason` says why,
    and no edit of the roots is made. Scanning stays on, since it writes only the disposable cache.

    :param queue: the task queue scans and removals are enqueued on.
    :param parent: optional Qt parent.
    :param rename_coordinator: what a scan holds each directory and record read under, so it never blocks a
        rename ([[mounts-and-storage#out-of-band]]).
    :param resource_events: the app's file announcements (#376), which keep the cache current between scans
        without reading anything a rename moved: a rename rebases the rows it moved
        (:meth:`~rehuco_core.LocalCatalog.follow`), and a record the app wrote is read back into its row
        (:meth:`~rehuco_core.LocalCatalog.refresh`). Either way only the rows it touched are announced, by
        :attr:`rows_changed`. ``None`` leaves the cache to the scans alone.
    :param access: the access seam (#417): the open file's cache is attached to its local
        :attr:`~rehuco_core.LocalAccess.catalog`, and every read of the cache and every change to it goes through
        there. The window's own, when given; a router over a new local access otherwise.
    """

    rehuco_path_changed: Signal = Signal(object)
    """Emitted with the open ``.rehuco``'s :class:`~pathlib.Path`, or ``None`` once none is open."""

    opened: Signal = Signal(object)
    """Emitted with the :class:`~rehuco_core.RehucoFile` just made current, before :attr:`refreshed` says what it
    holds."""

    closing: Signal = Signal(object)
    """Emitted with the :class:`~rehuco_core.RehucoFile` about to be let go, while its cache is still open: what a
    dock remembers about a catalog, it remembers now."""

    refreshed: Signal = Signal()
    """The file or the cache changed as a whole -- an open, a close, an edit of the roots, the end of a scan:
    whatever a dock shows of it is to be read again."""

    rows_changed: Signal = Signal(object)
    """Emitted with the ``set`` of cache row ids a change may have touched; only those are to be read again
    (#379)."""

    records_verified: Signal = Signal(object)
    """Emitted with the ``set`` of record :class:`~pathlib.Path` objects whose rows a verify-on-access changed (#487),
    after :attr:`rows_changed` has said which rows: what the cache says of them -- a type, a title -- is new."""

    files_seen: Signal = Signal(object)
    """Emitted with a ``dict`` of file :class:`~pathlib.Path` objects, each with the ``(modification time in ns, size)``
    it has on disk now -- every record a verify looked at, changed or not, and every file :meth:`read_signatures` was
    asked about (#487). Whatever shows one compares it with what it showed; the cache is not asked."""

    class Marshaller(QObject):
        """Carries "one of our jobs may have finished" across the thread boundary, and nothing else."""

        queue_changed = Signal()
        """Carries nothing: the payload is whatever the queue says by the time the slot runs."""

    class Verifier(QObject):
        """Carries a verify-on-access answer from the pool to the GUI thread, and nothing else."""

        answered = Signal(int, object, object, object)
        """``(serial, key, cache path, findings)``: one check's answer, judged on the GUI thread."""

        statted = Signal(int, object)
        """``(serial, signatures)``: what :meth:`RootCatalog.read_signatures` found, judged on the GUI thread."""

    def __init__(
        self,
        queue: TaskQueue,
        parent: QObject | None = None,
        *,
        rename_coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
        resource_events: ResourceEvents | None = None,
        access: AccessRouter | None = None,
    ) -> None:
        super().__init__(parent)
        self.__queue: Final = queue
        self.__access: Final = (
            access if access is not None else AccessRouter(LocalAccess(coordinator=rename_coordinator))
        )
        self.__catalog: Final = self.__access.local.catalog
        self.__rename_coordinator: Final = rename_coordinator
        self.__events: Final = resource_events
        self.__listening_to_events = resource_events is not None
        self.__file: RehucoFile | None = None
        self.__load_error = ""
        self.__save_error = ""

        self.__lock: Final = threading.Lock()
        self.__serials: Final[set[int]] = set()
        """The jobs this catalog enqueued that have not been read back yet. Written under :attr:`__lock` from
        both the GUI thread and the worker's listener callbacks; the lock is never held while calling the
        queue, whose own lock the listener callbacks arrive under."""

        self.__marshaller: Final = RootCatalog.Marshaller(self)
        self.__marshaller.queue_changed.connect(self.__on_queue_changed, Qt.ConnectionType.QueuedConnection)
        self.__verifier: Final = RootCatalog.Verifier(self)
        self.__verifier.answered.connect(self.__on_verified, Qt.ConnectionType.QueuedConnection)
        self.__verifier.statted.connect(self.__on_statted, Qt.ConnectionType.QueuedConnection)
        self.__latest_stat = 0
        self.__verify_serials: Final = itertools.count(1)
        self.__latest_verify: Final[dict[Hashable, int]] = {}
        """The newest verify asked for per key, under :attr:`__lock`: an older one still queued does nothing, and an
        older answer is dropped."""
        queue.add_listener(self)
        if resource_events is not None:
            resource_events.moved.connect(self.__on_moved)
            resource_events.changed.connect(self.__on_files_changed)
            resource_events.accessed.connect(self.__on_accessed)

    # region the open file

    @property
    def file(self) -> RehucoFile | None:
        """The open ``.rehuco``, or ``None`` while none is open."""
        return self.__file

    @property
    def rehuco_path(self) -> Path | None:
        """The open ``.rehuco``'s path, or ``None`` while none is open."""
        return None if self.__file is None else self.__file.path

    @property
    def editable(self) -> bool:
        """Whether a file is open and its roots may be edited: not one newer than this build."""
        return self.__file is not None and self.__file.lock_reason is None

    @property
    def load_error(self) -> str:
        """Why the last :meth:`open_rehuco` or :meth:`new_rehuco` failed, in a sentence a reader can act on;
        empty before any failure."""
        return self.__load_error

    @property
    def save_error(self) -> str:
        """Why the last save of an edit of the roots failed, in a sentence a reader can act on; empty before any
        failure."""
        return self.__save_error

    def new_rehuco(self, path: Path) -> bool:
        """Create an empty ``.rehuco`` at ``path`` and open it, replacing the open one.

        :param path: where to write it.
        :returns: whether it was created and opened; ``False`` leaves the open file as it was, with
            :attr:`load_error` saying why.
        """
        file = RehucoFile.new()
        # the cache first: a file written and then reported as not created would be a stray on disk that
        # the next New prompts to overwrite
        session = self.__open_cache(file)
        if session is None:
            return False
        try:
            file.save(path)
        except (OSError, ValueError) as error:
            return self.__fail(f"Could not create {path}: {error}")
        return self.__adopt(file, session)

    def open_rehuco(self, path: Path) -> bool:
        """Open the ``.rehuco`` at ``path``, replacing the open one, and bring its cache in line with it.

        :param path: the file to open.
        :returns: whether it was opened; ``False`` leaves the open file as it was, with :attr:`load_error`
            saying why.
        """
        try:
            file = RehucoFile.load(path)
        except (OSError, RehucoFileError) as error:
            return self.__fail(f"Could not open {path}: {error}")
        session = self.__open_cache(file)
        return session is not None and self.__adopt(file, session)

    def close_rehuco(self) -> None:
        """Close the open ``.rehuco`` and its cache. A no-op when none is open."""
        if self.__file is None:
            return
        self.__release_session()
        self.refreshed.emit()
        self.rehuco_path_changed.emit(None)

    def detach(self) -> None:
        """Stop listening to the queue and the file announcements, and let the open file go -- the docks hear
        :attr:`closing` -- before the window goes ([[appendices.task-queue#teardown]]).

        Safe to call again: a window closed twice (the tray's hide, then a quit) detaches twice, and the second time
        there is nothing left to disconnect."""
        self.__queue.remove_listener(self)
        if self.__events is not None and self.__listening_to_events:
            self.__listening_to_events = False
            self.__events.moved.disconnect(self.__on_moved)
            self.__events.changed.disconnect(self.__on_files_changed)
            self.__events.accessed.disconnect(self.__on_accessed)
        self.__release_session()

    def __fail(self, message: str) -> bool:
        """Log and keep ``message`` as :attr:`load_error`.

        :param message: why the open or create failed.
        :returns: ``False``, so a caller can ``return self.__fail(...)``.
        """
        LOG.error(message)
        self.__load_error = message
        return False

    def __open_cache(self, file: RehucoFile) -> CatalogSession | None:
        """Open ``file``'s cache, named by its rehuco id, and bring its roots in line with the file's -- without
        making it current, so a file that then fails to open leaves the current one as it was.

        :param file: the file whose cache to open.
        :returns: what the catalog is to read, or ``None`` with :attr:`load_error` saying why.
        """
        try:
            return self.__catalog.prepare(rehudb_path(cache_folder(), file.rehuco_id), file.roots)
        except CatalogUnreadable as error:
            self.__fail(str(error))
            return None

    def __adopt(self, file: RehucoFile, session: CatalogSession) -> bool:
        """Make ``file`` and its cache's ``session`` the current ones, releasing the previous pair.

        The jobs still tracked are kept when the new file is the same catalog -- the same rehuco id, so the
        same cache -- which is what re-opening the open file from the recents is: its running scans still
        end in the cache now shown, and the rows must still be read again when they do.

        :param file: the file to show.
        :param session: its cache, reconciled.
        :returns: ``True``, for the callers that return this.
        """
        same_catalog = self.__file is not None and self.__file.rehuco_id == file.rehuco_id
        self.__release_session(keep_jobs=same_catalog)
        self.__file = file
        self.__catalog.attach(session)
        self.opened.emit(file)
        self.refreshed.emit()
        self.rehuco_path_changed.emit(file.path)
        return True

    def __release_session(self, *, keep_jobs: bool = False) -> None:
        """Say the open file is :attr:`closing`, close its cache, and forget the file.

        :param keep_jobs: whether to go on tracking the jobs this catalog enqueued -- only right when the cache
            about to be shown is the one they write to.
        """
        if self.__file is not None:
            self.closing.emit(self.__file)
        self.__catalog.detach()
        self.__file = None
        if not keep_jobs:
            with self.__lock:
                self.__serials.clear()

    # endregion

    # region reading the cache

    def rows(self, query: CatalogQuery, ids: set[int] | None = None) -> list[CatalogRow]:
        """The rows ``query`` matches under the roots the file lists.

        The access seam's calls block, so the agent makes them from workers: the browsers' loader calls this on the
        pool (:class:`~.catalog_rows_loader.CatalogRowsLoader`, #455), which is safe because it touches nothing here
        but the seam, which any thread may call.

        :param query: a browser's query.
        :param ids: only these rows, for an update in place; every matching row when ``None``.
        :returns: the rows, in the cache's order; none while no catalog is open. A root removed from the file
            keeps its rows until its removal job has run, and they are not returned.
        :raises CatalogUnreadable: when the cache cannot be read.
        """
        return self.__catalog.query(query, ids=ids)

    def root_paths(self) -> dict[UUID, Path]:
        """Where each root of the open file is, by id; empty while none is open."""
        return {} if self.__file is None else {root.root_id: root.path for root in self.__file.roots}

    def resource_key(self, root_id: UUID, relative: str) -> ResourceKey | None:
        """What a resource is reached by: the **one place** a catalog row's ``(root_id, relative)`` becomes a
        document's key (#381, #414).

        Both the browsers' rows and the Roots view name a resource this way, and the preview and the browsers' opens
        go through here -- so a node-served resource (#421) is a change to this method, not to every view.

        :param root_id: the root the resource is under.
        :param relative: its path below the root, ``/``-separated, as the cache keeps it.
        :returns: the key, or ``None`` when the root is not one the open file lists -- or its folder is no absolute
            path, which only a hand-edited ``.rehuco`` produces and nothing here can reach.
        """
        root = self.root_paths().get(root_id)
        if root is None:
            return None
        try:
            return LocalKey(root / relative)
        except ValueError:
            LOG.warning("The root %s of %s is not an absolute path; its resources cannot be reached", root, self.__file)
            return None

    def resource_type(self, record: Path) -> str | None:
        """The type the cache holds for a record, as an indexed lookup -- nothing is read from disk (#456).

        :param record: the ``.rehu`` or ``.tc``, by its absolute path.
        :returns: the type as the record spells it; ``None`` when the record is outside every root, or the cache has
            no row for it yet (it is read by the next scan) or cannot be read.
        """
        row = self.__row(record)
        return None if row is None else row.record.type

    def resource_uuid(self, record: Path) -> str | None:
        """The id the cache holds for a record, as an indexed lookup -- nothing is read from disk (#395).

        :param record: the ``.rehu`` or ``.tc``, by its absolute path.
        :returns: the id, ``""`` for a legacy record; ``None`` when the record is outside every root, or the cache has
            no row for it yet or cannot be read.
        """
        row = self.__row(record)
        return None if row is None else row.record.uuid

    def __row(self, record: Path) -> CatalogRow | None:
        """The cache's row for a record -- an indexed lookup, on the GUI thread until #455.

        :param record: the ``.rehu`` or ``.tc``, by its absolute path.
        :returns: its row, or ``None``.
        """
        try:
            return self.__catalog.row(self.__access.key_for_path(record))
        except ValueError:  # a relative path is no record of any root
            return None

    def resource_count(self, root: RehucoRoot) -> int:
        """How many resources the cache lists under ``root``; ``0`` when that cannot be read.

        :param root: one of the open file's roots.
        :returns: the count.
        """
        return self.__catalog.count(root.root_id)

    # endregion

    # region editing the roots

    def commit_roots(self) -> bool:
        """Save an edit made to :attr:`file`'s roots, bring the cache's copy of them in line, and say the catalog
        :attr:`refreshed`.

        On a failed save the in-memory edit is not what is on disk, so the file is read back -- or closed, when
        even that cannot be read -- and the edit is gone from the screen too.

        :returns: whether it was saved; ``False`` with :attr:`save_error` saying why.
        """
        saved = self.__save_file()
        # a failed save reads the file back, so the cache follows what is on disk either way
        self.__reconcile_cache()
        if self.__file is not None:
            self.refreshed.emit()
        return saved

    def remove_root(self, row: int) -> bool:
        """Remove the root at ``row`` from the file, saving it at once, and its rows from the cache on the queue.

        :param row: the root's place in the file.
        :returns: whether it was saved; ``False`` with :attr:`save_error` saying why.
        """
        file, cache_path = self.__file, self.__catalog.cache_path
        if file is None or cache_path is None or file.lock_reason is not None:
            return False
        removed = file.remove_root(row)
        saved = self.__save_file()
        if saved:
            self.__catalog.hide(removed.root_id)
            self.__enqueue(RemoveCatalogRootJob(cache_path, removed.root_id, root_label=removed.label), removed.path)
        if self.__file is not None:
            self.refreshed.emit()
        return saved

    def __save_file(self) -> bool:
        """Write the edited file, reading it back from disk when that fails.

        :returns: whether it was saved.
        """
        file = self.__file
        if file is None:  # pragma: no cover  (only called with a file open)
            return False
        try:
            file.save()
        except OSError as error:
            LOG.error("Could not save %s: %s", file.path, error)
            self.__save_error = f"Could not save {file.path}: {error}"
            self.__reload_from_disk(file)
            return False
        return True

    def __reload_from_disk(self, file: RehucoFile) -> None:
        """Replace an edited ``file`` that could not be saved with what is on disk, or close it when even that
        cannot be read.

        :param file: the file whose save failed.
        """
        path = file.path
        try:
            if path is None:  # pragma: no cover  (an open file always has a path)
                raise OSError("The file has no path.")
            self.__file = RehucoFile.load(path)
        except (OSError, RehucoFileError) as error:
            LOG.error("Could not read %s back: %s", path, error)
            self.close_rehuco()

    def __reconcile_cache(self) -> None:
        """Bring the cache's roots in line with the file's after an edit, and show those roots; a failure is
        logged, since the next scan rebuilds the cache anyway."""
        if self.__file is not None:
            self.__catalog.reconcile(self.__file.roots)

    # endregion

    # region scanning

    def scan(self) -> None:
        """Enqueue one scan job per root, skipping a root whose scan is already waiting."""
        file = self.__file
        cache_path = self.__catalog.cache_path
        if file is None or cache_path is None:
            return
        for root in file.roots:
            self.__enqueue(
                ScanCatalogRootJob(
                    cache_path, root.root_id, root.path, root_label=root.label, coordinator=self.__rename_coordinator
                ),
                root.path,
            )

    def __enqueue(self, job: TaskJob, scope: Path) -> None:
        """Put ``job`` on the queue inside ``scope``'s log scope, and remember its serial so its end can be
        read back.

        **Asked twice is not asked again** ([[data-model#checksums]]'s rule for the checksum jobs), but only among
        the jobs this catalog itself enqueued and still tracks: a queue-wide match on label and folder would also
        refuse another catalog's scan of a root with the same label and folder. A job naming no folder -- a
        removal -- is never refused: its label is all a row shows, and two removals of roots that happened to
        share a label would read alike, while running one twice is a cascade over nothing.

        :param job: the job.
        :param scope: the folder the job is about, which its log records are attributed to.
        """
        with self.__lock:
            tracked = set(self.__serials)
        waiting = (status for status in self.__queue.jobs() if status.serial in tracked)
        if job.source is not None and any(
            status.state not in FINISHED_JOB_STATES and status.label == job.label and status.source == job.source
            for status in waiting
        ):
            LOG.info("%s is already in the task queue; it was not queued again.", job.label)
            return
        with LogScope.open(scope):
            serial = self.__queue.enqueue(job)
        with self.__lock:
            self.__serials.add(serial)
        # the job may have finished before its serial was remembered, in which case no callback is left
        # to say so: ask once now
        self.__marshaller.queue_changed.emit()

    def __on_queue_changed(self) -> None:
        """Say the catalog :attr:`refreshed` once the **last** of its own jobs has ended (GUI thread).

        Once for a whole Scan rather than once per root: each read is the whole cache and a reset of every
        table, which drops the selection, so eight roots finishing one after another would be eight stalls
        and eight lost selections for one picture that is only complete at the end.
        """
        with self.__lock:
            tracked = set(self.__serials)
        if not tracked:
            return
        present = {status.serial: status for status in self.__queue.jobs()}
        # a serial the queue no longer lists was cleared by the user: nothing more will be said about it
        ended = {serial for serial in tracked if serial not in present or present[serial].state in FINISHED_JOB_STATES}
        if not ended:
            return
        with self.__lock:
            self.__serials.difference_update(ended)
            remaining = bool(self.__serials)
        if not remaining and self.__file is not None:
            self.refreshed.emit()

    # region TaskQueueListener -- called on the worker thread, under the queue's lock

    def job_enqueued(self, status: JobStatus, index: int) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del status, index

    def job_updated(self, status: JobStatus) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        if status.state not in FINISHED_JOB_STATES:
            return
        with self.__lock:
            tracked = status.serial in self.__serials
        if tracked:
            self.__marshaller.queue_changed.emit()

    def jobs_reordered(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del serials

    def jobs_removed(self, serials: Sequence[int]) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        with self.__lock:
            tracked = any(serial in self.__serials for serial in serials)
        if tracked:
            self.__marshaller.queue_changed.emit()

    def queue_paused_changed(self, paused: bool) -> None:
        """See :class:`~rehuco_core.TaskQueueListener`."""
        del paused

    # endregion

    # endregion

    # region verify-on-access

    def verify_records(self, paths: Iterable[Path], *, key: Hashable) -> None:
        """Check each record's row against its file and bring the cache in line, off the GUI thread (#487,
        [[data-model#scan-and-staleness]]).

        What the cache holds is read here, the ``stat`` and any read run on the pool, and the answer is written back
        on this thread -- a share can block a ``stat`` for its whole timeout, and the cache is this thread's.
        **A newer call with the same** ``key`` **supersedes an older one** still out: its answer is dropped, and one
        not yet started does nothing.

        :param paths: records' absolute paths; those that are no record, or under no root, are passed over.
        :param key: what the call is about -- a listed folder, an opened record -- for superseding.
        """
        cache_path = self.__catalog.cache_path
        if cache_path is None:
            return
        keys: list[ResourceKey] = []
        for path in paths:
            try:
                keys.append(self.__access.key_for_path(path))
            except ValueError:  # a relative path is no record of any root
                continue
        checks = self.__catalog.plan_verify(keys)
        if not checks:
            return
        serial = next(self.__verify_serials)
        with self.__lock:
            self.__latest_verify[key] = serial  # pylint: disable=unsupported-assignment-operation
        QThreadPool.globalInstance().start(lambda: self.__run_verify(serial, key, cache_path, checks))

    def __run_verify(self, serial: int, key: Hashable, cache_path: Path, checks: list[RecordCheck]) -> None:
        """Compare the records with the disk, on a pool thread, and answer; never touches the cache.

        :param serial: the call's serial.
        :param key: what the call is about.
        :param cache_path: only handed back, to tell the answer which cache it was planned against.
        :param checks: what to compare.
        """
        with self.__lock:
            if self.__latest_verify.get(key) != serial:
                return
        try:
            checked = check_records(checks, self.__rename_coordinator)
        except Exception:  # pylint: disable=broad-exception-caught  # the pool swallows what escapes: no answer would come
            LOG.exception("Could not verify %d records against the disk.", len(checks))
            checked = RecordsChecked([], {})
        try:
            self.__verifier.answered.emit(serial, key, cache_path, checked)
        except RuntimeError:  # the catalog was destroyed while the check was out
            pass

    def __on_verified(self, serial: int, key: Hashable, cache_path: Path, checked: RecordsChecked) -> None:
        """Say what the disk showed, and write what the cache did not know into it -- unless the check was superseded,
        or the cache is not this one any more (GUI thread). The same ``.rehuco`` closed and opened again is the same
        cache, so an answer planned before the close is still written: the updater drops any finding its row moved
        past meanwhile.

        :param serial: the call's serial.
        :param key: what the call is about.
        :param cache_path: the cache the check was planned against.
        :param checked: what the disk said.
        """
        with self.__lock:
            if self.__latest_verify.get(key) != serial:
                return
            del self.__latest_verify[key]  # pylint: disable=unsupported-delete-operation
        if checked.seen:
            self.files_seen.emit(checked.seen)
        findings = checked.findings
        if cache_path != self.__catalog.cache_path or not findings:
            return
        affected, changed = self.__catalog.apply_verify(findings)
        if changed:
            self.rows_changed.emit(affected)
            self.records_verified.emit(changed)

    def read_signatures(self, paths: Iterable[Path]) -> None:
        """Read the modification time and size of files on the pool and announce them as :attr:`files_seen` --
        what a scan's end asks of the files open documents stand for, which no row of the cache can say (#487).

        A newer call supersedes an older one still out.

        :param paths: the files' absolute paths.
        """
        wanted = list(paths)
        if not wanted:
            return
        self.__latest_stat = serial = next(self.__verify_serials)
        QThreadPool.globalInstance().start(lambda: self.__run_stat(serial, wanted))

    def __run_stat(self, serial: int, paths: list[Path]) -> None:
        """Stat the files on a pool thread, each under the rename hold, and answer.

        :param serial: the call's serial.
        :param paths: the files.
        """
        signatures: dict[Path, tuple[int, int]] = {}
        try:
            for path in paths:
                try:
                    key = self.__access.key_for_path(path)
                    signature = self.__access.for_key(key).records.signature(key)
                except ValueError, NodeUnreachable:  # a relative path, or a node that cannot be reached
                    continue
                if signature is not None:
                    signatures[path] = signature
        except Exception:  # pylint: disable=broad-exception-caught  # the pool swallows what escapes: no answer would come
            LOG.exception("Could not read the state of %d files.", len(paths))
        try:
            self.__verifier.statted.emit(serial, signatures)
        except RuntimeError:  # the catalog was destroyed while the read was out
            pass

    def __on_statted(self, serial: int, signatures: dict[Path, tuple[int, int]]) -> None:
        """Pass on what the pool read, unless a newer read was asked for (GUI thread).

        :param serial: the call's serial.
        :param signatures: the files' times and sizes.
        """
        if serial == self.__latest_stat and signatures:
            self.files_seen.emit(signatures)

    def __on_accessed(self, keys: tuple[ResourceKey, ...]) -> None:
        """Verify the records the app is opening (#487) -- those on this machine: a node's records are its own
        cache's.

        :param keys: the records.
        """
        paths = tuple(key.path for key in keys if isinstance(key, LocalKey))
        if paths:
            self.verify_records(paths, key=paths)

    # endregion

    # region the app's own file changes

    def __on_moved(self, moved_keys: KeyRelocation) -> None:
        """Rebase the rows a rename moved, reading no record, and announce them (#376, #379).

        A scan still running under a renamed folder already reads on under the new name (its tracked
        locations were rewritten by the coordinator), so its rows land under the paths this rebased the old
        ones to. Only this machine's renames concern the cache: a node's roots are that node's to cache.

        :param moved_keys: the rename's executed plan.
        """
        # the rows moving, and any stale one at a destination the rebase drops; they keep their ids
        affected = self.__catalog.follow(moved_keys)
        if affected:
            self.rows_changed.emit(affected)

    def __on_files_changed(self, keys: tuple[ResourceKey, ...]) -> None:
        """Read each record the app wrote back into its row, and announce what changed (#376, #379).

        A path that is not a record, or not under a root, is passed over by the updater itself; a node's file is
        that node's cache's.

        :param keys: the files written or replaced.
        """
        affected = self.__catalog.refresh(keys)
        if affected:
            self.rows_changed.emit(affected)

    # endregion
