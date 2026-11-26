"""Tests for the license sidecar's names, parsing, serializing, reading and writing (#677, #705,
[[assets#licenses]])."""

import datetime
import json
from pathlib import Path
from typing import Final

from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    LICENSE_SIDECAR_SUFFIX,
    LicenseTerms,
    LicenseTermsError,
    LicenseTermsSet,
    is_license_terms_name,
    license_terms_owner,
    license_terms_path,
    read_license_terms,
    write_license_terms,
)

MODULE: Final = "rehuco_core.license_terms"
NAME: Final = "foo.rehuterms"
READ: Final = datetime.date(2026, 11, 18)
TERMS: Final = LicenseTerms("Standard License", "https://example.com/eula", READ, "# Terms\n\nUse freely.\n")
CUSTOM: Final = LicenseTerms("Custom", None, READ, "Mine.")
SET: Final = LicenseTermsSet({"fab-standard": TERMS, "mine": CUSTOM})


# region Names


def test_the_sidecar_sits_beside_its_record_under_its_stem() -> None:
    """``<stem>.rehuterms`` beside the record, for a named record and for a directory-scoped ``info.rehu``.

    **Test steps:**

    * name the sidecar of ``foo.rehu`` and of ``info.rehu``
    * verify each is the record's stem plus the suffix, in the record's folder
    """
    assert license_terms_path(Path("/r/foo.rehu")) == Path("/r/foo" + LICENSE_SIDECAR_SUFFIX)
    assert license_terms_path(Path("/r/info.rehu")) == Path("/r/info.rehuterms")


@mark.parametrize(
    ("filename", "owner"),
    [
        ("foo.rehuterms", "foo"),
        ("Foo.REHUTERMS", "Foo"),
        (".rehuterms", None),
        ("foo.rehu", None),
        ("foo.rehuterms.lock", None),
        ("foo.txt", None),
    ],
)
def test_a_license_sidecar_is_known_by_its_name_alone(filename: str, owner: str | None) -> None:
    """The suffix is matched without case and needs a stem in front of it.

    **Test steps:**

    * ask whose sidecar ``filename`` is, and whether it is one
    * verify the owner stem, or ``None`` for a name that is none
    """
    assert license_terms_owner(filename) == owner
    assert is_license_terms_name(filename) is (owner is not None)


# endregion

# region Parsing and serializing


def test_a_sidecar_is_json_keyed_by_license_id_with_each_text_as_its_lines() -> None:
    """The file is a ``.rehu``'s kind of JSON: an object by license id, each text a list of its lines (#705).

    **Test steps:**

    * serialize two licenses' texts
    * verify the file is two-space-indented JSON ending in a newline, each entry's keys in order, the texts split at
      each line end, and no ``url`` key for the one with none
    """
    text = SET.to_text()

    assert text.endswith("}\n")
    assert text.startswith('{\n  "fab-standard": {\n    "title": "Standard License",\n')
    assert json.loads(text) == {
        "fab-standard": {
            "title": "Standard License",
            "url": "https://example.com/eula",
            "read": "2026-11-18",
            "text": ["# Terms", "", "Use freely.", ""],
        },
        "mine": {"title": "Custom", "read": "2026-11-18", "text": ["Mine."]},
    }


@mark.parametrize(
    "body",
    [
        "Line with two trailing spaces  \nnext",
        "",
        "\n",
        'Ünïcode — "quotes" and \\ backslash\tand a tab',
        "Above\n\n---\n\nBelow\n",
    ],
)
def test_every_text_round_trips_exactly(body: str) -> None:
    """A text comes back as it went, trailing spaces, empty lines, characters JSON escapes and a rule line included.

    **Test steps:**

    * serialize a set holding ``body`` and parse it back
    * verify the set is equal
    """
    terms = LicenseTermsSet({"x": LicenseTerms("T", None, READ, body)})

    assert LicenseTermsSet.parse(terms.to_text(), NAME) == terms


def test_characters_are_written_as_they_are() -> None:
    """``ensure_ascii`` is off, as for a ``.rehu``, so a text reads in the file as typed.

    **Test steps:**

    * serialize a text with accented letters
    * verify they are in the file unescaped
    """
    assert "Ünï" in LicenseTermsSet({"x": LicenseTerms("T", None, READ, "Ünï")}).to_text()


