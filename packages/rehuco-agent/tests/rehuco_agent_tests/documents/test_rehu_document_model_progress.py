"""Tests for a document model recording watch progress and measured lengths (#316, [[field-schema#watch-progress]]).

Real files under ``tmp_path``, read and written through real records; the writer's thread is stood in for by
``inline_progress_writes`` (the default here) or held until the test runs each write (``held_writes``).
"""

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import shiboken6
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import (
    ProgressEntry,
    RehuDocument,
    VideoFacts,
    current_block_version,
    user_sidecar_path,
)
from rehuco_core.access import Records, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.progress_writes import HeldWrites
from rehuco_agent_tests.record_reads import read_now

pytestmark = mark.usefixtures("real_path_stat")

type OpenModel = Callable[[Path], RehuDocumentModel]
"""What builds the model an open builds over a record's path."""

UPDATED: Final = "2026-01-01T00:00:00Z"
"""The ``updated`` the records here are written with, which a progress write must leave."""


def write_tutorial(
    folder: Path,
    files: tuple[str, ...] = ("a.mp4", "b.mp4"),
    *,
    title: str = "Old",
    resource_type: str = "tutorial",
    block: dict[str, Any] | None = None,
) -> Path:
    """Write a tutorial record with empty video files beside it.

    :param folder: the resource's folder, created.
    :param files: the video files to create.
    :param title: the record's title.
    :param resource_type: the record's type.
    :param block: extra entries for the type's block.
    :returns: the record's path.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name in files:
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"")
    data: dict[str, Any] = {
        "format_version": 2,
        "core": {
            "type": resource_type,
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "updated": UPDATED,
            "sources": [{"title": title, "primary": True}],
        },
        resource_type: {"format_version": current_block_version(resource_type), **(block or {})},
    }
    path = folder / "info.rehu"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def stored(path: Path) -> dict[str, Any]:
    """The record as stored.

    :param path: the record.
    :returns: its JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def stored_progress(path: Path, username: str) -> dict[str, Any]:
    """One user's progress entries as stored in their sidecar.

    :param path: the record.
    :param username: whose.
    :returns: the entries by key; empty when the sidecar holds none.
    """
    sidecar = user_sidecar_path(path, username)
    if not sidecar.exists():
        return {}
    return json.loads(sidecar.read_text(encoding="utf-8")).get("tutorial", {}).get("progress", {})


@fixture(name="records")
def fixture_records() -> Records:
    """The records the models here read and write through.

    :returns: real records over the filesystem.
    """
    return Records()


@fixture(name="open_model")
def fixture_open_model(qtbot: QtBot, records: Records, delete_at_teardown: DeleteAtTeardown) -> OpenModel:
    """Build the model an open builds over a record on disk.

    :param qtbot: pytest-qt fixture.
    :param records: the records.
    :param delete_at_teardown: deletes the bare models when the test ends.
    :returns: the builder, given the record's path.
    """
    del qtbot

    def open_model(path: Path) -> RehuDocumentModel:
        record = read_now(records, ResourceKey(path))
        return delete_at_teardown(
            RehuDocumentModel(record.document, records=records, version=record.version, signature=record.signature)
        )

    return open_model


# region recording


def test_a_recorded_position_is_shown_written_to_the_sidecar_and_leaves_the_document_clean(
    tmp_path: Path, open_model: OpenModel, qtbot: QtBot
) -> None:
    """Progress is the user's own state beside the record: shown and written at once, never an edit.

    **Test steps:**

    * open a tutorial and record a position on one video
    * verify the change was announced, the entry reads back, the user's sidecar holds it, and the record's own file,
      ``updated`` and dirty flag are untouched
    """
    path = write_tutorial(tmp_path / "t")
    record_before = stored(path)
    model = open_model(path)
    username = model.document.username

    with qtbot.waitSignal(model.progress_changed):
        model.record_progress("a.mp4", 12.5, 100.0)

    assert model.progress_of("a.mp4") == ProgressEntry(12.5, 100.0, False, 0)
    assert stored_progress(path, username)["a.mp4"]["position"] == 12.5
    assert stored(path) == record_before
    assert (model.dirty, model.progress_unsaved) == (False, "")


