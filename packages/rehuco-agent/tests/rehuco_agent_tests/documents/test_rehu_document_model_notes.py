"""Tests for a document model recording per-user notes and favorites (#571, [[field-schema#video-notes]]).

Real files under ``tmp_path``, read and written through real records; the writer's thread is stood in for by
``inline_progress_writes`` (the default here) or held until the test runs each write (``held_writes``).
"""

import json
from pathlib import Path
from typing import Any

from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RehuDocument, SaveRecordJob, user_sidecar_path
from rehuco_core.access import Records

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown
from rehuco_agent_tests.documents.test_rehu_document_model_progress import (  # noqa: F401  # pylint: disable=unused-import
    OpenModel,
    fixture_open_model,
    fixture_records,
    stored,
    write_tutorial,
)
from rehuco_agent_tests.progress_writes import HeldWrites

pytestmark = mark.usefixtures("real_path_stat")


def stored_user(path: Path, username: str) -> dict[str, Any]:
    """One user's tutorial fields as stored in their sidecar.

    :param path: the record.
    :param username: whose.
    :returns: the fields; empty when there is no sidecar or it holds none.
    """
    sidecar = user_sidecar_path(path, username)
    if not sidecar.exists():
        return {}
    return json.loads(sidecar.read_text(encoding="utf-8")).get("tutorial", {})


# region recording
def test_a_recorded_note_is_shown_written_to_the_sidecar_and_leaves_the_document_clean(
    tmp_path: Path, open_model: OpenModel, qtbot: QtBot
) -> None:
    """A note is the user's own state beside the record: shown and written at once, never an edit.

    **Test steps:**

    * open a tutorial and record the tutorial's notes, a video's note and a favorite
    * verify the change was announced, each reads back, the user's sidecar holds them, and the record's own file,
      ``updated`` and dirty flag are untouched
    """
    path = write_tutorial(tmp_path / "t")
    record_before = stored(path)
    model = open_model(path)
    username = model.document.username

    with qtbot.waitSignal(model.notes_changed):
        model.record_notes(notes="About it", video_notes={"a.mp4": "a note"}, favorites={"b.mp4": True})

    assert (model.notes, model.video_notes_of("a.mp4"), model.video_notes_of("b.mp4")) == ("About it", "a note", "")
    assert (model.is_favorite("b.mp4"), model.is_favorite("a.mp4")) == (True, False)
    fields = stored_user(path, username)
    assert (fields["notes"], fields["video_notes"], fields["video_favorites"]) == (
        "About it",
        {"a.mp4": "a note"},
        ["b.mp4"],
    )
    assert stored(path) == record_before
    assert (model.dirty, model.notes_unsaved) == (False, "")


def test_clearing_a_note_and_unstarring_remove_them(tmp_path: Path, open_model: OpenModel) -> None:
    """An empty text and a ``False`` read as nothing at once and leave nothing stored.

    **Test steps:**

    * record a note and a favorite, then clear the note and unstar the video
    * verify the model reads neither and the sidecar holds no key for them
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    model.record_notes(video_notes={"a.mp4": "a note"}, favorites={"a.mp4": True})

    model.record_notes(video_notes={"a.mp4": ""}, favorites={"a.mp4": False})

    assert (model.video_notes_of("a.mp4"), model.is_favorite("a.mp4")) == ("", False)
    assert stored_user(path, model.document.username) == {}


def test_an_unsaved_edit_survives_a_notes_write_and_the_notes_survive_its_save(
    tmp_path: Path, open_model: OpenModel
) -> None:
    """Recording a note neither reads the edit away nor loses the note when the edit is saved.

    **Test steps:**

    * open a tutorial and edit its title without saving
    * record a video's note
    * verify the title is still the edit, the document is still dirty, and the file holds the old title
    * save, and verify the file holds the edit and the note is still stored and shown
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    model.title = "Mine"

    model.record_notes(video_notes={"a.mp4": "a note"})

    assert (model.title, model.dirty) == ("Mine", True)
    assert stored(path)["core"]["sources"][0]["title"] == "Old"
    model.save()
    assert stored(path)["core"]["sources"][0]["title"] == "Mine"
    assert stored_user(path, model.document.username)["video_notes"] == {"a.mp4": "a note"}
    assert model.video_notes_of("a.mp4") == "a note"


