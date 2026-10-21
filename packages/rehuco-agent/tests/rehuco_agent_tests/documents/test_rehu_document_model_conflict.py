"""Tests for a document model saving through its records (#416): a read-merge-write that merges per-user fields
written meanwhile, and refuses a save over details changed on disk as a conflict the person resolves.

Real records under ``tmp_path``: one model opens a record the way a holder does, and a second reading of the same file
stands for the other writer -- another app, another user, a progress write.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from freezegun.api import FrozenDateTimeFactory
from pytest import mark, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import (
    ABSENT,
    DEFAULT_CURRENT_USERNAME,
    DEFAULT_UNKNOWN_USERNAME,
    RecordConflict,
    RehuDocument,
    record_differences,
)
from rehuco_core.access import ChangeFeed, Records, ResourceKey

pytestmark = mark.usefixtures("real_path_stat")

TYPE: Final = "tutorial"
"""The records' type: one whose block holds the per-user fields."""

TITLE_PATH: Final = ("core", "sources", 0, "title")
URL_PATH: Final = ("core", "sources", 0, "url")
DESCRIPTION_PATH: Final = ("core", "description")
RATING_PATH: Final = (TYPE, "users", DEFAULT_CURRENT_USERNAME, "rating")
"""The current user's rating, as a conflict row names it."""

PROGRESS: Final = {"part1.mp4": {"position": 42.0}}
"""A progress entry, as a player writes one."""


def write_record(path: Path, title: str, *, url: str = "", rating: int | None = None) -> None:
    """Write a tutorial record from nothing.

    :param path: where.
    :param title: its title.
    :param url: its URL; none when empty.
    :param rating: the current user's rating; none when ``None``.
    """
    document = RehuDocument.new(path)
    document.core["type"] = TYPE
    document.title = title
    if url:
        document.url = url
    if rating is not None:
        document.set_user_field(DEFAULT_CURRENT_USERNAME, "rating", rating)
    document.save()


def edit_on_disk(path: Path, edit: Callable[[RehuDocument], None]) -> None:
    """Change the record the way another writer would: read it afresh, edit, save.

    :param path: the record.
    :param edit: what to change on the fresh reading.
    """
    document = RehuDocument.load(path)
    edit(document)
    document.save()


def retitle(title: str) -> Callable[[RehuDocument], None]:
    """An edit setting the title.

    :param title: the new title.
    :returns: the edit.
    """

    def edit(document: RehuDocument) -> None:
        document.title = title

    return edit


def rate(rating: int) -> Callable[[RehuDocument], None]:
    """An edit setting the current user's rating.

    :param rating: the rating.
    :returns: the edit.
    """

    def edit(document: RehuDocument) -> None:
        document.set_user_field(DEFAULT_CURRENT_USERNAME, "rating", rating)

    return edit


def on_disk(path: Path) -> tuple[int, int]:
    """The file's modification time and size, as the catalog reports them.

    :param path: the file.
    :returns: its signature.
    """
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def stored(path: Path) -> RehuDocument:
    """The record as the file holds it now.

    :param path: the record.
    :returns: a fresh reading of it.
    """
    return RehuDocument.load(path)


def opened(path: Path) -> RehuDocumentModel:
    """The model a holder builds for ``path``, read and saved through records of its own.

    :param path: the record.
    :returns: the model.
    """
    records = Records()
    record = records.load(
        ResourceKey(path), username=DEFAULT_CURRENT_USERNAME, unknown_username=DEFAULT_UNKNOWN_USERNAME
    )
    return RehuDocumentModel(record.document, records=records, version=record.version, signature=record.signature)


def in_conflict(path: Path, mine: str, theirs: str) -> tuple[RehuDocumentModel, RecordConflict]:
    """A model whose save was refused: its title edited to ``mine`` while the file's became ``theirs``.

    :param path: a record already written.
    :param mine: the model's title.
    :param theirs: the file's title.
    :returns: the model, and the refusal it raised.
    """
    model = opened(path)
    model.title = mine
    edit_on_disk(path, retitle(theirs))
    with raises(RecordConflict) as refused:
        model.save()
    return model, refused.value


