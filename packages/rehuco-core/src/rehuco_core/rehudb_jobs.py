"""The catalog cache's slow work, as task-queue jobs: scanning a root, and removing one
([[data-model#cache-schema]], [[appendices.task-queue#lifetime]], #372).

**Each job opens its own** :class:`~rehuco_core.CatalogCache` **on the worker**, because a connection belongs
to the thread that opened it; what a job carries is the cache file's path, never a connection. That is also
what lets a job survive the saved queue: a restored one is rebuilt from paths and ids alone.

**A root is the unit** -- the one the ``.rehuco`` keys its rows on, and the one that is online or offline as a
whole ([[mounts-and-storage#offline-mounts]]). Scanning a whole ``.rehuco`` is one job per root.
"""

import logging
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from .rehudb import CatalogCache
from .rehudb_scan import CatalogRootScan, RootScanResult
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator
from .tasks import DEFAULT_TASK_JOB_REGISTRY, PROGRESS_UNIT_RESOURCES, JobControl, TaskJobBase

LOG: Final = logging.getLogger(__name__)

REHUDB_SCAN_KIND: Final = "rehudb-scan"
"""What a saved queue spells :class:`ScanCatalogRootJob` as -- a promise once written, never casually renamed."""

REHUDB_REMOVE_ROOT_KIND: Final = "rehudb-remove-root"
"""What a saved queue spells :class:`RemoveCatalogRootJob` as."""

STATE_CACHE_KEY: Final = "cache"
"""The key a job writes its cache file under."""

STATE_ROOT_ID_KEY: Final = "root_id"
"""The key a job writes its root's id under."""

STATE_ROOT_PATH_KEY: Final = "path"
"""The key a scan writes its root's folder under."""

STATE_ROOT_LABEL_KEY: Final = "root_label"
"""The key a job writes its root's label under, for a label rebuilt after a restore."""


class CatalogRootJob(TaskJobBase):  # pylint: disable=abstract-method  # a base; each subclass runs
    """One root of one cache: the location, label and saved state the two jobs share.

    :param cache_path: the ``.rehudb`` file, or ``None`` for a job about to be handed a saved state.
    :param root_id: the root's id in the ``.rehuco``.
    :param root_label: the root's label, for the job's own name.
    :param label: how the job is named to a reader, or ``None`` for one derived from :attr:`verb` and the
        root's label.
    """

    kind: str = ""
    """The stable saved name; set by each subclass, empty on this base, which is never registered."""

    verb: str = ""
    """What the job does, for its label -- set by each subclass."""

    def __init__(
        self,
        cache_path: Path | None = None,
        root_id: UUID | None = None,
        *,
        root_label: str = "",
        label: str | None = None,
    ) -> None:
        super().__init__()
        self.cache_path = cache_path
        self.root_id = root_id
        self.root_label = root_label
        self.label = label if label is not None else self.derived_label()

    def validate(self) -> str | None:
        """Say whether this job names something to work on.

        :returns: ``None`` when it does, else what is missing.
        """
        if self.cache_path is None or self.root_id is None:
            return "This task names no catalog root."
        return None

    def cache(self) -> CatalogCache:
        """Open this job's cache, on the calling thread.

        :returns: the cache, for a ``with`` block.
        :raises ValueError: the job names no cache.
        """
        if self.cache_path is None:
            raise ValueError("A catalog task has no cache to work on.")
        return CatalogCache.open(self.cache_path)

    def required_root_id(self) -> UUID:
        """This job's root id, refusing a job that has none.

        :raises ValueError: the job was built without one and never given a state.
        """
        if self.root_id is None:
            raise ValueError("A catalog task has no root to work on.")
        return self.root_id

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this job needs to be itself again in a later run.

        :returns: JSON primitives only.
        """
        return {
            STATE_CACHE_KEY: str(self.cache_path) if self.cache_path is not None else "",
            STATE_ROOT_ID_KEY: str(self.root_id) if self.root_id is not None else "",
            STATE_ROOT_LABEL_KEY: self.root_label,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``, read defensively: the registry logs and drops a job whose
        state does not describe a runnable one.

        :param state: whatever :meth:`capture_state` wrote.
        :raises ValueError: no cache, or a root id that is not a UUID.
        """
        cache = state.get(STATE_CACHE_KEY)
        root_id = state.get(STATE_ROOT_ID_KEY)
        if not isinstance(cache, str) or not cache:
            raise ValueError("A saved catalog task names no cache.")
        if not isinstance(root_id, str):
            raise ValueError("A saved catalog task names no root.")
        self.cache_path = Path(cache)
        self.root_id = UUID(root_id)
        root_label = state.get(STATE_ROOT_LABEL_KEY, "")
        self.root_label = root_label if isinstance(root_label, str) else ""
        self.label = self.derived_label()

    def derived_label(self) -> str:
        """This job's own name for itself, e.g. ``"Scan - tutorials"``; a restored item's saved label is used in
        preference ([[appendices.task-queue#lifetime]])."""
        return f"{self.verb} - {self.root_label}" if self.root_label else self.verb


