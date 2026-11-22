"""Tests for a library scan's new record, placed by its root's layout and written whole (#682).

Real files under ``tmp_path``: what is under test is that a record lands complete or not at all. The image fetch and
the bucket split are patched, each tested where it lives (`test_image_pipeline.py`, core's `test_prefix_buckets*`).
"""

import datetime
import errno
from pathlib import Path, PurePosixPath
from typing import Final
from uuid import UUID

import pytest
from borco_core import Presence
from pytest import fixture, raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping import library_record_writer as writer_module
from rehuco_agent.scraping.image_pipeline import AcquiredImage
from rehuco_agent.scraping.library_record_writer import STAGING_PREFIX, LibraryRecordWriter, WrittenRecord
from rehuco_agent.scraping.library_site import LibraryEntry, ScannedItem
from rehuco_agent.scraping.results import ScrapedImage, ScrapeResult
from rehuco_core import (
    DEFAULT_RECORD_MOVE_HOST,
    BucketChain,
    JobPaused,
    JobWaiting,
    LicenseTerms,
    RecordLockedError,
    Records,
    RehuDocument,
    RehurootFile,
    RenameYieldTimeout,
    read_license_terms,
    scan_rehu_screenshot_files,
)
from requests import ConnectionError as RequestsConnectionError

ACQUIRED: Final = "2024-05-03T12:34:56.789123Z"
"""When the account got the item below."""

ENTRY: Final = LibraryEntry("1234", ACQUIRED, "Rock pack", "https://www.fab.com/listings/1234")
"""The item every test writes."""

TERMS: Final = LicenseTerms("Standard License", "https://www.fab.com/eula", datetime.date(2026, 11, 22), "The terms.")
"""The license the item is held under."""

IMAGE: Final = ScrapedImage(0, "https://cdn.example/0.png", None)
"""The item's one screenshot."""

ROOT_ID: Final = UUID(int=1)
"""The root every writer below writes into; the host is patched to answer for any id."""

pytestmark = pytest.mark.usefixtures("real_path_stat")


def item(*images: ScrapedImage, license_path: str | None = "license/standard") -> ScannedItem:
    """The item, read in full.

    :param images: its screenshots.
    :param license_path: the license it is held under.
    :returns: the item.
    """
    result = ScrapeResult({"title": "Rock pack"}, "See ![](#image-00).", images)
    return ScannedItem(result, ENTRY.url, license_path)


@fixture(name="root")
def fixture_root(tmp_path: Path, mocker: MockerFixture) -> Path:
    """A root this machine maps, its records laid out as ``{site}/{site_id}``.

    :param tmp_path: where it is.
    :param mocker: pytest-mock fixture.
    :returns: its folder.
    """
    root = tmp_path / "root"
    root.mkdir()
    mocker.patch.object(DEFAULT_RECORD_MOVE_HOST, "root_folder", return_value=root)
    RehurootFile.new(tmp_path / "root.rehuroot", str(root), "Assets", layouts={"asset": ("{site}/{site_id}",)}).save()
    return root


@fixture(name="fetched")
def fixture_fetched(mocker: MockerFixture) -> object:
    """Every screenshot fetched as a PNG's bytes.

    :param mocker: pytest-mock fixture.
    :returns: the patched fetch.
    """
    return mocker.patch.object(writer_module, "acquire", return_value=AcquiredImage(b"png", ".png"))


def writer(root: Path) -> LibraryRecordWriter:
    """A writer for the root's records.

    :param root: the root's folder, beside which its file lies.
    :returns: the writer.
    """
    return LibraryRecordWriter(ROOT_ID, root.parent / "root.rehuroot", username="me", checkpoint=lambda: None)


def test_a_new_record_lands_whole_at_its_layouts_place(root: Path, fetched: object) -> None:
    """The record, its screenshot and its license text land together at the place the layout names.

    **Test steps:**

    * write an item with a screenshot and a license under a root laid out as ``{site}/{site_id}``
    * verify the record is at ``Fab/1234`` with its title, acquisition, store id and image reference
    * verify its screenshot and license text are beside it, and no staging folder is left
    """
    del fetched

    written = writer(root).write(ENTRY, item(IMAGE), "Fab", TERMS)

    folder = root / "Fab" / "1234"
    assert written == WrittenRecord(folder / "info.rehu")
    document = RehuDocument.load(written.path)
    assert (document.title, document.acquired, document.site_id) == ("Rock pack", ACQUIRED, "1234")
    assert document.description == "See ![](info00)."
    assert [path.name for path in scan_rehu_screenshot_files(folder, "info")] == ["info00.png"]
    assert read_license_terms(written.path) == TERMS
    assert not any(path.name.startswith(STAGING_PREFIX) for path in (root / "Fab").iterdir())


