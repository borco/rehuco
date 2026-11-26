"""*Refresh License* as two jobs on the task queue ([[assets#licenses]], #688, #705): one that reads and compares, one
that replaces what the user chose to replace.

**A record's saved text of a license is only changed by a refresh when it has none.** A record holds several licenses,
each with its own text in its ``.rehuterms`` (#705), so the jobs work on each license of each record. The first job
reads each distinct ``url`` among the selected records' licenses once and puts it in each record's ``.rehuterms`` under
that license's id: a license with no text gets it, one holding the same text is left alone, and one holding another
text is **kept as it is** and handed back as a :class:`LicenseDifference` -- the license, the store's text, and every
record holding another -- for the user to decide on (:mod:`~rehuco_agent.rehuco.license_refresh`). A text with no
``url`` is terms written for that item alone and is never touched, whatever its license's ``url`` says. The second job
replaces the texts the user confirmed, and only those still as the first job read them.

Neither writes the ``.rehu``: a text lives in its own file, written under the record's lock like every write of a
record's files, inside the rename barrier. What no reader knows, what cannot be read, and what is locked or on a share
that does not answer is counted and logged, and never stops the rest.
"""

import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, override

from borco_core import Presence, presence_of
from rehuco_core import (
    ASSET_PLUGIN,
    DEFAULT_RENAME_COORDINATOR,
    PROGRESS_UNIT_RESOURCES,
    JobControl,
    JobOutcome,
    LicenseTerms,
    LicenseTermsError,
    LicenseTermsSet,
    RecordLockedError,
    RehuDocument,
    RehuFormatError,
    RenameCoordinator,
    TaskJobBase,
    locked_record,
    read_license_terms,
    write_license_terms,
)

from .library_site import StoreOfflineError
from .protocols import FetchError

LOG: Final = logging.getLogger(__name__)

type LicenseTextReader = Callable[[str], LicenseTerms | None]
"""What reads the text a license's ``url`` names, today: the terms, or ``None`` for an address it knows no text for. It
raises :class:`~.library_site.StoreOfflineError` for a store that does not answer and
:class:`~.protocols.FetchError` for an answer that is no text."""


class LicenseRefreshResult(Enum):
    """What became of one license of a record in a refresh -- or of the whole record, when it was left out before its
    licenses were looked at -- in the order a summary says them."""

    WRITTEN = "written"
    REPLACED = "replaced"
    UNCHANGED = "unchanged"
    DIFFERENT = "differ"
    OWN = "with terms of their own"
    NO_TEXT = "with no text to read"
    NOT_ASSET = "not assets"
    UNREADABLE = "unreadable"
    UNANSWERED = "whose text could not be read"
    LOCKED = "locked"
    OFFLINE = "offline"
    GONE = "gone"
    CHANGED = "changed meanwhile"


NEEDS_A_LOOK: Final = frozenset(
    {
        LicenseRefreshResult.DIFFERENT,
        LicenseRefreshResult.UNREADABLE,
        LicenseRefreshResult.UNANSWERED,
        LicenseRefreshResult.LOCKED,
        LicenseRefreshResult.OFFLINE,
        LicenseRefreshResult.GONE,
        LicenseRefreshResult.CHANGED,
    }
)
"""The results a user has something to do about: a text to decide on, or a record left as it was for a reason that
may pass."""


@dataclass(frozen=True)
class SavedLicense:
    """A record whose saved text of one license is not the one the store gives today.

    :param record: the ``.rehu``.
    :param license_id: the license, by its short id.
    :param terms: the text the record holds for it, as read.
    """

    record: Path
    license_id: str
    terms: LicenseTerms


@dataclass(frozen=True)
class LicenseDifference:
    """One license whose text the store gives differently from some records' saved text.

    :param url: the ``url`` the records' license states.
    :param terms: the store's text, read today.
    :param holders: the records holding another text, in the order they were selected.
    """

    url: str
    terms: LicenseTerms
    holders: tuple[SavedLicense, ...]


def same_text(saved: LicenseTerms, fresh: LicenseTerms) -> bool:
    """Whether two readings of a license say the same: their text, without the blanks around it. The title and the date
    are not the terms.

    :param saved: what a record holds.
    :param fresh: what the store gives.
    :returns: whether the text is the same.
    """
    return saved.text.strip() == fresh.text.strip()


