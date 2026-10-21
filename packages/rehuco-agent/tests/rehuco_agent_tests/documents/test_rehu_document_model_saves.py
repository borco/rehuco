"""Tests for a document model whose saves are handed to jobs (#497): the snapshot a job writes, taking back a save
that landed or failed, hearing its file gone, and showing edits kept from elsewhere.

Real records under ``tmp_path``, as in ``test_rehu_document_model_conflict``: one model opens a record the way a holder
does, and a second reading of the same file stands for the other writer. What a save job left on disk is handed back as
a :class:`~rehuco_core.SaveOutcome` built here, since the job's own write is tested with the job.
"""

import copy
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from pytest import mark, param, raises
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.excluded_files_settings import shared_excluded_files_settings
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    DEFAULT_CURRENT_USERNAME,
    DEFAULT_UNKNOWN_USERNAME,
    FORMAT_VERSION_KEY,
    JobWaiting,
    LockReasonKind,
    RecordConflict,
    RecordVersion,
    RehuDocument,
    SaveOutcome,
    SavePayload,
    SaveRecordJob,
    rebase_payload,
)
from rehuco_core.access import LoadedRecord, Records, ResourceKey

from .test_rehu_document_model_conflict import (
    TYPE,
    edit_on_disk,
    in_conflict,
    on_disk,
    opened,
    retitle,
    stored,
    write_record,
)

pytestmark = mark.usefixtures("real_path_stat")

LANDED_VERSION: Final = RecordVersion("landed metadata", "landed file", ())
"""What a landed save says the next save is checked against."""

LANDED_SIGNATURE: Final = (123, 456)
"""The signature a landed save says its write left; no file here has it."""

LANDED_STAMP: Final = "2030-01-01T00:00:00Z"
"""The ``updated`` stamp a landed save wrote."""


def user_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """The current user's per-user fields in a tutorial payload.

    :param payload: the payload.
    :returns: its fields, in place.
    """
    return payload[TYPE]["users"][DEFAULT_CURRENT_USERNAME]


def landed(payload: SavePayload, *, rating: int | None = None, signature: tuple[int, int] | None = None) -> SaveOutcome:
    """What a save of ``payload`` left on disk: its stamp moved, and the file's rating merged in when given.

    :param payload: what the save wrote.
    :param rating: the rating the file held, merged into what was written; ``None`` merges nothing.
    :param signature: the written file's signature.
    :returns: the outcome.
    """
    written = copy.deepcopy(payload.payload)
    written["core"]["updated"] = LANDED_STAMP
    if rating is not None:
        user_fields(written)["rating"] = rating
    return SaveOutcome(written, LANDED_VERSION, signature, users_merged=rating is not None)


def handed_over(model: RehuDocumentModel) -> SavePayload:
    """Take a snapshot of ``model`` and hand it to a save, as the window's save jobs do.

    :param model: the document.
    :returns: the snapshot.
    """
    payload = model.snapshot()
    model.begin_save()
    return payload


def read(path: Path) -> LoadedRecord:
    """The record as a holder reads it now.

    :param path: the record.
    :returns: the reading.
    """
    return Records().load(
        ResourceKey(path), username=DEFAULT_CURRENT_USERNAME, unknown_username=DEFAULT_UNKNOWN_USERNAME
    )


def opened_with_pending_saves(
    path: Path, pending_save_of: Callable[[ResourceKey], SavePayload | None]
) -> RehuDocumentModel:
    """The model a holder builds for ``path``, as :func:`opened` does, told where the record's pending save is found.

    :param path: the record.
    :param pending_save_of: the record's save not landed yet, as the window's save owner answers it.
    :returns: the model.
    """
    records = Records()
    record = records.load(
        ResourceKey(path), username=DEFAULT_CURRENT_USERNAME, unknown_username=DEFAULT_UNKNOWN_USERNAME
    )
    return RehuDocumentModel(
        record.document,
        records=records,
        version=record.version,
        signature=record.signature,
        pending_save_of=pending_save_of,
    )