def test_forgetting_a_video_clears_its_note_and_favorite_in_the_model_and_on_disk(
    tmp_path: Path, open_model: OpenModel
) -> None:
    """Forget takes everything the user keeps about one video, and only that video.

    **Test steps:**

    * keep progress, a note and a favorite on two videos
    * forget one
    * verify the other keeps all three in the model and on disk, and the forgotten one has none
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    for name in ("a.mp4", "b.mp4"):
        model.record_progress(name, 1.0, 10.0)
    model.record_notes(video_notes={"a.mp4": "one", "b.mp4": "two"}, favorites={"a.mp4": True, "b.mp4": True})

    model.forget_progress("a.mp4")

    assert (model.video_notes_of("a.mp4"), model.is_favorite("a.mp4"), model.progress_of("a.mp4")) == ("", False, None)
    assert (model.video_notes_of("b.mp4"), model.is_favorite("b.mp4")) == ("two", True)
    fields = stored_user(path, model.document.username)
    assert (fields["video_notes"], fields["video_favorites"]) == ({"b.mp4": "two"}, ["b.mp4"])


# endregion


# region before the write lands
def test_a_note_shows_before_its_write_runs_and_the_landed_write_is_taken_in(
    tmp_path: Path, open_model: OpenModel, held_writes: HeldWrites
) -> None:
    """The note is the session's own until the record holds it, and then the record is where it is read from.

    **Test steps:**

    * record a note while the writer holds its writes
    * verify it reads back, the document does not hold it yet, and nothing is stored
    * let the write run, and verify the document holds the note and the sidecar stores it
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    username = model.document.username

    model.record_notes(video_notes={"a.mp4": "a note"})

    assert model.video_notes_of("a.mp4") == "a note"
    assert model.document.user_field(username, "video_notes") is None
    assert stored_user(path, username) == {}
    held_writes.release_all()
    assert model.document.user_field(username, "video_notes") == {"a.mp4": "a note"}
    assert stored_user(path, username)["video_notes"] == {"a.mp4": "a note"}
    assert (model.video_notes_of("a.mp4"), model.dirty) == ("a note", False)


def test_a_landed_progress_write_does_not_take_a_waiting_note_away(
    tmp_path: Path, open_model: OpenModel, held_writes: HeldWrites
) -> None:
    """A write that lands takes the record in whole, and what the session recorded that the record lacks stays.

    **Test steps:**

    * record a note and a position while the writer holds its writes, and let only the position's run
    * verify the note still reads back, and nothing says it is unsaved
    * let the note's write run, and verify the sidecar holds it
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    model.record_notes(video_notes={"b.mp4": "a note"})
    model.record_progress("a.mp4", 3.0, 10.0, viewed=True)

    held_writes.release(("progress", "a.mp4"))

    assert model.video_notes_of("b.mp4") == "a note"
    assert model.notes_unsaved == ""
    held_writes.release_all()
    assert stored_user(path, model.document.username)["video_notes"] == {"b.mp4": "a note"}


def test_a_note_written_while_a_save_is_out_is_in_the_document_once_the_save_lands(
    tmp_path: Path, open_model: OpenModel, records: Records
) -> None:
    """A write that lands while a save is out is not taken in on its own -- the save is the record here -- and the
    save's own merge brings it in; it shows the whole time and is never an edit.

    **Test steps:**

    * open a tutorial and hand its snapshot to a save that has not landed
    * record a note, which writes at once
    * verify it reads back and the document does not hold it yet
    * land the save, and verify the document holds the note, is clean, and the sidecar still stores it
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    username = model.document.username
    payload = model.snapshot()
    model.begin_save()
    job = SaveRecordJob(payload, records=records, coordinator=None)

    model.record_notes(video_notes={"a.mp4": "a note"})

    assert model.video_notes_of("a.mp4") == "a note"
    assert model.document.user_field(username, "video_notes") is None
    model.complete_save(payload, job.write())
    assert model.document.user_field(username, "video_notes") == {"a.mp4": "a note"}
    assert (model.video_notes_of("a.mp4"), model.dirty) == ("a note", False)
    assert stored_user(path, username)["video_notes"] == {"a.mp4": "a note"}


# endregion