# region save
def test_a_save_writes_through_the_records_and_announces_nothing(tmp_path: Path, mocker: MockerFixture) -> None:
    """The record goes through the records, and nobody announces it: the folder's file notifier reports the write to
    every view (#511).

    **Test steps:**

    * open a record, and edit its title
    * save it
    * verify the file holds the title, the model is clean, and nothing was published on any change feed
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    published = mocker.spy(ChangeFeed, "publish")
    model.title = "Mine"

    model.save()

    assert stored(path).title == "Mine"
    assert not model.dirty
    published.assert_not_called()


def test_a_second_save_is_checked_against_the_first(tmp_path: Path) -> None:
    """A save moves what the next is checked against: saving twice in a row is never a conflict with oneself.

    **Test steps:**

    * open a record, edit and save it, then edit and save it again
    * verify the file holds the second title and no conflict was raised
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "First"
    model.save()
    model.title = "Second"

    model.save()

    assert stored(path).title == "Second"
    assert model.conflict is None


def test_a_document_with_no_location_is_not_saved(qtbot: QtBot) -> None:
    """A new document not yet bound to a path has nowhere to be saved, and says so rather than guessing.

    **Test steps:**

    * start a new document with no path
    * verify a save raises ``ValueError``
    """
    del qtbot
    model = RehuDocumentModel.create_new(None)

    with raises(ValueError, match="No path given"):
        model.save()


def test_a_save_over_details_changed_on_disk_is_refused_and_kept_as_the_conflict(tmp_path: Path, qtbot: QtBot) -> None:
    """Overwriting another writer's edit silently is the one thing a save must not do: it is refused, and the
    refusal is kept on the model for the banner and the dialog.

    **Test steps:**

    * open a record and edit its title, then retitle the file outside the app
    * save, watching ``conflict_changed``
    * verify the save raised the conflict now held in ``conflict``, carrying the file's title
    * verify the file still holds the other title, and the model is still dirty
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    edit_on_disk(path, retitle("Theirs"))

    with qtbot.waitSignal(model.conflict_changed), raises(RecordConflict) as refused:  # type: ignore[attr-defined]
        model.save()

    assert model.conflict is refused.value
    assert refused.value.theirs.title == "Theirs"
    assert stored(path).title == "Theirs"
    assert model.dirty


def test_a_rating_written_on_disk_meanwhile_is_merged_and_shown(tmp_path: Path) -> None:
    """A per-user field written while the document was open is not someone else's metadata edit: the save merges
    it rather than refusing or overwriting, and the field shows the merged value at once.

    **Test steps:**

    * open a rated record and edit its title, then change the rating outside the app
    * save
    * verify the file holds both the new title and the new rating, and the model shows the new rating
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)
    model = opened(path)
    model.title = "Mine"
    edit_on_disk(path, rate(3))

    model.save()

    on_file = stored(path)
    assert (on_file.title, on_file.user_field(DEFAULT_CURRENT_USERNAME, "rating")) == ("Mine", 3)
    assert model.rating == 3
    assert not model.dirty


def test_a_save_clears_the_changed_on_disk_notice(tmp_path: Path) -> None:
    """A file changed under unsaved edits raises the notice; a save that merged the change has nothing left to say.

    **Test steps:**

    * open a rated record and edit its title, change the rating outside the app, and report the file as it is now
    * verify the model says the file changed on disk
    * save it
    * verify the notice is down, and no conflict stands
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)
    model = opened(path)
    model.title = "Mine"
    edit_on_disk(path, rate(5))
    model.note_file_signature(*on_disk(path))
    assert model.changed_on_disk

    model.save()

    assert not model.changed_on_disk
    assert model.conflict is None


# endregion


# region resolve_conflict
def test_resolving_without_a_conflict_is_refused(tmp_path: Path) -> None:
    """There is nothing to resolve until a save was refused.

    **Test steps:**

    * open a record
    * verify ``resolve_conflict`` raises ``ValueError``
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)

    with raises(ValueError, match="no conflict"):
        model.resolve_conflict({})