def test_two_sets_of_the_same_texts_are_equal_in_any_order() -> None:
    """A reorder of a record's licenses is no change to its texts, so a save never rewrites the sidecar for it.

    **Test steps:**

    * build the set's two texts in the other order
    * verify the sets are equal
    """
    assert LicenseTermsSet({"mine": CUSTOM, "fab-standard": TERMS}) == SET


@mark.parametrize(
    ("text", "reason"),
    [
        ("", "invalid JSON"),
        ("title: T\n", "invalid JSON"),
        ("[]", "expected a JSON object"),
        ('{"x": "terms"}', "x: The license terms are not an object"),
        ('{"x": {"read": "2026-11-18", "text": []}}', "x: .*need a title"),
        ('{"x": {"title": 4, "read": "2026-11-18", "text": []}}', "x: .*need a title"),
        ('{"x": {"title": "T", "read": "2026-11-18", "text": "one string"}}', "x: .*need a title and a text"),
        ('{"x": {"title": "T", "read": "2026-11-18", "text": ["a", 4]}}', "x: .*need a title and a text"),
        ('{"x": {"title": "T", "read": "2026-11-18", "text": [], "url": 4}}', "x: .*url that is a string"),
        ('{"x": {"title": "T", "text": []}}', "x: .*date is not a day"),
        ('{"x": {"title": "T", "read": "yesterday", "text": []}}', "x: .*date is not a day"),
    ],
)
def test_a_sidecar_that_cannot_be_read_is_refused_with_its_name(text: str, reason: str) -> None:
    """Every malformed file is a :class:`LicenseTermsError` that starts with the file's name, and an entry's with its
    license id.

    **Test steps:**

    * parse ``text``
    * verify the refusal starts with the file name and names ``reason``
    """
    with raises(LicenseTermsError, match=f"^{NAME}: {reason}"):
        LicenseTermsSet.parse(text, NAME)


def test_terms_round_trip_through_the_data_a_document_holds_them_as() -> None:
    """A document holds its texts as JSON primitives by license id (#688, #705), a date as its day and a text as one
    string, and reads the same texts back; no url is no key.

    **Test steps:**

    * turn a set into data
    * verify the keys, the day as text, the text as one string, and that ``from_data`` reads it back equal
    """
    assert SET.to_data() == {
        "fab-standard": {
            "title": "Standard License",
            "url": "https://example.com/eula",
            "read": "2026-11-18",
            "text": "# Terms\n\nUse freely.\n",
        },
        "mine": {"title": "Custom", "read": "2026-11-18", "text": "Mine."},
    }
    assert LicenseTermsSet.from_data(SET.to_data()) == SET


@mark.parametrize(
    "data",
    [
        "terms",
        {"x": "terms"},
        {"x": {"url": "u", "read": "2026-11-18", "text": ""}},
        {"x": {"title": "T", "read": "2026-11-18"}},
        {"x": {"title": "T", "text": "", "read": "2026-11-18", "url": 3}},
        {"x": {"title": "T", "text": ""}},
        {"x": {"title": "T", "text": "", "read": "yesterday"}},
        {"x": {"title": "T", "text": "", "read": 20261118}},
        {"x": {"title": "T", "text": ["a"], "read": "2026-11-18"}},
    ],
)
def test_data_that_is_not_terms_is_refused(data: object) -> None:
    """What a kept payload might hold under the key, once someone edited it, is refused rather than guessed at.

    **Test steps:**

    * read data that is no object, or an entry with no title, no text, a url that is no string, a date that is no
      day, or the file's list of lines where one string belongs
    * verify each raises ``LicenseTermsError``
    """
    with raises(LicenseTermsError):
        LicenseTermsSet.from_data(data)


def test_one_license_text_is_set_in_its_place_added_last_and_removed() -> None:
    """``with_terms`` keeps a replaced text where it was, puts a new one last, and drops one set to ``None``.

    **Test steps:**

    * replace the first text, add a third, and remove the second
    * verify each set's ids in order and its texts
    """
    other = LicenseTerms("Other", None, READ, "Other.")

    replaced = SET.with_terms("fab-standard", other)
    added = SET.with_terms("cc-by-4.0", other)
    removed = SET.with_terms("mine", None)

    assert list(replaced.terms) == ["fab-standard", "mine"]
    assert replaced.get("fab-standard") == other
    assert list(added.terms) == ["fab-standard", "mine", "cc-by-4.0"]
    assert removed == LicenseTermsSet({"fab-standard": TERMS})
    assert SET.get("nothing") is None