class LicenseRefreshJobBase(TaskJobBase):  # pylint: disable=abstract-method  # a base; each subclass runs
    """What the two jobs share: the records they work on, who they write as, what they counted.

    **Unchained and not kept in the saved queue**: a refresh reads a store, so it takes turns with no disk, and one
    cut off by a quit is asked for again, which costs nothing it did not already do.

    :param username: whose identity the locks are written under.
    :param coordinator: the rename barrier every read and write of a record's files is made inside.
    """

    chain = None
    progress_unit = PROGRESS_UNIT_RESOURCES

    def __init__(self, username: str, coordinator: RenameCoordinator) -> None:
        super().__init__()
        self._username: Final = username
        self._coordinator: Final = coordinator
        self._results = Counter[LicenseRefreshResult]()

    @property
    def results(self) -> Counter[LicenseRefreshResult]:
        """How many licenses of records -- or whole records, for one left out -- each result happened to in the last
        run."""
        return self._results

    @property
    def outcome(self) -> JobOutcome | None:
        """What the last run did, in one line: ``None`` before it counted anything.

        :returns: the line, every result that happened in the order of :class:`LicenseRefreshResult`.
        """
        parts = [f"{self._results[result]} {result.value}" for result in LicenseRefreshResult if self._results[result]]
        if not parts:
            return None
        return JobOutcome(", ".join(parts), clean=not any(self._results[result] for result in NEEDS_A_LOOK))

    def _unreachable(self, record: Path, error: OSError) -> None:
        """Count a record that could not be reached: its share does not answer, or it could not be read.

        :param record: the ``.rehu``.
        :param error: what failed.
        """
        offline = presence_of(record.parent) is Presence.OFFLINE
        self._results[LicenseRefreshResult.OFFLINE if offline else LicenseRefreshResult.UNREADABLE] += 1
        LOG.warning("%s: its license text could not be %s: %s", record, "reached" if offline else "read", error)

    def _write(
        self,
        record: Path,
        license_id: str,
        terms: LicenseTerms,
        *,
        expecting: LicenseTerms | None,
        written: LicenseRefreshResult,
    ) -> None:
        """Write one license's text into a record's ``.rehuterms`` under its lock, if it still holds what the run read
        there; the record's other texts are left as they are.

        :param record: the ``.rehu``.
        :param license_id: the license, by its short id.
        :param terms: the text to write.
        :param expecting: the text of that license the file held when it was read, ``None`` for none: one that holds
            something else now was written meanwhile, and is left as it is.
        :param written: what a write counts as.
        """
        try:
            with self._coordinator.holding(), locked_record(record, user=self._username):
                if not record.is_file():
                    self._results[LicenseRefreshResult.GONE] += 1
                    LOG.warning("%s is gone: its license text was not written.", record)
                    return
                current = read_license_terms(record) or LicenseTermsSet()
                if current.get(license_id) != expecting:
                    self._results[LicenseRefreshResult.CHANGED] += 1
                    LOG.info("%s: its text of %s changed meanwhile; left as it is.", record, license_id)
                    return
                write_license_terms(record, current.with_terms(license_id, terms))
        except RecordLockedError as error:
            self._results[LicenseRefreshResult.LOCKED] += 1
            LOG.warning("%s: its license text was not written: %s", record, error)
        except LicenseTermsError as error:
            self._results[LicenseRefreshResult.UNREADABLE] += 1
            LOG.warning("%s", error)
        except OSError as error:
            self._unreachable(record, error)
        else:
            self._results[written] += 1
            LOG.info("%s: its text of %s was %s.", record, license_id, written.value)


