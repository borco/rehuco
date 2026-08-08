"""Hand a claim to the record that covers the file now ([[data-model#checksums]], #257).

Once a record counts only what it covers (#254), an entry for a file another record owns has to leave the
record holding it. **Dropping it destroys a real claim**: its digest, its algorithm, and the ``verified``
date saying when the file was last known good. Nothing else holds them, and a later baseline on the
covering record would re-read from disk and record whatever is there *now* -- including bytes that rotted
before the split. That is the argument :mod:`rehuco_core.checksum_seeding` makes for a legacy manifest,
reached from the other side: this is a seed from a ``.checksum`` instead of from an ``.sfv``.

So the entry **moves**, and three decisions shape what arrives:

- **The incoming claim wins.** It is written into the covering record and any resident entry of that name
  is dropped. **Provenance beats recency**: an ``.sfv``-seeded ``crc32`` was recorded when the files were
  made, where a locally-baselined XXH3 entry recorded only whatever was on disk the first time this app
  looked -- so the incoming claim wins even when it is older and weaker.
- **The date is cleared**, and the status with it -- neither is true of a record that has never checked
  the file. That is also what makes the rest work with no special case anywhere else: a dateless entry is
  never fresh (:meth:`~rehuco_core.rehu_checksums.ChecksumRun.verify`'s staleness skip), so the next
  ordinary verify reads the file whatever the window says, checks it under its own recorded algorithm,
  and *Update checksums on verify* re-keys it **only on a match** -- blessing bad bytes under a new name
  would launder corruption into a record that then looks clean forever.
- **Everything else is carried**, keys this build does not know included, the same round-trip discipline
  a run's own rewrite keeps.

**The covering record is written first, and the losing one after.** A failure between the two leaves the
claim in both records, which the next run resolves; the other order would lose it outright. And a
destination that cannot be written costs itself: those entries stay where they are and are reported
rather than moved, so one unwritable record never strands another resource's claims. **A destination
whose record does not exist but whose legacy manifest does is declined the same way** -- creating the
record here would spend that resource's one-time seed (#243) on the arriving names, silencing the
manifest's claims for everything else it covers; the move waits until that resource has seeded.

**Honest limit**: this writes a record the run is not otherwise about, which crosses the
one-resource-at-a-time assumption the rename barrier is built on (#241). It reads and writes inside a
:meth:`~rehuco_core.RenameCoordinator.holding` block, so a rename of the covering resource waits the
milliseconds the write takes rather than colliding with it, and the queue is serial
([[appendices.task-queue#serial]]), so no second job can be verifying that record at the same moment.
What is *not* covered is another process, or this app's own in-place
:func:`~rehuco_core.forget_checksums`, touching the covering record in the same instant -- the same
last-writer-wins window every record already has, one resource further away than usual.
"""

import logging
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any, Final

from .checksum_record import (
    CHECKSUM_FILES_KEY,
    CHECKSUM_NAME_KEY,
    CHECKSUM_STATUS_KEY,
    CHECKSUM_VERIFIED_KEY,
    ChecksumRecordError,
    checksum_entry_name,
    checksum_record_path,
    load_checksum_record,
    new_checksum_record,
    save_checksum_record,
)
from .checksum_seeding import legacy_manifest_for
from .rehu_content_files import CoveringRecord
from .rename_coordination import RenameCoordinator

LOG: Final = logging.getLogger(__name__)