def test_an_item_with_no_license_text_gets_no_sidecar(root: Path) -> None:
    """A license the store states no text for leaves the record with its id and no text.

    **Test steps:**

    * write an item with no license text
    * verify the record has no license sidecar
    """
    written = writer(root).write(ENTRY, item(license_path=None), "Fab", None)

    assert read_license_terms(written.path) is None


def test_a_staging_folder_a_crash_left_is_replaced(root: Path) -> None:
    """What a crash left half-written is the scan's own, and the item is written again from nothing.

    **Test steps:**

    * leave a staging folder holding a stray file at the item's place
    * write the item
    * verify the record landed without the stray file
    """
    staging = root / "Fab" / f"{STAGING_PREFIX}1234"
    staging.mkdir(parents=True)
    (staging / "stray.txt").write_text("half", encoding="utf-8")

    written = writer(root).write(ENTRY, item(), "Fab", None)

    assert not (written.path.parent / "stray.txt").exists()
    assert not staging.exists()


def test_a_record_of_the_item_already_at_its_place_is_kept(root: Path) -> None:
    """A record written before a crash, not yet in the cache, is found where it is and never written over.

    **Test steps:**

    * write the item, then mark the record so a rewrite would show
    * write the item again
    * verify the same record is handed back, unchanged
    """
    first = writer(root).write(ENTRY, item(), "Fab", None)
    text = first.path.read_text(encoding="utf-8")

    again = writer(root).write(ENTRY, item(), "Fab", None)

    assert again == WrittenRecord(first.path)
    assert first.path.read_text(encoding="utf-8") == text


def test_a_place_taken_by_something_else_pauses_the_scan(root: Path) -> None:
    """Something other than this item's record at its place is the user's, and the scan stops to say so.

    **Test steps:**

    * put a folder with no record at the item's place
    * write the item
    * verify the scan pauses naming the place
    """
    (root / "Fab" / "1234").mkdir(parents=True)

    with raises(JobPaused, match="is already there") as paused:
        writer(root).write(ENTRY, item(), "Fab", None)

    assert "1234" in str(paused.value.reason)


def test_a_layout_that_refuses_the_record_pauses_the_scan(root: Path) -> None:
    """A layout naming a placeholder the record leaves empty is the user's to fix, so the scan pauses.

    **Test steps:**

    * lay the root out by a placeholder the item has no value for
    * write the item
    * verify the scan pauses, saying the layout does not admit it
    """
    root_file = RehurootFile.load(root.parent / "root.rehuroot")
    root_file.layouts = {"asset": ("{advertised_version}",)}
    root_file.save()

    with raises(JobPaused, match="does not admit"):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_an_unreadable_root_file_pauses_the_scan(root: Path) -> None:
    """A root file that cannot be read names nowhere to put the record.

    **Test steps:**

    * replace the root's file with text that is not one
    * write the item
    * verify the scan pauses, saying the root's file cannot be read
    """
    (root.parent / "root.rehuroot").write_text("not json", encoding="utf-8")

    with raises(JobPaused, match="root's file cannot be read"):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_a_missing_root_file_on_a_root_that_answers_pauses_the_scan(root: Path) -> None:
    """A root file gone from a folder that answers is the user's to put back.

    **Test steps:**

    * delete the root's file
    * write the item
    * verify the scan pauses, saying the root's file cannot be read
    """
    (root.parent / "root.rehuroot").unlink()

    with raises(JobPaused, match="root's file cannot be read"):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_a_root_file_whose_folder_does_not_answer_makes_the_scan_wait(root: Path, mocker: MockerFixture) -> None:
    """The root file's share switched off comes back by itself.

    **Test steps:**

    * delete the root's file, and have its folder read as offline while the root itself answers
    * write the item
    * verify the scan waits
    """
    (root.parent / "root.rehuroot").unlink()
    mocker.patch.object(
        writer_module,
        "presence_of",
        side_effect=lambda folder: Presence.PRESENT if folder == root else Presence.OFFLINE,
    )

    with raises(JobWaiting, match="Waiting for the root"):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_an_unreadable_record_at_the_items_place_pauses_the_scan(root: Path) -> None:
    """A record at the place that cannot be read is not known to be this item's, so it is never written over.

    **Test steps:**

    * put a ``.rehu`` holding no JSON at the item's place
    * write the item
    * verify the scan pauses, saying the place is taken
    """
    folder = root / "Fab" / "1234"
    folder.mkdir(parents=True)
    (folder / "info.rehu").write_text("not json", encoding="utf-8")

    with raises(JobPaused, match="is already there"):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_a_write_failing_as_the_root_goes_quiet_makes_the_scan_wait(root: Path, mocker: MockerFixture) -> None:
    """A share switched off mid-write is a wait, not a failure.

    **Test steps:**

    * have the root answer when first asked and read as offline after, and make the record's save fail
    * write the item
    * verify the scan waits
    """
    answers = iter([Presence.PRESENT])
    mocker.patch.object(writer_module, "presence_of", side_effect=lambda _folder: next(answers, Presence.OFFLINE))
    mocker.patch.object(Records, "save", side_effect=OSError(errno.ENETUNREACH, "unreachable"))

    with raises(JobWaiting, match="Waiting for the root"):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_a_root_this_machine_does_not_map_pauses_the_scan(root: Path, mocker: MockerFixture) -> None:
    """With no folder for the root, only the user can say where it is.

    **Test steps:**

    * have the host map no folder to the root
    * ask for the root's folder
    * verify the scan pauses, saying so
    """
    mocker.patch.object(DEFAULT_RECORD_MOVE_HOST, "root_folder", return_value=None)

    with raises(JobPaused, match="maps no folder"):
        writer(root).root_folder()


