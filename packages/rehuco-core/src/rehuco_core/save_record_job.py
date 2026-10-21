"""A record's save, as a task-queue job: apply a payload to the record ([[sync#apply-payload]], #497).

A save is no longer a call the window makes and waits on. Pressing Save hands a **snapshot** of the document -- what
to write, what it was read at, whose it is -- to a job, and the job does what
:meth:`~rehuco_core.access.Records.save` always did, on a worker: take the record's lock, re-read, compare, merge the
per-user fields, write atomically, release ([[sync#lock-file]]). So a share that is switched off, or a lock someone
else holds, costs a row in the Tasks dock that *waits* instead of a window that blocks, and the save is written down
with the queue, so it lands after a restart too ([[sync#pending-saves]]).

**One job per record**, kept by its owner: a later Save hands the same job new data (:meth:`SaveRecordJob.replace`)
rather than queueing a second write, so edits made while a save waits land as one. Until it lands, the job's data is
the record on this machine -- a borrowed copy of one record, its landing the Return ([[sync#unlanded-save]]).

**A gone record is never recreated.** A save whose file or folder went from under it fails -- it never makes a folder
for a resource that is not there any more ([[sync#compare-and-swap]]).
"""

import copy
import dataclasses
import logging
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Final

from borco_core import Presence, device_of, presence_of

from .access import FileSignature, RecordConflict, Records, ResourceKey
from .checksum_claim_moves import take_enclosing_claims
from .constants import EXCLUDED_FILE_PATTERNS
from .record_file_lock import RecordLockedError
from .record_versions import RecordVersion, payload_changes, put_paths
from .rehu_document import RehuDocument
from .rehu_format import FORMAT_VERSION_KEY
from .rename_coordination import DEFAULT_RENAME_COORDINATOR, RenameCoordinator, ResourceLocation
from .resource_scoping import resource_name
from .tasks import DEFAULT_CHAIN_REGISTRY, DEFAULT_TASK_JOB_REGISTRY, JobControl, JobOutcome, JobWaiting, TaskJobBase

LOG: Final = logging.getLogger(__name__)

SAVE_RECORD_KIND: Final = "save-record"
"""What a saved queue spells this job as ([[appendices.task-queue#lifetime]]) -- a promise once written into a user's
queue file, never casually renamed."""

SAVE_FAMILY: Final = DEFAULT_CHAIN_REGISTRY.register("save")
"""The chains saves take turns in: one per server or drive, so saves to one share land in order, saves to another
beside them, and none waits behind a verify (#563)."""

OFFLINE_RETRY_SECONDS: Final = 30.0
"""How long a save waits for a share that does not answer before trying again; resuming the row tries at once."""

LOCKED_RETRY_SECONDS: Final = 10.0
"""How long a save waits for a lock someone else holds before trying again."""

STATE_PAYLOAD_KEY: Final = "payload"
"""The key this job writes its :class:`SavePayload` under, read back by this class and nothing else."""


