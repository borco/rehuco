"""Tests for records (#416): loading, the read-merge-write save, the stored text and the
legacy conversion, all against real files under ``tmp_path`` ([[nodes#access-seam]]).
"""

import json
import logging
from pathlib import Path
from typing import Any, Final
from unittest.mock import MagicMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from pytest import LogCaptureFixture
from pytest_mock import MockerFixture
from rehuco_core import (
    DEFAULT_DELETER,
    EXCLUDED_FILE_PATTERNS,
    SCREENSHOT_NAME_PATTERNS,
    LoadedRecord,
    LockReasonKind,
    RecordConflict,
    Records,
    RehuDocument,
    ResourceKey,
    VideoFacts,
    WatchRules,
    current_block_version,
    record_version,
    user_sidecar_paths,
)

from rehuco_core_tests.test_tc_conversion import TC_YAML

USERNAME: Final = "admin"
"""The identity records are opened and saved as."""

UNKNOWN: Final = "ghost"
"""The identity a legacy record's flags are filed under."""

UPDATED: Final = "2026-01-01T00:00:00Z"
"""The ``updated`` stamp every record here is written with."""

THEIRS_UPDATED: Final = "2026-05-05T05:05:05Z"
"""The ``updated`` another writer leaves on disk."""

SAVED_AT: Final = "2026-10-12T10:00:00Z"
"""When a save under test happens, and so what it stamps."""


def tutorial_data(users: dict[str, Any] | None = None, **core: Any) -> dict[str, Any]:
    """A current-format tutorial payload.

    :param users: the tutorial block's ``users`` map, or ``None`` for none.
    :param core: extra ``core`` fields.
    :returns: the payload.
    """
    block: dict[str, Any] = {"format_version": current_block_version("tutorial")}
    if users is not None:
        block["users"] = users
    return {
        "format_version": 2,
        "core": {
            "type": "tutorial",
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "updated": UPDATED,
            "description": "original",
            **core,
        },
        "tutorial": block,
    }


def write_record(path: Path, data: dict[str, Any]) -> ResourceKey:
    """Write a payload as a record.

    :param path: where.
    :param data: the payload.
    :returns: its key.
    """
    path.write_text(json.dumps(data), encoding="utf-8")
    return ResourceKey(path)


def load(records: Records, key: ResourceKey) -> LoadedRecord:
    """Load a record as :data:`USERNAME`.

    :param records: the records.
    :param key: the record.
    :returns: what was loaded.
    """
    return records.load(key, username=USERNAME, unknown_username=UNKNOWN)


def on_disk(path: Path) -> dict[str, Any]:
    """A record's payload as stored.

    :param path: the record.
    :returns: its JSON.
    """
    return json.loads(path.read_text(encoding="utf-8"))


def users_on_disk(path: Path, block: str = "tutorial") -> dict[str, Any]:
    """A block's per-user fields as stored in the record's sidecars, by each sidecar's slug.

    :param path: the record.
    :param block: the block key.
    :returns: each user's fields in that block, for the sidecars holding the block.
    """
    stored = {slug: on_disk(sidecar) for slug, sidecar in user_sidecar_paths(path).items()}
    return {slug: fields[block] for slug, fields in stored.items() if block in fields}


def write_meanwhile(path: Path, users: dict[str, Any] | None = None, **core: Any) -> None:
    """Change a record on disk as another writer would: load it, set per-user fields and ``core`` fields, save.

    :param path: the record.
    :param users: per-user fields to set, by username and key.
    :param core: ``core`` fields to set.
    """
    other = RehuDocument.load(path, username="bob")
    for username, fields in (users or {}).items():
        for name, value in fields.items():
            other.set_user_field(username, name, value)
    other.data["core"].update(core)
    other.save(touch_updated=False)