def test_a_root_that_does_not_answer_makes_the_scan_wait(root: Path, mocker: MockerFixture) -> None:
    """A share switched off comes back by itself, so the scan waits for it.

    **Test steps:**

    * have the root's folder read as offline
    * write the item
    * verify the scan waits, naming the root
    """
    mocker.patch.object(writer_module, "presence_of", return_value=Presence.OFFLINE)

    with raises(JobWaiting, match="Waiting for the root"):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_a_full_disk_pauses_the_scan_and_leaves_nothing_staged(root: Path, mocker: MockerFixture) -> None:
    """A full disk is the user's to fix; what was staged is removed, to give back the space it took.

    **Test steps:**

    * make the record's save fail as a full disk does
    * write the item
    * verify the scan pauses, saying the disk is full, and no staging folder is left
    """
    mocker.patch.object(Records, "save", side_effect=OSError(errno.ENOSPC, "No space left on device"))

    with raises(JobPaused, match="is full"):
        writer(root).write(ENTRY, item(), "Fab", None)

    assert not (root / "Fab" / f"{STAGING_PREFIX}1234").exists()


def test_another_disk_failure_is_raised(root: Path, mocker: MockerFixture) -> None:
    """A failure on a root that answers is a failure, retryable from the row.

    **Test steps:**

    * make the record's save fail with a permission error
    * write the item
    * verify the error is raised as it is
    """
    mocker.patch.object(Records, "save", side_effect=PermissionError(errno.EACCES, "Access is denied"))

    with raises(PermissionError):
        writer(root).write(ENTRY, item(), "Fab", None)


