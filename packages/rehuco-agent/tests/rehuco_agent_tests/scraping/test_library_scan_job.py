"""Tests for the library scan job (#682): where a run starts, what it does with each item, how it stops, and what it
keeps.

Everything the job drives is tested where it lives and stands in here: the site and its session (`Mock`s of their
protocols), the catalog's cache and its updater, the record writer (`test_library_record_writer.py`), the persona
browser (`test_persona_lease.py`) and the records a rescan marks. The wait between pages runs on a patched clock.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock, Mock, call
from uuid import UUID

import pytest
from pytest import fixture, raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping import library_scan_job as job_module
from rehuco_agent.scraping.library_record_writer import WrittenRecord
from rehuco_agent.scraping.library_scan_job import (
    ADDED_LINE,
    LIBRARY_SCAN_KIND,
    PRESENT_LINE,
    LibraryScanJob,
    LibraryScanTarget,
)
from rehuco_agent.scraping.library_site import (
    LibraryEntry,
    LibrarySession,
    LibrarySite,
    ScannedItem,
    StoreOfflineError,
    StorePausedError,
)
from rehuco_agent.scraping.protocols import FetchError
from rehuco_agent.scraping.results import ScrapeResult
from rehuco_agent.settings.scrapers_settings import Browser
from rehuco_core import (
    DEFAULT_RECORD_MOVE_HOST,
    CatalogCache,
    CatalogRecord,
    CatalogRoot,
    CatalogRow,
    JobControl,
    JobOutcome,
    JobPaused,
    JobWaiting,
    LibraryCursor,
    PersistableTaskJob,
    RecordConflict,
    RecordKind,
    RecordLockedError,
    ReportingTaskJob,
)

ROOT_ID: Final = UUID(int=7)
"""The root every scan below fills."""

OLD: Final = LibraryEntry("old", "2024-01-01T00:00:00.000000Z", "Old", "https://fab.example/old")
"""An item the cursor already covers."""

FILED: Final = LibraryEntry("filed", "2024-02-01T00:00:00.000000Z", "Filed", "https://fab.example/filed")
"""An item the root already holds a record of, past the cursor."""

NEW: Final = LibraryEntry("new", "2024-03-01T00:00:00.000000Z", "New", "https://fab.example/new")
"""An item the root has no record of."""

NEWER: Final = LibraryEntry("newer", "2024-04-01T00:00:00.000000Z", "Newer", "https://fab.example/newer")
"""A second item the root has no record of."""


LISTED_ROOT: Final = CatalogRoot(ROOT_ID, "Assets", Path("assets"), 0, False, True, None)
"""The scanned root's row in the cache, while the catalog lists it."""


def target(tmp_path: Path, *, full_rescan: bool = False) -> LibraryScanTarget:
    """A scan of the Fab library into the root.

    :param tmp_path: where the catalog's files are.
    :param full_rescan: whether the whole library is walked again.
    :returns: the target.
    """
    return LibraryScanTarget("fab", ROOT_ID, "Assets", tmp_path / "root.rehuroot", tmp_path / "c.rehudb", full_rescan)


def scanned(entry: LibraryEntry, license_path: str | None = "license/standard") -> ScannedItem:
    """An item read in full.

    :param entry: what the listing said of it.
    :param license_path: the license it is held under.
    :returns: the item.
    """
    return ScannedItem(ScrapeResult({"title": entry.title}, None, ()), entry.url, license_path)


# one stand-in for each thing a scan drives, and the listing it walks
@dataclass
class Store:  # pylint: disable=too-many-instance-attributes
    """The stand-ins one scan drives: the site, its session, the cache, the writer and the persona.

    :param site: the site.
    :param session: its open library.
    :param cache: the catalog's cache, as the job opens it.
    :param writer: the record writer the job builds.
    :param updater: the cache updater the job builds.
    :param browser: the persona browser.
    :param lease: the lease the job takes on it.
    :param entries: what the listing yields, oldest first, one page each.
    """

    site: Mock
    session: Mock
    cache: Mock
    writer: Mock
    updater: Mock
    browser: Mock
    lease: Mock
    entries: list[LibraryEntry] = field(default_factory=list)

    def listing(self, cursor: LibraryCursor, wait: Callable[[], None]) -> Iterator[LibraryEntry]:
        """Yield the entries, waiting between two of them as a site waits between pages.

        :param cursor: unused; what the job asked from is checked on the session mock.
        :param wait: the job's paced wait.
        :returns: the entries.
        """
        del cursor
        for index, entry in enumerate(self.entries):
            if index:
                wait()
            yield entry