# region load
def test_a_rehu_loads_with_its_version_and_signature(tmp_path: Path) -> None:
    """A ``.rehu`` loads as the given identity, with the version of exactly what was read and the signature
    stat'ed before the read.

    **Test steps:**

    * write a record and load it
    * verify the document, the version against the file's text, the signature, and no lock
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data({USERNAME: {"rating": 3}}))
    records = Records()

    loaded = load(records, key)

    stat = path.stat()
    assert loaded.document.username == USERNAME
    assert loaded.document.active_user_field("rating") == 3
    assert loaded.version == record_version(loaded.document.data, path.read_text(encoding="utf-8"))
    assert loaded.signature == (stat.st_mtime_ns, stat.st_size)
    assert not loaded.lock_reasons


def test_a_legacy_tc_loads_without_a_version_under_the_unknown_username(tmp_path: Path) -> None:
    """A ``.tc`` is never saved over, so it has no version; its flags' owner is unknown, so it is opened as the
    given unknown identity.

    **Test steps:**

    * write a ``.tc`` and load it
    * verify no version, the unknown identity, its lock reasons and its signature
    """
    path = tmp_path / "info.tc"
    path.write_text(TC_YAML, encoding="utf-8")

    loaded = load(Records(), ResourceKey(path))

    assert loaded.version is None
    assert loaded.document.username == UNKNOWN
    assert loaded.lock_reasons == tuple(loaded.document.lock_reasons)
    assert loaded.lock_reasons
    assert loaded.signature == (path.stat().st_mtime_ns, path.stat().st_size)


@pytest.mark.parametrize("name", ["info.rehu", "info.tc"])
def test_a_missing_record_loads_as_a_locked_stub(tmp_path: Path, caplog: LogCaptureFixture, name: str) -> None:
    """Loading never raises: a record that is not there is an empty stub, locked as missing, with no version and
    no signature, and the failure is logged.

    **Test steps:**

    * load a ``.rehu`` and a ``.tc`` that do not exist
    * verify the stub, its lock, and the logged error
    """
    path = tmp_path / name

    with caplog.at_level(logging.ERROR):
        loaded = load(Records(), ResourceKey(path))

    assert loaded.document.load_failed
    assert "core" not in loaded.document.data
    assert loaded.document.path == path
    assert [reason.kind for reason in loaded.lock_reasons] == [LockReasonKind.MISSING]
    assert (loaded.version, loaded.signature) == (None, None)
    assert f"Could not read {path}" in caplog.text


def test_an_unparseable_record_loads_as_a_locked_stub_with_its_signature(tmp_path: Path) -> None:
    """A file that is there but not a record is a stub locked as invalid; it could be stat'ed, so it has a
    signature.

    **Test steps:**

    * write broken JSON and load it
    * verify the stub's lock, no version, and a signature
    """
    path = tmp_path / "info.rehu"
    path.write_text("{not json", encoding="utf-8")

    loaded = load(Records(), ResourceKey(path))

    assert loaded.document.load_failed
    assert [reason.kind for reason in loaded.lock_reasons] == [LockReasonKind.INVALID_FILE]
    assert loaded.version is None
    assert loaded.signature is not None


def test_an_older_format_record_loads_at_one_version_every_time(tmp_path: Path) -> None:
    """The version is taken after migration, so two loads of one older-format file -- each migrating it -- give
    equal versions, and a save of either is not mistaken for a conflict.

    **Test steps:**

    * write a flat format-1 record
    * load it twice
    * verify the versions are equal
    """
    key = write_record(
        tmp_path / "info.rehu",
        {"format_version": 1, "type": "tutorial", "updated": UPDATED, "sources": [{"title": "T", "primary": True}]},
    )
    records = Records()

    assert load(records, key).version == load(records, key).version


# endregion


# region save
def test_a_save_with_no_base_writes_the_document_as_it_is(tmp_path: Path) -> None:
    """A record never read from this file -- a new one, a save-as -- is written as it is, over whatever is there;
    nobody is told here, the file notifier reports the write like any other writer's (#511).

    **Test steps:**

    * save a new document at a fresh path, then another over an existing file with other ratings
    * verify each file holds its document, the versions match a fresh load, nothing was merged
    """
    records = Records()
    new_key = ResourceKey(tmp_path / "new.rehu")
    existing = tmp_path / "existing.rehu"
    existing_key = write_record(existing, tutorial_data({"bob": {"rating": 1}}))

    created = records.save(
        new_key, RehuDocument(tutorial_data(), username=USERNAME), None, username=USERNAME, overwrite=False
    )
    replaced = records.save(
        existing_key, RehuDocument(tutorial_data(), username=USERNAME), None, username=USERNAME, overwrite=False
    )

    assert created.version == load(records, new_key).version
    assert created.users_merged is False
    assert replaced.users_merged is False
    assert "users" not in on_disk(existing)["tutorial"]


def test_a_new_record_found_already_there_is_a_conflict(tmp_path: Path) -> None:
    """A record saved as new that someone created meanwhile is refused: the conflict carries the record found and its
    version, and the file is untouched (#497).

    **Test steps:**

    * write a record at a path, then save a new document there as ``new``, against no base
    * verify ``RecordConflict`` with the file's document and version, the file unchanged
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data(description="theirs"))
    records = Records()
    before = path.read_text(encoding="utf-8")

    with pytest.raises(RecordConflict) as raised:
        records.save(
            key, RehuDocument(tutorial_data(), username=USERNAME), None, username=USERNAME, overwrite=False, new=True
        )

    assert raised.value.theirs.data["core"]["description"] == "theirs"
    assert raised.value.version == load(records, key).version
    assert path.read_text(encoding="utf-8") == before