def test_resolving_with_the_files_values_saves_them_and_removes_what_the_file_removed(tmp_path: Path) -> None:
    """The person's picks become the saved record: the file's title and description, and the file's removal of the
    URL -- an ``ABSENT`` value removes the detail rather than writing a placeholder.

    **Test steps:**

    * open a record with a URL and edit its title, then retitle the file, give it a description and drop its URL
    * save, resolve the conflict keeping the file's value of every differing detail, and save again
    * verify the file holds the file's title and description and no URL, and the model shows the same
    * verify the conflict is gone and the model is clean
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", url="https://old.example")

    def theirs(document: RehuDocument) -> None:
        document.title = "Theirs"
        document.description = "Their notes"
        del document.core["sources"][0]["url"]

    model = opened(path)
    model.title = "Mine"
    edit_on_disk(path, theirs)
    with raises(RecordConflict) as refused:
        model.save()
    differences = record_differences(
        model.base_data(), model.document.data, refused.value.theirs.data, DEFAULT_CURRENT_USERNAME
    )
    values: dict[Any, Any] = {difference.path: difference.theirs for difference in differences}
    assert values == {TITLE_PATH: "Theirs", URL_PATH: ABSENT, DESCRIPTION_PATH: "Their notes"}

    model.resolve_conflict(values)
    model.save()

    on_file = stored(path)
    assert (on_file.title, on_file.url, on_file.description) == ("Theirs", "", "Their notes")
    assert (model.title, model.url, model.description) == ("Theirs", "", "Their notes")
    assert model.conflict is None
    assert not model.dirty


def test_resolving_writes_a_per_user_field_kept_as_mine_over_the_files(tmp_path: Path) -> None:
    """A per-user field the file changed and this document did not would take the file's value in the merge alone;
    kept as *Mine* in the dialog, the document's value is the one saved.

    **Test steps:**

    * open a record rated 1 and edit its title, then retitle the file and rate it 3 there
    * save, and list the rows: the title and the rating, the rating changed on disk only
    * resolve keeping this document's title and its rating of 1, and save
    * verify the file and the model hold this document's title and the rating of 1
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)

    def theirs(document: RehuDocument) -> None:
        document.title = "Theirs"
        document.set_user_field(DEFAULT_CURRENT_USERNAME, "rating", 3)

    model = opened(path)
    model.title = "Mine"
    edit_on_disk(path, theirs)
    with raises(RecordConflict) as refused:
        model.save()
    differences = record_differences(
        model.base_data(), model.document.data, refused.value.theirs.data, DEFAULT_CURRENT_USERNAME
    )
    assert [(row.path, row.mine_changed, row.theirs_changed) for row in differences] == [
        (TITLE_PATH, True, True),
        (RATING_PATH, False, True),
    ]

    model.resolve_conflict({difference.path: difference.mine for difference in differences})
    model.save()

    on_file = stored(path)
    assert (on_file.title, on_file.user_field(DEFAULT_CURRENT_USERNAME, "rating")) == ("Mine", 1)
    assert (model.title, model.rating) == ("Mine", 1)
    assert model.conflict is None