def context(entered: object) -> MagicMock:
    """A context manager whose ``with`` hands out ``entered``.

    :param entered: what entering it returns.
    :returns: the manager.
    """
    manager = MagicMock()
    manager.__enter__.return_value = entered
    manager.__exit__.return_value = False
    return manager


@fixture(name="store")
def fixture_store(mocker: MockerFixture, tmp_path: Path) -> Store:
    """Everything a scan drives, stood in for, the root mapped and the clock patched so waits pass at once.

    :param mocker: pytest-mock fixture.
    :param tmp_path: where the catalog's files are.
    :returns: the stand-ins.
    """
    site = mocker.Mock(spec=LibrarySite)
    site.key, site.name = "fab", "Fab"
    session = mocker.Mock(spec=LibrarySession)
    site.session.return_value = context(session)
    cache = mocker.Mock(spec=CatalogCache)
    cache.library_cursor.return_value = LibraryCursor(OLD.acquired, frozenset({OLD.site_id}))
    cache.find_by_site_id.side_effect = lambda _site, site_id, _root: [row(FILED)] if site_id == FILED.site_id else []
    cache.library_rows.return_value = []
    cache.roots.return_value = (LISTED_ROOT,)
    mocker.patch.object(CatalogCache, "open", return_value=context(cache))
    writer = mocker.patch.object(job_module, "LibraryRecordWriter").return_value
    writer.root_folder.return_value = tmp_path / "root"
    writer.write.side_effect = lambda entry, _item, _site, _terms: WrittenRecord(tmp_path / entry.site_id / "info.rehu")
    updater = mocker.patch.object(job_module, "CatalogRecordUpdater").return_value
    lease = mocker.Mock()
    browser = mocker.patch.object(job_module, "shared_persona_browser").return_value
    browser.lease.return_value = context(lease)
    mocker.patch.object(job_module, "shared_scrapers_settings").return_value = mocker.Mock(
        browser=Browser.FIREFOX, show_browser=False
    )
    mocker.patch.object(job_module, "shared_identity_settings").return_value = mocker.Mock(
        current_username="me", unknown_username="unknown"
    )
    mocker.patch.object(DEFAULT_RECORD_MOVE_HOST, "root_folder", return_value=tmp_path / "root")
    mocker.patch("rehuco_agent.scraping.library_scan_job.random.uniform", return_value=0.25)
    clock = iter(range(1000))
    mocker.patch("rehuco_agent.scraping.library_scan_job.time.monotonic", side_effect=lambda: next(clock) / 10)
    mocker.patch("rehuco_agent.scraping.library_scan_job.time.sleep")
    built = Store(site, session, cache, writer, updater, browser, lease)
    session.listing.side_effect = built.listing
    session.read_item.side_effect = scanned
    session.read_license.return_value = None
    return built


def row(entry: LibraryEntry, *, dated: bool = True) -> CatalogRow:
    """The cache's row of a record of an item.

    :param entry: the item.
    :param dated: whether the record names when it was acquired.
    :returns: the row.
    """
    record = CatalogRecord(
        f"Fab/{entry.site_id}/info.rehu",
        RecordKind.REHU,
        title=entry.title,
        site_ids=(("Fab", entry.site_id),),
        acquired=entry.acquired if dated else None,
    )
    return CatalogRow(1, ROOT_ID, "Assets", record, 0.0)


def job_of(store: Store, scan: LibraryScanTarget) -> LibraryScanJob:
    """A scan of the store's site.

    :param store: the stand-ins.
    :param scan: what to scan.
    :returns: the job.
    """
    return LibraryScanJob(lambda key: store.site if key == "fab" else None, scan)


# region A run