# region what cannot be written
def test_a_document_with_no_file_keeps_notes_for_the_session_and_says_so(
    qtbot: QtBot, held_writes: HeldWrites, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Nothing is handed to the writer, the note is shown anyway, and the banner's reason names why -- in the notes'
    property, not the progress one.

    **Test steps:**

    * build a new document with no path and record a note
    * verify nothing was written, the note reads back, and ``notes_unsaved`` says it is not a file here
    """
    del qtbot
    model = delete_at_teardown(RehuDocumentModel.create_new())

    model.record_notes(notes="About it", favorites={"a.mp4": True})

    assert held_writes.keys == []
    assert (model.notes, model.is_favorite("a.mp4")) == ("About it", True)
    assert model.notes_unsaved == "Notes are not being saved: this is not a file on this machine"
    assert model.progress_unsaved == ""


def test_a_failed_write_keeps_the_note_says_why_and_is_cleared_by_the_next_that_lands(
    tmp_path: Path, open_model: OpenModel, records: Records, mocker: MockerFixture
) -> None:
    """The share going away loses nothing: the note stays, and the next write retries with it.

    **Test steps:**

    * record a note while the records' write raises ``OSError``
    * verify the note still reads back and ``notes_unsaved`` carries the system's reason, and progress says nothing
    * record again once writing works, and verify the sidecar holds the note and the reason is gone
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    real = records.record_notes
    mocker.patch.object(records, "record_notes", side_effect=OSError(53, "The network path was not found"))

    model.record_notes(video_notes={"a.mp4": "a note"})

    assert model.video_notes_of("a.mp4") == "a note"
    assert model.notes_unsaved == "Notes could not be saved: The network path was not found."
    assert model.progress_unsaved == ""

    mocker.patch.object(records, "record_notes", real)
    model.record_notes(video_notes={"a.mp4": "a better note"})

    assert stored_user(path, model.document.username)["video_notes"] == {"a.mp4": "a better note"}
    assert model.notes_unsaved == ""


def test_a_note_that_failed_stays_while_progress_lands(
    tmp_path: Path, open_model: OpenModel, records: Records, mocker: MockerFixture
) -> None:
    """A progress write landing is no proof the notes were saved: the failed note stays shown and reported.

    **Test steps:**

    * record a note while the records' notes write raises, then record a position that lands
    * verify the note still reads back and is still reported as unsaved
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    mocker.patch.object(records, "record_notes", side_effect=OSError(53, "The network path was not found"))
    model.record_notes(video_notes={"a.mp4": "a note"})

    model.record_progress("a.mp4", 3.0, 10.0, viewed=True)

    assert model.video_notes_of("a.mp4") == "a note"
    assert model.notes_unsaved != ""


def test_a_failed_progress_write_survives_a_note_landing_and_is_carried_by_its_next_write(
    tmp_path: Path, open_model: OpenModel, records: Records, mocker: MockerFixture
) -> None:
    """A landed write lets go of its own overlay only: a position that could not be written stays shown and reported
    while notes and other videos' positions land, until a write of its own video carries it.

    **Test steps:**

    * record a position while the records' progress write raises, then a note and another video's position that land
    * verify the failed position still reads back and the banner still says why
    * record the video again once writing works, and verify the sidecar holds it and the banner is clear
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    real = records.record_progress
    mocker.patch.object(records, "record_progress", side_effect=OSError(53, "The network path was not found"))
    model.record_progress("a.mp4", 7.0, 10.0)
    mocker.patch.object(records, "record_progress", real)

    model.record_notes(video_notes={"b.mp4": "a note"})
    model.record_progress("b.mp4", 2.0, 10.0)

    entry = model.progress_of("a.mp4")
    assert entry is not None and entry.position == 7.0
    assert model.progress_unsaved == "Watch progress could not be saved: The network path was not found."

    model.record_progress("a.mp4", 8.0, 10.0)

    assert stored_user(path, model.document.username)["progress"]["a.mp4"]["position"] == 8.0
    assert model.progress_unsaved == ""


# endregion


# region a renamed video
def test_the_first_play_of_a_renamed_video_finds_its_notes_and_favorite(tmp_path: Path, open_model: OpenModel) -> None:
    """A video's first write looks for the data its old name left, so a renamed video does not start over.

    **Test steps:**

    * note and star a video of five bytes, then rename its file
    * play the renamed video for the first time
    * verify the note and the favorite read under the new name and not the old
    """
    path = write_tutorial(tmp_path / "t", ("a.mp4",))
    (tmp_path / "t" / "a.mp4").write_bytes(b"12345")
    model = open_model(path)
    model.record_notes(video_notes={"a.mp4": "a note"}, favorites={"a.mp4": True})
    (tmp_path / "t" / "a.mp4").rename(tmp_path / "t" / "c.mp4")

    model.record_progress("c.mp4", 1.0, 10.0)

    assert (model.video_notes_of("c.mp4"), model.is_favorite("c.mp4")) == ("a note", True)
    assert (model.video_notes_of("a.mp4"), model.is_favorite("a.mp4")) == ("", False)


def test_starring_a_renamed_video_finds_its_note_and_only_the_first_touch_looks(
    tmp_path: Path, open_model: OpenModel, records: Records, mocker: MockerFixture
) -> None:
    """The first note or favorite on a video with no data looks under its old name too, and a second does not.

    **Test steps:**

    * note a video of five bytes, then rename its file
    * star the renamed video, and then unstar and star it again
    * verify the note followed, and the search ran once
    """
    path = write_tutorial(tmp_path / "t", ("a.mp4",))
    (tmp_path / "t" / "a.mp4").write_bytes(b"12345")
    model = open_model(path)
    model.record_notes(video_notes={"a.mp4": "a note"})
    (tmp_path / "t" / "a.mp4").rename(tmp_path / "t" / "c.mp4")
    search = mocker.spy(records, "reattach_renamed_progress")

    model.record_notes(favorites={"c.mp4": True})
    model.record_notes(favorites={"c.mp4": False})
    model.record_notes(favorites={"c.mp4": True})

    assert (model.video_notes_of("c.mp4"), model.is_favorite("c.mp4")) == ("a note", True)
    assert search.call_count == 1


def test_ticking_viewed_by_hand_on_a_renamed_video_finds_its_data_too(tmp_path: Path, open_model: OpenModel) -> None:
    """The first write under a new name is not always a play: a hand-set flag searches as well, or the old progress
    would stay missing for good.

    **Test steps:**

    * play a video of five bytes, then rename its file
    * tick the renamed video viewed by hand
    * verify its old position came along under the new name, and the old name has none
    """
    path = write_tutorial(tmp_path / "t", ("a.mp4",))
    (tmp_path / "t" / "a.mp4").write_bytes(b"12345")
    model = open_model(path)
    model.record_progress("a.mp4", 4.0, 10.0)
    (tmp_path / "t" / "a.mp4").rename(tmp_path / "t" / "c.mp4")

    model.record_progress("c.mp4", 4.0, 10.0, viewed=True)

    entry = model.progress_of("c.mp4")
    assert entry is not None and (entry.position, entry.viewed) == (4.0, True)
    assert model.progress_of("a.mp4") is None


def test_clearing_or_unstarring_a_video_with_no_data_searches_nothing(
    tmp_path: Path, open_model: OpenModel, records: Records, mocker: MockerFixture
) -> None:
    """Only a write that starts a video's data can be the first write of a renamed one.

    **Test steps:**

    * open a tutorial and spy on the records' search
    * clear a note and unstar a video that have neither
    * verify the search never ran
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)
    search = mocker.spy(records, "reattach_renamed_progress")

    model.record_notes(video_notes={"a.mp4": ""}, favorites={"b.mp4": False})

    assert search.call_count == 0


# endregion


# region the rename search's answer (#573)


def test_the_rename_search_says_when_it_answered_even_with_nothing_moved(
    tmp_path: Path, open_model: OpenModel, held_writes: HeldWrites, qtbot: QtBot
) -> None:
    """What shows a video's notes while the search is out needs to know when it is over, found or not.

    **Test steps:**

    * ask for the search while the writer holds its writes, and verify it was handed over and has not answered
    * let it run, on a tutorial where nothing was renamed, and verify it says it answered
    """
    path = write_tutorial(tmp_path / "t")
    model = open_model(path)

    assert model.reattach_renamed_progress() is True
    assert held_writes.keys == [("reattach",)]

    with qtbot.waitSignal(model.rename_search_finished, timeout=1000):
        held_writes.release_all()


def test_a_rename_search_the_record_cannot_take_is_refused_and_never_answers(
    qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """**Test steps:**

    * ask for the search on a document with no file
    * verify it was not handed over and nothing fires
    """
    model = delete_at_teardown(RehuDocumentModel(RehuDocument({"type": "Tutorial"})))

    with qtbot.assertNotEmitted(model.rename_search_finished):
        assert model.reattach_renamed_progress() is False


# endregion