def test_resolving_with_the_files_details_keeps_the_files_updated(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """Keeping every detail the file's way and only a per-user field of this document's writes nothing about the
    resource, so the file's ``updated`` stands -- although the resolving save is made against the conflict's own
    version, which makes the file read as unchanged.

    **Test steps:**

    * at day 1, open a record rated 1, retitle it and rate it 5
    * at day 2, retitle the file and rate it 3 there; the save is refused
    * at day 3, resolve with the file's title and this document's rating, and save
    * verify the file holds the file's title, the rating of 5, and day 2's ``updated``
    """
    path = tmp_path / "info.rehu"
    freezer.move_to("2026-01-01T00:00:00Z")
    write_record(path, "Old", rating=1)
    model = opened(path)
    model.title = "Mine"
    model.rating = 5

    def theirs(document: RehuDocument) -> None:
        document.title = "Theirs"
        document.set_user_field(DEFAULT_CURRENT_USERNAME, "rating", 3)

    freezer.move_to("2026-02-02T00:00:00Z")
    edit_on_disk(path, theirs)
    with raises(RecordConflict):
        model.save()

    freezer.move_to("2026-03-03T00:00:00Z")
    model.resolve_conflict({TITLE_PATH: "Theirs", RATING_PATH: 5})
    model.save()

    on_file = stored(path)
    assert (on_file.title, on_file.user_field(DEFAULT_CURRENT_USERNAME, "rating")) == ("Theirs", 5)
    assert on_file.updated == "2026-02-02T00:00:00Z"


def test_resolving_writes_the_original_values_kept(tmp_path: Path) -> None:
    """A row kept as *Original* puts back the value as opened -- neither side's -- and an original the record did not
    have removes the detail and the per-user field.

    **Test steps:**

    * open a record rated 1, with no description; edit its title, description and rating
    * meanwhile give the file another title, description and rating
    * save, resolve keeping every row's original value, and save again
    * verify the file and the model hold the old title, no description and the old rating
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)

    def theirs(document: RehuDocument) -> None:
        document.title = "Theirs"
        document.description = "Their notes"
        document.set_user_field(DEFAULT_CURRENT_USERNAME, "rating", 3)

    model = opened(path)
    model.title = "Mine"
    model.description = "My notes"
    model.rating = 5
    edit_on_disk(path, theirs)
    with raises(RecordConflict) as refused:
        model.save()
    differences = record_differences(
        model.base_data(), model.document.data, refused.value.theirs.data, DEFAULT_CURRENT_USERNAME
    )
    originals: dict[Any, Any] = {difference.path: difference.base for difference in differences}
    assert originals == {TITLE_PATH: "Old", DESCRIPTION_PATH: ABSENT, RATING_PATH: 1}

    model.resolve_conflict(originals)
    model.save()

    on_file = stored(path)
    assert (on_file.title, on_file.description) == ("Old", "")
    assert "description" not in on_file.core
    assert on_file.user_field(DEFAULT_CURRENT_USERNAME, "rating") == 1
    assert (model.title, model.description, model.rating) == ("Old", "", 1)
    assert not model.dirty


def test_resolving_keeps_a_progress_entry_written_meanwhile(tmp_path: Path) -> None:
    """A player's progress write landing with the other edit must survive the resolution: the per-user fields are
    merged against what the document was read at before the picks are put.

    **Test steps:**

    * open a rated record and edit its title, then retitle the file and add a progress entry to it
    * save, resolve the conflict keeping this document's title, and save again
    * verify the file holds this document's title, the rating, and the progress entry
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=2)

    def theirs(document: RehuDocument) -> None:
        document.title = "Theirs"
        document.set_user_field(DEFAULT_CURRENT_USERNAME, "progress", PROGRESS)

    model = opened(path)
    model.title = "Mine"
    edit_on_disk(path, theirs)
    with raises(RecordConflict):
        model.save()

    model.resolve_conflict({})
    model.save()

    on_file = stored(path)
    assert on_file.title == "Mine"
    assert on_file.user_field(DEFAULT_CURRENT_USERNAME, "rating") == 2
    assert on_file.user_field(DEFAULT_CURRENT_USERNAME, "progress") == PROGRESS