def test_a_new_record_with_overwrite_is_written_over_the_one_found(tmp_path: Path) -> None:
    """With ``overwrite`` a record saved as new is written over the one found there, which it is not merged with.

    **Test steps:**

    * write a record with ``bob``'s rating, then save a new document there as ``new`` with ``overwrite``
    * verify the file holds the new document's description and no per-user fields, and the version matches a fresh
      load
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data({"bob": {"rating": 1}}, description="theirs"))
    records = Records()

    saved = records.save(
        key, RehuDocument(tutorial_data(), username=USERNAME), None, username=USERNAME, overwrite=True, new=True
    )

    stored = on_disk(path)
    assert stored["core"]["description"] == "original"
    assert "users" not in stored["tutorial"]
    assert saved.version == load(records, key).version
    assert saved.users_merged is False


def test_a_new_record_with_nothing_there_is_written(tmp_path: Path) -> None:
    """A record saved as new where nothing is is simply written.

    **Test steps:**

    * save a new document as ``new`` at a fresh path
    * verify the file holds it and the version matches a fresh load
    """
    key = ResourceKey(tmp_path / "info.rehu")
    records = Records()

    saved = records.save(
        key, RehuDocument(tutorial_data(), username=USERNAME), None, username=USERNAME, overwrite=False, new=True
    )

    assert on_disk(key.path)["core"]["description"] == "original"
    assert saved.version == load(records, key).version


def test_a_save_over_an_unchanged_file_writes_without_merging(tmp_path: Path) -> None:
    """While the file is the one read, nothing needs merging: the edit is written and the returned version and
    signature describe the new file.

    **Test steps:**

    * load a record, change its description, save it against the loaded version
    * verify the file, the version against a fresh load, the signature, and that nothing was merged
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)

    loaded.document.data["core"]["description"] = "edited"
    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert on_disk(path)["core"]["description"] == "edited"
    assert saved.version == load(records, key).version
    assert saved.signature == (path.stat().st_mtime_ns, path.stat().st_size)
    assert saved.users_merged is False