def test_a_text_kept_under_another_id_keeps_its_place() -> None:
    """``renamed`` moves a text to a new id where it was, drops a text the new id already had, and gives the set back
    for an id with no text or a rename to itself.

    **Test steps:**

    * rename the first id to a new one, then to the second id
    * verify the order and texts, and that renaming an absent id or to itself gives the set back
    """
    assert list(SET.renamed("fab-standard", "fab-new").terms) == ["fab-new", "mine"]
    assert SET.renamed("fab-standard", "fab-new").get("fab-new") == TERMS
    assert SET.renamed("fab-standard", "mine") == LicenseTermsSet({"mine": TERMS})
    assert SET.renamed("nothing", "mine") is SET
    assert SET.renamed("mine", "mine") is SET


# endregion

# region Reading and writing


def test_a_record_with_no_sidecar_reads_none(tmp_path: Path) -> None:
    """An absent file is no terms, not an error.

    **Test steps:**

    * read the sidecar of a record that has none
    * verify ``None``
    """
    assert read_license_terms(tmp_path / "foo.rehu") is None


def test_a_written_sidecar_reads_back(tmp_path: Path) -> None:
    """Writing replaces what the file held, and reading returns it.

    **Test steps:**

    * write terms, then other terms, for one record
    * verify the file is at the record's sidecar path and reads back the later terms
    """
    record = tmp_path / "foo.rehu"
    write_license_terms(record, SET)
    later = LicenseTermsSet({"other": LicenseTerms("Other", None, READ, "Later.\n")})

    write_license_terms(record, later)

    assert (tmp_path / NAME).is_file()
    assert read_license_terms(record) == later


def test_a_write_goes_through_the_atomic_write(tmp_path: Path, mocker: MockerFixture) -> None:
    """A sidecar is written as a ``.rehu`` is, by a temp sibling and a replace, never in place.

    **Test steps:**

    * patch the atomic write and write terms
    * verify it was handed the sidecar's path and the serialized text
    """
    atomic = mocker.patch(f"{MODULE}.atomic_write_text")

    write_license_terms(tmp_path / "foo.rehu", SET)

    atomic.assert_called_once_with(tmp_path / NAME, SET.to_text())


def test_an_unparsable_sidecar_is_refused_on_read(tmp_path: Path) -> None:
    """A file that is no sidecar raises rather than reading as empty terms.

    **Test steps:**

    * write junk at a record's sidecar path
    * verify reading it raises, naming the file
    """
    (tmp_path / NAME).write_text("not json", encoding="utf-8")

    with raises(LicenseTermsError, match=NAME):
        read_license_terms(tmp_path / "foo.rehu")


def test_a_sidecar_saved_with_a_byte_order_mark_reads(tmp_path: Path) -> None:
    """An editor's byte-order mark in front of the object is no part of the text, so the file reads as without it.

    **Test steps:**

    * write a sidecar's text behind a UTF-8 byte-order mark
    * verify it reads back as the terms
    """
    (tmp_path / NAME).write_bytes(b"\xef\xbb\xbf" + SET.to_text().encode("utf-8"))

    assert read_license_terms(tmp_path / "foo.rehu") == SET


def test_a_sidecar_that_is_not_utf8_is_refused_on_read(tmp_path: Path) -> None:
    """Bytes that are not UTF-8 are a :class:`LicenseTermsError` like any other unreadable sidecar, never a bare
    decoding error.

    **Test steps:**

    * write bytes that are not UTF-8 at a record's sidecar path
    * verify reading it raises, naming the file
    """
    (tmp_path / NAME).write_bytes(b'{"x": {"title": "\xff\xfe"}}')

    with raises(LicenseTermsError, match=f"^{NAME}: not UTF-8 text"):
        read_license_terms(tmp_path / "foo.rehu")


def test_an_oversized_sidecar_is_refused_before_it_is_read(tmp_path: Path, mocker: MockerFixture) -> None:
    """The same size cap a record is held to (:mod:`rehuco_core.rehu_parse_limits`).

    **Test steps:**

    * write a sidecar and make the cap report it oversized
    * verify reading raises, naming the file and saying it refuses to parse
    """
    (tmp_path / NAME).write_text(SET.to_text(), encoding="utf-8")
    mocker.patch(f"{MODULE}.oversized_file_reason", return_value="too big")

    with raises(LicenseTermsError, match=f"^{NAME}: refusing to parse — too big"):
        read_license_terms(tmp_path / "foo.rehu")


# endregion
