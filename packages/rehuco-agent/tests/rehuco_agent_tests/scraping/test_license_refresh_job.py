"""Tests for *Refresh License* as jobs (#688, #705, [[assets#licenses]]): what a refresh does with a license of a record
that has no saved text, the same one, another one or terms of its own, how it counts and survives what it cannot read,
and the second job that replaces only what was confirmed -- each license's text on its own, the others' left as they
are.

Real records under ``tmp_path``, read and written through core; the store's reader is a stand-in answering by address.
"""

import datetime
from collections.abc import Callable
from pathlib import Path
from typing import Final
from unittest.mock import Mock

from borco_core import Presence
from pytest import fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping.library_site import StoreOfflineError
from rehuco_agent.scraping.license_refresh_job import (
    LicenseDifference,
    LicenseRefreshResult,
    RefreshLicenseJob,
    ReplaceLicenseJob,
    SavedLicense,
    same_text,
)
from rehuco_agent.scraping.protocols import FetchError
from rehuco_core import (
    JobCanceled,
    JobControl,
    LicenseTerms,
    LicenseTermsSet,
    RecordLockedError,
    RehuDocument,
    license_terms_path,
    read_license_terms,
    write_license_terms,
)

pytestmark = mark.usefixtures("real_path_stat")

URL: Final = "https://example.com/eula"
OTHER_URL: Final = "https://example.com/other"
OLD_DAY: Final = datetime.date(2026, 3, 1)
NEW_DAY: Final = datetime.date(2026, 11, 25)
STORE: Final = LicenseTerms("Standard License", URL, NEW_DAY, "# Terms\n\nUse freely.")
OLD: Final = LicenseTerms("Standard License", URL, OLD_DAY, "# Terms\n\nOlder wording.")
LICENSE_ID: Final = "fab-standard"
"""The license every record below is held under, unless a test gives it another beside."""
USER: Final = "admin"
JOB_MODULE: Final = "rehuco_agent.scraping.license_refresh_job"


def asset(
    tmp_path: Path, name: str, url: str | None = URL, terms: LicenseTerms | None = None, kind: str = "asset"
) -> Path:
    """A record, with the license address it states and a sidecar when given terms.

    :param tmp_path: the folder.
    :param name: the record's folder name.
    :param url: the address its one license states; no license at all for ``None``.
    :param terms: what the sidecar holds for that license; none made for ``None``.
    :param kind: the record's type.
    :returns: the ``.rehu``.
    """
    path = tmp_path / name / "info.rehu"
    path.parent.mkdir()
    document = RehuDocument.new(path)
    document.core["type"] = kind
    document.title = name
    if url is not None:
        document.set_active_field("licenses", [{"license": LICENSE_ID, "url": url}])
    document.save()
    if terms is not None:
        keep_text(path, terms)
    return path


def saved_text(record: Path, license_id: str = LICENSE_ID) -> LicenseTerms | None:
    """What a record's sidecar holds for one license.

    :param record: the ``.rehu``.
    :param license_id: the license.
    :returns: its text; ``None`` for no sidecar, or none for that license.
    """
    texts = read_license_terms(record)
    return None if texts is None else texts.get(license_id)


def keep_text(record: Path, terms: LicenseTerms, license_id: str = LICENSE_ID) -> None:
    """Write one license's text into a record's sidecar, keeping the others it holds.

    :param record: the ``.rehu``.
    :param terms: the text.
    :param license_id: the license.
    """
    write_license_terms(record, (read_license_terms(record) or LicenseTermsSet()).with_terms(license_id, terms))


def reader(texts: dict[str, LicenseTerms | Exception | None] | None = None) -> Mock:
    """What stands for the store: answers each address with its terms, its failure, or none.

    :param texts: the answer for each address; the Standard text for :data:`URL` and nothing for others by default.
    :returns: the reader, a mock, so its calls can be read.
    """
    answers = {URL: STORE} if texts is None else texts

    def read(url: str) -> LicenseTerms | None:
        answer = answers.get(url)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return Mock(side_effect=read)


def refresh(records: list[Path], read_text: Callable[[str], LicenseTerms | None] | None = None) -> RefreshLicenseJob:
    """Run a refresh to its end.

    :param records: the selected records.
    :param read_text: the store's reader; the default answers :data:`STORE` for :data:`URL`.
    :returns: the job, after its run.
    """
    job = RefreshLicenseJob(records, read_text if read_text is not None else reader(), username=USER)
    job.run(Mock(spec=JobControl))
    return job


def count(job: RefreshLicenseJob, result: LicenseRefreshResult) -> int:
    """How many records a result happened to.

    :param job: the job.
    :param result: the result.
    :returns: the count.
    """
    return job.results[result]