def test_a_save_merges_a_progress_entry_written_meanwhile(tmp_path: Path, freezer: FrozenDateTimeFactory) -> None:
    """A per-user write landing while a rating is edited survives the rating's save, field by field; neither is a
    metadata edit, so ``updated`` stays where it was.

    **Test steps:**

    * load a record; meanwhile, another writer adds a progress entry for the same user and a rating for ``bob``
    * change the loaded rating and save it later against the loaded version
    * verify the sidecars hold all three, the save reports a merge, the document holds them too, ``updated`` is
      unmoved
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data({USERNAME: {"rating": 1}}))
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, {USERNAME: {"progress": {"a.mp4": 12}}, "bob": {"rating": 2}})

    freezer.move_to("2026-10-12T10:00:00Z")
    loaded.document.set_active_user_field("rating", 5)
    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    users = users_on_disk(path)
    assert users == {USERNAME: {"rating": 5, "progress": {"a.mp4": 12}}, "bob": {"rating": 2}}
    assert on_disk(path)["core"]["updated"] == UPDATED
    assert saved.users_merged is True
    assert loaded.document.data["tutorial"]["users"] == users
    assert saved.version == load(records, key).version


def test_the_first_per_user_field_written_meanwhile_into_a_bare_block_is_no_conflict(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """A block holding only its version stamp -- what a type switch writes -- is no metadata with or without a
    ``users`` map, so another user's first rating landing in it merges rather than conflicts, and a rating-only save
    leaves ``updated`` alone.

    **Test steps:**

    * write a tutorial whose block has no ``users`` map, and load it
    * meanwhile, ``bob`` writes the first per-user field into the block
    * change the loaded rating and save against the loaded version later
    * verify no conflict, both ratings in their sidecars, ``updated`` unmoved
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, {"bob": {"rating": 2}})

    freezer.move_to("2026-10-12T10:00:00Z")
    loaded.document.set_active_user_field("rating", 4)
    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert users_on_disk(path) == {USERNAME: {"rating": 4}, "bob": {"rating": 2}}
    assert on_disk(path)["core"]["updated"] == UPDATED
    assert saved.users_merged is True


def test_per_user_fields_written_meanwhile_into_a_block_the_record_lacked_survive(tmp_path: Path) -> None:
    """A record opened with no plugin block gains one on disk from another user's first rating; saving a metadata edit
    keeps that block and its rating rather than writing the record back without them.

    **Test steps:**

    * write a tutorial with no ``tutorial`` block, and load it
    * meanwhile, ``bob`` rates it, which creates the block on disk
    * retitle the loaded record and save it against the loaded version
    * verify the save reports a merge, the record holds the new title and the block's stamp, and ``bob``'s sidecar
      his rating
    """
    path = tmp_path / "info.rehu"
    data = tutorial_data()
    del data["tutorial"]
    key = write_record(path, data)
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, {"bob": {"rating": 3}})

    loaded.document.title = "Mine"
    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    stored = on_disk(path)
    assert saved.users_merged is True
    assert stored["core"]["sources"][0]["title"] == "Mine"
    assert stored["tutorial"] == {"format_version": current_block_version("tutorial")}
    assert users_on_disk(path) == {"bob": {"rating": 3}}


def test_a_metadata_edit_made_meanwhile_is_a_conflict(tmp_path: Path) -> None:
    """A metadata edit on disk since the read refuses the save: the conflict carries the record as it is now and its
    version, and the file is untouched.

    **Test steps:**

    * load a record; meanwhile, another writer changes its description
    * change the loaded rating and save against the loaded version
    * verify ``RecordConflict`` with the file's document and version, the file unchanged
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, description="theirs")
    before = path.read_text(encoding="utf-8")

    loaded.document.set_active_user_field("rating", 5)
    with pytest.raises(RecordConflict) as raised:
        records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert raised.value.theirs.data["core"]["description"] == "theirs"
    assert raised.value.version == load(records, key).version
    assert str(path) in str(raised.value)
    assert path.read_text(encoding="utf-8") == before


def test_a_save_leaves_out_a_block_it_drops_whatever_the_file_holds_there(tmp_path: Path) -> None:
    """A save built from a snapshot that left a block out on purpose names it as dropped, and the merge never adds it
    back from the file (#497).

    **Test steps:**

    * write a record whose ``reference_images`` block holds ``bob``'s rating, and load it
    * meanwhile, another writer adds a progress entry, so the save merges
    * save a document without that block, naming it as dropped; verify the file no longer holds it
    """
    path = tmp_path / "info.rehu"
    data = tutorial_data()
    data["reference_images"] = {"format_version": 1, "users": {"bob": {"rating": 2}}}
    key = write_record(path, data)
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, {USERNAME: {"progress": {"a.mp4": 12}}})
    without = {name: value for name, value in loaded.document.payload_to_write().items() if name != "reference_images"}
    document = RehuDocument(without, path, username=USERNAME, on_disk_format_version=2)

    records.save(key, document, loaded.version, username=USERNAME, overwrite=False, dropped=("reference_images",))

    assert "reference_images" not in on_disk(path)


def test_overwrite_writes_over_a_metadata_edit_and_still_merges_per_user_fields(tmp_path: Path) -> None:
    """With ``overwrite`` the caller's metadata wins, and the per-user fields written meanwhile are still merged.

    **Test steps:**

    * load a record; meanwhile, another writer changes its description and rates it as ``bob``
    * change the loaded description and save with ``overwrite``
    * verify the caller's description is in the record and ``bob``'s rating in his sidecar
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, {"bob": {"rating": 2}}, description="theirs")

    loaded.document.data["core"]["description"] = "mine"
    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=True)

    assert on_disk(path)["core"]["description"] == "mine"
    assert users_on_disk(path) == {"bob": {"rating": 2}}
    assert saved.users_merged is True


