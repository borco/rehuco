"""Tests for the .rehu document model: round-trip fidelity and field accessors."""

import json
from pathlib import Path
from typing import Any, Final

import pytest
from pytest_mock import MockerFixture
from rehuco_core import RehuDocument, RehuFormatError

# A Tutorial document exercising multi-source, a plugin block, and unknown keys ([[field-schema#example-files]]).
TUTORIAL: Final = {
    "format_version": 1,
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "Tutorial",
    "created": "2026-01-15T09:30:00Z",
    "updated": "2026-06-20T14:12:00Z",
    "sources": [
        {
            "title": "Intro to Sculpting",
            "publisher": "Example Publisher",
            "url": "https://example.com/x",
            "primary": True,
        },
        {"title": "Extended Cut", "publisher": "Second Platform", "url": "https://second.example/x"},
    ],
    "authors": ["First Author", "Second Author"],
    "released": "2025-03",
    "description": "# Intro to Sculpting\n\nSee `info01.jpg`.",
    "advertised_tags": ["sculpting", "3d"],
    "extra_tags": ["rework"],
    "tutorial": {"format_version": 0, "rating": 4, "complete": True},
    "some_future_key": {"nested": [1, 2, 3]},
}

FAKE_PATH: Final = Path("/fake/info.rehu")