def test_a_scan_is_a_persistable_reporting_job_of_its_own_kind(store: Store, tmp_path: Path) -> None:
    """The queue saves it, restores it by its kind and shows what it found; its row names the store and the root.

    **Test steps:**

    * build a scan
    * verify it satisfies both protocols, under its kind, with a label naming the store and the root
    """
    job = job_of(store, target(tmp_path))

    assert isinstance(job, PersistableTaskJob)
    assert isinstance(job, ReportingTaskJob)
    assert job.kind == LIBRARY_SCAN_KIND
    assert job.label == "Scan the Fab library into Assets"
    assert job.resumes_where_it_stopped is True


def test_a_run_files_what_the_root_lacks_from_where_its_records_reach(
    store: Store, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The records are the cursor: a run asks the cache how far they reach, skips what is filed, writes the rest.

    **Test steps:**

    * list an item the cursor covers, one the root holds already, and a new one
    * run the scan
    * verify the session was asked first, then listed from the root's cursor
    * verify only the new item was read and written, entered in the cache and settled, and each item logged
    * verify the outcome counts the one added and the one already there
    """
    caplog.set_level("INFO")
    store.entries = [OLD, FILED, NEW]
    control = Mock(spec=JobControl)
    job = job_of(store, target(tmp_path))

    job.run(control)

    store.session.check.assert_called_once_with()
    assert store.session.listing.call_args.args[0] == LibraryCursor(OLD.acquired, frozenset({OLD.site_id}))
    store.session.read_item.assert_called_once_with(NEW)
    written = WrittenRecord(tmp_path / "new" / "info.rehu")
    store.updater.upsert.assert_called_once_with(written.path)
    store.writer.settle.assert_called_once_with(written)
    assert ADDED_LINE % (NEW.title, NEW.url) in caplog.text
    assert PRESENT_LINE % (FILED.title, FILED.url) in caplog.text
    assert control.report.call_args_list == [call(1), call(2)]
    assert job.outcome == JobOutcome("1 added, 1 already there")


def test_a_license_is_read_once_per_run_and_handed_to_the_writer(store: Store, tmp_path: Path) -> None:
    """One license under many items is read from the store once.

    **Test steps:**

    * list two new items under the same license
    * run the scan
    * verify the license was read once, and both writes were handed its text
    """
    store.entries = [NEW, NEWER]
    terms = Mock()
    store.session.read_license.return_value = terms

    job_of(store, target(tmp_path)).run(Mock(spec=JobControl))

    store.session.read_license.assert_called_once_with("license/standard")
    assert [write.args[3] for write in store.writer.write.call_args_list] == [terms, terms]


def test_a_license_is_read_again_by_the_next_run(store: Store, tmp_path: Path) -> None:
    """A run reads the terms as they are on its day, never a text an earlier run kept.

    **Test steps:**

    * run a scan over one new item, then run it again over another under the same license
    * verify the license was read once by each run
    """
    job = job_of(store, target(tmp_path))
    store.entries = [NEW]
    job.run(Mock(spec=JobControl))
    store.entries = [NEWER]

    job.run(Mock(spec=JobControl))

    assert store.session.read_license.call_count == 2


def test_an_item_naming_no_license_reads_none(store: Store, tmp_path: Path) -> None:
    """An item held under no license the store names gets no text.

    **Test steps:**

    * list a new item naming no license
    * run the scan
    * verify no license was read and the write was handed none
    """
    store.entries = [NEW]
    store.session.read_item.side_effect = lambda entry: scanned(entry, None)

    job_of(store, target(tmp_path)).run(Mock(spec=JobControl))

    store.session.read_license.assert_not_called()
    assert store.writer.write.call_args.args[3] is None


def test_the_persona_is_offered_to_a_drop_before_every_item_and_in_every_wait(store: Store, tmp_path: Path) -> None:
    """A drop waiting for the browser gets it before the next item, and in the wait between two pages.

    **Test steps:**

    * list two new items, so the listing waits once between them
    * run the scan
    * verify the lease was asked to yield before each item and in that wait
    """
    store.entries = [NEW, NEWER]

    job_of(store, target(tmp_path)).run(Mock(spec=JobControl))

    assert store.lease.yield_if_wanted.call_count == 3


def test_a_pause_asked_during_the_wait_unwinds_before_the_next_item(
    store: Store, tmp_path: Path, mocker: MockerFixture
) -> None:
    """The checkpoints sit inside the wait for a page, so a pause or an app close costs at most the item in hand.

    **Test steps:**

    * list two new items, and have the scan asked to pause during the first slice of the wait between them
    * run the scan
    * verify it paused with no reason after that one slice, and the second item was never read
    """
    store.entries = [NEW, NEWER]
    job = job_of(store, target(tmp_path))
    sleep = mocker.patch("rehuco_agent.scraping.library_scan_job.time.sleep", side_effect=lambda _seconds: job.pause())

    with raises(JobPaused) as paused:
        job.run(Mock(spec=JobControl))

    assert paused.value.reason is None
    assert sleep.call_count == 1
    store.session.read_item.assert_called_once_with(NEW)


# endregion

# region Stops


def test_a_challenge_pauses_with_its_reason_and_shows_the_browser_once_the_session_is_closed(
    store: Store, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A challenge page is the user's to answer in the browser, which the scan's own session must have let go first.

    **Test steps:**

    * make the session's first question meet a challenge
    * run the scan
    * verify it paused with the challenge's reason
    * verify the persona browser was opened at the page, after the session and the lease were closed
    """
    order = mocker.Mock()

    def closing(name: str) -> Callable[..., bool]:
        """An ``__exit__`` that records its closing and lets the exception through.

        :param name: what to record.
        :returns: the stand-in.
        """

        def exit_(*_: object) -> bool:
            getattr(order, name)()
            return False

        return exit_

    store.session.check.side_effect = StorePausedError("Fab asks for a challenge.", "https://fab.example/challenge")
    store.site.session.return_value.__exit__.side_effect = closing("session_closed")
    store.browser.lease.return_value.__exit__.side_effect = closing("lease_closed")
    store.browser.open_for_login.side_effect = lambda *_: order.browser_opened()

    with raises(JobPaused) as paused:
        job_of(store, target(tmp_path)).run(Mock(spec=JobControl))

    assert paused.value.reason == "Fab asks for a challenge."
    store.browser.open_for_login.assert_called_once_with(Browser.FIREFOX, "https://fab.example/challenge")
    assert [name for name, _, _ in order.mock_calls] == ["session_closed", "lease_closed", "browser_opened"]


def test_a_browser_that_cannot_open_still_pauses_with_the_reason(store: Store, tmp_path: Path) -> None:
    """The reason is on the row whether or not the browser could be shown.

    **Test steps:**

    * make the session meet an expired login, and the browser fail to open
    * run the scan
    * verify it paused with the login's reason
    """
    store.session.check.side_effect = StorePausedError("Log in to Fab again.", "https://fab.example/login")
    store.browser.open_for_login.side_effect = FetchError("no Firefox here")

    with raises(JobPaused, match="Log in to Fab again."):
        job_of(store, target(tmp_path)).run(Mock(spec=JobControl))


def test_a_store_that_does_not_answer_makes_the_scan_wait(store: Store, tmp_path: Path) -> None:
    """A network down comes back by itself, so the queue tries again.

    **Test steps:**

    * make the listing meet a store that does not answer
    * run the scan
    * verify it waits with the store's reason
    """
    store.session.listing.side_effect = StoreOfflineError("Fab does not answer.")

    with raises(JobWaiting, match="Fab does not answer."):
        job_of(store, target(tmp_path)).run(Mock(spec=JobControl))


def test_a_persona_browser_that_will_not_start_pauses_the_scan(store: Store, tmp_path: Path) -> None:
    """A login window holding the profile is the user's to close, so the scan pauses saying so.

    **Test steps:**

    * make the session fail to start the browser
    * run the scan
    * verify it paused with the browser's error
    """
    store.session.check.side_effect = FetchError("Could not start Firefox: in use")

    with raises(JobPaused, match="Could not start Firefox"):
        job_of(store, target(tmp_path)).run(Mock(spec=JobControl))


@pytest.mark.usefixtures("store")
def test_a_site_no_longer_installed_pauses_the_run(tmp_path: Path) -> None:
    """A run whose site went away between its start check and its run stops, saying which.

    **Test steps:**

    * build a scan whose site lookup finds nothing
    * run it
    * verify it paused naming the site
    """
    job = LibraryScanJob(lambda _key: None, target(tmp_path))

    with raises(JobPaused, match="No library scanner named fab"):
        job.run(Mock(spec=JobControl))


# endregion

# region A full rescan


def test_a_full_rescan_marks_what_left_the_account_offline_and_keeps_its_position(
    store: Store, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A rescan reads the whole library again and marks the records it passed over, changing nothing else.

    **Test steps:**

    * hold dated records of an item still listed and of one no longer listed, and an undated one
    * rescan, listing only the first
    * verify the unlisted dated record was saved offline against the version read and entered in the cache, and the
      undated one left alone
    * verify the outcome counts it, and the saved state holds the rescan's position
    """
    gone = LibraryEntry("gone", "2024-02-15T00:00:00.000000Z", "Gone", "https://fab.example/gone")
    store.cache.library_rows.return_value = [row(FILED), row(gone), row(OLD, dated=False)]
    store.cache.find_by_site_id.side_effect = lambda _site, site_id, _root: {
        FILED.site_id: [row(FILED)],
        gone.site_id: [row(gone)],
    }.get(site_id, [])
    records = mocker.patch.object(job_module, "Records").return_value
    loaded = records.load.return_value
    loaded.document.active_field.return_value = True
    store.entries = [FILED]
    job = job_of(store, target(tmp_path, full_rescan=True))

    job.run(Mock(spec=JobControl))

    store.session.listing.assert_called_once()
    assert store.session.listing.call_args.args[0] == LibraryCursor()
    loaded.document.set_active_field.assert_called_once_with("online", False)
    assert records.save.call_args.args[2] is loaded.version
    store.updater.upsert.assert_called_once_with(tmp_path / "root" / "Fab" / "gone" / "info.rehu")
    assert job.outcome == JobOutcome("0 added, 1 already there, 1 no longer in the account")
    assert job.capture_state()["position"] == {"acquired": FILED.acquired, "site_ids": [FILED.site_id]}


def test_a_record_already_offline_is_not_saved_again(store: Store, tmp_path: Path, mocker: MockerFixture) -> None:
    """A record a rescan finds gone twice is written once.

    **Test steps:**

    * hold a dated record no longer listed, already marked offline
    * rescan an empty library
    * verify nothing was saved
    """
    store.cache.library_rows.return_value = [row(FILED)]
    store.cache.find_by_site_id.side_effect = lambda _site, _site_id, _root: [row(FILED)]
    records = mocker.patch.object(job_module, "Records").return_value
    records.load.return_value.document.active_field.return_value = False

    job_of(store, target(tmp_path, full_rescan=True)).run(Mock(spec=JobControl))

    records.save.assert_not_called()


# endregion

# region What is kept


def test_a_scan_restored_from_its_state_is_the_scan_that_was_captured(store: Store, tmp_path: Path) -> None:
    """The state holds the target and a rescan's position, and nothing the records can say.

    **Test steps:**

    * capture a rescan's state, with a position
    * restore a bare job from it
    * verify the restored job captures the same state and names itself alike
    """
    original = job_of(store, target(tmp_path, full_rescan=True))
    state: dict[str, Any] = original.capture_state()
    state["position"] = {"acquired": FILED.acquired, "site_ids": [FILED.site_id]}

    restored = LibraryScanJob(lambda key: store.site if key == "fab" else None)
    restored.restore_state(state)

    assert restored.capture_state() == state
    assert restored.label == "Full rescan of the Fab library into Assets"


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"site": "fab", "root": str(ROOT_ID), "root_label": 1, "root_file": "r", "cache": "c"},
        {"site": "fab", "root": str(ROOT_ID), "root_label": "A", "root_file": "r", "cache": "c", "full_rescan": "yes"},
        {
            "site": "fab",
            "root": str(ROOT_ID),
            "root_label": "A",
            "root_file": "r",
            "cache": "c",
            "position": {"acquired": 5},
        },
        {
            "site": "fab",
            "root": str(ROOT_ID),
            "root_label": "A",
            "root_file": "r",
            "cache": "c",
            "counts": [1, 2, 3],
        },
        {
            "site": "fab",
            "root": str(ROOT_ID),
            "root_label": "A",
            "root_file": "r",
            "cache": "c",
            "counts": {"added": True},
        },
    ],
    ids=[
        "empty",
        "a-label-not-text",
        "a-flag-not-a-bool",
        "a-position-not-a-time",
        "counts-not-a-mapping",
        "a-count-not-a-number",
    ],
)
def test_a_state_this_class_did_not_write_is_refused(state: dict[str, Any]) -> None:
    """A queue file someone edited is refused rather than restored half-built.

    **Test steps:**

    * restore a bare job from a state missing or mistyping a key
    * verify it is refused
    """
    with raises(ValueError):
        LibraryScanJob(lambda _key: None).restore_state(state)


def test_a_bare_job_has_nothing_to_capture() -> None:
    """A job built for restoring and never restored names no scan.

    **Test steps:**

    * build a bare job
    * verify it is named as a library scan, and capturing its state is refused
    """
    job = LibraryScanJob(lambda _key: None)

    assert job.label == "Library scan"
    with raises(ValueError):
        job.capture_state()


def test_retrying_a_rescan_starts_it_over(store: Store, tmp_path: Path) -> None:
    """Retry means start over: the position and the counts go.

    **Test steps:**

    * restore a rescan with a position and run it over one present item
    * reset it
    * verify its position is empty and it reports no outcome
    """
    job = job_of(store, target(tmp_path, full_rescan=True))
    store.entries = [FILED]
    job.run(Mock(spec=JobControl))

    job.reset()

    assert job.capture_state()["position"] == {"acquired": None, "site_ids": []}
    assert job.outcome is None


def test_a_scan_with_nothing_walked_reports_no_outcome(store: Store, tmp_path: Path) -> None:
    """Before an item is walked there is nothing to say.

    **Test steps:**

    * build a scan
    * verify it has no outcome
    """
    assert job_of(store, target(tmp_path)).outcome is None


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ("no-target", "names no library"),
        ("no-site", "No library scanner named fab"),
        ("no-root", "maps no folder to the root Assets"),
        ("no-cache", "cache is gone"),
    ],
)
def test_a_scan_that_cannot_start_says_why(
    store: Store, tmp_path: Path, mocker: MockerFixture, change: str, refusal: str
) -> None:
    """Before every start the scan checks its site, its root and its catalog's cache.

    **Test steps:**

    * take away one of the target, the site, the root's folder or the cache file
    * ask the scan whether it can start
    * verify it refuses, saying which
    """
    (tmp_path / "c.rehudb").write_text("", encoding="utf-8")
    sites: Callable[[str], LibrarySite | None] = lambda _key: None if change == "no-site" else store.site  # noqa: E731
    job = LibraryScanJob(sites, None if change == "no-target" else target(tmp_path))
    if change == "no-root":
        mocker.patch.object(DEFAULT_RECORD_MOVE_HOST, "root_folder", return_value=None)
    if change == "no-cache":
        (tmp_path / "c.rehudb").unlink()

    reason = job.validate()

    assert reason is not None
    assert refusal in reason


def test_a_scan_that_can_start_says_nothing(store: Store, tmp_path: Path) -> None:
    """A scan with its site, root and cache in place is startable.

    **Test steps:**

    * create the cache file
    * verify the scan has no objection
    """
    (tmp_path / "c.rehudb").write_text("", encoding="utf-8")

    assert job_of(store, target(tmp_path)).validate() is None


# endregion


def test_a_scan_keeps_only_its_target_and_comes_back_as_it_was(store: Store, tmp_path: Path) -> None:
    """A scan that is not a rescan keeps no position: the records say how far it got.

    **Test steps:**

    * capture a scan's state
    * verify it holds no position
    * restore a bare job from it and verify it captures the same state
    """
    state = job_of(store, target(tmp_path)).capture_state()

    restored = LibraryScanJob(lambda key: store.site if key == "fab" else None)
    restored.restore_state(state)

    assert "position" not in state
    assert restored.capture_state() == state


def test_a_record_edited_while_a_rescan_marks_it_is_left_as_it_is(
    store: Store, tmp_path: Path, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """The user's edit landing between the read and the write wins; the record is not counted gone.

    **Test steps:**

    * hold a dated record no longer listed, whose save meets an edit made meanwhile
    * rescan an empty library
    * verify the conflict was logged and nothing was counted gone
    """
    store.cache.library_rows.return_value = [row(FILED)]
    store.cache.find_by_site_id.side_effect = lambda _site, _site_id, _root: [row(FILED)]
    records = mocker.patch.object(job_module, "Records").return_value
    records.load.return_value.document.active_field.return_value = True
    records.save.side_effect = RecordConflict(Mock(), Mock())
    job = job_of(store, target(tmp_path, full_rescan=True))

    job.run(Mock(spec=JobControl))

    assert "changed while a rescan marked it offline" in caplog.text
    assert job.outcome is None


def test_a_record_locked_while_a_rescan_marks_it_makes_the_scan_wait(
    store: Store, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A record another write holds will be let go, so the rescan waits for it.

    **Test steps:**

    * hold a dated record no longer listed, whose save meets a lock held elsewhere
    * rescan an empty library
    * verify the scan waits
    """
    store.cache.library_rows.return_value = [row(FILED)]
    store.cache.find_by_site_id.side_effect = lambda _site, _site_id, _root: [row(FILED)]
    records = mocker.patch.object(job_module, "Records").return_value
    records.load.return_value.document.active_field.return_value = True
    records.save.side_effect = RecordLockedError(tmp_path / "info.rehu", None)

    with raises(JobWaiting):
        job_of(store, target(tmp_path, full_rescan=True)).run(Mock(spec=JobControl))


def test_a_resumed_rescan_marks_what_it_passes_after_its_position(
    store: Store, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A rescan resumed from its saved position judges only what lies past it, and goes on from there.

    **Test steps:**

    * restore a rescan whose position is the filed item, holding a record before it and one between it and the next
    * run it over a listing that names the next item only
    * verify only the record between was marked offline, and the listing was asked from the position
    """
    between = LibraryEntry("between", "2024-02-15T00:00:00.000000Z", "Between", "https://fab.example/between")
    store.cache.library_rows.return_value = [row(OLD), row(FILED), row(between)]
    store.cache.find_by_site_id.side_effect = lambda _site, site_id, _root: {
        OLD.site_id: [row(OLD)],
        FILED.site_id: [row(FILED)],
        between.site_id: [row(between)],
    }.get(site_id, [])
    records = mocker.patch.object(job_module, "Records").return_value
    records.load.return_value.document.active_field.return_value = True
    job = LibraryScanJob(lambda key: store.site if key == "fab" else None)
    state = target(tmp_path, full_rescan=True).to_state()
    state["position"] = {"acquired": FILED.acquired, "site_ids": [FILED.site_id]}
    job.restore_state(state)
    store.entries = [NEW]

    job.run(Mock(spec=JobControl))

    assert store.session.listing.call_args.args[0] == LibraryCursor(FILED.acquired, frozenset({FILED.site_id}))
    assert [load.args[0].path.parent.name for load in records.load.call_args_list] == ["between"]


def test_a_root_gone_quiet_while_a_rescan_marks_makes_the_scan_wait(
    store: Store, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A share switched off mid-rescan is a wait, as it is for a write.

    **Test steps:**

    * hold a dated record no longer listed, whose save fails, while the root then reads as not answering
    * rescan an empty library
    * verify the scan waits
    """
    store.cache.library_rows.return_value = [row(FILED)]
    store.cache.find_by_site_id.side_effect = lambda _site, _site_id, _root: [row(FILED)]
    records = mocker.patch.object(job_module, "Records").return_value
    records.load.return_value.document.active_field.return_value = True
    records.save.side_effect = OSError("the share went away")
    root = tmp_path / "root"
    store.writer.root_folder.side_effect = [root, root, JobWaiting("Waiting for the root", 30.0)]

    with raises(JobWaiting, match="Waiting for the root"):
        job_of(store, target(tmp_path, full_rescan=True)).run(Mock(spec=JobControl))


def test_a_restored_scan_keeps_what_its_runs_counted(store: Store, tmp_path: Path) -> None:
    """The bar and the outcome survive a restart: the counts are saved with the scan.

    **Test steps:**

    * run a scan over a filed item and a new one, and capture its state
    * restore a bare job from it
    * verify the restored job reports the same outcome
    """
    store.entries = [FILED, NEW]
    original = job_of(store, target(tmp_path))
    original.run(Mock(spec=JobControl))

    restored = LibraryScanJob(lambda key: store.site if key == "fab" else None)
    restored.restore_state(original.capture_state())

    assert restored.outcome == JobOutcome("1 added, 1 already there")


def test_a_rescan_save_failing_on_a_root_that_answers_is_raised(
    store: Store, tmp_path: Path, mocker: MockerFixture
) -> None:
    """A failure on a root that still answers is a failure, retryable from the row.

    **Test steps:**

    * hold a dated record no longer listed, whose save fails while the root still answers
    * rescan an empty library
    * verify the failure is raised as it is
    """
    store.cache.library_rows.return_value = [row(FILED)]
    store.cache.find_by_site_id.side_effect = lambda _site, _site_id, _root: [row(FILED)]
    records = mocker.patch.object(job_module, "Records").return_value
    records.load.return_value.document.active_field.return_value = True
    records.save.side_effect = PermissionError("Access is denied")

    with raises(PermissionError):
        job_of(store, target(tmp_path, full_rescan=True)).run(Mock(spec=JobControl))


def test_a_record_the_cache_places_under_no_root_is_logged(
    store: Store, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A record written where the catalog sees no root is said so, since the cursor will not move past it.

    **Test steps:**

    * have the cache refuse the written record
    * run the scan over one new item
    * verify a warning names the record
    """
    store.updater.upsert.return_value = False
    store.entries = [NEW]

    job_of(store, target(tmp_path)).run(Mock(spec=JobControl))

    assert "the catalog places it under no root" in caplog.text


def test_an_item_written_before_its_buckets_made_the_scan_wait_is_counted_added(store: Store, tmp_path: Path) -> None:
    """A wait met while settling leaves the record written, so the run that wrote it counts it.

    **Test steps:**

    * have settling the buckets meet a wait
    * run the scan over one new item
    * verify the scan waits, and its outcome counts the item as added
    """
    store.writer.settle.side_effect = JobWaiting("a record is locked", 10.0)
    store.entries = [NEW]
    job = job_of(store, target(tmp_path))

    with raises(JobWaiting):
        job.run(Mock(spec=JobControl))

    assert job.outcome == JobOutcome("1 added, 0 already there")


def test_a_root_removed_before_the_run_pauses_it_before_anything_is_read(store: Store, tmp_path: Path) -> None:
    """A scan of a root the catalog no longer lists does not start its walk (#685).

    **Test steps:**

    * make the cache list no root
    * run the scan over one new item
    * verify it pauses naming the root, having leased no browser and read nothing
    """
    store.cache.roots.return_value = ()
    store.entries = [NEW]

    with raises(JobPaused, match="The root Assets was removed from the catalog"):
        job_of(store, target(tmp_path)).run(Mock(spec=JobControl))

    store.browser.lease.assert_not_called()
    store.session.read_item.assert_not_called()


def test_a_root_removed_during_the_run_pauses_it_before_the_next_item(store: Store, tmp_path: Path) -> None:
    """Remove Root leaves the root's file and its mapping, so the scan asks the cache before every item (#685).

    **Test steps:**

    * list two new items, and have the root leave the cache once the first is written
    * run the scan
    * verify it pauses naming the root
    * verify the first item was written and counted, and the second neither read nor written
    """
    store.entries = [NEW, NEWER]
    written: list[LibraryEntry] = []

    def write(entry: LibraryEntry, _item: object, _site: object, _terms: object) -> WrittenRecord:
        written.append(entry)
        store.cache.roots.return_value = ()
        return WrittenRecord(tmp_path / entry.site_id / "info.rehu")

    store.writer.write.side_effect = write
    job = job_of(store, target(tmp_path))

    with raises(JobPaused, match="The root Assets was removed from the catalog"):
        job.run(Mock(spec=JobControl))

    assert written == [NEW]
    store.session.read_item.assert_called_once_with(NEW)
    assert job.outcome == JobOutcome("1 added, 0 already there")
