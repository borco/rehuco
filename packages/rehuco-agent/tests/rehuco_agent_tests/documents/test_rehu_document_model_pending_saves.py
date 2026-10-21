"""Tests for a document model whose record has a save that has not landed (#497, [[sync#unlanded-save]]): that save is
the record's saved state on this machine, so reverting, loading and opening go back to it, a file changed or gone
meanwhile is left for the save to judge, and edits kept elsewhere are shown over it without a word of their own.

Real records under ``tmp_path``, as in ``test_rehu_document_model_saves``; the record's pending save is what the
model's ``pending_save_of`` answers, as the window's save owner would.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Final
from unittest.mock import Mock

from pytest import LogCaptureFixture, mark, param
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RecordConflict, SavePayload
from rehuco_core.access import ResourceKey

from .test_rehu_document_model_conflict import edit_on_disk, on_disk, opened, retitle, stored, write_record
from .test_rehu_document_model_saves import (
    LANDED_SIGNATURE,
    LANDED_VERSION,
    counted,
    edited_snapshot,
    handed_over,
    landed,
    opened_with_pending_saves,
    read,
)

pytestmark = mark.usefixtures("real_path_stat")

MODEL_LOGGER: Final = "rehuco_agent.documents.rehu_document_model"
"""The logger the model writes its records to."""


def answering(payload: SavePayload, path: Path) -> Callable[[ResourceKey], SavePayload | None]:
    """A save owner's answer naming ``payload`` as the pending save of the record at ``path``, and none for others.

    :param payload: the pending save.
    :param path: its record.
    :returns: the answer.
    """
    key = ResourceKey(path)

    def pending_save_of(asked: ResourceKey) -> SavePayload | None:
        """The pending save of ``asked``.

        :param asked: the record asked about.
        :returns: ``payload`` for its record, else ``None``.
        """
        return payload if asked == key else None

    return pending_save_of


def with_pending_save(tmp_path: Path) -> tuple[Path, SavePayload, RehuDocumentModel]:
    """A record titled ``Old`` whose pending save titles it ``Mine``, and a model opened over it as a holder builds it.

    :param tmp_path: where the record is written.
    :returns: the record, its pending save, and the model, still showing the file.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    payload = edited_snapshot(path)
    return path, payload, opened_with_pending_saves(path, answering(payload, path))