def test_an_unsaved_edit_survives_a_progress_write_and_still_saves(tmp_path: Path, open_model: OpenModel) -> None:
    """Writing progress neither reads the edit away nor loses the progress when the edit is saved.

    **Test steps:**

    * open a tutorial and edit its title without saving
    * record a position on a video
    * verify the title is still the edit, the document is still dirty, the file still holds the old title, and the
      progress shows
    * save, and verify the file holds the edit and the progress is still there
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    username = model.document.username
    model.title = "Mine"

    model.record_progress("a.mp4", 5.0, 100.0)

    assert (model.title, model.dirty) == ("Mine", True)
    assert stored(path)["core"]["sources"][0]["title"] == "Old"
    assert model.progress_of("a.mp4") is not None
    model.save()
    assert stored(path)["core"]["sources"][0]["title"] == "Mine"
    assert stored_progress(path, username)["a.mp4"]["position"] == 5.0
    assert model.progress_of("a.mp4") is not None


def test_the_last_video_reaching_its_end_marks_the_tutorial_viewed_without_dirtying_it(
    tmp_path: Path, open_model
) -> None:
    """The rule's change to the tutorial's own flag shows, and is still not an edit.

    **Test steps:**

    * open a one-video tutorial, and record a position at that video's end
    * verify the video and the tutorial read as viewed, and the document is clean
    """
    path = write_tutorial(tmp_path / "t", ("a.mp4",))
    model = open_model(path)

    model.record_progress("a.mp4", 100.0, 100.0)

    entry = model.progress_of("a.mp4")
    assert entry is not None and entry.viewed
    assert (model.viewed, model.dirty) == (True, False)


def test_a_viewed_checkbox_set_by_hand_is_recorded_as_given(tmp_path: Path, open_model: OpenModel) -> None:
    """A video cleared by hand stays cleared whatever its position.

    **Test steps:**

    * record a video to its end, then clear its flag
    * verify the entry is not viewed and keeps its position
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    model.record_progress("a.mp4", 100.0, 100.0)

    model.record_progress("a.mp4", 100.0, 100.0, viewed=False)

    assert model.progress_of("a.mp4") == ProgressEntry(100.0, 100.0, False, 0)


def test_forgetting_removes_an_entry(tmp_path: Path, open_model: OpenModel) -> None:
    """A forgotten entry is gone from the model and from the user's sidecar.

    **Test steps:**

    * record progress on two videos and forget one
    * verify only the other remains, in the model and on disk
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    username = model.document.username
    model.record_progress("a.mp4", 1.0, 10.0)
    model.record_progress("b.mp4", 2.0, 10.0)

    model.forget_progress("a.mp4")

    assert list(model.progress_entries()) == ["b.mp4"]
    assert list(stored_progress(path, username)) == ["b.mp4"]


# endregion


# region measured lengths


def test_a_measure_is_written_to_the_record_without_dirtying_the_document(
    tmp_path: Path, open_model: OpenModel
) -> None:
    """The lengths land in the record on their own, show in the model, and are no unknown field.

    **Test steps:**

    * open a tutorial with an unsaved edit, and write a Measure's result
    * verify the model reads the lengths, the file holds them with ``updated`` unchanged, the edit is untouched and
      the document is not newly dirty, and ``videos`` is not an unrecognized field
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    model.title = "Mine"

    model.record_videos({"a.mp4": VideoFacts(100.0, 1920, 1080)})

    assert model.measured_videos() == {"a.mp4": VideoFacts(100.0, 1920, 1080)}
    assert stored(path)["tutorial"]["videos"] == {"a.mp4": {"duration": 100.0, "width": 1920, "height": 1080}}
    assert stored(path)["core"]["updated"] == UPDATED
    assert (model.title, model.dirty) == ("Mine", True)
    assert "videos" not in model.unknown_field_names()
    model.save()
    assert stored(path)["tutorial"]["videos"]["a.mp4"]["duration"] == 100.0


# endregion


# region what cannot be written


