"""Tests for a record's license text riding its payload (#688, [[assets#licenses]]): read with the record into the
document, written by its save to the ``.rehuterms`` and never to the record, all against real files under
``tmp_path``.
"""

import datetime
import json
import logging
from pathlib import Path
from typing import Final

import pytest
from borco_core import atomic_write_text
from pytest import LogCaptureFixture
from pytest_mock import MockerFixture
from rehuco_core import (
    LICENSE_TERMS_KEY,
    LicenseTerms,
    LicenseTermsError,
    LicenseTermsSet,
    RecordConflict,
    Records,
    RehuDocument,
    ResourceKey,
    SavePayload,
    license_terms_path,
    read_license_terms,
    write_license_terms,
)

from rehuco_core_tests.access.test_records import USERNAME, load, on_disk, tutorial_data, write_record

SAVED_AT: Final = "2026-10-12T10:00:00+00:00"
"""When a save under test happens, and so what it stamps."""

TERMS: Final = LicenseTermsSet(
    {
        "fab-standard": LicenseTerms(
            "Standard License", "https://example.com/eula", datetime.date(2026, 11, 18), "# Terms\n"
        )
    }
)
"""The texts a record is written with: one license's."""

EDITED: Final = LicenseTermsSet(
    {
        "fab-standard": LicenseTerms(
            "Standard License", "https://example.com/eula", datetime.date(2026, 11, 18), "# Mine\n"
        )
    }
)
"""The same texts, that license's edited."""


def record_with_terms(tmp_path: Path, terms: LicenseTermsSet | None = TERMS) -> ResourceKey:
    """A record, and its ``.rehuterms`` when given terms.

    :param tmp_path: the folder.
    :param terms: the terms to write beside it; ``None`` for no sidecar.
    :returns: the record's key.
    """
    key = write_record(tmp_path / "info.rehu", tutorial_data())
    if terms is not None:
        write_license_terms(key.path, terms)
    return key


# region reading


def test_a_record_loads_with_its_license_text_and_a_version_that_follows_it(tmp_path: Path) -> None:
    """The terms are read into the document with the record, and a change to the sidecar is a change of the record's
    version, so a save made against the old one is checked.

    **Test steps:**

    * write a record with a sidecar and load it
    * verify the document holds the terms, none is unreadable and no lock is raised
    * change the sidecar and load again
    * verify the version's file hash and license hash moved on, and its details' hash did not: the text is
      judged apart from the record's details
    """
    key = record_with_terms(tmp_path)
    first = load(Records(), key)
    write_license_terms(key.path, EDITED)
    second = load(Records(), key)

    assert first.document.license_terms == TERMS
    assert first.document.license_unreadable == ""
    assert not first.lock_reasons
    assert second.document.license_terms == EDITED
    assert first.version is not None and second.version is not None
    assert first.version.file_hash != second.version.file_hash
    assert first.version.license_hash != second.version.license_hash
    assert first.version.metadata_hash == second.version.metadata_hash


def test_a_record_with_no_sidecar_holds_no_terms(tmp_path: Path) -> None:
    """No sidecar is no terms, and not a problem.

    **Test steps:**

    * write a record alone and load it
    * verify no terms, nothing unreadable, and no key in the payload
    """
    loaded = load(Records(), record_with_terms(tmp_path, None))

    assert loaded.document.license_terms is None
    assert loaded.document.license_unreadable == ""
    assert LICENSE_TERMS_KEY not in loaded.document.data


def test_a_read_that_does_not_ask_opens_no_sidecar(tmp_path: Path, mocker: MockerFixture) -> None:
    """A catalog scan loads records and has no use for their license text, so it opens nothing more than the record.

    **Test steps:**

    * write a record with a sidecar and watch the sidecar's reader
    * load the record the way a scan does
    * verify the document holds none and the reader was never called
    """
    key = record_with_terms(tmp_path)
    reader = mocker.patch("rehuco_core.rehu_document.read_license_terms")

    document = RehuDocument.load(key.path)

    assert document.license_terms is None
    reader.assert_not_called()


