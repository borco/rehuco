"""Tests for the .rehu document model: round-trip fidelity and field accessors."""

import json
from pathlib import Path
from typing import Any, Final

import pytest
from pytest import mark, param
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
            "some_future_source_key": "kept verbatim",
        },
        {"title": "Extended Cut", "publisher": "Second Platform", "url": "https://second.example/x"},
    ],
    "authors": ["First Author", "Second Author"],
    "released": "2025-03",
    "original_size": 5368709120,
    "current_size": 1073741824,
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
    assert doc.format_version == 1
    assert doc.type == "Tutorial"
    assert doc.id == "550e8400-e29b-41d4-a716-446655440000"
    assert doc.title == "Intro to Sculpting"
    assert doc.publisher == "Example Publisher"
    assert doc.url == "https://example.com/x"
    assert doc.authors == ["First Author", "Second Author"]
    assert doc.released == "2025-03"
    assert doc.original_size == 5368709120
    assert doc.current_size == 1073741824
    assert doc.advertised_tags == ["sculpting", "3d"]
    assert doc.extra_tags == ["rework"]
    assert doc.description.startswith("# Intro to Sculpting")


def test_roundtrip_preserves_unknown_fields(mocker: MockerFixture) -> None:
    """A load/edit/save cycle keeps unknown top-level keys, an unknown sibling key inside a known
    nested object (a ``sources[]`` entry), and the plugin block, in the saved JSON
    ([[data-model#schema-version]]'s preserve-unknown-fields guarantee).

    **Test steps:**

    * mock ``Path.read_text`` to return the Tutorial fixture
    * mock ``atomic_write_text`` to capture the written JSON
    * load, edit the title, save
    * parse the captured JSON and verify the edit applied, and every unknown key -- top-level,
      nested-sibling, and the plugin block -- survived untouched
    """
    doc = load_doc(mocker, TUTORIAL)
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.title = "Renamed Title"
    doc.save()

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["sources"][0]["title"] == "Renamed Title"
    assert saved["sources"][0]["some_future_source_key"] == "kept verbatim"
    assert saved["tutorial"] == {"format_version": 0, "rating": 4, "complete": True}
    assert saved["some_future_key"] == {"nested": [1, 2, 3]}
    assert saved["updated"] == TUTORIAL["updated"]  # A0 does not auto-touch timestamps


def test_format_version_defaults_to_zero_when_absent() -> None:
    """``format_version`` reads ``0`` for a document with no such key (the historical `.tc`-origin
    shape, format v0, [[acquisition-tooling#tc-to-rehu]]).

    **Test steps:**

    * construct a document with no ``format_version`` key
    * verify the accessor reads ``0``
    """
    assert RehuDocument({"type": "Tutorial"}).format_version == 0


def test_format_version_defensively_coerces_a_malformed_value() -> None:
    """A non-``int`` (or ``bool``) stored ``format_version`` reads back as ``0`` rather than raising
    or returning the malformed value (#35).

    **Test steps:**

    * construct a document whose ``format_version`` is a string
    * verify the accessor reads ``0``
    """
    assert RehuDocument({"format_version": "v1"}).format_version == 0


def test_save_stamps_current_format_version_when_older(mocker: MockerFixture) -> None:
    """Saving a document loaded at an older ``format_version`` upgrades it to
    ``RehuDocument.CURRENT_FORMAT_VERSION`` -- the upgrade-on-write half of
    [[data-model#schema-version]].

    **Test steps:**

    * load a document whose ``format_version`` is below the current one (and one with the key absent)
    * save each
    * verify the saved JSON's ``format_version`` is ``CURRENT_FORMAT_VERSION``
    """
    for original in (RehuDocument.CURRENT_FORMAT_VERSION - 1, None):
        data = {"type": "Tutorial"} if original is None else {"type": "Tutorial", "format_version": original}
        doc = load_doc(mocker, data)
        mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

        doc.save()

        saved = json.loads(mock_write.call_args[0][1])
        assert saved["format_version"] == RehuDocument.CURRENT_FORMAT_VERSION


def test_save_does_not_downgrade_a_newer_format_version(mocker: MockerFixture) -> None:
    """Saving a document loaded at a *newer* ``format_version`` than this build understands leaves
    the stamped version untouched -- lowering it would mislabel a file that still carries fields from
    that newer schema ([[data-model#schema-version]]'s "must fail safe, not lossy" rule).

    **Test steps:**

    * load a document whose ``format_version`` is above the current one
    * save it
    * verify the saved JSON's ``format_version`` is still the newer, unlowered value
    """
    newer_version = RehuDocument.CURRENT_FORMAT_VERSION + 1
    doc = load_doc(mocker, {"type": "Tutorial", "format_version": newer_version})
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.save()

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["format_version"] == newer_version


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


def test_released_setter_replaces_the_value() -> None:
    """Setting ``released`` replaces the stored partial-precision date.

    **Test steps:**

    * construct a document with an existing ``released`` value
    * assign a new value
    * verify the document reflects it
    """
    doc = RehuDocument({"released": "2024"})
    doc.released = "2025-03-08"
    assert doc.released == "2025-03-08"