def load_doc(mocker: MockerFixture, data: dict[str, Any]) -> RehuDocument:
    """Mock ``Path.read_text`` and load a ``RehuDocument`` from ``data``.

    :param mocker: pytest-mock fixture.
    :param data: dict to serialize as the file's JSON content.
    :returns: the loaded document.
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps(data))
    return RehuDocument.load(FAKE_PATH)


def test_common_field_accessors(mocker: MockerFixture) -> None:
    """Common-core accessors read the expected values off a loaded document.

    **Test steps:**

    * mock ``Path.read_text`` to return the Tutorial fixture
    * load via ``RehuDocument.load``
    * verify type/id, the primary-source-derived title/publisher/url, and the list fields
    """
    doc = load_doc(mocker, TUTORIAL)
    assert doc.path == FAKE_PATH
    assert doc.data["type"] == "Tutorial"
    assert doc.type == "Tutorial"
    assert doc.id == "550e8400-e29b-41d4-a716-446655440000"
    assert doc.title == "Intro to Sculpting"
    assert doc.publisher == "Example Publisher"
    assert doc.url == "https://example.com/x"
    assert doc.authors == ["First Author", "Second Author"]
    assert doc.released == "2025-03"
    assert doc.advertised_tags == ["sculpting", "3d"]
    assert doc.extra_tags == ["rework"]
    assert doc.description.startswith("# Intro to Sculpting")


def test_roundtrip_preserves_unknown_fields(mocker: MockerFixture) -> None:
    """A load/edit/save cycle keeps unknown keys and the plugin block in the saved JSON.

    **Test steps:**

    * mock ``Path.read_text`` to return the Tutorial fixture
    * mock ``atomic_write_text`` to capture the written JSON
    * load, edit the title, save
    * parse the captured JSON and verify the edit applied, plugin block and unknown key intact
    """
    doc = load_doc(mocker, TUTORIAL)
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.title = "Renamed Title"
    doc.save()

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["sources"][0]["title"] == "Renamed Title"
    assert saved["tutorial"] == {"format_version": 0, "rating": 4, "complete": True}
    assert saved["some_future_key"] == {"nested": [1, 2, 3]}
    assert saved["updated"] == TUTORIAL["updated"]  # A0 does not auto-touch timestamps


def test_primary_source_prefers_flagged_entry() -> None:
    """The entry flagged ``primary: true`` wins even when it is not first.

    **Test steps:**

    * construct a document with two sources where the second carries ``primary: true``
    * verify the title comes from that flagged entry
    """
    doc = RehuDocument({"sources": [{"title": "First"}, {"title": "Second", "primary": True}]})
    assert doc.title == "Second"


def test_primary_source_falls_back_to_first() -> None:
    """With no ``primary`` flag anywhere, the first source is treated as primary ([[field-schema#sources]]).

    **Test steps:**

    * construct a document with two unflagged sources
    * verify the title comes from the first entry
    """
    doc = RehuDocument({"sources": [{"title": "First"}, {"title": "Second"}]})
    assert doc.title == "First"


def test_primary_source_skips_non_object_entries() -> None:
    """Malformed non-object entries in ``sources`` are skipped, not crashed on (#35).

    **Test steps:**

    * construct a document whose ``sources`` mixes a bare string with a real source object
    * verify the title comes from the first *object* entry, past the junk
    """
    doc = RehuDocument({"sources": ["junk", {"title": "Ok"}]})
    assert doc.title == "Ok"


def test_primary_source_is_none_when_no_entry_is_an_object() -> None:
    """A ``sources`` list holding only non-object junk yields no primary source, and empty accessors (#35).

    **Test steps:**

    * construct a document whose ``sources`` holds only a bare string
    * verify ``primary_source`` is ``None`` and the title accessor returns empty instead of crashing
    """
    doc = RehuDocument({"sources": ["junk"]})
    assert doc.primary_source is None
    assert doc.title == ""


def test_title_setter_creates_primary_source_when_absent() -> None:
    """Setting the title on a source-less document creates a flagged primary entry.

    **Test steps:**

    * construct a document with no ``sources``
    * assign a title
    * verify a single primary source with that title now exists
    """
    doc = RehuDocument({"type": "Tutorial"})
    doc.title = "Brand New"
    assert doc.sources == [{"title": "Brand New", "primary": True}]


def test_publisher_setter_creates_primary_source_when_absent() -> None:
    """Setting the publisher on a source-less document creates a flagged primary entry.

    **Test steps:**

    * construct a document with no ``sources``
    * assign a publisher
    * verify a single primary source with that publisher now exists
    """
    doc = RehuDocument({"type": "Tutorial"})
    doc.publisher = "Brand New Publisher"
    assert doc.sources == [{"publisher": "Brand New Publisher", "primary": True}]


def test_url_setter_creates_primary_source_when_absent() -> None:
    """Setting the url on a source-less document creates a flagged primary entry.

    **Test steps:**

    * construct a document with no ``sources``
    * assign a url
    * verify a single primary source with that url now exists
    """
    doc = RehuDocument({"type": "Tutorial"})
    doc.url = "https://example.com/new"
    assert doc.sources == [{"url": "https://example.com/new", "primary": True}]


def test_publisher_and_url_setters_update_existing_primary_source() -> None:
    """Setting publisher/url on a document with an existing primary source updates it in place.

    **Test steps:**

    * construct a document with one flagged-primary source and one secondary source
    * assign a new publisher and url
    * verify only the primary source changed, and the secondary source is untouched
    """
    doc = RehuDocument(
        {
            "sources": [
                {"title": "First", "publisher": "Old Publisher", "url": "https://old.example/x", "primary": True},
                {"title": "Second", "publisher": "Other Publisher", "url": "https://other.example/x"},
            ]
        }
    )
    doc.publisher = "New Publisher"
    doc.url = "https://new.example/x"
    assert doc.publisher == "New Publisher"
    assert doc.url == "https://new.example/x"
    assert doc.sources[1] == {"title": "Second", "publisher": "Other Publisher", "url": "https://other.example/x"}


def test_authors_setter_replaces_the_list() -> None:
    """Setting ``authors`` replaces the stored list with an independent copy.

    **Test steps:**

    * construct a document with an existing ``authors`` list
    * assign a new list
    * verify the document reflects it and mutating the input list afterward has no effect
    """
    doc = RehuDocument({"authors": ["Old Author"]})
    new_authors = ["New Author"]
    doc.authors = new_authors
    new_authors.append("Mutated After Assignment")
    assert doc.authors == ["New Author"]


def test_advertised_tags_setter_replaces_the_list() -> None:
    """Setting ``advertised_tags`` replaces the stored list with an independent copy.

    **Test steps:**

    * construct a document with an existing ``advertised_tags`` list
    * assign a new list
    * verify the document reflects it and mutating the input list afterward has no effect
    """
    doc = RehuDocument({"advertised_tags": ["old"]})
    new_tags = ["new"]
    doc.advertised_tags = new_tags
    new_tags.append("mutated-after-assignment")
    assert doc.advertised_tags == ["new"]


def test_extra_tags_setter_replaces_the_list() -> None:
    """Setting ``extra_tags`` replaces the stored list with an independent copy.

    **Test steps:**

    * construct a document with an existing ``extra_tags`` list
    * assign a new list
    * verify the document reflects it and mutating the input list afterward has no effect
    """
    doc = RehuDocument({"extra_tags": ["old"]})
    new_tags = ["new"]
    doc.extra_tags = new_tags
    new_tags.append("mutated-after-assignment")
    assert doc.extra_tags == ["new"]


def test_save_without_path_raises() -> None:
    """Calling ``save`` on a pathless document with no explicit target raises.

    **Test steps:**

    * construct a document with no ``path``
    * call ``save()`` with no argument
    * verify ``ValueError`` is raised
    """
    doc = RehuDocument({"type": "Tutorial"})
    with pytest.raises(ValueError, match="no path given"):
        doc.save()


def test_extra_tags_returns_empty_for_non_list() -> None:
    """``extra_tags`` falls back to an empty list when the stored value is not a list.

    **Test steps:**

    * construct a document where ``extra_tags`` holds a non-list value
    * verify the property returns an empty list
    """
    doc = RehuDocument({"extra_tags": 42})
    assert not doc.extra_tags


def test_type_fields_key_is_the_type_in_snake_case() -> None:
    """The plugin-block key is the resource ``type`` in snake_case ([[field-schema#resource-types]]).

    **Test steps:**

    * verify a single-word type lowercases and a multi-word type snake-cases
    * verify a typeless document yields an empty key
    """
    assert RehuDocument({"type": "Tutorial"}).type_fields_key == "tutorial"
    assert RehuDocument({"type": "ReferenceImages"}).type_fields_key == "reference_images"
    assert RehuDocument({}).type_fields_key == ""


def test_type_field_reads_from_the_type_keyed_block() -> None:
    """``type_field`` reads a key out of the ``type``-keyed plugin block ([[field-schema#resource-types]]).

    **Test steps:**

    * construct a Tutorial document carrying a ``tutorial`` block with a rating
    * verify the stored key reads back, and an absent key returns the given default
    """
    doc = RehuDocument({"type": "Tutorial", "tutorial": {"format_version": 0, "rating": 4}})
    assert doc.type_field("rating") == 4
    assert doc.type_field("missing", 0) == 0


def test_type_field_defaults_when_block_is_absent_or_malformed() -> None:
    """``type_field`` returns the default when the block is missing or not an object (#35).

    **Test steps:**

    * verify a document with no block returns the default
    * verify a document whose block is a non-object returns the default (malformed, skipped)
    """
    assert RehuDocument({"type": "Tutorial"}).type_field("rating", 0) == 0
    assert RehuDocument({"type": "Tutorial", "tutorial": "junk"}).type_field("rating", 0) == 0
    assert RehuDocument({"type": "Tutorial", "tutorial": "junk"}).type_fields == {}


def test_set_type_field_updates_an_existing_block() -> None:
    """``set_type_field`` writes into an existing block, leaving its other keys intact.

    **Test steps:**

    * construct a Tutorial document with a ``tutorial`` block
    * set a new value on one key
    * verify the key updated and the block's ``format_version`` is untouched
    """
    doc = RehuDocument({"type": "Tutorial", "tutorial": {"format_version": 0, "rating": 1}})
    doc.set_type_field("rating", 5)
    assert doc.data["tutorial"] == {"format_version": 0, "rating": 5}


def test_set_type_field_creates_the_block_when_absent() -> None:
    """``set_type_field`` installs a fresh block keyed by ``type`` when none exists.

    **Test steps:**

    * construct a Tutorial document with no plugin block
    * set a type-field value
    * verify a ``tutorial`` block now holds it
    """
    doc = RehuDocument({"type": "Tutorial"})
    doc.set_type_field("complete", False)
    assert doc.data["tutorial"] == {"complete": False}


def test_set_type_field_replaces_a_malformed_block() -> None:
    """``set_type_field`` replaces a non-object block with a fresh one rather than crashing (#35).

    **Test steps:**

    * construct a Tutorial document whose ``tutorial`` block is a non-object
    * set a type-field value
    * verify the malformed block was replaced by a fresh object holding it
    """
    doc = RehuDocument({"type": "Tutorial", "tutorial": "junk"})
    doc.set_type_field("rating", 3)
    assert doc.data["tutorial"] == {"rating": 3}


def test_load_rejects_invalid_json(mocker: MockerFixture) -> None:
    """A ``.rehu`` with malformed JSON is rejected as a ``RehuFormatError``.

    **Test steps:**

    * mock ``Path.read_text`` to return syntactically invalid JSON
    * verify loading raises :class:`RehuFormatError` chained from ``JSONDecodeError``
    """
    mocker.patch.object(Path, "read_text", return_value="{not valid")
    with pytest.raises(RehuFormatError) as exc_info:
        RehuDocument.load(FAKE_PATH)
    assert exc_info.value.__cause__ is not None


def test_load_rejects_non_object(mocker: MockerFixture) -> None:
    """A ``.rehu`` whose top-level JSON is not an object is rejected.

    **Test steps:**

    * mock ``Path.read_text`` to return a JSON array
    * verify loading raises :class:`RehuFormatError`
    """
    mocker.patch.object(Path, "read_text", return_value="[1, 2, 3]")
    with pytest.raises(RehuFormatError):
        RehuDocument.load(FAKE_PATH)