class RefreshLicenseJob(LicenseRefreshJobBase):
    """Read the texts the selected records' licenses name, and write the ones that have none.

    :param records: the ``.rehu`` of each selected record.
    :param read_text: what reads the text a license's ``url`` names.
    :param username: whose identity the locks are written under.
    :param coordinator: the rename barrier the records' files are read and written inside.
    """

    def __init__(
        self,
        records: Sequence[Path],
        read_text: LicenseTextReader,
        *,
        username: str,
        coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
    ) -> None:
        super().__init__(username, coordinator)
        self.__records: Final = tuple(dict.fromkeys(records))
        self.__read_text: Final = read_text
        self.__differences: tuple[LicenseDifference, ...] = ()
        self.label = f"Refresh License - {len(self.__records):,} record{'' if len(self.__records) == 1 else 's'}"

    @property
    def differences(self) -> tuple[LicenseDifference, ...]:
        """The licenses the store gives another text for than some records hold, as the last run found them -- for the
        user to decide on; nothing of them is written."""
        return self.__differences

    @override
    def reset(self) -> None:
        """Forget what the last run found."""
        super().reset()
        self._results.clear()
        self.__differences = ()

    @override
    def run(self, control: JobControl) -> None:
        """Read the records, then each distinct license address once, then settle each record's license against it.

        :param control: the engine's face to this job.
        """
        self._results.clear()
        self.__differences = ()
        wanted: dict[str, list[tuple[Path, str, LicenseTerms | None]]] = {}
        left_out = 0
        for record in self.__records:
            self.checkpoint()
            found = self.__inspect(record)
            left_out += not found
            for url, license_id, saved in found:
                wanted.setdefault(url, []).append((record, license_id, saved))
        total = left_out + sum(len(group) for group in wanted.values())
        done = left_out
        control.report(done, total)
        differences: list[LicenseDifference] = []
        for url, group in wanted.items():
            self.checkpoint()
            terms = self.__fresh(url, len(group))
            if terms is None:
                done += len(group)
                control.report(done, total)
                continue
            holders: list[SavedLicense] = []
            for record, license_id, saved in group:
                self.checkpoint()
                if saved is None:
                    self._write(record, license_id, terms, expecting=None, written=LicenseRefreshResult.WRITTEN)
                elif same_text(saved, terms):
                    self._results[LicenseRefreshResult.UNCHANGED] += 1
                else:
                    self._results[LicenseRefreshResult.DIFFERENT] += 1
                    holders.append(SavedLicense(record, license_id, saved))
                done += 1
                control.report(done, total)
            if holders:
                differences.append(LicenseDifference(url, terms, tuple(holders)))
        self.__differences = tuple(differences)

    def __inspect(self, record: Path) -> list[tuple[str, str, LicenseTerms | None]]:
        """What a record needs of the store: the address of each of its licenses and the text it holds for it.

        :param record: the ``.rehu``.
        :returns: each license's address, id and saved text, ``None`` for none; a license or a record left out is
            counted as why: not an asset, stating no address, holding terms of its own, or unreadable.
        """
        try:
            with self._coordinator.holding():
                document = RehuDocument.load(record, username=self._username)
                saved = read_license_terms(record) or LicenseTermsSet()
        except (RehuFormatError, LicenseTermsError) as error:
            self._results[LicenseRefreshResult.UNREADABLE] += 1
            LOG.warning("%s: %s", record, error)
            return []
        except OSError as error:
            self._unreachable(record, error)
            return []
        if document.type != ASSET_PLUGIN.key:
            self._results[LicenseRefreshResult.NOT_ASSET] += 1
            return []
        found: list[tuple[str, str, LicenseTerms | None]] = []
        for entry in document.licenses:
            url = (entry.url or "").strip()
            held = saved.get(entry.license)
            if not url:
                self._results[LicenseRefreshResult.NO_TEXT] += 1
            elif held is not None and held.url is None:
                self._results[LicenseRefreshResult.OWN] += 1
            else:
                found.append((url, entry.license, held))
        if not document.licenses:
            self._results[LicenseRefreshResult.NO_TEXT] += 1
        return found

    def __fresh(self, url: str, records: int) -> LicenseTerms | None:
        """The text a license address gives today.

        :param url: the address.
        :param records: how many licenses of records state it, for what it counts when there is no text.
        :returns: the terms; ``None`` when there are none to compare with, counted as why: a store that does not
            answer costs the records of that license and no other, and the refresh is asked for again.
        """
        try:
            terms = self.__read_text(url)
        except (StoreOfflineError, FetchError) as error:
            self._results[LicenseRefreshResult.UNANSWERED] += records
            LOG.warning("The license text of %s could not be read: %s", url, error)
            return None
        if terms is None:
            self._results[LicenseRefreshResult.NO_TEXT] += records
            LOG.info("No text is known for the license address %s: %s record(s) left as they are.", url, records)
        return terms


class ReplaceLicenseJob(LicenseRefreshJobBase):
    """Replace the saved texts the user confirmed with the store's, where a record still holds the one that was
    compared.

    :param differences: the licenses to replace the text of, each with the records holding another.
    :param username: whose identity the locks are written under.
    :param coordinator: the rename barrier the records' files are read and written inside.
    """

    def __init__(
        self,
        differences: Sequence[LicenseDifference],
        *,
        username: str,
        coordinator: RenameCoordinator = DEFAULT_RENAME_COORDINATOR,
    ) -> None:
        super().__init__(username, coordinator)
        self.__differences: Final = tuple(differences)
        count = sum(len(difference.holders) for difference in self.__differences)
        self.label = f"Replace License text - {count:,} record{'' if count == 1 else 's'}"

    @override
    def reset(self) -> None:
        """Forget what the last run counted."""
        super().reset()
        self._results.clear()

    @override
    def run(self, control: JobControl) -> None:
        """Replace each record's text with its license's.

        :param control: the engine's face to this job.
        """
        self._results.clear()
        total = sum(len(difference.holders) for difference in self.__differences)
        done = 0
        for difference in self.__differences:
            for holder in difference.holders:
                self.checkpoint()
                self._write(
                    holder.record,
                    holder.license_id,
                    difference.terms,
                    expecting=holder.terms,
                    written=LicenseRefreshResult.REPLACED,
                )
                done += 1
                control.report(done, total)