def test_a_document_with_no_file_keeps_progress_for_the_session_and_says_so(
    qtbot: QtBot, held_writes: HeldWrites, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Nothing is handed to the writer, the entry is shown anyway, and the banner's reason names why.

    **Test steps:**

    * build a new document with no path and record a position
    * verify nothing was written, the entry reads back, and ``progress_unsaved`` says it is not a file here
    """
    del qtbot
    model = delete_at_teardown(RehuDocumentModel.create_new())

    model.record_progress("a.mp4", 3.0, 10.0)

    assert held_writes.keys == []
    assert model.progress_of("a.mp4") is not None
    assert "not a file on this machine" in model.progress_unsaved


def test_a_document_whose_own_sidecar_cannot_be_read_writes_nothing(
    tmp_path: Path, open_model: OpenModel, held_writes: HeldWrites
) -> None:
    """The user's own state is what locks, and the sidecar is never written over.

    **Test steps:**

    * write a tutorial whose user's sidecar is not JSON, and open it
    * record a position
    * verify nothing was written, the sidecar is as it was, and the reason names the user's own file
    """
    path = write_tutorial(tmp_path / "t")
    bad = user_sidecar_path(path, open_model(path).document.username)
    bad.write_text("{", encoding="utf-8")
    model = open_model(path)

    model.record_progress("a.mp4", 3.0, 10.0)

    assert held_writes.keys == []
    assert bad.read_text(encoding="utf-8") == "{"
    assert "your own per-user file" in model.progress_unsaved
    assert model.progress_of("a.mp4") is not None


def test_a_failed_write_keeps_the_entry_says_why_and_is_cleared_by_the_next_that_lands(
    tmp_path: Path, open_model: OpenModel, records: Records, mocker: MockerFixture
) -> None:
    """The share going away loses nothing: the position stays, and the next write retries with it.

    **Test steps:**

    * record a position while the records' write raises ``OSError``
    * verify the entry still reads back and ``progress_unsaved`` carries the system's reason
    * record again once writing works, and verify the sidecar holds the entry and the reason is gone
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    username = model.document.username
    real = records.record_progress
    mocker.patch.object(records, "record_progress", side_effect=OSError(53, "The network path was not found"))

    model.record_progress("a.mp4", 7.0, 10.0)

    assert model.progress_of("a.mp4") is not None
    assert model.progress_unsaved == "Watch progress could not be saved: The network path was not found."

    mocker.patch.object(records, "record_progress", real)
    model.record_progress("a.mp4", 8.0, 10.0)

    assert stored_progress(path, username)["a.mp4"]["position"] == 8.0
    assert model.progress_unsaved == ""


def test_a_failed_renamed_file_move_is_not_reported(
    tmp_path: Path, open_model: OpenModel, records: Records, mocker: MockerFixture
) -> None:
    """Moving progress onto renamed files is automatic: when it cannot, the user has nothing to act on.

    **Test steps:**

    * make the records' move raise
    * ask for the move
    * verify ``progress_unsaved`` stays empty
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    mocker.patch.object(records, "reattach_renamed_progress", side_effect=OSError("a folder would not list"))

    model.reattach_renamed_progress()

    assert model.progress_unsaved == ""


# endregion


# region the file the write changed


def test_the_files_own_change_by_a_write_is_not_taken_for_one_made_outside(
    tmp_path: Path, open_model: OpenModel, held_writes: HeldWrites, records: Records, qtbot: QtBot
) -> None:
    """The file notifier hears the write while it is out; it is judged once the write is taken in, and a clean model
    does not reload over its own progress.

    **Test steps:**

    * open a tutorial and record a position, the write held
    * run the write, report the file's new signature while the write is still out, then let the write's answer land
    * verify the document never reloaded and shows the entry
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    model.record_progress("a.mp4", 4.0, 10.0)
    work, answer = held_writes.waiting[("progress", "a.mp4")]
    outcome = work()

    with qtbot.assertNotEmitted(model.reloaded):
        model.note_file_signature(*records.signature(ResourceKey(path)) or (0, 0))
        del held_writes.waiting[("progress", "a.mp4")]
        answer(outcome)

    assert model.progress_of("a.mp4") is not None
    assert model.progress_unsaved == ""


def test_a_resource_edited_on_disk_meanwhile_is_left_to_the_changed_on_disk_rule(tmp_path: Path, open_model) -> None:
    """A write that finds the record's details moved on is not taken in over them: a clean model reloads, and shows
    both the new details and the progress.

    **Test steps:**

    * open a tutorial, then change its title in the file as another program would
    * record a position
    * verify the model shows the new title and the progress, and is clean
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    other = RehuDocument.load(path)
    other.title = "Theirs, and longer"
    other.save()

    model.record_progress("a.mp4", 4.0, 10.0)

    assert (model.title, model.dirty, model.changed_on_disk) == ("Theirs, and longer", False, False)
    assert model.progress_of("a.mp4") is not None


# endregion


def test_a_tutorial_holding_other_details_takes_a_write_in_all_the_same(
    tmp_path: Path, open_model: OpenModel, records: Records
) -> None:
    """The comparison that decides whether a write is taken in sees the block's other fields, and finds them equal.

    **Test steps:**

    * open a tutorial whose block holds a detail, and record a position
    * verify the write was taken in: nothing is reported, and the model is based on the record as it now is
    """
    path = write_tutorial(tmp_path / "t", block={"complete": False})
    model = open_model(path)

    model.record_progress("a.mp4", 4.0, 10.0)

    assert model.progress_unsaved == ""
    assert (
        model.base_version
        == records.load(ResourceKey(path), username=model.document.username, unknown_username="x").version
    )


def test_a_record_locked_against_saving_keeps_progress_to_the_session_and_says_why(
    tmp_path: Path, open_model: OpenModel, held_writes: HeldWrites
) -> None:
    """A malformed field is never written over: no write is handed on, and the lock's own words are the reason.

    **Test steps:**

    * open a tutorial whose ``original_duration`` is not a number, and record a position
    * verify nothing was handed to the writer, the entry reads back, and the reason is the lock's message
    """
    path = write_tutorial(tmp_path / "t", block={"original_duration": "junk"})
    model = open_model(path)
    assert model.locked

    model.record_progress("a.mp4", 4.0, 10.0)

    assert held_writes.keys == []
    assert model.progress_of("a.mp4") is not None
    assert model.lock_reasons[0].message in model.progress_unsaved


# region a Measure's lengths from a worker thread


def post_from_a_thread(model: RehuDocumentModel, key: ResourceKey | None, measured: dict[str, VideoFacts]) -> None:
    """Post lengths the way the duration Compute's worker does, and wait for the thread to be done.

    :param model: the document.
    :param key: the record the lengths are of.
    :param measured: the facts by content key.
    """
    thread = threading.Thread(target=model.post_measured_videos, args=(key, measured))
    thread.start()
    thread.join()


def test_lengths_posted_from_a_worker_thread_are_written_on_the_gui_thread(
    tmp_path: Path, open_model: OpenModel, qtbot: QtBot
) -> None:
    """The duration Compute measures off the GUI thread and hands its per-video lengths over, to be written in.

    **Test steps:**

    * open a tutorial and post a Measure's lengths from another thread, for its own record
    * wait for the queued delivery
    * verify the model reads them, the record holds them, and the document is clean
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    measured = {"a.mp4": VideoFacts(100.0)}

    post_from_a_thread(model, model.key, measured)

    qtbot.waitUntil(lambda: model.measured_videos() == measured)
    assert stored(path)["tutorial"]["videos"] == {"a.mp4": {"duration": 100.0}}
    assert model.dirty is False


def test_lengths_measured_of_another_record_are_dropped(tmp_path: Path, open_model: OpenModel, qtbot: QtBot) -> None:
    """A Compute that outlived a switch to another record writes nothing into the one shown now.

    **Test steps:**

    * open a tutorial and post lengths for a different record, and for none
    * let the queued deliveries run
    * verify nothing was written
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    before = stored(path)

    post_from_a_thread(model, ResourceKey(tmp_path / "other" / "info.rehu"), {"a.mp4": VideoFacts(100.0)})
    post_from_a_thread(model, None, {"a.mp4": VideoFacts(100.0)})
    qtbot.wait(50)

    assert model.measured_videos() == {}
    assert stored(path) == before


def test_lengths_posted_after_the_model_is_gone_end_quietly(tmp_path: Path, open_model: OpenModel) -> None:
    """A document closed while its Compute ran has nobody left to take the lengths, and nothing fails.

    **Test steps:**

    * open a tutorial, delete its model, and post lengths
    * verify nothing was raised
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    key = model.key
    shiboken6.delete(model)

    model.post_measured_videos(key, {"a.mp4": VideoFacts(1.0)})


# endregion