def test_resolving_a_conflict_raised_again_keeps_the_new_one(tmp_path: Path) -> None:
    """The file can change once more while the dialog is open: the resolution's save is then refused against that newer
    file, which becomes the conflict to resolve.

    **Test steps:**

    * bring a model into conflict, then retitle the file a second time
    * resolve the first conflict, and save
    * verify the save is refused with the newest title, which is now the model's conflict
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model, _ = in_conflict(path, "Mine", "Theirs")
    edit_on_disk(path, retitle("Theirs again"))

    model.resolve_conflict({})
    with raises(RecordConflict) as again:
        model.save()

    assert again.value.theirs.title == "Theirs again"
    assert model.conflict is again.value


def test_resolving_on_a_model_not_read_from_its_file_puts_the_values_over_the_file(tmp_path: Path) -> None:
    """A model with no version to merge per-user fields against still resolves: the picks are put and the result is
    saved against the file as the conflict found it.

    **Test steps:**

    * build a model over a reading of a record, with no version, and hand it a conflict naming the file as it is
    * resolve it keeping the file's title, and save
    * verify the file holds that title, the conflict is gone and the model is clean
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    records = Records()
    record = records.load(
        ResourceKey(path), username=DEFAULT_CURRENT_USERNAME, unknown_username=DEFAULT_UNKNOWN_USERNAME
    )
    model = RehuDocumentModel(RehuDocument.load(path), records=records)
    model.title = "Mine"
    assert record.version is not None
    model.conflict = RecordConflict(record.document, record.version)

    model.resolve_conflict({TITLE_PATH: "Old"})
    model.save()

    assert stored(path).title == "Old"
    assert model.conflict is None
    assert not model.dirty


def test_a_revert_drops_the_conflict(tmp_path: Path) -> None:
    """Discarding the edits is the other way out of a conflict: the file is read as it is, and nothing is left to
    resolve.

    **Test steps:**

    * bring a model into conflict
    * revert it
    * verify it shows the file's title, is clean, and holds no conflict
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model, _ = in_conflict(path, "Mine", "Theirs")

    model.revert()

    assert (model.title, model.dirty, model.conflict) == ("Theirs", False, None)


# endregion


# region base_data, stored_text, signature
def test_the_base_data_is_the_record_as_read_with_its_per_user_fields(tmp_path: Path) -> None:
    """The *Original* column of the dialog: what was read, per-user fields included, not what is being edited -- and
    a copy a caller can change freely.

    **Test steps:**

    * open a rated record, edit its title and rating
    * verify the base data is the file's payload, with the old title and the old rating
    * change the returned copy, and verify a second call is unaffected
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=4)
    model = opened(path)
    model.title = "Mine"
    model.rating = 1

    base = model.base_data()

    assert base == stored(path).data
    assert base["core"]["sources"][0]["title"] == "Old"
    assert base[TYPE]["users"][DEFAULT_CURRENT_USERNAME]["rating"] == 4
    base["core"]["sources"][0]["title"] = "Scribbled"
    base[TYPE]["users"][DEFAULT_CURRENT_USERNAME]["rating"] = 9
    again = model.base_data()
    assert again["core"]["sources"][0]["title"] == "Old"
    assert again[TYPE]["users"][DEFAULT_CURRENT_USERNAME]["rating"] == 4


def test_the_base_data_follows_a_save(tmp_path: Path) -> None:
    """After a save the file holds the edits, so they are what the next conflict compares against.

    **Test steps:**

    * open a rated record, edit its title and rating and save it
    * verify the base data now holds the saved title and rating
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=4)
    model = opened(path)
    model.title = "Mine"
    model.rating = 2

    model.save()

    base = model.base_data()
    assert base["core"]["sources"][0]["title"] == "Mine"
    assert base[TYPE]["users"][DEFAULT_CURRENT_USERNAME]["rating"] == 2


def test_the_stored_text_is_the_file_not_the_edited_document(tmp_path: Path) -> None:
    """The On Disk view shows the file through the records; an unsaved edit is not in it.

    **Test steps:**

    * open a record and edit its title
    * verify the stored text is the file's text, still without the edit
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"

    text = model.stored_text()

    assert text == path.read_text(encoding="utf-8")
    assert '"Old"' in text
    assert '"Mine"' not in text


def test_a_document_with_no_location_has_no_stored_text(qtbot: QtBot) -> None:
    """With no file behind it, there is nothing stored to show.

    **Test steps:**

    * start a new document with no path
    * verify ``stored_text`` raises ``FileNotFoundError``
    """
    del qtbot
    model = RehuDocumentModel.create_new(None)

    with raises(FileNotFoundError):
        model.stored_text()