# region revert, load, load_pending
def test_a_revert_goes_back_to_the_records_pending_save_and_says_so(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """A save not landed is the saved state: Revert drops the edits made since and shows that save, clean, based on
    what it was read at -- not the file.

    **Test steps:**

    * open a record whose pending save titles it ``Mine``, and retitle the document
    * revert it
    * verify the save owner was asked about the record, and the model shows the pending save, clean, saved on disk
      and based on what the save was read at
    * verify the log says the revert went back to the save not landed
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    payload = edited_snapshot(path)
    pending_save_of = Mock(return_value=payload)
    model = opened_with_pending_saves(path, pending_save_of)
    model.title = "Later"

    with caplog.at_level(logging.INFO, logger=MODEL_LOGGER):
        model.revert()

    pending_save_of.assert_called_with(ResourceKey(path))
    assert (model.title, model.dirty, model.saved_on_disk) == ("Mine", False, True)
    assert model.base_version == payload.base
    assert model.base_data() == payload.base_payload
    assert f"Reverted {path} to its save not landed yet" in caplog.messages


def test_a_revert_with_no_pending_save_goes_back_to_the_file_and_says_so(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """With no save pending, Revert reads the file, as it always did.

    **Test steps:**

    * open a record whose save owner knows no pending save of it, and retitle the document
    * revert it
    * verify the model shows the file's title, clean, and the log says the revert went back to what is on disk
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    model = opened_with_pending_saves(path, lambda _key: None)
    model.title = "Later"

    with caplog.at_level(logging.INFO, logger=MODEL_LOGGER):
        model.revert()

    assert (model.title, model.dirty) == ("Old", False)
    assert f"Reverted {path} to what is on disk" in caplog.messages


def test_loading_a_record_with_a_pending_save_shows_that_save(tmp_path: Path) -> None:
    """A preview moving on to a record whose save has not landed shows the save, clean, as every open of it does.

    **Test steps:**

    * write two records, the second with a pending save titling it ``Mine``, and open the first
    * load the second in place
    * verify the model is bound to the second, shows the pending save, clean, and announced the switch once
    """
    first = tmp_path / "first.rehu"
    second = tmp_path / "second.rehu"
    write_record(first, "First")
    write_record(second, "Old")
    payload = edited_snapshot(second)
    model = opened_with_pending_saves(first, answering(payload, second))
    switches = counted(model.switched)

    model.load(second)

    assert model.path == second
    assert (model.title, model.dirty) == ("Mine", False)
    assert len(switches) == 1


def test_a_placeholder_with_a_pending_save_loads_that_save(tmp_path: Path) -> None:
    """A restored session's placeholder read at last shows its record's save not landed, form and all.

    **Test steps:**

    * write a record whose pending save titles it ``Mine``, and build a placeholder for it
    * load the placeholder
    * verify the form was rebuilt, the model is not pending, and it shows the pending save, clean
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    payload = edited_snapshot(path)
    model = RehuDocumentModel.create_pending(path, pending_save_of=answering(payload, path))
    rebuilds = counted(model.active_block_changed)

    model.load_pending()

    assert rebuilds
    assert not model.pending
    assert (model.title, model.dirty) == ("Mine", False)


# endregion


# region follow_pending_save
def test_a_clean_document_follows_its_records_pending_save(tmp_path: Path) -> None:
    """A document just opened over a record whose save has not landed shows that save, clean.

    **Test steps:**

    * open a record whose pending save titles it ``Mine``
    * follow the pending save
    * verify the model shows it, clean, and was announced as read again
    """
    _path, _payload, model = with_pending_save(tmp_path)
    reloads = counted(model.reloaded)

    model.follow_pending_save()

    assert (model.title, model.dirty) == ("Mine", False)
    assert reloads


def test_a_never_saved_document_follows_its_records_pending_save(tmp_path: Path) -> None:
    """A new document starts dirty but holds no edits of its own yet: its record's first save not landed is what it
    shows, clean and still never saved on disk.

    **Test steps:**

    * keep a new document's first save titling it ``Mine``, and start another new document at its path
    * follow the pending save
    * verify the model shows it, clean, and not saved on disk
    """
    path = tmp_path / "info.rehu"
    source = RehuDocumentModel.create_new(path)
    source.title = "Mine"
    payload = source.snapshot()
    model = RehuDocumentModel.create_new(path, pending_save_of=answering(payload, path))
    assert model.dirty

    model.follow_pending_save()

    assert (model.title, model.dirty, model.saved_on_disk) == ("Mine", False, False)


def own_edits(tmp_path: Path) -> RehuDocumentModel:
    """A saved record's model, with a pending save, holding edits of its own.

    :param tmp_path: where the record is written.
    :returns: the model, retitled ``Later``.
    """
    _path, _payload, model = with_pending_save(tmp_path)
    model.title = "Later"
    return model


def placeholder(tmp_path: Path) -> RehuDocumentModel:
    """A placeholder, not read yet, for a record with a pending save.

    :param tmp_path: where the record is written.
    :returns: the placeholder.
    """
    path, payload, _model = with_pending_save(tmp_path)
    return RehuDocumentModel.create_pending(path, pending_save_of=answering(payload, path))


def no_pending_save(tmp_path: Path) -> RehuDocumentModel:
    """A record's model whose save owner knows no pending save of it.

    :param tmp_path: where the record is written.
    :returns: the model.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    return opened_with_pending_saves(path, lambda _key: None)


def no_path(_tmp_path: Path) -> RehuDocumentModel:
    """A new document with no path, whose save owner would answer a pending save for anything asked.

    :param _tmp_path: unused.
    :returns: the model.
    """
    payload = Mock(spec=SavePayload)
    return RehuDocumentModel.create_new(None, pending_save_of=lambda _key: payload)


@mark.parametrize(
    "build",
    [
        param(own_edits, id="own-edits"),
        param(placeholder, id="placeholder"),
        param(no_pending_save, id="no-pending-save"),
        param(no_path, id="no-path"),
    ],
)
def test_a_document_with_nothing_to_follow_keeps_what_it_shows(
    tmp_path: Path, build: Callable[[Path], RehuDocumentModel]
) -> None:
    """Edits of the document's own win over the pending save; a placeholder not read yet, a record with no save pending
    and a document with no path have nothing to follow.

    **Test steps:**

    * build the document
    * follow the pending save
    * verify the model shows what it showed, as dirty and as pending as it was, and was not read again
    """
    model = build(tmp_path)
    before = (model.title, model.dirty, model.pending)
    reloads = counted(model.reloaded)

    model.follow_pending_save()

    assert (model.title, model.dirty, model.pending) == before
    assert not reloads


# endregion


# region adopt_unsaved
def test_a_pending_save_adopted_keeps_what_its_failure_said_and_never_says_the_file_changed(tmp_path: Path) -> None:
    """A pending save is the save's own to judge: shown over a file changed since it was read, it keeps the conflict
    and the gone notice its failure raised, and says nothing of its own about the file.

    **Test steps:**

    * keep a pending save of a record, retitle the file outside the app, and open the record, holding a conflict and
      a gone notice
    * adopt the pending save, clean, with the record as it is now
    * verify the model shows it, clean, keeps the conflict and the notice, and does not say the file changed on disk
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    payload = edited_snapshot(path)
    edit_on_disk(path, retitle("Theirs"))
    model = opened(path)
    conflict = RecordConflict(stored(path), LANDED_VERSION)
    model.conflict = conflict
    model.gone = "said before"

    model.adopt_unsaved(payload, read(path), dirty=False)

    assert (model.title, model.dirty) == ("Mine", False)
    assert model.conflict is conflict
    assert model.gone == "said before"
    assert not model.changed_on_disk


@mark.parametrize("moved", [True, False], ids=["other-path", "same-path"])
def test_adopting_edits_of_another_path_announces_the_switch(tmp_path: Path, moved: bool) -> None:
    """Edits kept for another record bind the model to it, which is a switch like any other load's; the same record's
    are not.

    **Test steps:**

    * write two records, keep edits of the second or of the first, and open the first
    * adopt the kept edits
    * verify the model is bound to their record, and announced a switch only when that is another one
    """
    first = tmp_path / "first.rehu"
    second = tmp_path / "second.rehu"
    write_record(first, "First")
    write_record(second, "Second")
    kept = second if moved else first
    payload = edited_snapshot(kept)
    model = opened(first)
    switches = counted(model.switched)

    model.adopt_unsaved(payload, read(kept))

    assert model.path == kept
    assert len(switches) == (1 if moved else 0)


# endregion


# region note_file_signature, note_file_gone
def test_a_change_on_disk_heard_while_a_save_is_pending_is_left_to_the_save(tmp_path: Path) -> None:
    """While a save has not landed, a change on disk reloads nothing, and the document says nothing of it: the save's
    own check finds it when it runs.

    **Test steps:**

    * open a clean record with a pending save, no save running
    * retitle the file outside the app, and report it
    * verify the model was not read again, keeps its title, and does not say the file changed on disk
    """
    path, _payload, model = with_pending_save(tmp_path)
    reloads = counted(model.reloaded)
    edit_on_disk(path, retitle("Theirs"))

    model.note_file_signature(*on_disk(path))

    assert not reloads
    assert model.title == "Old"
    assert not model.changed_on_disk


def test_a_stat_heard_while_a_save_is_pending_still_says_what_was_gone_is_back(tmp_path: Path) -> None:
    """A file that stats is there: the *gone* notice goes even while the stat itself waits for the pending save to be
    judged, so Save is offered again on a record put back, and tries the save.

    **Test steps:**

    * open a record with a pending save, and have its file reported gone
    * hear a stat of the file
    * verify the notice is gone, and the stat waits: the document says nothing of a change on disk
    """
    path, _, model = with_pending_save(tmp_path)
    model.gone = f"The file is gone: {path}"
    signature = read(path).signature
    assert signature is not None

    model.note_file_signature(*signature)

    assert model.gone == ""
    assert model.changed_on_disk is False


def test_a_rename_is_refused_while_the_records_save_has_not_landed(tmp_path: Path) -> None:
    """A rename writes the record before moving it; with a save of it pending, that write would run ahead of the save
    and the two would conflict -- so the rename is refused, and says to wait or discard.

    **Test steps:**

    * open a file-scoped record with a pending save
    * rename it
    * verify the rename was refused, the reason names the save not landed, and the file was not moved
    """
    path = tmp_path / "foo.rehu"
    write_record(path, "Old")
    payload = edited_snapshot(path)
    model = opened_with_pending_saves(path, answering(payload, path))

    renamed = model.rename_location("bar")

    assert renamed is False
    assert "has not landed yet" in model.rename_error
    assert path.exists() and not (tmp_path / "bar.rehu").exists()


def test_a_stat_deferred_by_a_pending_save_is_judged_once_no_save_is_pending(tmp_path: Path) -> None:
    """A stat heard while a save is pending waits for it: a save coming back while another is still pending defers it
    again, and once none is, it is judged -- the clean document follows the file.

    **Test steps:**

    * open a record whose save owner names a pending save, hand the document to a save, and report another writer's
      change to the file
    * land the save while a save is still pending
    * verify the model was not read again
    * let no save be pending, and fail a save of it
    * verify the model was read again, and shows the other writer's title
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    pending: list[SavePayload] = []
    model = opened_with_pending_saves(path, lambda _key: pending[0] if pending else None)
    model.title = "Mine"
    payload = handed_over(model)
    pending.append(payload)
    edit_on_disk(path, retitle("Theirs"))
    model.note_file_signature(*on_disk(path))
    reloads = counted(model.reloaded)

    model.complete_save(payload, landed(payload, signature=LANDED_SIGNATURE))
    assert not reloads

    pending.clear()
    model.fail_save(None)

    assert reloads
    assert model.title == "Theirs"


@mark.parametrize("folder_gone", [False, True], ids=["file", "folder"])
def test_a_clean_document_with_a_pending_save_whose_file_went_keeps_it_and_says_what_is_gone(
    tmp_path: Path, folder_gone: bool
) -> None:
    """A save not landed is the record here: its file going reverts nothing, and the banner's sentence names the file --
    or the folder, when that went too.

    **Test steps:**

    * open a clean record with a pending save, and follow it
    * hear that its file is gone, with its folder or without
    * verify the model was not read again, still shows the pending save, clean, and names what is gone
    """
    path, _payload, model = with_pending_save(tmp_path)
    model.follow_pending_save()
    reloads = counted(model.reloaded)

    model.note_file_gone(folder_gone=folder_gone)

    assert not reloads
    assert (model.title, model.dirty) == ("Mine", False)
    assert model.gone == (f"The resource's folder is gone: {tmp_path}" if folder_gone else f"The file is gone: {path}")


# endregion