class ScanCatalogRootJob(CatalogRootJob):
    """Scan one root and replace its rows with what was found (#372).

    **Incremental** (#373): only the records whose stat signature no longer matches their row are read, and
    progress is reported against how many rows the root had -- a first scan, with none, shows a running count.

    **Safely interruptible**: nothing is written until the walk has finished, so a stop part-way leaves the
    cache exactly as it was. It does not resume -- a paused scan starts its walk over, which costs little now
    that an unchanged record is a stat.

    A root that does not list, or goes away before the walk ends, keeps its rows; the job still finishes, since
    an offline root is a state to record, not a failure.

    :param cache_path: the ``.rehudb`` file, or ``None`` for a job about to be handed a saved state.
    :param root_id: the root's id in the ``.rehuco``.
    :param root: the root's folder.
    :param root_label: the root's label, for the job's own name.
    :param coordinator: the rename barrier every read goes through.
    :param label: how the job is named to a reader, or ``None`` for a derived one.
    """

    kind = REHUDB_SCAN_KIND
    verb = "Scan"
    progress_unit = PROGRESS_UNIT_RESOURCES

    def __init__(  # pylint: disable=too-many-arguments
        self,
        cache_path: Path | None = None,
        root_id: UUID | None = None,
        root: Path | None = None,
        *,
        root_label: str = "",
        coordinator: RenameCoordinator | None = None,
        label: str | None = None,
    ) -> None:
        self.__coordinator: Final = coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR
        self.__location = self.__coordinator.track(root) if root is not None else None
        self.__result: RootScanResult | None = None
        super().__init__(cache_path, root_id, root_label=root_label, label=label)

    # a property over TaskJobBase's plain attribute: the root can be renamed under a running scan
    @property
    def source(self) -> Path | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The root's folder, **as it is now** (#241)."""
        return self.__location.path if self.__location is not None else None

    @property
    def result(self) -> RootScanResult | None:
        """What the last completed scan found, or ``None`` before one has finished."""
        return self.__result

    def validate(self) -> str | None:
        """See :meth:`CatalogRootJob.validate` -- also requires a folder. Whether it is *there* is the scan's
        to find out: an offline root is an outcome, not a reason not to start."""
        return super().validate() or (None if self.source is not None else "This task names no folder to scan.")

    def reset(self) -> None:
        """Drop the last scan's result along with the stop request, so a retry reports its own run."""
        super().reset()
        self.__result = None

    def run(self, control: JobControl) -> None:
        """Scan the root, then apply what was found, or record that the root is offline.

        :param control: the engine's face to this job.
        """
        root = self.source
        if root is None:
            raise ValueError("A catalog scan has no folder to work on.")
        root_id = self.required_root_id()
        with self.cache() as cache:
            known = cache.signatures(root_id)
            total = len(known) or None
            control.report(0, total)
            result = CatalogRootScan(
                root,
                coordinator=self.__coordinator,
                checkpoint=self.checkpoint,
                progress=lambda done: control.report(done, None if total is None else max(total, done)),
                known=known,
            ).scan()
            if result.applicable:
                cache.apply_root_scan(root_id, result.records, unchanged=result.unchanged)
            else:
                cache.mark_root_unreachable(root_id)
        self.__result = result
        LOG.info(
            "%s: %s, %d records read (%d legacy, %d unreadable), %d unchanged, %d branches unreadable.",
            self.label,
            result.outcome,
            len(result.records),
            result.legacy_records,
            result.unreadable_records,
            len(result.unchanged),
            len(result.unreadable_branches),
        )

    def capture_state(self) -> dict[str, Any]:
        """See :meth:`CatalogRootJob.capture_state` -- adds the root's folder."""
        state = super().capture_state()
        root = self.source
        state[STATE_ROOT_PATH_KEY] = str(root) if root is not None else ""
        return state

    def restore_state(self, state: dict[str, Any]) -> None:
        """See :meth:`CatalogRootJob.restore_state` -- adds the root's folder.

        :raises ValueError: the state names no folder, or fails the shared checks.
        """
        path = state.get(STATE_ROOT_PATH_KEY)
        if not isinstance(path, str) or not path:
            raise ValueError("A saved catalog scan names no folder.")
        super().restore_state(state)
        self.__location = self.__coordinator.track(Path(path))


class RemoveCatalogRootJob(CatalogRootJob):
    """Delete one root's rows from the cache, and give their space back (#372).

    One transaction and one vacuum: there is nowhere in it to stop, so a pause or a cancel asked of a running
    one waits for it to finish.
    """

    kind = REHUDB_REMOVE_ROOT_KIND
    verb = "Remove root"
    safely_interruptible = False

    def run(self, control: JobControl) -> None:
        """Remove the root.

        :param control: the engine's face to this job.
        """
        root_id = self.required_root_id()
        control.report(0, 1)
        with self.cache() as cache:
            cache.remove_root(root_id)
        control.report(1, 1)
        LOG.info("%s: removed from %s.", self.label, self.cache_path)


DEFAULT_TASK_JOB_REGISTRY.register(REHUDB_SCAN_KIND, ScanCatalogRootJob)
DEFAULT_TASK_JOB_REGISTRY.register(REHUDB_REMOVE_ROOT_KIND, RemoveCatalogRootJob)