def test_a_save_whose_details_are_the_files_keeps_the_files_updated(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """A save whose details come out as the file's -- the other writer's edit made here too -- writes only per-user
    fields: it takes the file's ``updated`` rather than stamping one, though the details moved since the read.

    **Test steps:**

    * load a record; meanwhile, another writer changes its description and its ``updated``
    * make the same description edit here, rate it, and save later with ``overwrite``
    * verify the record holds the description and the file's ``updated`` -- on the document too -- and the sidecar
      the rating
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, description="theirs", updated=THEIRS_UPDATED)

    freezer.move_to(SAVED_AT)
    loaded.document.data["core"]["description"] = "theirs"
    loaded.document.set_active_user_field("rating", 5)
    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=True)

    stored = on_disk(path)
    assert stored["core"]["description"] == "theirs"
    assert users_on_disk(path) == {USERNAME: {"rating": 5}}
    assert stored["core"]["updated"] == THEIRS_UPDATED
    assert loaded.document.updated == THEIRS_UPDATED


def test_a_save_whose_details_differ_from_the_files_stamps_updated(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """Writing details the file does not hold is an edit landing on disk: ``updated`` is stamped with the save's time,
    neither the file's nor the one read.

    **Test steps:**

    * load a record; meanwhile, another writer changes its description and its ``updated``
    * change the description here to another value, and save later with ``overwrite``
    * verify the file holds this description and the save's time as ``updated``
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, description="theirs", updated=THEIRS_UPDATED)

    freezer.move_to(SAVED_AT)
    loaded.document.data["core"]["description"] = "mine"
    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=True)

    stored = on_disk(path)
    assert stored["core"]["description"] == "mine"
    assert stored["core"]["updated"] == SAVED_AT


