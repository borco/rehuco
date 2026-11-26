"""Tests for a document model holding a record's license texts (#688, #705, [[assets#licenses]]): shown as read,
each license's edited as an edit of the record -- dirty, saved to the ``.rehuterms`` with the record, reverted with
it -- never removed once saved but with its license, and carried or dropped when the license is replaced.

Real records under ``tmp_path``, opened the way a holder does (:func:`~.test_rehu_document_model_conflict.opened`).
"""

import datetime
from pathlib import Path
from typing import Final

from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import (
    LICENSE_TERMS_KEY,
    AssetLicense,
    LicenseTerms,
    LicenseTermsError,
    LicenseTermsSet,
    LockReason,
    LockReasonKind,
    RehuDocument,
    license_terms_path,
    read_license_terms,
    write_license_terms,
)
from rehuco_core.access import Records, ResourceKey

from .test_rehu_document_model_conflict import opened, stored, write_record

pytestmark = mark.usefixtures("real_path_stat")

READ: Final = datetime.date(2026, 11, 18)
TERMS: Final = LicenseTerms("Standard License", "https://example.com/eula", READ, "# Terms\n")
TODAY: Final = datetime.date(2026, 11, 25)
ID: Final = "fab-standard"
"""The license whose text every test below edits."""


def record(tmp_path: Path, terms: LicenseTerms | None = TERMS) -> Path:
    """A record, and a ``.rehuterms`` beside it when given terms.

    :param tmp_path: the folder.
    :param terms: what the sidecar holds for :data:`ID`; none made for ``None``.
    :returns: the record's path.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Pack")
    if terms is not None:
        write_license_terms(path, LicenseTermsSet({ID: terms}))
    return path


def held(model: RehuDocumentModel, license_id: str = ID) -> LicenseTerms | None:
    """The text a model holds for one license.

    :param model: the model.
    :param license_id: the license.
    :returns: its terms; ``None`` for none.
    """
    texts = model.license_terms
    return None if texts is None else texts.get(license_id)


def on_disk(path: Path, license_id: str = ID) -> LicenseTerms | None:
    """The text a record's sidecar holds for one license.

    :param path: the record.
    :param license_id: the license.
    :returns: its terms; ``None`` for none.
    """
    texts = read_license_terms(path)
    return None if texts is None else texts.get(license_id)


# region what it shows


def test_a_record_with_a_sidecar_is_opened_showing_its_terms_and_clean(tmp_path: Path) -> None:
    """Seeding the terms is no edit.

    **Test steps:**

    * open a record that has a sidecar
    * verify the model holds its terms, is clean, and calls nothing unreadable
    """
    model = opened(record(tmp_path))

    assert held(model) == TERMS
    assert model.license_unreadable == ""
    assert not model.dirty


def test_a_sidecar_that_cannot_be_read_is_named_and_the_text_left_out(tmp_path: Path) -> None:
    """The reason is mirrored for the dock to say, the record stays editable, and a save never writes over the file.

    **Test steps:**

    * open a record whose sidecar has no header
    * verify the reason names the file, no terms are held, and the details are not locked
    * type terms and save
    * verify the save is refused, the document stays dirty and the sidecar is as the hand left it
    """
    path = record(tmp_path, None)
    license_terms_path(path).write_text("no header", encoding="utf-8")
    model = opened(path)

    assert model.license_unreadable.startswith("info.rehuterms:")
    assert model.license_terms is None
    assert not model.locked
    model.edit_license(ID, text="Mine")
    with raises(LicenseTermsError):
        model.save()

    assert model.dirty
    assert license_terms_path(path).read_text(encoding="utf-8") == "no header"


# endregion

# region editing


def test_an_edit_of_the_text_dirties_the_document_and_is_saved_with_it(tmp_path: Path) -> None:
    """Editing the terms is editing the record: dirty until saved, the sidecar written by the save, the record's own
    file free of them.

    **Test steps:**

    * open a record with a sidecar and change the terms' text
    * verify the document is dirty and holds it, the title, url and date kept
    * save
    * verify it is clean, the sidecar holds the edit, and the record's file has no license key
    """
    path = record(tmp_path)
    model = opened(path)

    model.edit_license(ID, text="# Mine\n")
    assert model.dirty
    model.save()

    expected = LicenseTerms(TERMS.title, TERMS.url, READ, "# Mine\n")
    assert held(model) == expected
    assert not model.dirty
    assert on_disk(path) == expected
    assert LICENSE_TERMS_KEY not in stored(path).data


def test_a_change_that_changes_nothing_is_no_edit(tmp_path: Path) -> None:
    """Typing the same text again, or nothing into a record with none, leaves the document clean.

    **Test steps:**

    * open a record with a sidecar and give its own text back
    * open one with none and give it nothing
    * verify both are clean
    """
    held = opened(record(tmp_path))
    other = tmp_path / "other"
    other.mkdir()
    empty = opened(record(other, None))

    held.edit_license(ID, TERMS.text)
    empty.edit_license(ID, "")

    assert not held.dirty
    assert not empty.dirty
    assert empty.license_terms is None


def test_text_typed_into_a_license_with_none_makes_terms_of_its_own(tmp_path: Path, mocker: MockerFixture) -> None:
    """The terms are written for this item alone: no url, read today, titled by the license's id.

    **Test steps:**

    * open a record with no sidecar
    * type a text for one license
    * verify the terms are titled by its id, with no url, today's date and the text, and the document is dirty
    """
    mocker.patch("rehuco_agent.documents.rehu_document_model.date").today.return_value = TODAY
    model = opened(record(tmp_path, None))

    model.edit_license(ID, "Mine")

    assert model.license_terms == LicenseTermsSet({ID: LicenseTerms(ID, None, TODAY, "Mine")})
    assert model.dirty


def test_text_typed_for_a_second_license_keeps_the_first_s(tmp_path: Path, mocker: MockerFixture) -> None:
    """Each license's text is its own: typing one never touches another (#705).

    **Test steps:**

    * open a record holding the Standard License's text and type a text for another license
    * verify both are held, the first as it was
    * empty the second again and verify the first alone is left, as the file holds it
    """
    mocker.patch("rehuco_agent.documents.rehu_document_model.date").today.return_value = TODAY
    model = opened(record(tmp_path))

    model.edit_license("other", text="Mine")

    assert held(model) == TERMS
    assert held(model, "other") == LicenseTerms("other", None, TODAY, "Mine")
    model.edit_license("other", text="")
    assert model.license_terms == LicenseTermsSet({ID: TERMS})


def test_terms_typed_and_emptied_again_before_a_save_are_gone(tmp_path: Path) -> None:
    """Nothing was ever saved, so nothing is left behind: the document holds no terms and no key for them.

    **Test steps:**

    * open a record with no sidecar, type a text and empty it again
    * verify no terms are held and the document holds no key for them
    * save and verify no sidecar was made
    """
    path = record(tmp_path, None)
    model = opened(path)

    model.edit_license(ID, text="Mine")
    model.edit_license(ID, text="")
    model.save()

    assert model.license_terms is None
    assert LICENSE_TERMS_KEY not in model.document.data
    assert not license_terms_path(path).exists()


def test_a_saved_text_is_never_removed_only_emptied(tmp_path: Path) -> None:
    """The file keeps what the user last said, empty text included.

    **Test steps:**

    * open a record with a sidecar and empty its text, then save
    * verify the sidecar is still there, with its title and url and no text
    """
    path = record(tmp_path)
    model = opened(path)

    model.edit_license(ID, text="")
    model.save()

    assert on_disk(path) == LicenseTerms(TERMS.title, TERMS.url, READ, "")


def test_a_revert_goes_back_to_the_file_terms(tmp_path: Path) -> None:
    """An edit not saved is dropped with the rest of the record's.

    **Test steps:**

    * open a record with a sidecar, edit its text and revert
    * verify the model holds the file's terms and is clean
    """
    path = record(tmp_path)
    model = opened(path)
    model.edit_license(ID, text="Mine")

    model.revert()

    assert held(model) == TERMS
    assert not model.dirty


# endregion

# region the file changed under it


def test_a_clean_document_follows_a_sidecar_changed_on_disk(tmp_path: Path) -> None:
    """The signature a held document is judged by includes the sidecar, so a text written elsewhere is picked up like
    any other change to the record.

    **Test steps:**

    * open a record with a sidecar and rewrite the sidecar as a refresh would
    * tell the model the file's signature as it is now
    * verify the model shows the new text
    """
    path = record(tmp_path)
    model = opened(path)
    newer = LicenseTerms(TERMS.title, TERMS.url, datetime.date(2026, 11, 20), "# Newer\n")

    write_license_terms(path, LicenseTermsSet({ID: newer}))
    signature = Records().signature(ResourceKey(path))
    assert signature is not None
    model.note_file_signature(*signature)

    assert held(model) == newer
    assert not model.dirty


def test_a_dirty_document_is_told_the_sidecar_changed_and_keeps_its_edit(tmp_path: Path) -> None:
    """Edits are not replaced by what changed on disk: the notice is raised, and the save shows the differences.

    **Test steps:**

    * open a record with a sidecar, edit its text, and rewrite the sidecar elsewhere
    * tell the model the file's signature as it is now
    * verify the notice is raised and the edit is still shown
    """
    path = record(tmp_path)
    model = opened(path)
    model.edit_license(ID, text="Mine")

    write_license_terms(path, LicenseTermsSet({ID: LicenseTerms(TERMS.title, TERMS.url, READ, "# Theirs\n")}))
    signature = Records().signature(ResourceKey(path))
    assert signature is not None
    model.note_file_signature(*signature)

    assert model.changed_on_disk
    kept = held(model)
    assert kept is not None and kept.text == "Mine"


# endregion


# region edits kept from elsewhere


def test_edits_kept_from_elsewhere_still_say_the_sidecar_cannot_be_read(tmp_path: Path) -> None:
    """Edits put back over a record say nothing of its files: a text that cannot be read is still one not to edit.

    **Test steps:**

    * open a record, snapshot it, and break its sidecar
    * put the snapshot back over the record as read now
    * verify the model names the unreadable file
    """
    path = record(tmp_path)
    model = opened(path)
    payload = model.snapshot()
    license_terms_path(path).write_text("no header", encoding="utf-8")
    current = Records().load(ResourceKey(path), username=payload.username, unknown_username=payload.username)

    model.adopt_unsaved(payload, current)

    assert model.license_unreadable.startswith("info.rehuterms:")


# endregion


def test_a_revert_puts_the_licenses_back_and_is_no_edit(tmp_path: Path) -> None:
    """The licenses are read again with the rest of the record, and reading them is no edit (#705).

    **Test steps:**

    * open a record holding one license, give the model another list, and revert
    * verify the model holds the file's list again and is clean
    """
    path = record(tmp_path)
    document = RehuDocument.load(path)
    document.set_active_field("licenses", [{"license": ID}])
    document.save()
    model = opened(path)
    model.licenses = [AssetLicense("cc-by-4.0")]

    model.revert()

    assert model.licenses == [AssetLicense(ID)]
    assert not model.dirty


# region renaming and removing a license


def held_by(path: Path, *ids: str) -> Path:
    """Give a record the licenses ``ids``, in order.

    :param path: the record.
    :param ids: the licenses' short ids.
    :returns: the record's path.
    """
    document = RehuDocument.load(path)
    document.set_active_field("licenses", [{"license": license_id} for license_id in ids])
    document.save()
    return path


def test_a_license_replaced_keeping_its_text_carries_it_to_the_new_id(tmp_path: Path) -> None:
    """A custom license renamed keeps the text its user wrote (#705).

    **Test steps:**

    * open a record holding a license with a text, and replace it with another id, keeping the text
    * verify the model holds the new license in its place and the text under its id, and is dirty
    * save and verify the sidecar holds the text under the new id alone
    """
    path = held_by(record(tmp_path), ID)
    model = opened(path)

    model.replace_license(ID, AssetLicense("mine", "https://example.com/mine"), keep_text=True)

    assert model.licenses == [AssetLicense("mine", "https://example.com/mine")]
    assert held(model, "mine") == TERMS
    assert model.dirty
    model.save()
    assert (on_disk(path), on_disk(path, "mine")) == (None, TERMS)


def test_a_license_replaced_by_a_preset_drops_its_text(tmp_path: Path) -> None:
    """A preset's text is its own, read for it: the replaced license's goes (#705).

    **Test steps:**

    * open a record holding two licenses, a text saved for the first, and replace the first, dropping its text
    * verify the new license is first and the record holds no text
    * save and verify the sidecar holds none
    """
    path = held_by(record(tmp_path), ID, "fab-ue-only")
    model = opened(path)

    model.replace_license(ID, AssetLicense("cc-by-4.0"), keep_text=False)

    assert model.licenses == [AssetLicense("cc-by-4.0"), AssetLicense("fab-ue-only")]
    assert model.license_terms == LicenseTermsSet()
    model.save()
    assert read_license_terms(path) == LicenseTermsSet()


def test_replacing_a_license_with_no_text_replaces_it_alone(tmp_path: Path) -> None:
    """**Test steps:**

    * open a record holding two licenses, a text for the first, and replace the second
    * verify the second is replaced in its place and the first's text is untouched
    """
    model = opened(held_by(record(tmp_path), ID, "fab-ue-only"))

    model.replace_license("fab-ue-only", AssetLicense("cc-by-4.0"), keep_text=False)

    assert model.licenses == [AssetLicense(ID), AssetLicense("cc-by-4.0")]
    assert model.license_terms == LicenseTermsSet({ID: TERMS})


@mark.parametrize(("old", "new"), [(ID, AssetLicense(ID)), ("other", AssetLicense("cc-by-4.0"))])
def test_replacing_with_the_same_license_or_one_not_held_changes_nothing(
    tmp_path: Path, old: str, new: AssetLicense
) -> None:
    """**Test steps:**

    * replace a license with itself, and one the record does not hold
    * verify the model is clean and holds what it did
    """
    model = opened(held_by(record(tmp_path), ID))

    model.replace_license(old, new, keep_text=False)

    assert model.licenses == [AssetLicense(ID)]
    assert held(model) == TERMS
    assert not model.dirty


def test_a_text_read_for_a_license_is_held_as_read(tmp_path: Path) -> None:
    """A preset's text arrives with where and when it was read, and is an edit of the record (#705).

    **Test steps:**

    * open a record holding a license with no text, and hold a text read for it
    * verify the model holds the text as read, and is dirty
    """
    model = opened(held_by(record(tmp_path, None), ID))

    model.hold_license_text(ID, TERMS)

    assert held(model) == TERMS
    assert model.dirty


def test_a_text_read_for_a_license_no_longer_held_is_not_kept(tmp_path: Path) -> None:
    """**Test steps:**

    * open a record holding no license, and hold a text read for one
    * verify the model holds no text and is clean
    """
    model = opened(record(tmp_path, None))

    model.hold_license_text(ID, TERMS)

    assert model.license_terms is None
    assert not model.dirty


def test_a_text_read_for_a_document_locked_meanwhile_is_not_kept(tmp_path: Path) -> None:
    """A locked document takes no edit, a text that arrives late included.

    **Test steps:**

    * open a record holding a license with no text, lock the document, and hold a text read for the license
    * verify the model holds no text and is clean
    """
    model = opened(held_by(record(tmp_path, None), ID))
    model.lock_reasons = [LockReason(LockReasonKind.INVALID_FIELD, "a field is wrong")]

    model.hold_license_text(ID, TERMS)

    assert model.license_terms is None
    assert not model.dirty


def test_removing_a_license_takes_its_saved_text_out_of_the_file(tmp_path: Path) -> None:
    """Unlike an emptied text, a license taken off the record has no text to keep (#705).

    **Test steps:**

    * open a record holding two licenses, a text saved for the first, and remove the first
    * verify the model holds the second alone and no text for the first, and is dirty
    * save and verify the sidecar holds no text for it
    """
    path = held_by(record(tmp_path), ID, "fab-ue-only")
    model = opened(path)

    model.remove_license(ID)

    assert model.licenses == [AssetLicense("fab-ue-only")]
    assert held(model) is None
    assert model.dirty
    model.save()
    assert read_license_terms(path) == LicenseTermsSet()


def test_removing_a_license_whose_text_was_never_saved_leaves_no_file_to_write(tmp_path: Path) -> None:
    """**Test steps:**

    * open a record with no sidecar, type a text for its license, and remove the license
    * verify the model holds no license and no texts, and a save writes no sidecar
    """
    path = held_by(record(tmp_path, None), ID)
    model = opened(path)
    model.edit_license(ID, text="Mine")

    model.remove_license(ID)

    assert model.licenses == []
    assert model.license_terms is None
    model.save()
    assert not license_terms_path(path).exists()


def test_removing_a_license_with_no_text_keeps_the_others(tmp_path: Path) -> None:
    """**Test steps:**

    * open a record holding two licenses, a text for the first, and remove the second
    * verify the first and its text are untouched
    """
    model = opened(held_by(record(tmp_path), ID, "fab-ue-only"))

    model.remove_license("fab-ue-only")

    assert model.licenses == [AssetLicense(ID)]
    assert model.license_terms == LicenseTermsSet({ID: TERMS})


# endregion