def test_an_unreadable_sidecar_is_named_and_left_out_and_the_record_still_loads(
    tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """A sidecar that cannot be read costs its own text and nothing else, and is logged.

    **Test steps:**

    * write a record beside a sidecar with no header
    * load it
    * verify the reason starts with the file's name, no terms are held, the record is unlocked, and the log says so
    """
    key = record_with_terms(tmp_path, None)
    license_terms_path(key.path).write_text("not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        loaded = load(Records(), key)

    assert loaded.document.license_unreadable.startswith("info.rehuterms:")
    assert loaded.document.license_terms is None
    assert not loaded.lock_reasons
    assert "info.rehuterms" in caplog.text


def test_a_sidecar_that_cannot_be_opened_is_named_too(tmp_path: Path, mocker: MockerFixture) -> None:
    """An operating-system failure reading the sidecar is a sidecar that cannot be read, not a record that cannot.

    **Test steps:**

    * make the sidecar's reader fail with an ``OSError``
    * load the record
    * verify the reason names the file and the error, and the record loads
    """
    key = record_with_terms(tmp_path)
    mocker.patch("rehuco_core.rehu_document.read_license_terms", side_effect=PermissionError("denied"))

    loaded = load(Records(), key)

    assert loaded.document.license_unreadable == "info.rehuterms: could not be read — denied."
    assert loaded.document.license_terms is None


def test_a_record_that_holds_the_key_itself_has_it_left_out(tmp_path: Path, caplog: LogCaptureFixture) -> None:
    """Only the sidecar may say a record's license text: what a ``.rehu`` holds under that key is not read, so a save
    never writes it out as a sidecar.

    **Test steps:**

    * write a record that holds the key, and no sidecar
    * load it
    * verify no terms are held and the warning names the key
    """
    data = tutorial_data()
    data[LICENSE_TERMS_KEY] = TERMS.to_data()
    key = write_record(tmp_path / "info.rehu", data)

    with caplog.at_level(logging.WARNING):
        loaded = load(Records(), key)

    assert loaded.document.license_terms is None
    assert LICENSE_TERMS_KEY in caplog.text


def test_a_document_reloads_its_license_text_with_the_rest(tmp_path: Path) -> None:
    """A revert picks up a sidecar edited by hand, or one that has since become readable.

    **Test steps:**

    * load a record whose sidecar is unreadable, then fix the sidecar
    * reload the document
    * verify it holds the terms and no longer calls the sidecar unreadable
    """
    key = record_with_terms(tmp_path, None)
    license_terms_path(key.path).write_text("not json", encoding="utf-8")
    document = load(Records(), key).document
    write_license_terms(key.path, TERMS)

    document.reload()

    assert document.license_terms == TERMS
    assert document.license_unreadable == ""


# endregion


# region saving


def test_a_save_writes_edited_terms_to_the_sidecar_and_never_to_the_record(tmp_path: Path) -> None:
    """The edited text lands in the ``.rehuterms``; the ``.rehu`` holds none of it, and the version the save leaves
    is what a fresh load reads.

    **Test steps:**

    * load a record with a sidecar, edit its terms and save
    * verify the sidecar holds the edit, the record's JSON has no key for it, and the saved version is a fresh load's
    """
    key = record_with_terms(tmp_path)
    records = Records()
    loaded = load(records, key)
    loaded.document.license_terms = EDITED

    saved = records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert read_license_terms(key.path) == EDITED
    assert LICENSE_TERMS_KEY not in on_disk(key.path)
    assert saved.version == load(records, key).version


def test_a_new_record_writes_its_terms_beside_it(tmp_path: Path) -> None:
    """Terms typed into a record never saved are written with its first save.

    **Test steps:**

    * build a document for a path with nothing there, give it terms, and save it as new
    * verify the record and its sidecar are both there
    """
    path = tmp_path / "info.rehu"
    document = RehuDocument(tutorial_data(), path, username=USERNAME)
    document.license_terms = TERMS

    Records().save(ResourceKey(path), document, None, username=USERNAME, overwrite=False, new=True)

    assert read_license_terms(path) == TERMS
    assert LICENSE_TERMS_KEY not in on_disk(path)


def test_a_save_of_unchanged_terms_writes_no_sidecar(tmp_path: Path, mocker: MockerFixture) -> None:
    """A save that does not change the text leaves its file alone, so a per-user write never rewrites it.

    **Test steps:**

    * load a record with a sidecar, change a detail of the record and save
    * verify the sidecar was never written
    """
    key = record_with_terms(tmp_path)
    records = Records()
    loaded = load(records, key)
    loaded.document.description = "changed"
    writer = mocker.patch("rehuco_core.rehu_document.write_license_terms")

    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    writer.assert_not_called()
    assert on_disk(key.path)["core"]["description"] == "changed"


def test_a_payload_without_terms_leaves_the_sidecar_as_it_is(tmp_path: Path) -> None:
    """A writer that read the record without its text -- progress, a Measure, a value rename -- saves it back and never
    removes the text it did not see.

    **Test steps:**

    * write a record with a sidecar, load it the way such a writer does and save it
    * verify the sidecar is unchanged
    """
    key = record_with_terms(tmp_path)
    before = license_terms_path(key.path).read_bytes()
    document = RehuDocument.load(key.path, username=USERNAME)
    document.description = "changed"

    document.save(touch_updated=False)

    assert license_terms_path(key.path).read_bytes() == before


def test_a_save_refuses_to_write_over_a_sidecar_it_cannot_read(tmp_path: Path) -> None:
    """A sidecar broken since it was read is never written over: the save is refused and the file is untouched.

    **Test steps:**

    * load a record with terms, then break its sidecar by hand
    * edit the terms and save
    * verify the save raises, and the sidecar holds what the hand left
    """
    key = record_with_terms(tmp_path)
    records = Records()
    loaded = load(records, key)
    license_terms_path(key.path).write_text("not json", encoding="utf-8")
    loaded.document.license_terms = EDITED

    with pytest.raises(LicenseTermsError):
        records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=True)

    assert license_terms_path(key.path).read_text(encoding="utf-8") == "not json"


def test_a_save_refuses_terms_that_are_not_terms(tmp_path: Path) -> None:
    """A payload kept across a quit that holds something else under the key is refused, not written as a sidecar.

    **Test steps:**

    * hold a payload whose terms are a string and save it
    * verify the save raises and no sidecar was made
    """
    path = tmp_path / "info.rehu"
    data = tutorial_data()
    data[LICENSE_TERMS_KEY] = "not an object"
    document = RehuDocument(data, path, username=USERNAME)

    with pytest.raises(LicenseTermsError):
        document.save()

    assert not license_terms_path(path).exists()
    assert document.license_terms is None


def test_terms_changed_on_disk_meanwhile_are_a_conflict_with_the_files_side_offered(tmp_path: Path) -> None:
    """A text edited elsewhere since the record was read is a detail of it that changed: the save is refused, with the
    file as it is now to choose from (#688).

    **Test steps:**

    * load a record, then rewrite its sidecar as another writer would
    * edit the terms here and save against what was read
    * verify the save is a conflict whose file side holds the other writer's terms
    """
    key = record_with_terms(tmp_path)
    records = Records()
    loaded = load(records, key)
    elsewhere = LicenseTermsSet(
        {
            "fab-standard": LicenseTerms(
                "Standard License", "https://example.com/eula", datetime.date(2026, 11, 20), "# Theirs\n"
            )
        }
    )
    write_license_terms(key.path, elsewhere)
    loaded.document.license_terms = EDITED

    with pytest.raises(RecordConflict) as conflict:
        records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert conflict.value.theirs.license_terms == elsewhere
    assert read_license_terms(key.path) == elsewhere


def test_editing_the_terms_stamps_updated_and_leaving_them_does_not(tmp_path: Path, mocker: MockerFixture) -> None:
    """The text is a detail of the record, so editing it is an edit; a save that changes nothing is not.

    The clock is replaced rather than frozen: a frozen one hands the sidecar's reader a date class PyYAML cannot write.

    **Test steps:**

    * load a record, save it unchanged, and verify ``updated`` is as it was
    * edit the terms and save, and verify ``updated`` is the save's time
    """
    key = record_with_terms(tmp_path)
    records = Records()
    mocker.patch("rehuco_core.rehu_document.datetime").now.return_value = datetime.datetime.fromisoformat(SAVED_AT)
    loaded = load(records, key)

    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)
    unchanged = on_disk(key.path)["core"]["updated"]
    again = load(records, key)
    again.document.license_terms = EDITED
    records.save(key, again.document, again.version, username=USERNAME, overwrite=False)

    assert unchanged == "2026-01-01T00:00:00Z"
    assert on_disk(key.path)["core"]["updated"] == "2026-10-12T10:00:00Z"