@fixture(name="control")
def fixture_control() -> Mock:
    """What a running job is handed.

    :returns: a stand-in for the engine's face, whose reports can be read.
    """
    return Mock(spec=JobControl)


# region what a refresh does with each record


def test_a_record_with_no_saved_text_gets_the_stores(tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a record that states a license address and has no sidecar
    * verify the sidecar now holds the store's text, the run counted it written, and no difference is offered
    """
    record = asset(tmp_path, "a")

    job = refresh([record])

    assert saved_text(record) == STORE
    assert count(job, LicenseRefreshResult.WRITTEN) == 1
    assert not job.differences


def test_a_record_holding_the_same_text_is_left_alone_whatever_its_date_and_title(tmp_path: Path) -> None:
    """The terms are the text: another day or title, or blanks around it, are not another license.

    **Test steps:**

    * refresh a record whose saved text is the store's but for its title, its day and a trailing newline
    * verify the file is byte for byte as it was, and counted unchanged
    """
    saved = LicenseTerms("Old title", URL, OLD_DAY, STORE.text + "\n")
    record = asset(tmp_path, "a", terms=saved)
    before = license_terms_path(record).read_bytes()

    job = refresh([record])

    assert license_terms_path(record).read_bytes() == before
    assert count(job, LicenseRefreshResult.UNCHANGED) == 1
    assert not job.differences


def test_a_record_holding_another_text_is_kept_and_offered_for_the_user_to_decide(tmp_path: Path) -> None:
    """The text an item was got under may be the one that still applies to it, so it is not the tool's to overwrite.

    **Test steps:**

    * refresh two records holding an older wording of one license, and a third with none, the store read once
    * verify no saved text changed, the third got the store's, and one difference names the license, the store's
      text and both holders with the text each holds
    """
    first = asset(tmp_path, "a", terms=OLD)
    second = asset(tmp_path, "b", terms=OLD)
    third = asset(tmp_path, "c")
    read_text = reader()

    job = refresh([first, second, third], read_text)

    assert saved_text(first) == OLD
    assert saved_text(second) == OLD
    assert saved_text(third) == STORE
    read_text.assert_called_once_with(URL)
    assert job.differences == (
        LicenseDifference(URL, STORE, (SavedLicense(first, LICENSE_ID, OLD), SavedLicense(second, LICENSE_ID, OLD))),
    )
    assert count(job, LicenseRefreshResult.DIFFERENT) == 2


def test_terms_with_no_address_are_the_items_own_and_never_touched(tmp_path: Path) -> None:
    """Typed in for one item, they are nothing a store's text is compared with, whatever the record's address says.

    **Test steps:**

    * refresh a record whose saved terms have no ``url``
    * verify the store was not asked, the file is as it was, and it is counted as terms of its own
    """
    own = LicenseTerms("Mine", None, OLD_DAY, "Only for this item.")
    record = asset(tmp_path, "a", terms=own)
    read_text = reader()

    job = refresh([record], read_text)

    read_text.assert_not_called()
    assert saved_text(record) == own
    assert count(job, LicenseRefreshResult.OWN) == 1


def test_a_record_that_states_no_license_address_has_no_text_to_refresh(tmp_path: Path) -> None:
    """**Test steps:**

    * refresh an asset holding no license
    * verify nothing was read or written, and it is counted as having no text to read
    """
    record = asset(tmp_path, "a", url=None)
    read_text = reader()

    job = refresh([record], read_text)

    read_text.assert_not_called()
    assert not license_terms_path(record).exists()
    assert count(job, LicenseRefreshResult.NO_TEXT) == 1


def test_an_address_no_reader_knows_leaves_every_record_stating_it_as_it_is(tmp_path: Path) -> None:
    """**Test steps:**

    * refresh two records stating an address the reader answers nothing for
    * verify no sidecar was made and both are counted as having no text to read, the address asked for once
    """
    records = [asset(tmp_path, "a", url=OTHER_URL), asset(tmp_path, "b", url=OTHER_URL)]
    read_text = reader()

    job = refresh(records, read_text)

    read_text.assert_called_once_with(OTHER_URL)
    assert not any(license_terms_path(record).exists() for record in records)
    assert count(job, LicenseRefreshResult.NO_TEXT) == 2


def test_a_record_that_is_not_an_asset_is_left_out(tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a tutorial
    * verify it is counted as no asset, and nothing was read or written
    """
    record = asset(tmp_path, "a", kind="tutorial")
    read_text = reader()

    job = refresh([record], read_text)

    read_text.assert_not_called()
    assert count(job, LicenseRefreshResult.NOT_ASSET) == 1


def test_a_record_selected_twice_is_refreshed_once(tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a record named twice
    * verify it is counted once
    """
    record = asset(tmp_path, "a")

    job = refresh([record, record])

    assert count(job, LicenseRefreshResult.WRITTEN) == 1


# endregion

# region what it survives


def test_a_store_that_does_not_answer_costs_the_records_of_that_license_and_no_other(tmp_path: Path) -> None:
    """One license's store being down neither holds back the others nor loses what the run already did.

    **Test steps:**

    * refresh a record of a license whose store does not answer, and one of a license that reads
    * verify the first is counted as unanswered and left without a text, and the second was written
    """
    down, fine = asset(tmp_path, "a", url=OTHER_URL), asset(tmp_path, "b")

    job = refresh([down, fine], reader({OTHER_URL: StoreOfflineError("no network"), URL: STORE}))

    assert count(job, LicenseRefreshResult.UNANSWERED) == 1
    assert not license_terms_path(down).exists()
    assert saved_text(fine) == STORE


def test_a_text_that_cannot_be_read_costs_its_records_and_nothing_else(tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a record whose license's text is no text, and another of a license that reads
    * verify the first is counted as unanswered and the second was written
    """
    broken = asset(tmp_path, "a", url=OTHER_URL)
    fine = asset(tmp_path, "b")

    job = refresh([broken, fine], reader({OTHER_URL: FetchError("not JSON"), URL: STORE}))

    assert count(job, LicenseRefreshResult.UNANSWERED) == 1
    assert saved_text(fine) == STORE
    assert not license_terms_path(broken).exists()


def test_a_sidecar_or_a_record_that_cannot_be_read_is_counted_and_the_rest_go_on(tmp_path: Path) -> None:
    """**Test steps:**

    * refresh a record whose sidecar has no header, one that is no record, and a good one
    * verify two are counted unreadable and the good one was written
    """
    bad_sidecar = asset(tmp_path, "a")
    license_terms_path(bad_sidecar).write_text("no header", encoding="utf-8")
    bad_record = asset(tmp_path, "b")
    bad_record.write_text("{not json", encoding="utf-8")
    good = asset(tmp_path, "c")

    job = refresh([bad_sidecar, bad_record, good])

    assert count(job, LicenseRefreshResult.UNREADABLE) == 2
    assert saved_text(good) == STORE
    assert license_terms_path(bad_sidecar).read_text(encoding="utf-8") == "no header"


def test_a_record_on_a_share_that_does_not_answer_is_counted_offline(tmp_path: Path, mocker: MockerFixture) -> None:
    """**Test steps:**

    * make reading a record fail as a share that went away does
    * refresh it
    * verify it is counted offline, not unreadable
    """
    record = asset(tmp_path, "a")
    mocker.patch(f"{JOB_MODULE}.RehuDocument.load", side_effect=OSError("the network name is no longer available"))
    mocker.patch(f"{JOB_MODULE}.presence_of", return_value=Presence.OFFLINE)

    job = refresh([record])

    assert count(job, LicenseRefreshResult.OFFLINE) == 1
    assert count(job, LicenseRefreshResult.UNREADABLE) == 0


def test_a_record_locked_by_someone_else_is_counted_and_left_without_a_text(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * make the record's lock one someone else holds
    * refresh it and a record that is free
    * verify the locked one is counted and left, and the other was written
    """
    locked = asset(tmp_path, "a")
    free = asset(tmp_path, "b")
    taken = mocker.patch(f"{JOB_MODULE}.locked_record")
    taken.side_effect = [RecordLockedError(locked, None), mocker.MagicMock()]

    job = refresh([locked, free])

    assert count(job, LicenseRefreshResult.LOCKED) == 1
    assert not license_terms_path(locked).exists()
    assert saved_text(free) == STORE


def test_a_sidecar_written_between_the_read_and_the_write_is_not_written_over(tmp_path: Path) -> None:
    """Someone else's text, put there while the store was being read, is not a record with none.

    **Test steps:**

    * have the store's reader write a sidecar for the record while it answers
    * verify the sidecar is the other writer's, and the record is counted as changed meanwhile
    """
    record = asset(tmp_path, "a")
    other = LicenseTerms("Other", URL, OLD_DAY, "Written meanwhile.")

    def read(url: str) -> LicenseTerms:
        del url
        keep_text(record, other)
        return STORE

    job = refresh([record], read)

    assert saved_text(record) == other
    assert count(job, LicenseRefreshResult.CHANGED) == 1


def test_a_record_gone_while_the_store_was_read_gets_no_stray_file(tmp_path: Path) -> None:
    """**Test steps:**

    * have the store's reader delete the record while it answers
    * verify no sidecar was made beside the vanished record, and it is counted as gone
    """
    record = asset(tmp_path, "a")

    def read(url: str) -> LicenseTerms:
        del url
        record.unlink()
        return STORE

    job = refresh([record], read)

    assert not license_terms_path(record).exists()
    assert count(job, LicenseRefreshResult.GONE) == 1


def test_a_cancel_stops_the_run_before_the_next_record(tmp_path: Path) -> None:
    """**Test steps:**

    * ask a job to cancel and run it
    * verify it unwinds and wrote nothing
    """
    record = asset(tmp_path, "a")
    job = RefreshLicenseJob([record], reader(), username=USER)
    job.cancel()

    with raises(JobCanceled):
        job.run(Mock(spec=JobControl))

    assert not license_terms_path(record).exists()


def test_a_write_that_fails_or_meets_a_sidecar_broken_meanwhile_is_counted_and_the_rest_go_on(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """**Test steps:**

    * make the first write fail as a disk does, and the sidecar of the second break after it was read
    * verify both are counted unreadable, and a third record was written
    """
    failing, broken, fine = asset(tmp_path, "a"), asset(tmp_path, "b"), asset(tmp_path, "c")
    real_write = write_license_terms

    def write(record: Path, terms: LicenseTermsSet) -> None:
        if record == failing:
            raise PermissionError("denied")
        real_write(record, terms)

    mocker.patch(f"{JOB_MODULE}.write_license_terms", side_effect=write)

    def read(url: str) -> LicenseTerms:
        del url
        license_terms_path(broken).write_text("no header", encoding="utf-8")
        return STORE

    job = refresh([failing, broken, fine], read)

    assert count(job, LicenseRefreshResult.UNREADABLE) == 2
    assert saved_text(fine) == STORE


# endregion

# region what it says


def test_a_run_says_what_it_did_in_one_line_and_whether_anything_needs_a_look(tmp_path: Path) -> None:
    """**Test steps:**

    * verify a job that has not run says nothing
    * refresh one record to write and one that differs
    * verify the line counts both in order and is not clean
    * refresh only a record that is already current and verify the line is clean
    """
    job = RefreshLicenseJob([], reader(), username=USER)
    assert job.outcome is None
    written, differing = asset(tmp_path, "a"), asset(tmp_path, "b", terms=OLD)

    mixed = refresh([written, differing])
    current = refresh([written])

    assert mixed.outcome is not None
    assert (mixed.outcome.summary, mixed.outcome.clean) == ("1 written, 1 differ", False)
    assert current.outcome is not None
    assert (current.outcome.summary, current.outcome.clean) == ("1 unchanged", True)


def test_progress_is_reported_in_records_to_the_total(tmp_path: Path, control: Mock) -> None:
    """**Test steps:**

    * run a refresh of a record that is no asset and one that is written
    * verify the engine was told each record done, to the total of two
    """
    records = [asset(tmp_path, "a", kind="tutorial"), asset(tmp_path, "b")]
    job = RefreshLicenseJob(records, reader(), username=USER)

    job.run(control)

    assert [call.args for call in control.report.call_args_list] == [(1, 2), (2, 2)]


@mark.parametrize(("records", "label"), [(1, "Refresh License - 1 record"), (2, "Refresh License - 2 records")])
def test_the_label_counts_the_records(tmp_path: Path, records: int, label: str) -> None:
    """**Test steps:**

    * build a job over one record and over two
    * verify the label says how many
    """
    paths = [tmp_path / f"{index}.rehu" for index in range(records)]

    assert RefreshLicenseJob(paths, reader(), username=USER).label == label


def test_a_reset_forgets_what_the_last_run_found(tmp_path: Path) -> None:
    """**Test steps:**

    * run a job that finds a difference, then reset it
    * verify nothing is left of its findings or its counts
    """
    job = refresh([asset(tmp_path, "a", terms=OLD)])
    assert job.differences

    job.reset()

    assert not job.differences
    assert job.outcome is None


def test_the_same_text_is_the_terms_without_the_blanks_around_them() -> None:
    """**Test steps:**

    * compare texts that differ in blanks around them, in their title and in their day, then in a word
    * verify the first are the same and the last is not
    """
    assert same_text(OLD, LicenseTerms("T", None, NEW_DAY, f"\n{OLD.text}\n\n"))
    assert not same_text(OLD, STORE)


# endregion

# region replacing what was confirmed


def test_a_confirmed_text_replaces_the_one_a_record_holds(tmp_path: Path) -> None:
    """**Test steps:**

    * replace the text of two records that still hold the one that was compared
    * verify both hold the store's, and the run says it replaced two
    """
    first, second = asset(tmp_path, "a", terms=OLD), asset(tmp_path, "b", terms=OLD)
    difference = LicenseDifference(
        URL, STORE, (SavedLicense(first, LICENSE_ID, OLD), SavedLicense(second, LICENSE_ID, OLD))
    )
    job = ReplaceLicenseJob([difference], username=USER)

    job.run(Mock(spec=JobControl))

    assert saved_text(first) == saved_text(second) == STORE
    assert job.outcome is not None and job.outcome.summary == "2 replaced"
    assert job.label == "Replace License text - 2 records"


def test_a_text_changed_since_it_was_compared_is_not_replaced(tmp_path: Path) -> None:
    """The user decided about the text they were shown, not about whatever is there now.

    **Test steps:**

    * edit one record's saved text after the comparison, and replace both
    * verify the edited one is as the edit left it and counted as changed meanwhile, and the other was replaced
    """
    edited, untouched = asset(tmp_path, "a", terms=OLD), asset(tmp_path, "b", terms=OLD)
    typed = LicenseTerms("Typed", URL, OLD_DAY, "Typed since.")
    keep_text(edited, typed)
    difference = LicenseDifference(
        URL, STORE, (SavedLicense(edited, LICENSE_ID, OLD), SavedLicense(untouched, LICENSE_ID, OLD))
    )
    job = ReplaceLicenseJob([difference], username=USER)

    job.run(Mock(spec=JobControl))

    assert saved_text(edited) == typed
    assert saved_text(untouched) == STORE
    assert job.results[LicenseRefreshResult.CHANGED] == 1
    assert job.results[LicenseRefreshResult.REPLACED] == 1
    assert job.outcome is not None and not job.outcome.clean


def test_a_second_run_of_a_replacement_counts_afresh(tmp_path: Path) -> None:
    """**Test steps:**

    * run a replacement, reset it and run it again
    * verify the second run counts its own, the first run's records now holding the store's text
    """
    record = asset(tmp_path, "a", terms=OLD)
    job = ReplaceLicenseJob([LicenseDifference(URL, STORE, (SavedLicense(record, LICENSE_ID, OLD),))], username=USER)
    job.run(Mock(spec=JobControl))

    job.reset()
    assert job.outcome is None
    job.run(Mock(spec=JobControl))

    assert job.results[LicenseRefreshResult.CHANGED] == 1
    assert job.results[LicenseRefreshResult.REPLACED] == 0


# endregion


# region several licenses


def test_each_license_of_a_record_is_settled_on_its_own(tmp_path: Path) -> None:
    """A record of three licenses: one holding the store's text, one with none and one stating no address (#705).

    **Test steps:**

    * save a record holding the Standard License with its text, a second license with none, and a third with no url
    * refresh it
    * verify the second got the store's text under its own id, the first was left as it was, and the third counted
      as having no text to read
    """
    second_text = LicenseTerms("Other License", OTHER_URL, NEW_DAY, "Other terms.")
    record = asset(tmp_path, "a", terms=STORE)
    document = RehuDocument.load(record)
    document.set_active_field(
        "licenses",
        [{"license": LICENSE_ID, "url": URL}, {"license": "other", "url": OTHER_URL}, {"license": "fab-ue-only"}],
    )
    document.save()

    job = refresh([record], reader({URL: STORE, OTHER_URL: second_text}))

    assert saved_text(record) == STORE
    assert saved_text(record, "other") == second_text
    assert saved_text(record, "fab-ue-only") is None
    assert (count(job, LicenseRefreshResult.UNCHANGED), count(job, LicenseRefreshResult.WRITTEN)) == (1, 1)
    assert count(job, LicenseRefreshResult.NO_TEXT) == 1


def test_a_replacement_changes_its_license_s_text_alone(tmp_path: Path) -> None:
    """Replacing one license's text keeps every other text the record holds (#705).

    **Test steps:**

    * save a record holding an older Standard text and a text of another license
    * replace the Standard text as confirmed
    * verify it is the store's now, and the other license's text is as it was
    """
    other = LicenseTerms("Other License", OTHER_URL, OLD_DAY, "Other terms.")
    record = asset(tmp_path, "a", terms=OLD)
    keep_text(record, other, "other")

    ReplaceLicenseJob([LicenseDifference(URL, STORE, (SavedLicense(record, LICENSE_ID, OLD),))], username=USER).run(
        Mock(spec=JobControl)
    )

    assert saved_text(record) == STORE
    assert saved_text(record, "other") == other


# endregion