@mark.parametrize("attr", [param("original_size", id="original_size"), param("current_size", id="current_size")])
def test_size_field_defaults_to_zero_when_absent(attr: str) -> None:
    """``original_size``/``current_size`` default to ``0`` when the key is absent (e.g. a Collection).

    **Test steps:**

    * construct a document with neither key
    * verify the attribute reads ``0``
    """
    doc = RehuDocument({})
    assert getattr(doc, attr) == 0


@mark.parametrize(
    ("attr", "malformed"),
    [
        param("original_size", "5 GB", id="original_size-non-int-string"),
        param("original_size", True, id="original_size-bool"),
        param("current_size", "5 GB", id="current_size-non-int-string"),
        param("current_size", True, id="current_size-bool"),
    ],
)
def test_size_field_defensively_coerces_a_malformed_value(attr: str, malformed: object) -> None:
    """A non-``int`` (or ``bool``, technically an ``int`` subclass) stored value reads back as ``0``
    rather than raising or returning the malformed value (#35).

    **Test steps:**

    * construct a document with ``attr`` set to a malformed value
    * verify the attribute reads ``0``
    """
    doc = RehuDocument({attr: malformed})
    assert getattr(doc, attr) == 0


@mark.parametrize("attr", [param("original_size", id="original_size"), param("current_size", id="current_size")])
def test_size_field_setter_replaces_the_value(attr: str) -> None:
    """Setting ``original_size``/``current_size`` replaces the stored byte count.

    **Test steps:**

    * construct a document with an existing value
    * assign a new value
    * verify the document reflects it
    """
    doc = RehuDocument({attr: 100})
    setattr(doc, attr, 5368709120)
    assert getattr(doc, attr) == 5368709120


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


def test_hidden_images_defaults_to_empty_when_absent_or_malformed() -> None:
    """``hidden_images`` reads as an empty list when the key is missing or not a list (#35).

    **Test steps:**

    * verify a document with no ``hidden_images`` key reads ``[]``
    * verify a document whose ``hidden_images`` is a non-list reads ``[]``
    """
    assert not RehuDocument({}).hidden_images
    assert not RehuDocument({"hidden_images": "info00.jpg"}).hidden_images


def test_hidden_images_reads_and_coerces_stored_names() -> None:
    """``hidden_images`` reads the stored filename list, coercing entries to strings.

    **Test steps:**

    * construct a document with a mixed-type ``hidden_images`` list
    * verify every entry is read back as a string
    """
    doc = RehuDocument({"hidden_images": ["info00.jpg", 7]})
    assert doc.hidden_images == ["info00.jpg", "7"]


def test_hidden_images_setter_replaces_the_list() -> None:
    """Setting ``hidden_images`` replaces the stored list with an independent copy.

    **Test steps:**

    * construct a document with an existing ``hidden_images`` list
    * assign a new list
    * verify the document reflects it and mutating the input list afterward has no effect
    """
    doc = RehuDocument({"hidden_images": ["old00.jpg"]})
    new_hidden = ["new00.jpg"]
    doc.hidden_images = new_hidden
    new_hidden.append("mutated-after-assignment")
    assert doc.hidden_images == ["new00.jpg"]


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


def test_reload_replaces_data_in_place_from_disk(mocker: MockerFixture) -> None:
    """``reload`` re-reads the document's own path and refreshes its data, keeping ``data``'s identity.

    **Test steps:**

    * load a document, then mock ``Path.read_text`` to return different content
    * call ``reload()``
    * verify the document's fields reflect the new content, and ``data`` is still the same object
    """
    doc = load_doc(mocker, TUTORIAL)
    original_data = doc.data

    mocker.patch.object(
        Path, "read_text", return_value=json.dumps({"type": "Tutorial", "authors": ["Reloaded Author"]})
    )
    doc.reload()

    assert doc.data is original_data
    assert doc.authors == ["Reloaded Author"]
    assert doc.title == ""


def test_reload_without_a_path_raises() -> None:
    """Calling ``reload`` on a document never loaded from a file raises.

    **Test steps:**

    * construct a document with no ``path``
    * call ``reload()``
    * verify ``ValueError`` is raised
    """
    doc = RehuDocument({"type": "Tutorial"})
    with pytest.raises(ValueError, match="no path to reload from"):
        doc.reload()


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


def test_remove_type_field_deletes_a_present_key() -> None:
    """``remove_type_field`` deletes a key from the block and reports it was present.

    **Test steps:**

    * construct a Tutorial document whose block holds an extra (unknown) key
    * remove that key
    * verify it returns ``True`` and the key is gone while the rest of the block is intact
    """
    doc = RehuDocument({"type": "Tutorial", "tutorial": {"rating": 5, "mystery": 42}})
    assert doc.remove_type_field("mystery") is True
    assert doc.data["tutorial"] == {"rating": 5}


def test_remove_type_field_is_a_noop_when_absent() -> None:
    """``remove_type_field`` reports ``False`` when the key or block is absent, changing nothing.

    **Test steps:**

    * a Tutorial document with a block missing the key -> ``False``
    * a document with no block at all -> ``False``
    """
    doc = RehuDocument({"type": "Tutorial", "tutorial": {"rating": 5}})
    assert doc.remove_type_field("mystery") is False
    assert doc.data["tutorial"] == {"rating": 5}

    blockless = RehuDocument({"type": "Tutorial"})
    assert blockless.remove_type_field("mystery") is False


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