def test_a_save_whose_details_are_the_files_stamps_nothing_when_the_file_has_no_updated(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """A file with no ``updated`` has none to take: the document's own is written as it is, not stamped -- the save
    still changes no detail.

    **Test steps:**

    * load a record; meanwhile, another writer changes its description and drops its ``updated``
    * make the same description edit here, and save later with ``overwrite``
    * verify the file holds the description and the ``updated`` read, not the save's time
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    other = RehuDocument.load(path, username="bob")
    other.data["core"]["description"] = "theirs"
    del other.data["core"]["updated"]
    other.save(touch_updated=False)
    assert "updated" not in on_disk(path)["core"]

    freezer.move_to(SAVED_AT)
    loaded.document.data["core"]["description"] = "theirs"
    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=True)

    stored = on_disk(path)
    assert stored["core"]["description"] == "theirs"
    assert stored["core"]["updated"] == UPDATED


def test_restoring_the_original_over_the_files_edit_stamps_updated(
    tmp_path: Path, freezer: FrozenDateTimeFactory
) -> None:
    """Writing back the value the document was opened with, over another writer's edit, changes the record as stored:
    it is an edit, stamped with the save's time -- never the older ``updated`` the document was read with, which the
    document's own baseline would leave in place since its details never moved.

    **Test steps:**

    * load a record; meanwhile, another writer changes its description and its ``updated``
    * save the unchanged document against the file's version, as a conflict resolved with the original is
    * verify the file holds the original description and the save's time as ``updated``
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    write_meanwhile(path, description="theirs", updated=THEIRS_UPDATED)
    theirs = load(records, key)

    freezer.move_to(SAVED_AT)
    records.save(key, loaded.document, theirs.version, username=USERNAME, overwrite=False)

    stored = on_disk(path)
    assert stored["core"]["description"] == "original"
    assert stored["core"]["updated"] == SAVED_AT


def test_a_save_dropping_an_abandoned_block_stamps_updated(tmp_path: Path, freezer: FrozenDateTimeFactory) -> None:
    """A block claimed and abandoned this session is dropped by the save -- a change to the record -- although the
    document's data still holds it: what the save writes is compared with the file, so ``updated`` is stamped.

    **Test steps:**

    * write a tutorial with a foreign ``reference_images`` block, and load it
    * switch to ``reference_images`` and back, and save against the loaded version later
    * verify the block is gone from the file and ``updated`` is the save's time
    """
    path = tmp_path / "info.rehu"
    data = tutorial_data()
    data["reference_images"] = {"format_version": 1, "image_count": 12}
    key = write_record(path, data)
    records = Records()
    loaded = load(records, key)
    loaded.document.set_active_type("reference_images")
    loaded.document.set_active_type("tutorial")

    freezer.move_to(SAVED_AT)
    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    stored = on_disk(path)
    assert "reference_images" not in stored
    assert stored["core"]["updated"] == SAVED_AT


def test_the_version_after_a_save_matches_a_fresh_load_when_a_block_was_dropped(tmp_path: Path) -> None:
    """The saved version is read back from the file, not derived from the document: a block claimed then
    abandoned is still in the document's data but not in the file, and the next save checks the file.

    **Test steps:**

    * load a record typed ``audiopack`` with a ``tutorial`` block, switch it to ``tutorial``, save
    * verify the file lost ``audiopack``, the document still holds it, and the version matches a fresh load
    * after another writer rates it, save again against that version and verify it is no conflict
    """
    path = tmp_path / "info.rehu"
    data = tutorial_data({"bob": {"rating": 1}})
    data["core"]["type"] = "audiopack"
    data["audiopack"] = {"bitrate": 320}
    key = write_record(path, data)
    records = Records()
    loaded = load(records, key)

    loaded.document.set_active_type("tutorial")
    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert "audiopack" not in on_disk(path)
    assert "audiopack" in loaded.document.data
    assert saved.version == load(records, key).version
    write_meanwhile(path, {"bob": {"rating": 2}})
    records.save(key, loaded.document, saved.version, username=USERNAME, overwrite=False)


def test_a_save_after_the_file_vanished_writes_it_again(tmp_path: Path) -> None:
    """A file gone since the read has nothing to conflict or merge with: the document is written as it is.

    **Test steps:**

    * load a record, delete the file, edit and save against the loaded version
    * verify the file is back with the edit and nothing was merged
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    path.unlink()

    loaded.document.data["core"]["description"] = "edited"
    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert on_disk(path)["core"]["description"] == "edited"
    assert saved.users_merged is False


def test_a_save_over_a_file_broken_meanwhile_restores_it_and_logs(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """A file that is no longer a readable record since the read is written over: there is nothing in it to merge or
    conflict with, and the break is logged since what made it is lost under the write.

    **Test steps:**

    * load a record, overwrite the file with broken JSON, edit and save against the loaded version
    * verify the file is a record again with the edit, nothing was merged, and a warning names the file
    """
    path = tmp_path / "info.rehu"
    key = write_record(path, tutorial_data())
    records = Records()
    loaded = load(records, key)
    path.write_text("{not json", encoding="utf-8")

    loaded.document.data["core"]["description"] = "edited"
    with caplog.at_level(logging.WARNING):
        saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert on_disk(path)["core"]["description"] == "edited"
    assert saved.users_merged is False
    assert f"{path} is no longer a readable record" in caplog.text


def test_a_legacy_record_is_never_saved_over(tmp_path: Path) -> None:
    """A ``.tc`` is converted, not written: the records refuse to save one whatever document it is handed, so the
    toolbar's hidden Save is not the only thing standing between a legacy file and a JSON write over it.

    **Test steps:**

    * write a ``.tc``, load it, and try to save its document against no base
    * verify the refusal, and the file untouched
    """
    path = tmp_path / "info.tc"
    path.write_text(TC_YAML, encoding="utf-8")
    records = Records()
    loaded = load(records, ResourceKey(path))

    with pytest.raises(ValueError, match="legacy record"):
        records.save(ResourceKey(path), loaded.document, None, username=USERNAME, overwrite=False)

    assert path.read_text(encoding="utf-8") == TC_YAML


# endregion


# region stored text and conversion
def test_stored_files_are_the_files_as_they_are(tmp_path: Path) -> None:
    """The record's text and then every user's sidecar's, by name, each byte for byte -- not the document
    reserialized; another record's sidecar is not among them.

    **Test steps:**

    * write a record with a layout of its own, two sidecars of its own out of name order, and another record's
    * verify ``stored_files`` answers the record first, then its sidecars by name, each unchanged
    """
    path = tmp_path / "info.rehu"
    text = json.dumps(tutorial_data(), indent=7)
    path.write_text(text, encoding="utf-8")
    sidecars = {
        "info.user-bob.rehuser": '{"format_version": 1, "tutorial": {"rating": 2}}',
        "info.user-admin.rehuser": '{ "format_version" : 1 }',
    }
    for name, sidecar in sidecars.items():
        (tmp_path / name).write_text(sidecar, encoding="utf-8")
    (tmp_path / "other.user-admin.rehuser").write_text('{"format_version": 1}', encoding="utf-8")

    assert Records().stored_files(ResourceKey(path)) == [
        ("info.rehu", text),
        ("info.user-admin.rehuser", sidecars["info.user-admin.rehuser"]),
        ("info.user-bob.rehuser", sidecars["info.user-bob.rehuser"]),
    ]


def test_a_legacy_records_stored_files_are_only_itself(tmp_path: Path) -> None:
    """A ``.tc`` has no sidecars: its stored files are just its own text, whatever sits beside it.

    **Test steps:**

    * write a ``.tc`` and a sidecar named after its stem
    * verify ``stored_files`` answers only the ``.tc``
    """
    path = tmp_path / "info.tc"
    path.write_text(TC_YAML, encoding="utf-8")
    (tmp_path / "info.user-admin.rehuser").write_text('{"format_version": 1}', encoding="utf-8")

    assert Records().stored_files(ResourceKey(path)) == [("info.tc", TC_YAML)]


def test_convert_writes_the_rehu_and_loads_it(tmp_path: Path) -> None:
    """A legacy ``.tc`` becomes a ``.rehu`` beside it, and the new record comes back loaded as the given identity, with
    a version; the file notifier, not the conversion, reports both files changed (#511).

    **Test steps:**

    * write a ``.tc`` and convert it
    * verify the loaded ``.rehu`` and the ``.tc`` gone
    """
    tc_path = tmp_path / "info.tc"
    tc_path.write_text(TC_YAML, encoding="utf-8")
    rehu_path = tmp_path / "info.rehu"
    records = Records()

    loaded = records.convert(
        ResourceKey(tc_path),
        keep_backups=False,
        overwrite=False,
        username=UNKNOWN,
        excluded_patterns=EXCLUDED_FILE_PATTERNS,
        screenshot_name_patterns=SCREENSHOT_NAME_PATTERNS,
        deleter=DEFAULT_DELETER,
    )

    assert loaded.document.path == rehu_path
    assert loaded.document.username == UNKNOWN
    assert loaded.version == load(records, ResourceKey(rehu_path)).version
    assert not tc_path.exists()


# endregion


# region The signature


def test_a_records_signature_is_its_time_and_size_looked_at_under_the_rename_hold(tmp_path: Path) -> None:
    """What a later look is compared with: the file's modification time and size, each read inside the rename
    coordinator's hold so it never blocks a rename; nothing for a file that is gone (#417).

    **Test steps:**

    * build records over a coordinator that notes each hold, and write a record
    * verify its signature is its stat's time and size, a missing file answers nothing, and each look took the hold
      once
    """
    coordinator = MagicMock()
    records = Records(coordinator)
    key = write_record(tmp_path / "info.rehu", tutorial_data())
    stat = key.path.stat()

    assert records.signature(key) == (stat.st_mtime_ns, stat.st_size)
    assert records.signature(ResourceKey(tmp_path / "gone.rehu")) is None
    assert coordinator.holding.call_count == 2


# endregion


# region progress and measured lengths


def test_a_progress_write_goes_through_core_and_answers_the_record_as_read_after(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Recording progress is core's write path with the caller's identity as both the user and the one the record is
    opened as, answered with the record read after it.

    **Test steps:**

    * write a record, and replace core's write with a mock
    * record progress through the records
    * verify core was called with the key's path, the identity twice and the settings handed in, and the answer is the
      record loaded after it
    """
    key = write_record(tmp_path / "info.rehu", tutorial_data())
    write = mocker.patch("rehuco_core.access.records.record_progress")
    rules = WatchRules(mark_file_viewed_at_end=False)

    loaded = Records().record_progress(
        key,
        username=USERNAME,
        relative="a.mp4",
        position=12.5,
        duration=100.0,
        viewed=None,
        rules=rules,
        video_extensions=(".mp4",),
        excluded_patterns=("*.tmp",),
    )

    write.assert_called_once_with(
        key.path,
        USERNAME,
        "a.mp4",
        12.5,
        100.0,
        viewed=None,
        rules=rules,
        current_username=USERNAME,
        video_extensions=(".mp4",),
        excluded_patterns=("*.tmp",),
    )
    assert loaded.version == load(Records(), key).version


def test_forgetting_progress_goes_through_core_and_answers_the_record_as_read_after(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Forgetting an entry is core's forget, answered with the record read after it.

    **Test steps:**

    * write a record, and replace core's forget with a mock
    * forget an entry through the records
    * verify core was called for that entry and the answer is the record loaded after it
    """
    key = write_record(tmp_path / "info.rehu", tutorial_data())
    forget = mocker.patch("rehuco_core.access.records.forget_progress")

    loaded = Records().forget_progress(key, username=USERNAME, relative="gone.mp4")

    forget.assert_called_once_with(key.path, USERNAME, "gone.mp4", current_username=USERNAME)
    assert loaded.version == load(Records(), key).version


@pytest.mark.parametrize(("moved", "answers"), [({"a.mp4": "b.mp4"}, True), ({}, False)])
def test_moving_progress_answers_the_record_only_when_something_moved(
    tmp_path: Path, mocker: MockerFixture, moved: dict[str, str], answers: bool
) -> None:
    """Reattaching renamed progress is core's, and reads the record again only when it wrote.

    **Test steps:**

    * write a record, and replace core's reattach with a mock answering the moves
    * reattach through the records
    * verify core got the settings handed in, and the answer is the loaded record after a move and ``None`` after none
    """
    key = write_record(tmp_path / "info.rehu", tutorial_data())
    reattach = mocker.patch("rehuco_core.access.records.reattach_renamed_progress", return_value=moved)

    loaded = Records().reattach_renamed_progress(
        key, username=USERNAME, match_by_size=False, video_extensions=(".mp4",), excluded_patterns=()
    )

    reattach.assert_called_once_with(
        key.path,
        USERNAME,
        match_by_size=False,
        current_username=USERNAME,
        video_extensions=(".mp4",),
        excluded_patterns=(),
    )
    assert (loaded is not None) is answers


def test_a_measure_goes_through_core_and_answers_the_record_as_read_after(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Writing a Measure's lengths is core's, answered with the record read after it.

    **Test steps:**

    * write a record, and replace core's write with a mock
    * record a Measure through the records
    * verify core was called with the facts and the identity, and the answer is the record loaded after it
    """
    key = write_record(tmp_path / "info.rehu", tutorial_data())
    write = mocker.patch("rehuco_core.access.records.record_videos")
    facts = {"a.mp4": VideoFacts(100.0)}

    loaded = Records().record_videos(key, facts, username=USERNAME)

    write.assert_called_once_with(key.path, facts, current_username=USERNAME)
    assert loaded.version == load(Records(), key).version


# endregion