def counted(signal: Any) -> list[object]:
    """Count the emissions of a signal taking no arguments.

    :param signal: the signal.
    :returns: the list each emission appends to.
    """
    heard: list[object] = []
    signal.connect(lambda: heard.append(None))
    return heard


# region snapshot
def test_a_snapshot_is_a_deep_copy_of_what_a_save_writes(tmp_path: Path) -> None:
    """The snapshot carries the payload, what it was read at and whose it is -- copied, so editing goes on while it is
    written.

    **Test steps:**

    * open a rated record and edit its title
    * take a snapshot
    * verify it holds the payload a save writes, the base it is checked against, the user and the junk globs
    * edit the document again and scribble on the snapshot's payload
    * verify neither reached the other
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)
    model = opened(path)
    model.title = "Mine"

    payload = model.snapshot()

    assert payload.path == path
    assert payload.username == DEFAULT_CURRENT_USERNAME
    assert payload.payload == model.document.payload_to_write()
    assert payload.base == model.base_version
    assert payload.base is not None
    assert payload.base_payload == model.base_data()
    assert not payload.first_save
    assert not payload.discarded
    assert payload.excluded_patterns == shared_excluded_files_settings().excluded_file_patterns
    model.title = "Later"
    user_fields(payload.payload)["rating"] = 9
    assert payload.payload["core"]["sources"][0]["title"] == "Mine"
    assert model.rating == 1


def test_a_snapshot_of_a_new_document_is_a_first_save_with_no_base(tmp_path: Path) -> None:
    """A document never read from its file has nothing a save is checked against, and its save takes its checksums.

    **Test steps:**

    * start a new document bound to a path under ``tmp_path``
    * take a snapshot
    * verify it is a first save, with no base and no base payload
    """
    payload = RehuDocumentModel.create_new(tmp_path / "info.rehu").snapshot()

    assert payload.first_save
    assert payload.base is None
    assert payload.base_payload is None


def test_a_snapshot_names_the_blocks_the_save_drops(tmp_path: Path) -> None:
    """A block claimed and abandoned is dropped by the save, which logs it once it lands (#86).

    **Test steps:**

    * open a tutorial holding a foreign ``reference_images`` block, switch to that type and back
    * take a snapshot
    * verify it names that block as dropped and as discarded, and leaves it out of the payload
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    edit_on_disk(path, lambda document: document.data.update(reference_images={"format_version": 1}))
    model = opened(path)
    model.document.set_active_type("reference_images")
    model.document.set_active_type(TYPE)

    payload = model.snapshot()

    assert payload.dropped == ("reference_images",)
    assert payload.discarded == ("reference_images",)
    assert "reference_images" not in payload.payload


def locked_against_saving(tmp_path: Path) -> RehuDocumentModel:
    """A model over a record whose ``authors`` cannot be read, which a save would overwrite.

    :param tmp_path: where the record is written.
    :returns: the model.
    """
    path = tmp_path / "info.rehu"
    path.write_text(f'{{"{FORMAT_VERSION_KEY}": 1, "type": "Tutorial", "authors": 42}}', encoding="utf-8")
    return RehuDocumentModel(RehuDocument.load(path))


@mark.parametrize(
    ("build", "message"),
    [
        param(lambda _tmp_path: RehuDocumentModel.create_new(None), "No path given", id="no-path"),
        param(
            lambda tmp_path: RehuDocumentModel(
                RehuDocument({"type": "Tutorial"}, tmp_path / "info.tc", legacy_tc=True)
            ),
            "legacy record",
            id="legacy-tc",
        ),
        param(locked_against_saving, "locked document", id="locked"),
    ],
)
def test_a_snapshot_is_refused_for_a_document_no_save_may_write(
    tmp_path: Path, build: Callable[[Path], RehuDocumentModel], message: str
) -> None:
    """A document with nowhere to go, a legacy ``.tc`` and one locked against saving are never handed to a save.

    **Test steps:**

    * build the document
    * verify a snapshot raises ``ValueError`` saying why
    """
    model = build(tmp_path)

    with raises(ValueError, match=message):
        model.snapshot()


# endregion


# region complete_save
def test_a_landed_save_merges_back_what_it_changed_and_leaves_the_document_clean(tmp_path: Path) -> None:
    """With nothing edited while it ran, what the save changed on its way to disk -- the stamp, a rating merged from
    the file -- is the document's now, and the next save is checked against what it wrote.

    **Test steps:**

    * open a record rated 1, edit its title, hand it to a save, and say something is gone
    * verify handing it over left the document saving and clean: the save is its saved state now
    * land the save with a new stamp and the file's rating of 3 merged in
    * verify the model shows the rating and the stamp, keeps the title, is clean and no longer saving, and nothing is
      gone
    * verify the save's version, signature and written payload are what the next save is checked against
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)
    model = opened(path)
    model.title = "Mine"
    payload = handed_over(model)
    assert (model.saving, model.dirty) == (True, False)
    model.gone = "said before"
    outcome = landed(payload, rating=3, signature=LANDED_SIGNATURE)

    model.complete_save(payload, outcome)

    assert (model.title, model.rating) == ("Mine", 3)
    assert model.document.data["core"]["updated"] == LANDED_STAMP
    assert not model.dirty
    assert not model.saving
    assert model.base_version is LANDED_VERSION
    assert model.base_data() == outcome.written
    assert (model.conflict, model.changed_on_disk, model.gone) == (None, False, "")
    assert model.saved_on_disk
    model.note_file_signature(*LANDED_SIGNATURE)
    assert not model.changed_on_disk


def test_an_edit_made_while_the_save_ran_wins_over_what_it_merged_and_keeps_the_document_dirty(tmp_path: Path) -> None:
    """The user edited after the snapshot: that edit stands over what the save brought back, everything else the save
    changed is taken, and the document is still dirty, for its next save.

    **Test steps:**

    * open a record rated 1, edit its title, and hand it to a save
    * meanwhile rate it 5 and retitle it again
    * land the save with a new stamp and the file's rating of 3 merged in
    * verify the model keeps the rating of 5 and the later title, takes the stamp, and is dirty
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old", rating=1)
    model = opened(path)
    model.title = "Mine"
    payload = handed_over(model)
    model.rating = 5
    model.title = "Later"

    model.complete_save(payload, landed(payload, rating=3, signature=LANDED_SIGNATURE))

    assert (model.title, model.rating) == ("Later", 5)
    assert model.document.data["core"]["updated"] == LANDED_STAMP
    assert model.dirty
    assert not model.saving
    assert model.base_version is LANDED_VERSION


@mark.parametrize("edited_again", [False, True], ids=["nothing-since", "edited-since"])
def test_a_landed_save_with_a_later_one_pending_judges_dirty_against_the_later_one(
    tmp_path: Path, edited_again: bool
) -> None:
    """A later Save handed over while the first was writing is the saved state now: the first landing leaves the
    document dirty only when it was edited after that later Save, not merely since the first.

    **Test steps:**

    * open a record, edit its title and hand it to a save, then retitle it and hand that over too
    * edit it once more, or not
    * land the first save, naming the later one, moved onto what the first wrote, as still pending
    * verify the model keeps the later title, takes the first save's stamp, and is dirty only when edited since
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    first = handed_over(model)
    model.title = "Later"
    later = handed_over(model)
    if edited_again:
        model.rating = 5
    outcome = landed(first, signature=LANDED_SIGNATURE)

    model.complete_save(first, outcome, latest=rebase_payload(later, first, outcome))

    assert model.title == "Later"
    assert model.document.data["core"]["updated"] == LANDED_STAMP
    assert model.dirty is edited_again


def test_a_new_documents_landed_save_marks_it_saved_on_disk(tmp_path: Path) -> None:
    """A document's first save that landed leaves a file to revert to (#147).

    **Test steps:**

    * start a new document under ``tmp_path``, and hand it to a save
    * land the save as written
    * verify the model is saved on disk and clean
    """
    model = RehuDocumentModel.create_new(tmp_path / "info.rehu")
    payload = handed_over(model)

    model.complete_save(payload, SaveOutcome(copy.deepcopy(payload.payload), LANDED_VERSION, None, False))

    assert model.saved_on_disk
    assert not model.dirty


def test_a_save_landing_on_a_document_reverted_meanwhile_merges_into_the_save_it_went_back_to(tmp_path: Path) -> None:
    """A revert while the save ran goes back to that save, the record's saved state: the save landing then merges what
    it changed into it, and the document is clean, checked against what the save wrote.

    **Test steps:**

    * open a record whose pending save is the one handed over, edit its title, and hand it to a save
    * edit it again, and revert it
    * verify the revert went back to the save's title, clean
    * land the save
    * verify the model keeps that title, takes the save's stamp, is clean and not saving, and is checked against what
      the save wrote
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    handed: list[SavePayload] = []
    model = opened_with_pending_saves(path, lambda _key: handed[0])
    model.title = "Mine"
    payload = handed_over(model)
    handed.append(payload)
    model.title = "Later"
    model.revert()
    assert (model.title, model.dirty) == ("Mine", False)

    model.complete_save(payload, landed(payload, signature=LANDED_SIGNATURE))

    assert model.title == "Mine"
    assert model.document.data["core"]["updated"] == LANDED_STAMP
    assert not model.dirty
    assert not model.saving
    assert model.base_version is LANDED_VERSION


def test_a_stat_heard_while_saving_waits_and_is_dropped_when_it_was_the_saves_own(tmp_path: Path) -> None:
    """The file's signature heard while a save is out may be the save's own write: it is not judged until the save is
    back, and then it is the written file's signature, so nothing changed on disk.

    **Test steps:**

    * open a record and edit its title, and hand it to a save
    * report the file with the signature the save will say it wrote
    * verify the dirty model was not told the file changed
    * land the save as written, edited again meanwhile
    * verify the model is still not told the file changed
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    payload = handed_over(model)

    model.note_file_signature(*LANDED_SIGNATURE)
    assert not model.changed_on_disk
    model.title = "Later"

    model.complete_save(payload, SaveOutcome(copy.deepcopy(payload.payload), LANDED_VERSION, LANDED_SIGNATURE, False))

    assert not model.changed_on_disk
    assert model.dirty
    assert model.title == "Later"


def test_a_stat_heard_while_saving_is_judged_once_the_save_lands(tmp_path: Path) -> None:
    """Another writer changed the file after the save wrote it: the signature heard meanwhile is not the save's, so it
    is judged once the save is back -- and the clean document follows the file.

    **Test steps:**

    * open a record and edit its title, and hand it to a save
    * retitle the file outside the app, and report it
    * land the save, which says it wrote another signature
    * verify the clean model reloaded the other writer's title
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    payload = handed_over(model)
    edit_on_disk(path, retitle("Theirs, written after the save"))
    model.note_file_signature(*on_disk(path))
    reloads = counted(model.reloaded)
    assert not reloads

    model.complete_save(payload, landed(payload, signature=LANDED_SIGNATURE))

    assert reloads
    assert model.title == "Theirs, written after the save"
    assert not model.dirty


# endregion


# region fail_save
def test_a_failed_save_keeps_the_edits_and_the_conflict(tmp_path: Path) -> None:
    """A save refused as a conflict leaves the document as it was -- clean, since the failed save is still the saved
    state -- holding the refusal for the banner and the dialog.

    **Test steps:**

    * open a record, edit its title, and hand it to a save
    * fail the save with a conflict
    * verify the model is no longer saving, keeps its edit, clean, and holds that conflict, and nothing is gone
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    handed_over(model)
    conflict = RecordConflict(stored(path), LANDED_VERSION)

    model.fail_save(conflict)

    assert not model.saving
    assert model.conflict is conflict
    assert (model.title, model.dirty, model.gone) == ("Mine", False, "")


@mark.parametrize("gone", ["The file is gone: somewhere", None], ids=["gone", "nothing-said"])
def test_a_failed_save_says_what_is_gone(tmp_path: Path, gone: str | None) -> None:
    """A save whose file or folder went says so; one that failed otherwise says nothing more.

    **Test steps:**

    * open a record, edit its title, and hand it to a save
    * fail the save, naming what is gone or not
    * verify the model is no longer saving, holds no conflict, and says what is gone -- or nothing
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    handed_over(model)

    model.fail_save(None, gone=gone)

    assert not model.saving
    assert model.conflict is None
    assert model.gone == (gone or "")


def test_a_stat_heard_while_saving_is_judged_once_the_save_fails(tmp_path: Path) -> None:
    """A save that did not land wrote nothing, so a change heard meanwhile is someone else's: once the save is back,
    the document edited since is told the file changed.

    **Test steps:**

    * open a record, edit its title, hand it to a save, and edit it again
    * retitle the file outside the app, and report it
    * verify the model was not told yet
    * fail the save
    * verify the model now says the file changed on disk, and keeps its later edit
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    handed_over(model)
    model.title = "Later"
    edit_on_disk(path, retitle("Theirs"))
    model.note_file_signature(*on_disk(path))
    assert not model.changed_on_disk

    model.fail_save(None)

    assert model.changed_on_disk
    assert model.title == "Later"


# endregion


# region save() inline
def test_an_inline_save_waiting_for_its_share_fails_as_an_os_error(mocker: MockerFixture, tmp_path: Path) -> None:
    """A save made here must have the file written now; one that would wait for its share or a lock fails instead,
    saying what it waits for, and the document keeps its edits.

    **Test steps:**

    * open a record and edit its title, with the save job's write waiting for its share
    * save inline
    * verify an ``OSError`` carrying the wait's reason was raised, from the wait
    * verify the model is no longer saving, still dirty, and holds no conflict
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    waiting = JobWaiting("Waiting for the share: nas", 30.0)
    mocker.patch.object(SaveRecordJob, "write", side_effect=waiting)

    with raises(OSError, match="Waiting for the share: nas") as failed:
        model.save()

    assert failed.value.__cause__ is waiting
    assert not model.saving
    assert model.dirty
    assert model.conflict is None


def test_an_inline_save_of_a_record_whose_folder_went_says_it_is_gone(tmp_path: Path) -> None:
    """A save never recreates a folder: the record's folder deleted from under it fails the save, and the banner's
    sentence names it.

    **Test steps:**

    * open a folder's record and edit its title, then delete the folder
    * save inline
    * verify a ``FileNotFoundError`` was raised, the model says the folder is gone, and nothing was recreated
    * verify the model is dirty again: no job holds the edits the save did not land
    """
    folder = tmp_path / "sculpting"
    folder.mkdir()
    path = folder / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    shutil.rmtree(folder)

    with raises(FileNotFoundError):
        model.save()

    assert model.gone == f"The resource's folder is gone: {folder}"
    assert not model.saving
    assert not folder.exists()
    assert model.dirty


# endregion


# region resolve_conflict
def test_resolving_a_conflict_writes_nothing_and_leaves_the_save_to_the_caller(tmp_path: Path) -> None:
    """The picks are taken into the document, ready to be saved again; the file is not touched until that save.

    **Test steps:**

    * bring a model into conflict over its title
    * resolve it keeping this document's title
    * verify the file still holds the other title, and the model holds its own, dirty, with no conflict or notice
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model, _ = in_conflict(path, "Mine", "Theirs")

    model.resolve_conflict({})

    assert stored(path).title == "Theirs"
    assert (model.title, model.dirty, model.conflict, model.changed_on_disk) == ("Mine", True, None, False)


# endregion


# region note_file_gone
def test_a_clean_saved_document_whose_file_went_reverts_to_the_missing_stub(tmp_path: Path) -> None:
    """With no edits to keep, a file gone is heard as any change is: the document reads it again, and becomes the
    locked *missing* stub a reopen would make.

    **Test steps:**

    * open a record, then delete its file
    * hear that it is gone, its folder still there
    * verify the model reloaded, is locked as missing, and says nothing is gone
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    reloads = counted(model.reloaded)
    path.unlink()

    model.note_file_gone(folder_gone=False)

    assert reloads
    assert [reason.kind for reason in model.lock_reasons] == [LockReasonKind.MISSING]
    assert model.gone == ""


@mark.parametrize("folder_gone", [False, True], ids=["file", "folder"])
def test_a_dirty_saved_document_whose_file_went_keeps_its_edits_and_says_what_is_gone(
    tmp_path: Path, folder_gone: bool
) -> None:
    """Edits are never thrown away by a file going: they are kept, and the banner's sentence names the file -- or the
    folder, when that went too.

    **Test steps:**

    * open a record and edit its title
    * hear that its file is gone, with its folder or without
    * verify the model keeps its edit, did not reload, and names what is gone
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    reloads = counted(model.reloaded)

    model.note_file_gone(folder_gone=folder_gone)

    assert not reloads
    assert (model.title, model.dirty) == ("Mine", True)
    assert model.gone == (f"The resource's folder is gone: {tmp_path}" if folder_gone else f"The file is gone: {path}")


@mark.parametrize("folder_gone", [True, False], ids=["folder-gone", "file-not-written-yet"])
def test_a_never_saved_document_hears_only_its_folder_going(tmp_path: Path, folder_gone: bool) -> None:
    """A document never saved has no file to lose: only its folder going is news, and a file simply not written yet
    leaves nothing said.

    **Test steps:**

    * start a new document under a folder of ``tmp_path``, saying something is gone
    * hear that its file is not there, with its folder or without
    * verify the model names the folder when it went, says nothing otherwise, and is still dirty
    """
    path = tmp_path / "sculpting" / "info.rehu"
    model = RehuDocumentModel.create_new(path)
    model.gone = "said before"

    model.note_file_gone(folder_gone=folder_gone)

    assert model.gone == (f"The resource's folder is gone: {path.parent}" if folder_gone else "")
    assert model.dirty


def saving_model(tmp_path: Path) -> RehuDocumentModel:
    """A record's model with an edit whose save is out.

    :param tmp_path: where the record is written.
    :returns: the model.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    handed_over(model)
    return model


@mark.parametrize(
    "build",
    [
        param(saving_model, id="saving"),
        param(lambda tmp_path: RehuDocumentModel.create_pending(tmp_path / "info.rehu"), id="pending"),
        param(
            lambda tmp_path: RehuDocumentModel(
                RehuDocument({FORMAT_VERSION_KEY: CURRENT_FORMAT_VERSION + 1}, tmp_path / "info.rehu")
            ),
            id="locked",
        ),
        param(lambda _tmp_path: RehuDocumentModel.create_new(None), id="no-path"),
    ],
)
def test_a_file_gone_is_not_heard_by_a_document_with_nothing_to_hear_it(
    tmp_path: Path, build: Callable[[Path], RehuDocumentModel]
) -> None:
    """A document whose save is out hears the save's own answer instead; a placeholder not read yet, a locked document
    and one with no path have no file this news could be about.

    **Test steps:**

    * build the document
    * hear that its file is gone, folder and all
    * verify nothing is said gone and the document was not read again
    """
    model = build(tmp_path)
    reloads = counted(model.reloaded)

    model.note_file_gone(folder_gone=True)

    assert model.gone == ""
    assert not reloads


def test_a_stat_of_the_file_says_it_is_back(tmp_path: Path) -> None:
    """A file heard again is there: whatever was said gone is withdrawn, and the change-on-disk rule decides the rest.

    **Test steps:**

    * open a record, edit its title, and hear its file gone
    * report the file as it is
    * verify nothing is said gone any more, and nothing changed on disk
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    model.note_file_gone(folder_gone=False)
    assert model.gone

    model.note_file_signature(*on_disk(path))

    assert model.gone == ""
    assert not model.changed_on_disk


def test_a_stat_heard_while_saving_says_what_was_gone_is_back_and_waits_for_the_save(tmp_path: Path) -> None:
    """A stat heard while a save is out waits for the save to be judged -- but a file that stats is there, so the gone
    notice goes at once, and Save is offered again on a record put back.

    **Test steps:**

    * open a record, edit its title, hear its file gone, and hand it to a save
    * report the file as it is
    * verify the notice is gone, and the stat waits: the model says nothing of a change on disk
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened(path)
    model.title = "Mine"
    model.note_file_gone(folder_gone=False)
    handed_over(model)

    model.note_file_signature(*on_disk(path))

    assert model.gone == ""
    assert model.changed_on_disk is False


# endregion


# region adopt_unsaved
def edited_snapshot(path: Path) -> SavePayload:
    """The snapshot of a reading of ``path`` whose title was edited to ``Mine``: edits kept elsewhere.

    :param path: the record.
    :returns: the snapshot.
    """
    source = opened(path)
    source.title = "Mine"
    return source.snapshot()


def test_adopted_edits_are_shown_unsaved_over_the_file_they_were_made_against(tmp_path: Path) -> None:
    """Edits kept across a quit are shown as the user left them -- dirty, based on what they were read at -- in place
    of what the model showed, and no form is rebuilt for a record of the same shape.

    **Test steps:**

    * keep the edits of a reading of a record, and open the record again, saying something was gone
    * adopt the kept edits, with the record as it is now
    * verify the model shows them, dirty, saved on disk, not changed on disk, and nothing gone
    * verify it is based on the kept edits' base, was announced as read again once, and kept its form
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    payload = edited_snapshot(path)
    model = opened(path)
    model.gone = "said before"
    reloads = counted(model.reloaded)
    rebuilds = counted(model.active_block_changed)

    model.adopt_unsaved(payload, read(path))

    assert (model.title, model.dirty, model.saved_on_disk) == ("Mine", True, True)
    assert (model.changed_on_disk, model.conflict, model.gone) == (False, None, "")
    assert model.base_version == payload.base
    assert model.base_data() == payload.base_payload
    assert len(reloads) == 1
    assert not rebuilds


def test_adopted_edits_over_a_file_changed_since_say_so(tmp_path: Path) -> None:
    """The file moved on after the edits were kept: the model says the file changed on disk, so the next save shows
    the differences first.

    **Test steps:**

    * keep the edits of a reading of a record, then retitle the file outside the app
    * adopt the kept edits into a fresh reading, with the record as it is now
    * verify the model shows the edits and says the file changed on disk
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    payload = edited_snapshot(path)
    edit_on_disk(path, retitle("Theirs"))
    model = opened(path)

    model.adopt_unsaved(payload, read(path))

    assert model.title == "Mine"
    assert model.changed_on_disk


@mark.parametrize("appeared", [True, False], ids=["file-appeared", "still-no-file"])
def test_adopted_edits_of_a_never_saved_record_say_whether_a_file_appeared(tmp_path: Path, appeared: bool) -> None:
    """A record never saved has nothing its edits were made against: a file written there meanwhile is a change on
    disk, and no file is none.

    **Test steps:**

    * keep the edits of a new document, and write a record at its path or not
    * adopt the kept edits into another new document there, with the record as it is now, or none
    * verify the model is dirty, never saved on disk, based on nothing, and says the file changed only when one appeared
    """
    path = tmp_path / "info.rehu"
    source = RehuDocumentModel.create_new(path)
    source.title = "Mine"
    payload = source.snapshot()
    if appeared:
        write_record(path, "Theirs")
    model = RehuDocumentModel.create_new(path)

    model.adopt_unsaved(payload, read(path) if appeared else None)

    assert (model.title, model.dirty, model.saved_on_disk) == ("Mine", True, False)
    assert model.base_version is None
    assert model.base_data() == {}
    assert model.changed_on_disk is appeared


def test_adopted_edits_rebuild_a_placeholders_form(tmp_path: Path) -> None:
    """A placeholder's form was built for a document not read yet (#66), so adopting edits into it rebuilds it --
    even when the record has the shape the placeholder's form was built for -- and the model is no longer pending.

    **Test steps:**

    * keep the edits of a reading of an untyped record, the shape of a placeholder's form, and build a placeholder
      for it
    * adopt the kept edits, with the record as it is now
    * verify the form was rebuilt, the model is not pending, and it shows the edits
    """
    path = tmp_path / "info.rehu"
    untyped = RehuDocument.new(path)
    untyped.title = "Old"
    untyped.save()
    payload = edited_snapshot(path)
    model = RehuDocumentModel.create_pending(path)
    rebuilds = counted(model.active_block_changed)

    model.adopt_unsaved(payload, read(path))

    assert rebuilds
    assert not model.pending
    assert model.title == "Mine"


# endregion
