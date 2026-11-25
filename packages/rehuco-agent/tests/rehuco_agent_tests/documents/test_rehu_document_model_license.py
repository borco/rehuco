"""Tests for a document model holding a record's license text (#688, [[assets#licenses]]): shown as read, edited as an
edit of the record -- dirty, saved to the ``.rehuterms`` with the record, reverted with it -- and never removed once
saved.

Real records under ``tmp_path``, opened the way a holder does (:func:`~.test_rehu_document_model_conflict.opened`).
"""

import datetime
from pathlib import Path
from typing import Final

from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_model import DEFAULT_LICENSE_TITLE
from rehuco_core import (
    LICENSE_TERMS_KEY,
    LicenseTerms,
    LicenseTermsError,
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


def record(tmp_path: Path, terms: LicenseTerms | None = TERMS) -> Path:
    """A record, and a ``.rehuterms`` beside it when given terms.

    :param tmp_path: the folder.
    :param terms: what the sidecar holds; none made for ``None``.
    :returns: the record's path.
    """
    path = tmp_path / "info.rehu"
    write_record(path, "Pack")
    if terms is not None:
        write_license_terms(path, terms)
    return path


# region what it shows


def test_a_record_with_a_sidecar_is_opened_showing_its_terms_and_clean(tmp_path: Path) -> None:
    """Seeding the terms is no edit.

    **Test steps:**

    * open a record that has a sidecar
    * verify the model holds its terms, is clean, and calls nothing unreadable
    """
    model = opened(record(tmp_path))

    assert model.license_terms == TERMS
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
    model.edit_license(text="Mine")
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

    * open a record with a sidecar and change the terms' text and title
    * verify the document is dirty and holds both, the url and date kept
    * save
    * verify it is clean, the sidecar holds the edit, and the record's file has no license key
    """
    path = record(tmp_path)
    model = opened(path)

    model.edit_license(text="# Mine\n")
    model.edit_license(title="My license")
    assert model.dirty
    model.save()

    expected = LicenseTerms("My license", TERMS.url, READ, "# Mine\n")
    assert model.license_terms == expected
    assert not model.dirty
    assert read_license_terms(path) == expected
    assert LICENSE_TERMS_KEY not in stored(path).data


def test_a_change_that_changes_nothing_is_no_edit(tmp_path: Path) -> None:
    """Typing the same text again, or nothing into a record with none, leaves the document clean.

    **Test steps:**

    * open a record with a sidecar and give its own text and title back
    * open one with none and give it nothing
    * verify both are clean
    """
    held = opened(record(tmp_path))
    other = tmp_path / "other"
    other.mkdir()
    empty = opened(record(other, None))

    held.edit_license(title=TERMS.title, text=TERMS.text)
    empty.edit_license(title="", text="")
    empty.edit_license()

    assert not held.dirty
    assert not empty.dirty
    assert empty.license_terms is None


@mark.parametrize(
    ("license_id", "title", "expected"),
    [
        ("fab-standard", None, "fab-standard"),
        (None, None, DEFAULT_LICENSE_TITLE),
        ("fab-standard", "Mine", "Mine"),
    ],
)
def test_text_typed_into_a_record_with_none_makes_terms_of_its_own(
    tmp_path: Path, mocker: MockerFixture, license_id: str | None, title: str | None, expected: str
) -> None:
    """The terms are written for this item alone: no url, read today, titled as typed, else by the record's license
    id, else plainly.

    **Test steps:**

    * open a record with no sidecar, giving it a license id or not
    * type a text, with a title or without
    * verify the terms have the expected title, no url, today's date and the text, and the document is dirty
    """
    mocker.patch("rehuco_agent.documents.rehu_document_model.date").today.return_value = TODAY
    model = opened(record(tmp_path, None))
    model.license = license_id

    model.edit_license(title=title, text="Mine")

    assert model.license_terms == LicenseTerms(expected, None, TODAY, "Mine")
    assert model.dirty


def test_a_title_typed_alone_makes_terms_with_no_text(tmp_path: Path, mocker: MockerFixture) -> None:
    """A title is enough to start terms, and empty text is still text.

    **Test steps:**

    * open a record with no sidecar and type a title
    * verify the terms hold it with an empty text
    """
    mocker.patch("rehuco_agent.documents.rehu_document_model.date").today.return_value = TODAY
    model = opened(record(tmp_path, None))

    model.edit_license(title="Mine")

    assert model.license_terms == LicenseTerms("Mine", None, TODAY, "")


def test_terms_typed_and_emptied_again_before_a_save_are_gone(tmp_path: Path) -> None:
    """Nothing was ever saved, so nothing is left behind: the document holds no terms and no key for them.

    **Test steps:**

    * open a record with no sidecar, type a text and empty it again
    * verify no terms are held and the document holds no key for them
    * save and verify no sidecar was made
    """
    path = record(tmp_path, None)
    model = opened(path)

    model.edit_license(text="Mine")
    model.edit_license(text="")
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

    model.edit_license(text="")
    model.save()

    assert read_license_terms(path) == LicenseTerms(TERMS.title, TERMS.url, READ, "")


def test_a_revert_goes_back_to_the_file_terms(tmp_path: Path) -> None:
    """An edit not saved is dropped with the rest of the record's.

    **Test steps:**

    * open a record with a sidecar, edit its text and revert
    * verify the model holds the file's terms and is clean
    """
    path = record(tmp_path)
    model = opened(path)
    model.edit_license(text="Mine")

    model.revert()

    assert model.license_terms == TERMS
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

    write_license_terms(path, newer)
    signature = Records().signature(ResourceKey(path))
    assert signature is not None
    model.note_file_signature(*signature)

    assert model.license_terms == newer
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
    model.edit_license(text="Mine")

    write_license_terms(path, LicenseTerms(TERMS.title, TERMS.url, READ, "# Theirs\n"))
    signature = Records().signature(ResourceKey(path))
    assert signature is not None
    model.note_file_signature(*signature)

    assert model.changed_on_disk
    assert model.license_terms is not None and model.license_terms.text == "Mine"


# endregion


# region a title being typed, and edits kept from elsewhere


def test_a_title_typed_through_the_default_one_is_kept_as_typed(tmp_path: Path) -> None:
    """A title on its way to something longer may spell the default one for a keystroke: the terms are not taken away
    under the typing, which would empty the line being typed in.

    **Test steps:**

    * open a record with none and type a title one keystroke at a time through the default title
    * verify the terms hold each as typed, the default spelling included
    * empty the title again and verify the terms, never saved and holding nothing, are gone
    """
    model = opened(record(tmp_path, None))

    for typed in ("Licens", DEFAULT_LICENSE_TITLE, DEFAULT_LICENSE_TITLE + " Agreement"):
        model.edit_license(title=typed)
        assert model.license_terms is not None and model.license_terms.title == typed
    model.edit_license(title="")

    assert model.license_terms is None


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