@dataclass(frozen=True, slots=True)
class SavePayload:  # pylint: disable=too-many-instance-attributes
    """What a Save hands over: the record to write and everything the write is checked against (#497).

    A snapshot, taken when Save is pressed, so the document can go on being edited while the job runs. JSON-able
    (:meth:`to_json`), because the job is written down with the queue -- and because it is also what an edited
    document is kept as across a quit.

    :param path: the record.
    :param username: whose per-user fields the payload carries.
    :param payload: the record as a save writes it (:meth:`~rehuco_core.RehuDocument.payload_to_write`), deep-copied.
    :param base_payload: the record as the document read or last saved it -- a conflict's *Original* -- or ``None``
        for a record never read from this file.
    :param base: the version the document was read at (:class:`~rehuco_core.RecordVersion`), or ``None`` for a record
        never read from this file, which is written as it is.
    :param dropped: the blocks this save leaves out -- claimed and abandoned by the document
        ([[plugins#plugin-blocks]]) -- so the merge never adds them back from the file.
    :param discarded: those of them no save logged yet, logged once the write lands (#86).
    :param first_save: whether nothing was ever written at ``path`` from this document, so its checksums are taken
        once it is (#467).
    :param excluded_patterns: the junk globs a checksum move's walk is given.
    """

    path: Path
    username: str
    payload: dict[str, Any]
    base_payload: dict[str, Any] | None
    base: RecordVersion | None
    dropped: tuple[str, ...] = ()
    discarded: tuple[str, ...] = ()
    first_save: bool = False
    excluded_patterns: tuple[str, ...] = EXCLUDED_FILE_PATTERNS

    def to_json(self) -> dict[str, Any]:
        """This payload as JSON primitives.

        :returns: what :meth:`from_json` reads back.
        """
        base = self.base
        return {
            "path": str(self.path),
            "username": self.username,
            "payload": self.payload,
            "base_payload": self.base_payload,
            "base": None
            if base is None
            else {
                "metadata_hash": base.metadata_hash,
                "file_hash": base.file_hash,
                "user_fields": [list(field) for field in base.user_fields],
            },
            "dropped": list(self.dropped),
            "discarded": list(self.discarded),
            "first_save": self.first_save,
            "excluded_patterns": list(self.excluded_patterns),
        }

    @classmethod
    def from_json(cls, state: Any) -> SavePayload:
        """Read a payload :meth:`to_json` wrote -- or, from a file someone edited, whatever is there instead.

        :param state: the JSON value.
        :returns: the payload.
        :raises ValueError: it does not describe one.
        """
        if not isinstance(state, dict):
            raise ValueError("A saved record save is not an object.")
        path, username, payload = state.get("path"), state.get("username"), state.get("payload")
        if not isinstance(path, str) or not path or not isinstance(username, str) or not isinstance(payload, dict):
            raise ValueError("A saved record save names no record, no user or no payload.")
        base_payload = state.get("base_payload")
        excluded = state.get("excluded_patterns")
        dropped = state.get("dropped")
        discarded = state.get("discarded")
        return cls(
            path=Path(path),
            username=username,
            payload=payload,
            base_payload=base_payload if isinstance(base_payload, dict) else None,
            base=cls.__version_from_json(state.get("base")),
            dropped=tuple(key for key in dropped if isinstance(key, str)) if isinstance(dropped, list) else (),
            discarded=tuple(key for key in discarded if isinstance(key, str)) if isinstance(discarded, list) else (),
            first_save=bool(state.get("first_save", False)),
            excluded_patterns=tuple(excluded)
            if isinstance(excluded, list) and all(isinstance(item, str) for item in excluded)
            else EXCLUDED_FILE_PATTERNS,
        )

    @staticmethod
    def __version_from_json(value: Any) -> RecordVersion | None:
        """Read a version :meth:`to_json` wrote.

        :param value: the JSON value, or ``None``.
        :returns: the version, or ``None`` when there is none.
        :raises ValueError: it is there but not a version.
        """
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("A saved record save's version is not an object.")
        metadata, file_hash, fields = value.get("metadata_hash"), value.get("file_hash"), value.get("user_fields")
        if not isinstance(metadata, str) or not isinstance(file_hash, str) or not isinstance(fields, list):
            raise ValueError("A saved record save's version is malformed.")
        user_fields: list[tuple[str, str, str, str]] = []
        for field in fields:
            if not isinstance(field, list) or len(field) != 4 or not all(isinstance(part, str) for part in field):
                raise ValueError("A saved record save's per-user field hash is malformed.")
            user_fields.append((field[0], field[1], field[2], field[3]))
        return RecordVersion(metadata, file_hash, tuple(user_fields))


@dataclass(frozen=True, slots=True)
class SaveOutcome:
    """What a landed save left on disk, for the document that asked for it (#497).

    :param written: the record as written, the merged per-user fields and the stamps included.
    :param version: what the next save is checked against.
    :param signature: the written file's signature, or ``None`` when it could not be stat'ed.
    :param users_merged: whether per-user fields the file held were merged in.
    """

    written: dict[str, Any]
    version: RecordVersion
    signature: FileSignature | None
    users_merged: bool


def rebase_payload(newer: SavePayload, landed_from: SavePayload, outcome: SaveOutcome) -> SavePayload:
    """A later Save of a record, moved onto what an earlier save of it just wrote (#497).

    What the user changed between the two snapshots is put onto the record as written -- which carries the earlier
    save's stamps and the per-user fields it merged -- and the result is checked against the version that write left,
    so the later save never conflicts with the earlier one ([[sync#unlanded-save]]).

    :param newer: the later snapshot.
    :param landed_from: the snapshot the earlier save wrote.
    :param outcome: what that save left on disk.
    :returns: the later snapshot, ready to write after the earlier one.
    """
    data = copy.deepcopy(outcome.written)
    put_paths(data, payload_changes(landed_from.payload, newer.payload), stamps=newer.payload)
    return dataclasses.replace(
        newer,
        payload=data,
        base=outcome.version,
        base_payload=copy.deepcopy(outcome.written),
        discarded=tuple(key for key in newer.discarded if key not in landed_from.discarded),
        first_save=False,
    )


