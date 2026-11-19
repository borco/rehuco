"""Tests for the license sidecar's names, parsing, serializing, reading and writing (#677, [[assets#licences]])."""

import datetime
from pathlib import Path
from typing import Final

from pytest import mark, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    LICENSE_SIDECAR_SUFFIX,
    LicenseTerms,
    LicenseTermsError,
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


def test_a_sidecar_round_trips_through_its_text() -> None:
    """What ``to_text`` writes ``parse`` reads back, the header and the Markdown both.

    **Test steps:**

    * serialize terms with a url
    * verify the text opens with the fence and carries the header keys in order
    * parse it back and verify the terms are equal
    """
    text = TERMS.to_text()

    assert text.startswith("---\ntitle: Standard License\nurl: https://example.com/eula\nread: 2026-11-18\n---\n\n")
    assert LicenseTerms.parse(text, NAME) == TERMS


def test_terms_with_no_url_write_no_url_key() -> None:
    """No ``url`` means terms written for the item alone, which nothing refreshes.

    **Test steps:**

    * serialize terms whose url is ``None``
    * verify the header has no ``url`` key
    * parse it back and verify the url is still ``None``
    """
    terms = LicenseTerms("Custom", None, READ, "Mine.\n")

    text = terms.to_text()

    assert "url" not in text
    assert LicenseTerms.parse(text, NAME) == terms


def test_markdown_that_holds_a_fence_line_is_not_cut_short() -> None:
    """Only the header's own closing fence ends it: a ``---`` rule in the terms stays text.

    **Test steps:**

    * round-trip terms whose Markdown holds a ``---`` line
    * verify the Markdown came back whole
    """
    terms = LicenseTerms("Rules", None, READ, "Above\n\n---\n\nBelow\n")

    assert LicenseTerms.parse(terms.to_text(), NAME) == terms


def test_windows_line_endings_parse() -> None:
    """A sidecar saved with CRLF endings still reads.

    **Test steps:**

    * parse a text whose lines end in CRLF
    * verify the header and the Markdown
    """
    text = "---\r\ntitle: T\r\nread: 2026-11-18\r\n---\r\n\r\nBody\r\n"

    parsed = LicenseTerms.parse(text, NAME)

    assert (parsed.title, parsed.url, parsed.read, parsed.text) == ("T", None, READ, "Body\r\n")


@mark.parametrize(
    ("text", "reason"),
    [
        ("", "expected a YAML header"),
        ("title: T\n", "expected a YAML header"),
        ("---\ntitle: T\n", "never closed"),
        ("---\ntitle: [\n---\n", "invalid YAML header"),
        ("---\n- a\n---\n", "expected a YAML mapping"),
        ("---\nread: 2026-11-18\n---\n", "title is missing"),
        ("---\ntitle: 4\nread: 2026-11-18\n---\n", "title is missing"),
        ("---\ntitle: T\nread: 2026-11-18\nurl: 4\n---\n", "url is not a string"),
        ("---\ntitle: T\n---\n", "read is missing"),
        ("---\ntitle: T\nread: yesterday\n---\n", "read is missing or not a date"),
        ("---\ntitle: T\nread: 2026-11-18 10:30:00\n---\n", "read is missing or not a date"),
    ],
)
def test_a_sidecar_that_cannot_be_read_is_refused_with_its_name(text: str, reason: str) -> None:
    """Every malformed header is a :class:`LicenseTermsError` that starts with the file's name.

    **Test steps:**

    * parse ``text``
    * verify the refusal starts with the file name and names ``reason``
    """
    with raises(LicenseTermsError, match=f"^{NAME}: .*{reason}"):
        LicenseTerms.parse(text, NAME)


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
    write_license_terms(record, TERMS)
    later = LicenseTerms("Other", None, READ, "Later.\n")

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

    write_license_terms(tmp_path / "foo.rehu", TERMS)

    atomic.assert_called_once_with(tmp_path / NAME, TERMS.to_text())


def test_an_unparseable_sidecar_is_refused_on_read(tmp_path: Path) -> None:
    """A file that is no sidecar raises rather than reading as empty terms.

    **Test steps:**

    * write junk at a record's sidecar path
    * verify reading it raises, naming the file
    """
    (tmp_path / NAME).write_text("not a header", encoding="utf-8")

    with raises(LicenseTermsError, match=NAME):
        read_license_terms(tmp_path / "foo.rehu")


def test_a_sidecar_saved_with_a_byte_order_mark_reads(tmp_path: Path) -> None:
    """An editor's byte-order mark in front of the header is no part of the text, so the file reads as without it.

    **Test steps:**

    * write a sidecar's text behind a UTF-8 byte-order mark
    * verify it reads back as the terms
    """
    (tmp_path / NAME).write_bytes(b"\xef\xbb\xbf" + TERMS.to_text().encode("utf-8"))

    assert read_license_terms(tmp_path / "foo.rehu") == TERMS


def test_a_sidecar_that_is_not_utf8_is_refused_on_read(tmp_path: Path) -> None:
    """Bytes that are not UTF-8 are a :class:`LicenseTermsError` like any other unreadable sidecar, never a bare
    decoding error.

    **Test steps:**

    * write bytes that are not UTF-8 at a record's sidecar path
    * verify reading it raises, naming the file
    """
    (tmp_path / NAME).write_bytes(b"---\ntitle: \xff\xfe\n---\n")

    with raises(LicenseTermsError, match=f"^{NAME}: not UTF-8 text"):
        read_license_terms(tmp_path / "foo.rehu")


def test_an_oversized_sidecar_is_refused_before_it_is_read(tmp_path: Path, mocker: MockerFixture) -> None:
    """The same size cap a record is held to (:mod:`rehuco_core.rehu_parse_limits`).

    **Test steps:**

    * write a sidecar and make the cap report it oversized
    * verify reading raises, naming the file and saying it refuses to parse
    """
    (tmp_path / NAME).write_text(TERMS.to_text(), encoding="utf-8")
    mocker.patch(f"{MODULE}.oversized_file_reason", return_value="too big")

    with raises(LicenseTermsError, match=f"^{NAME}: refusing to parse — too big"):
        read_license_terms(tmp_path / "foo.rehu")


# endregion