# endregion


# region what is shown and what is watched


def test_the_record_and_its_sidecars_are_rendered_apart(tmp_path: Path) -> None:
    """What a save would write: the record's text carries none of the terms, and the sidecar's own text is rendered on
    its own -- nothing for a document with none.

    **Test steps:**

    * load a record with terms and one without
    * verify the first's record text has no key for them and ``serialize_license_terms`` is the sidecar's text
    * verify the second renders none
    """
    with_terms = load(Records(), record_with_terms(tmp_path)).document
    other = tmp_path / "other"
    other.mkdir()
    without = load(Records(), record_with_terms(other, None)).document

    assert LICENSE_TERMS_KEY not in json.loads(with_terms.serialize())
    assert with_terms.serialize_license_terms() == TERMS.to_text()
    assert without.serialize_license_terms() is None


def test_the_stored_files_and_the_signature_include_the_sidecar(tmp_path: Path) -> None:
    """The On Disk view lists the sidecar, and a change to it moves the signature a held document is compared by.

    **Test steps:**

    * write a record and take its signature and stored files
    * write a sidecar beside it
    * verify the stored files end with the sidecar's text and the signature's size grew by its size
    """
    key = record_with_terms(tmp_path, None)
    records = Records()
    before = records.signature(key)

    write_license_terms(key.path, TERMS)

    after = records.signature(key)
    assert before is not None and after is not None
    assert after[1] == before[1] + len(TERMS.to_text().encode("utf-8"))
    assert records.stored_files(key)[-1] == ("info.rehuterms", TERMS.to_text())