# fourteen, in three groups each read on its own: the data (what is written next, what the owner last handed, what was
# handed during a write, what a write already landed), the run (its lock, whether one is under way, whether it landed,
# where the record is now), and what the last run found (result, conflict, gone) -- plus what it writes through
# pylint: disable-next=too-many-instance-attributes
class SaveRecordJob(TaskJobBase):
    """Write one record's payload, as a read-merge-write under its lock, on the queue (#497).

    **Waits rather than fails for what will pass**: a share that does not answer, a lock someone else holds
    (:class:`~rehuco_core.tasks.JobWaiting`). **Fails for what will not**: a conflict -- the record's details were
    changed on disk since the document read them, or a record saved for the first time was created meanwhile -- kept
    in :attr:`conflict` for the document to resolve, and a record whose file or folder is gone, named in :attr:`gone`.
    A failed job keeps its data, so Retry writes it once the cause is gone ([[sync#unlanded-save]]).

    **One job per record while it has not landed.** :meth:`replace` hands it a later Save: in place of the data it
    holds while it waits, or -- while it is writing -- to be written by the same run right after, moved onto what the
    first write left (:func:`rebase_payload`).

    **It follows renames** (#241): the record is tracked through ``coordinator``, so a save of a record renamed in the
    app writes where it went, and the write holds the rename barrier.

    **Safely interruptible**: the write is atomic, so a stop leaves the record either as it was or saved.

    **Threading.** :meth:`replace` is called from the owner's thread while :meth:`run` may be executing, and takes this
    job's own lock; :attr:`result`, :attr:`conflict` and :attr:`gone` are read by the owner once the row has finished.

    :param payload: what to write, or ``None`` for a job about to be handed a saved state.
    :param records: what the record is saved through; this machine's filesystem when not given.
    :param coordinator: the rename barrier the record is followed through and a first save's checksum move writes
        through (#241), or ``None`` for none: the record is then written where it was snapshotted.
    """

    kind = SAVE_RECORD_KIND
    safely_interruptible = True

    def __init__(
        self,
        payload: SavePayload | None = None,
        *,
        records: Records | None = None,
        coordinator: RenameCoordinator | None = DEFAULT_RENAME_COORDINATOR,
    ) -> None:
        super().__init__()
        self.__lock: Final = Lock()
        self.__payload = payload
        """What the next write writes."""
        self.__handed = payload
        """What the owner last handed over, as it was handed -- what a landed save is compared with."""
        self.__next: SavePayload | None = None
        """A Save handed while a write was under way, written by the same run once that write lands."""
        self.__wrote: tuple[SavePayload, SaveOutcome] | None = None
        """The last write that landed, and what it wrote from: what a Save made against the version before is moved
        onto."""
        self.__running = False
        self.__landed = False
        self.__records: Final = records if records is not None else Records()
        self.__coordinator: Final = coordinator
        self.__location: ResourceLocation | None = None
        self.__result: SaveOutcome | None = None
        self.__conflict: RecordConflict | None = None
        self.__gone: str | None = None
        self.label = ""
        self.chain = SAVE_FAMILY.chain()
        self.__declare()

    @property
    def payload(self) -> SavePayload | None:
        """What this job writes next -- or wrote, once it has landed."""
        with self.__lock:
            return self.__payload

    @property
    def handed(self) -> SavePayload | None:
        """The last Save handed to this job, as it was handed: the record's saved state on this machine while the job
        has not landed, and what its landing is compared with ([[sync#unlanded-save]])."""
        with self.__lock:
            return self.__handed

    # a property over TaskJobBase's plain attribute, as ChecksumJob's is: the record is tracked, so a rename that
    # landed while the save waited answers the new path
    @property
    def source(self) -> Path | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The record, **as it is now** -- read from the tracked location when there is one (#241)."""
        location = self.__location
        if location is not None:
            return location.path
        payload = self.payload
        return None if payload is None else payload.path

    @property
    def result(self) -> SaveOutcome | None:
        """What the last run left on disk, or ``None`` before one landed."""
        return self.__result

    @property
    def conflict(self) -> RecordConflict | None:
        """Why the last run was refused, when the record's details had changed on disk; else ``None``."""
        return self.__conflict

    @property
    def gone(self) -> str | None:
        """The sentence naming the record's missing file or folder, when that is why the last run failed."""
        return self.__gone

    @property
    def outcome(self) -> JobOutcome | None:
        """What the last run did, in one line: ``None`` before one landed."""
        result = self.__result
        if result is None:
            return None
        return JobOutcome("Saved; per-user fields merged from the file" if result.users_merged else "Saved")

    def replace(self, payload: SavePayload) -> bool:
        """Hand this job a later Save of its record -- written in place of the data it holds while it waits, or by the
        same run right after the write under way.

        A Save made against the version before a write this job already landed is moved onto that write
        (:func:`rebase_payload`), so it never conflicts with it.

        :param payload: the later snapshot.
        :returns: ``True`` when this job will write it; ``False`` once it has landed -- a landed save is history, and
            the later one is a save of its own, which the owner moves onto :attr:`result` itself.
        """
        with self.__lock:
            if self.__landed:
                return False
            self.__handed = payload
            if self.__running:
                self.__next = payload
            else:
                self.__payload = self.__onto_written(payload)
            location = self.__location
            if self.__coordinator is not None and (location is None or location.path != payload.path):
                self.__location = self.__coordinator.track(payload.path)
            return True

    def validate(self) -> str | None:
        """Say whether this save can start: whether it holds a record to write.

        :returns: ``None`` when it does.
        """
        return None if self.payload is not None else "This save has no record to write."

    def reset(self) -> None:
        """Drop the last run's outcome, keeping the data -- a retry writes it again."""
        super().reset()
        with self.__lock:
            self.__running = False
            self.__landed = False
        self.__result = None
        self.__conflict = None
        self.__gone = None

    def run(self, control: JobControl) -> None:
        """Write the payload (:meth:`write`).

        :param control: the engine's face to this job; a save reports no progress.
        :raises JobWaiting: the record's share does not answer, or its lock is held elsewhere.
        :raises RecordConflict: the record's details were changed on disk since the payload's base.
        :raises FileNotFoundError: the record's file or folder is gone.
        """
        self.write()

    def write(self) -> SaveOutcome:
        """Write the payload as a read-merge-write under the record's lock, on the caller's thread -- and then any Save
        handed meanwhile, moved onto what was just written.

        The whole of :meth:`run`, public so a document can save inline where it must wait anyway -- one mechanism,
        two entry points.

        :returns: what the last write landed.
        :raises JobWaiting: the record's share does not answer, or its lock is held elsewhere.
        :raises RecordConflict: the record's details were changed on disk since the payload's base.
        :raises FileNotFoundError: the record's file or folder is gone.
        :raises OSError: the record could not be read or written.
        :raises ValueError: there is nothing to write, or the record is locked against saving.
        """
        with self.__lock:
            held = self.__payload
            if held is None:
                raise ValueError("This save has no record to write.")
            self.__running = True
            payload = self.__following(held)
        while True:
            try:
                outcome = self.__write(payload)
            except BaseException:
                with self.__lock:
                    # nothing more landed: what was handed meanwhile is what the row writes when it runs again
                    self.__running = False
                    if self.__next is not None:
                        self.__payload = self.__onto_written(self.__next)
                        self.__next = None
                raise
            with self.__lock:
                self.__wrote = (payload, outcome)
                newer = self.__next
                if newer is None:
                    self.__running = False
                    self.__landed = True
                    return outcome
                self.__next = None
                payload = self.__following(rebase_payload(newer, payload, outcome))

    def __onto_written(self, payload: SavePayload) -> SavePayload:
        """``payload``, moved onto the write this job last landed when it was made against the version before it.

        Called with the lock held.

        :param payload: a Save handed to this job.
        :returns: what to write.
        """
        wrote = self.__wrote
        if wrote is None or payload.base == wrote[1].version:
            return payload
        return rebase_payload(payload, *wrote)

    def __following(self, payload: SavePayload) -> SavePayload:
        """``payload`` at where its record is now, kept as what this job writes next.

        Called with the lock held.

        :param payload: what is about to be written.
        :returns: the same, at the tracked location's path.
        """
        location = self.__location
        if location is not None and location.path != payload.path:
            payload = dataclasses.replace(payload, path=location.path)
        self.__payload = payload
        return payload

    def __write(self, payload: SavePayload) -> SaveOutcome:
        """One write of :meth:`write`.

        :param payload: what to write.
        :returns: what landed.
        :raises JobWaiting: as :meth:`write`.
        """
        self.__result = None
        self.__conflict = None
        self.__gone = None
        self.__check_reachable(payload)
        document = RehuDocument(
            copy.deepcopy(payload.payload),
            payload.path,
            username=payload.username,
            # an existing record's version keeps `created` from being stamped as though this were its first write
            on_disk_format_version=None if payload.first_save else self.__format_version(payload.payload),
        )
        try:
            with self.__holding():
                saved = self.__records.save(
                    ResourceKey(payload.path),
                    document,
                    payload.base,
                    username=payload.username,
                    overwrite=False,
                    dropped=payload.dropped,
                    new=payload.first_save and payload.base is None,
                )
        except RecordConflict as conflict:
            self.__conflict = conflict
            raise
        except RecordLockedError as error:
            raise JobWaiting(str(error), LOCKED_RETRY_SECONDS) from error
        except OSError as error:
            if presence_of(payload.path.parent) is Presence.OFFLINE:
                raise JobWaiting(self.__offline_reason(payload.path), OFFLINE_RETRY_SECONDS) from error
            raise
        for key in payload.discarded:
            LOG.info("%s block discarded on save from %s", key, payload.path)
        if payload.first_save:
            try:
                take_enclosing_claims(
                    payload.path, coordinator=self.__coordinator, excluded_patterns=payload.excluded_patterns
                )
            except OSError as error:
                # the record landed; its claims stay in the enclosing record until its next verify moves them (#467)
                LOG.warning("The checksums %s covers could not be moved into its own record: %s", payload.path, error)
        LOG.info("Saved %s", payload.path)
        result = SaveOutcome(
            copy.deepcopy(document.payload_to_write()), saved.version, saved.signature, saved.users_merged
        )
        self.__result = result
        return result

    def __holding(self) -> AbstractContextManager[None]:
        """The rename barrier the write is made inside, so a rename never moves the record from under it.

        :returns: the coordinator's hold, or nothing to hold when this job follows no renames.
        """
        return self.__coordinator.holding() if self.__coordinator is not None else nullcontext()

    def __check_reachable(self, payload: SavePayload) -> None:
        """Refuse to write a record whose share does not answer, or whose file or folder is gone.

        :param payload: what is about to be written.
        :raises JobWaiting: the share does not answer -- asked before any ``stat`` that would wait for it.
        :raises FileNotFoundError: the folder is gone, or the file a read record stood for is.
        """
        path = payload.path
        presence = presence_of(path.parent)
        if presence is Presence.OFFLINE:
            raise JobWaiting(self.__offline_reason(path), OFFLINE_RETRY_SECONDS)
        if presence is Presence.GONE:
            self.__gone = f"The resource's folder is gone: {path.parent}"
            raise FileNotFoundError(self.__gone)
        if payload.base is not None and not path.exists():
            self.__gone = f"The file is gone: {path}"
            raise FileNotFoundError(self.__gone)

    def capture_state(self) -> dict[str, Any]:
        """Hand over what this job needs to be itself again in a later run.

        :returns: the payload, as JSON primitives.
        """
        payload = self.payload
        return {STATE_PAYLOAD_KEY: None if payload is None else payload.to_json()}

    def restore_state(self, state: dict[str, Any]) -> None:
        """Become the job that captured ``state``.

        :param state: whatever this class's own :meth:`capture_state` wrote.
        :raises ValueError: the state does not describe a save.
        """
        payload = SavePayload.from_json(state.get(STATE_PAYLOAD_KEY))
        with self.__lock:
            self.__payload = payload
            self.__handed = payload
        self.__declare()

    def __declare(self) -> None:
        """Set what this job says about itself from its payload: its label, its chain, and the record it follows."""
        payload = self.payload
        if payload is None:
            return
        self.label = f"Save - {resource_name(payload.path)}"
        device = device_of(payload.path)
        self.chain = SAVE_FAMILY.chain(device.host or str(device.root))
        if self.__coordinator is not None:
            self.__location = self.__coordinator.track(payload.path)

    @staticmethod
    def __offline_reason(path: Path) -> str:
        """The sentence a save waiting for its share shows.

        :param path: the record.
        :returns: the sentence.
        """
        device = device_of(path)
        return f"Waiting for the share: {device.host or device.root}"

    @staticmethod
    def __format_version(payload: dict[str, Any]) -> int | None:
        """The format version a payload is stamped with.

        :param payload: the record.
        :returns: its stamp, or ``None`` when it has none.
        """
        version = payload.get(FORMAT_VERSION_KEY)
        return version if isinstance(version, int) and not isinstance(version, bool) else None


DEFAULT_TASK_JOB_REGISTRY.register(SAVE_RECORD_KIND, SaveRecordJob)