class ClaimHandover:  # pylint: disable=too-few-public-methods
    """Writes claims into the records that cover their files now (#257).

    Built per run and thrown away, like the run itself: what it holds is one batch of entries leaving one
    record, grouped by where they are going so a covering record naming forty of them is loaded and
    written once.

    :param claims: where each name goes, by the name the losing record spells it under.
    :param entries: the raw entries that record holds, by the same names -- what is actually carried
        across.
    :param coordinator: the rename barrier to write through (#241), or ``None`` for a private one, which
        no rename will ever arrive through.
    """

    def __init__(
        self,
        claims: Mapping[str, CoveringRecord],
        entries: Mapping[str, Any],
        coordinator: RenameCoordinator | None = None,
    ) -> None:
        self.__claims: Final = claims
        self.__entries: Final = entries
        self.__coordinator: Final = coordinator if coordinator is not None else RenameCoordinator()

    def hand_over(self) -> dict[str, CoveringRecord]:
        """Write every claim into the record that covers it now.

        :returns: the claims actually written, by the name the losing record spells them under -- what
            that record may now drop. A destination that refused to be written, or that is still owed
            its legacy-manifest seed (#243), is left out, so its entries stay where they are.
        """
        moved: dict[str, CoveringRecord] = {}
        for record, names in self.__grouped().items():
            if self.__written(record, names):
                moved.update({name: self.__claims[name] for name in names})
        return moved

    def __grouped(self) -> dict[Path, list[str]]:
        """The claims by the record they are going to, each record's names in the order given.

        :returns: covering record to the names bound for it.
        """
        grouped: dict[Path, list[str]] = {}
        for name, covering in self.__claims.items():
            grouped.setdefault(covering.record, []).append(name)
        return grouped

    def __written(self, record: Path, names: Collection[str]) -> bool:
        """Merge one record's incoming claims into it and write it back.

        A covering resource that has no ``.checksum`` yet gets one holding exactly these entries: this is
        the record's first content, arriving with a claim rather than with a baseline, which is the whole
        point -- and it is what makes a verify of that resource possible at all afterwards.

        **Unless a legacy manifest is waiting to seed it** (#243). Seeding is one-way -- the manifest is
        read only where there is no ``.checksum`` -- so a record created here would spend that resource's
        one seed on the handful of names arriving, and every *other* file it covers would be adopted from
        today's disk instead of checked against the claim made when the files were known good. The claims
        wait in the losing record instead: its next verify completes the move, into the record the seed
        has written by then.

        :param record: the covering resource's ``.rehu``/``.tc``.
        :param names: the names bound for it, as the losing record spells them.
        :returns: whether it was written; a record this build cannot read, or cannot write, or may not
            create yet, is reported and skipped rather than taking the run down with it.
        """
        location = self.__coordinator.track(checksum_record_path(record))
        try:
            with self.__coordinator.holding():
                path = location.path
                try:
                    target = load_checksum_record(path)
                except FileNotFoundError:
                    if legacy_manifest_for(location.path.with_suffix(record.suffix)) is not None:
                        LOG.info(
                            "%s has no record yet and a legacy manifest to seed one from; the claims "
                            "moving to it wait where they are until it has (#243).",
                            record,
                        )
                        return False
                    target = new_checksum_record()
                target[CHECKSUM_FILES_KEY] = self.__merged(target[CHECKSUM_FILES_KEY], names)
                save_checksum_record(path, target)
        except (OSError, ChecksumRecordError) as error:
            LOG.warning("%s could not take the claims moving to it, which stay where they are: %s", record, error)
            return False
        return True

    def __merged(self, resident: list[Any], names: Collection[str]) -> list[Any]:
        """One covering record's entries with the incoming claims in them.

        An incoming claim replaces the resident entry of its name **in place**, so a record keeps the
        order it was written in, and any further entry of that name goes -- a duplicate only ever arrives
        by hand-editing, and leaving one behind would keep a hash the incoming claim has just superseded.

        :param resident: the covering record's entries as loaded.
        :param names: the names bound for it, as the losing record spells them.
        :returns: the entries as this hand-over leaves them.
        """
        incoming = {self.__claims[name].name: self.__moved_entry(name) for name in names}
        taken: set[str] = set()
        merged: list[Any] = []
        for raw in resident:
            name = checksum_entry_name(raw)
            if name is None or name not in incoming:
                merged.append(raw)
                continue
            if name in taken:
                continue
            taken.add(name)
            merged.append(incoming[name])
        merged.extend(entry for name, entry in incoming.items() if name not in taken)
        return merged

    def __moved_entry(self, name: str) -> dict[str, Any]:
        """One claim as the covering record will hold it: renamed, dated by nothing, judged by nothing.

        :param name: the name the losing record spells it under.
        :returns: the entry to write -- the hash and every other key carried as found, under the name
            that record spells the file with.
        """
        moved: dict[str, Any] = {CHECKSUM_NAME_KEY: self.__claims[name].name}
        for key, value in self.__entries[name].items():
            if key not in (CHECKSUM_NAME_KEY, CHECKSUM_VERIFIED_KEY, CHECKSUM_STATUS_KEY):
                moved[key] = value
        return moved


def hand_over_claims(
    claims: Mapping[str, CoveringRecord],
    entries: Mapping[str, Any],
    *,
    coordinator: RenameCoordinator | None = None,
) -> dict[str, CoveringRecord]:
    """Write each claim into the record that covers its file now (#257).

    The one thing a record's entries do other than stay, be checked, or be dropped: they *leave*, for the
    record that covers those bytes today (:func:`~rehuco_core.covering_content_records`). Written before
    the losing record is rewritten without them, so a failure in between duplicates a claim rather than
    destroying one.

    :param claims: where each name goes, by the name the losing record spells it under.
    :param entries: the raw entries that record holds, by the same names.
    :param coordinator: the rename barrier to write through (#241), or ``None`` for a private one.
    :returns: the claims actually written, by that same name -- what the losing record may now drop. A
        destination that could not be written, or that is still owed its legacy-manifest seed (#243),
        keeps its claims in the losing record for a later run.
    """
    return ClaimHandover(claims, entries, coordinator).hand_over()