def test_the_record_signature_is_what_a_reported_file_is_compared_with(tmp_path: Path) -> None:
    """The signature the records took when reading is the model's own: reporting the file unchanged reloads nothing,
    reporting it changed does.

    **Test steps:**

    * open a record, then report the file as it is
    * verify nothing was reloaded
    * retitle the file outside the app and report it again
    * verify the clean model reloaded the new title
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    reloads: list[object] = []
    model.reloaded.connect(lambda: reloads.append(None))

    model.note_file_signature(*on_disk(path))
    assert not reloads

    edit_on_disk(path, retitle("Theirs, and longer"))
    model.note_file_signature(*on_disk(path))

    assert reloads
    assert model.title == "Theirs, and longer"


def test_a_save_takes_the_written_files_signature(tmp_path: Path) -> None:
    """The model's own write is not a change on disk: reporting the saved file afterwards changes nothing.

    **Test steps:**

    * open a record, edit and save it, then edit it again
    * report the file as it is now
    * verify the model was not told the file changed, and keeps its edit
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "A much longer title than before"
    model.save()
    model.title = "Unsaved"

    model.note_file_signature(*on_disk(path))

    assert not model.changed_on_disk
    assert model.title == "Unsaved"


def test_a_model_with_no_signature_compares_nothing(tmp_path: Path) -> None:
    """A model built without the file's signature has nothing to compare a report with, and takes no action.

    **Test steps:**

    * build a dirty model over a record, with no signature
    * report a different signature for the file
    * verify the model was not told the file changed
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = RehuDocumentModel(RehuDocument.load(path), records=Records())
    model.title = "Mine"

    model.note_file_signature(1, 2)

    assert not model.changed_on_disk


# endregion


def test_a_rename_whose_save_is_refused_as_a_conflict_moves_nothing(tmp_path: Path) -> None:
    """A rename saves a dirty document first; a refused save stops it, and the banner says why.

    **Test steps:**

    * open a folder's record and edit its title, then retitle the file outside the app
    * rename the resource
    * verify the rename failed with a message naming the refused save, the folder did not move, and the conflict
      stands
    """
    path = tmp_path / "sculpting" / "info.rehu"
    path.parent.mkdir()
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    edit_on_disk(path, retitle("Theirs"))

    assert not model.rename_location("modelling")

    assert model.rename_error.startswith('Could not save "sculpting" before renaming it:')
    assert "changed by someone else" in model.rename_error
    assert path.exists()
    assert not (tmp_path / "modelling").exists()
    assert isinstance(model.conflict, RecordConflict)


# region reads through the records
def test_another_record_loaded_in_place_is_saved_against_what_was_read(tmp_path: Path) -> None:
    """A preview moving on to the next record reads it through the records, version and all, so an edit made to it
    is checked like any other.

    **Test steps:**

    * open one record, then load another in its place
    * edit its title and retitle its file outside the app
    * verify a save is refused as a conflict carrying the other record's title
    """
    first, second = tmp_path / "a.rehu", tmp_path / "b.rehu"
    write_record(first, "First")
    write_record(second, "Second")
    model = opened(first)

    model.load(second)
    model.title = "Mine"
    edit_on_disk(second, retitle("Theirs"))

    with raises(RecordConflict) as refused:
        model.save()

    assert refused.value.theirs.title == "Theirs"


def test_a_conversion_goes_through_the_records_and_is_saved_against_the_new_record(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Converting a legacy record announces nothing -- the folder's file notifier reports both files (#511) -- and the
    new record is read with its version, so a later save over a change on disk is refused.

    **Test steps:**

    * open a legacy ``.tc``, and convert it
    * verify nothing was published on any change feed, and the model stands for the new record
    * edit its title and retitle the new file outside the app
    * verify a save is refused as a conflict
    """
    legacy = tmp_path / "info.tc"
    legacy.write_text("type: Tutorial\ntitle: Legacy\n", encoding="utf-8")
    model = opened(legacy)
    published = mocker.spy(ChangeFeed, "publish")

    model.convert(keep_backups=True)

    converted = tmp_path / "info.rehu"
    published.assert_not_called()
    assert model.path == converted
    model.title = "Mine"
    edit_on_disk(converted, retitle("Theirs"))
    with raises(RecordConflict):
        model.save()


# endregion