def test_a_screenshot_that_cannot_be_fetched_is_left_out(
    root: Path, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """One image the CDN refuses does not stop the record; it is logged and the rest lands.

    **Test steps:**

    * make the screenshot fetch fail
    * write an item with one screenshot
    * verify the record landed without it, and the failure was logged
    """
    mocker.patch.object(writer_module, "acquire", side_effect=RequestsConnectionError("refused"))

    written = writer(root).write(ENTRY, item(IMAGE), "Fab", None)

    assert written.path.is_file()
    assert scan_rehu_screenshot_files(written.path.parent, "info") == []
    assert "A screenshot of" in caplog.text


def test_settling_splits_each_bucketed_level_with_the_limit_as_it_is(root: Path, mocker: MockerFixture) -> None:
    """The record went into prefix buckets; each is settled, the innermost first, with today's limit.

    **Test steps:**

    * patch the splitter and the host's limit
    * settle a written record that went into two bucketed levels
    * verify the splitter was built with that limit and settled each level's folder in order
    """
    splitter = mocker.patch.object(writer_module, "BucketSplitter")
    mocker.patch.object(DEFAULT_RECORD_MOVE_HOST, "split_limit", return_value=77)
    inner = BucketChain(PurePosixPath("Fab/a"), ("a",))
    outer = BucketChain(PurePosixPath("Fab"), ())

    writer(root).settle(WrittenRecord(root / "Fab" / "a" / "1234" / "info.rehu", (inner, outer)))

    assert splitter.call_args.args[0] == 77
    settled = [call.args for call in splitter.return_value.settle.call_args_list]
    assert settled == [(root / "Fab" / "a", ("a",)), (root / "Fab", ())]


def test_a_record_with_no_buckets_settles_nothing(root: Path, mocker: MockerFixture) -> None:
    """A layout with no buckets has nothing to split.

    **Test steps:**

    * patch the splitter
    * settle a record that went into no bucketed level
    * verify no splitter was built
    """
    splitter = mocker.patch.object(writer_module, "BucketSplitter")

    writer(root).settle(WrittenRecord(root / "Fab" / "1234" / "info.rehu"))

    splitter.assert_not_called()


@pytest.mark.parametrize(
    "met",
    [RecordLockedError(Path("x.rehu"), None), RenameYieldTimeout("a reader did not let go")],
    ids=["a-locked-record", "a-busy-reader"],
)
def test_what_settling_waits_for_makes_the_scan_wait(root: Path, mocker: MockerFixture, met: Exception) -> None:
    """A record another write holds, or a reader slow to let go, passes by itself, so the scan waits rather than fails.

    **Test steps:**

    * make the split meet a locked record, or a reader that does not let go
    * settle a record that went into a bucketed level
    * verify the scan waits
    """
    splitter = mocker.patch.object(writer_module, "BucketSplitter")
    splitter.return_value.settle.side_effect = met
    chain = BucketChain(PurePosixPath("Fab"), ())

    with raises(JobWaiting):
        writer(root).settle(WrittenRecord(root / "Fab" / "1234" / "info.rehu", (chain,)))


def test_a_pause_mid_write_leaves_no_record_anywhere(root: Path, mocker: MockerFixture) -> None:
    """A pause while the screenshots are fetched leaves nothing a catalog scan could take for a record.

    **Test steps:**

    * have the fetch note whether the staging folder holds a ``.rehu`` yet, and the next checkpoint pause the scan
    * write an item with two screenshots
    * verify no ``.rehu`` was staged while fetching, the scan paused, and neither the place nor a staging folder is left
    """
    staging = root / "Fab" / f"{STAGING_PREFIX}1234"
    staged_records: list[bool] = []
    stops = iter([None, JobPaused()])

    def fetch(_url: str, _referrer: str | None) -> AcquiredImage:
        """Note what is staged, then hand over a PNG's bytes.

        :returns: the bytes.
        """
        staged_records.append((staging / "info.rehu").exists())
        return AcquiredImage(b"png", ".png")

    def checkpoint() -> None:
        """Let the first screenshot through and pause at the second.

        :raises JobPaused: at the second.
        """
        stop = next(stops)
        if stop is not None:
            raise stop

    mocker.patch.object(writer_module, "acquire", side_effect=fetch)
    images = (IMAGE, ScrapedImage(1, "https://cdn.example/1.png", None))

    with raises(JobPaused):
        LibraryRecordWriter(ROOT_ID, root.parent / "root.rehuroot", username="me", checkpoint=checkpoint).write(
            ENTRY, item(*images), "Fab", TERMS
        )

    assert staged_records == [False]
    assert not staging.exists()
    assert not (root / "Fab" / "1234").exists()


def test_a_bucketed_layout_places_the_record_and_names_its_level_to_settle(root: Path) -> None:
    """Under ``{site}/{buckets}/{site_id}`` a record lands in its layout folder, whose buckets are then the scan's to
    settle.

    **Test steps:**

    * lay the root out with a bucketed level
    * write the item
    * verify it landed under the site's folder, and the written record names that folder's chain to settle
    """
    root_file = RehurootFile.load(root.parent / "root.rehuroot")
    root_file.layouts = {"asset": ("{site}/{buckets}/{site_id}",)}
    root_file.save()

    written = writer(root).write(ENTRY, item(), "Fab", None)

    assert written.path == root / "Fab" / "1234" / "info.rehu"
    assert written.chains == (BucketChain(PurePosixPath("Fab"), ()),)


def test_a_screenshot_whose_slot_the_set_cannot_hold_is_left_out(
    root: Path, fetched: object, caplog: pytest.LogCaptureFixture
) -> None:
    """A slot past the numbered set's end costs that image, never the record.

    **Test steps:**

    * write an item whose one screenshot names slot 100
    * verify the record landed without it, and the image was logged as left out
    """
    del fetched

    written = writer(root).write(ENTRY, item(ScrapedImage(100, "https://cdn.example/x.png", None)), "Fab", None)

    assert written.path.is_file()
    assert not scan_rehu_screenshot_files(written.path.parent, "info")
    assert "A screenshot of" in caplog.text