# endregion


# region the text judged apart from the details


def test_a_save_cut_short_after_the_text_goes_through_on_the_retry(tmp_path: Path, mocker: MockerFixture) -> None:
    """The text is written before the record: a save that failed between the two finds its own text in the file on the
    retry, which is no one else's edit to conflict with.

    **Test steps:**

    * load a record, edit its text and a detail, and make the record's own write fail once
    * save, and verify it failed with the text already written
    * save again against the same version and verify it lands, both edits in their files
    """
    key = record_with_terms(tmp_path)
    records = Records()
    loaded = load(records, key)
    loaded.document.license_terms = EDITED
    loaded.document.description = "changed"
    real_write = atomic_write_text
    failing = mocker.patch("rehuco_core.rehu_document.atomic_write_text", side_effect=PermissionError("denied"))

    with pytest.raises(PermissionError):
        records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)
    assert read_license_terms(key.path) == EDITED
    failing.side_effect = real_write
    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert on_disk(key.path)["core"]["description"] == "changed"
    assert read_license_terms(key.path) == EDITED


def test_a_document_holding_no_text_takes_the_files_and_is_no_conflict(tmp_path: Path) -> None:
    """A document with none never removes the file's, so it shows it after the save -- and a text that appeared since
    the record was read, as a refresh writes one, is nothing its save is refused for.

    **Test steps:**

    * load a record with no text, then write one beside it as a refresh would
    * edit a detail and save against what was read
    * verify the save landed, the file's text is untouched and the document now holds it
    """
    key = record_with_terms(tmp_path, None)
    records = Records()
    loaded = load(records, key)
    write_license_terms(key.path, TERMS)
    loaded.document.description = "changed"

    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=False)

    assert loaded.document.license_terms == TERMS
    assert read_license_terms(key.path) == TERMS
    assert on_disk(key.path)["core"]["description"] == "changed"


def test_overwrite_writes_the_documents_text_over_one_changed_on_disk(tmp_path: Path) -> None:
    """**Test steps:**

    * load a record, change its text on disk and in the document, and save with ``overwrite``
    * verify the file holds the document's text
    """
    key = record_with_terms(tmp_path)
    records = Records()
    loaded = load(records, key)
    write_license_terms(
        key.path, LicenseTermsSet({"mine": LicenseTerms("Other", None, datetime.date(2026, 11, 20), "Theirs")})
    )
    loaded.document.license_terms = EDITED

    records.save(key, loaded.document, loaded.version, username=USERNAME, overwrite=True)

    assert read_license_terms(key.path) == EDITED


def test_a_kept_saves_version_carries_its_license_hash_and_one_from_before_reads_as_none(tmp_path: Path) -> None:
    """A save kept across a quit is checked against the same version it was made at, the text's hash included; one
    written before the hash existed reads as holding none, and a hash that is no text is refused.

    **Test steps:**

    * snapshot a save of a record with a text and read it back from its JSON
    * verify the version is equal, license hash and all
    * drop the hash from the JSON and verify it reads as empty; make it a number and verify it is refused
    """
    key = record_with_terms(tmp_path)
    loaded = load(Records(), key)
    assert loaded.version is not None and loaded.version.license_hash
    payload = SavePayload(key.path, USERNAME, loaded.document.payload_to_write(), None, loaded.version)

    state = payload.to_json()
    older = {**state, "base": {name: value for name, value in state["base"].items() if name != "license_hash"}}
    broken = {**state, "base": {**state["base"], "license_hash": 3}}

    assert SavePayload.from_json(state).base == loaded.version
    restored = SavePayload.from_json(older).base
    assert restored is not None and restored.license_hash == ""
    with pytest.raises(ValueError, match="license hash"):
        SavePayload.from_json(broken)


# endregion
