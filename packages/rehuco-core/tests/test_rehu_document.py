"""Tests for the .rehu document model: round-trip fidelity and field accessors."""

# the document has a broad surface (common-core accessors, the plugin block model, format versions,
# round-trip fidelity); its test suite is correspondingly long -- one cohesive module reads better than
# an arbitrary split, so the module-length cap is lifted here rather than fragmenting it.
# pylint: disable=too-many-lines

import json
import logging
from pathlib import Path
from typing import Any, Final

import pytest
from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    DEFAULT_PLUGIN_REGISTRY,
    RESERVED_KEYS,
    TUTORIAL_PLUGIN,
    LockReasonKind,
    PluginRegistry,
    RehuDocument,
    RehuFormatError,
    authors_comma_editable,
    current_block_version,
)

# A Tutorial document exercising multi-source, a plugin block, and unknown keys ([[field-schema#example-files]]).
# Format v2: the common fields live in the ``core`` block, and every other top-level key is a plugin
# block ([[data-model#rehu-format]]). ``core["type"]`` is the plugin's declared main key, which is also
# its block's key ([[plugins#plugin-blocks]]) -- tc4's ``Tutorial`` spelling is an alias, exercised by
# the normalization tests below.
TUTORIAL: Final = {
    "format_version": 2,
    "core": {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "tutorial",
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
        "some_future_core_key": "kept verbatim",
    },
    "tutorial": {"format_version": 1, "complete": True, "users": {"admin": {"rating": 4}}},
    "some_future_key": {"nested": [1, 2, 3]},
}

FAKE_PATH: Final = Path("/fake/info.rehu")


def load_doc(
    mocker: MockerFixture, data: dict[str, Any], *, plugins: PluginRegistry = DEFAULT_PLUGIN_REGISTRY
) -> RehuDocument:
    """Mock ``Path.read_text`` and load a ``RehuDocument`` from ``data``.

    :param mocker: pytest-mock fixture.
    :param data: dict to serialize as the file's JSON content.
    :param plugins: the plugins installed for this load; defaults to this build's shipped set.
    :returns: the loaded document.
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps(data))
    return RehuDocument.load(FAKE_PATH, plugins=plugins)


def test_common_field_accessors(mocker: MockerFixture) -> None:
    """Common-core accessors read the expected values off a loaded document.

    **Test steps:**

    * mock ``Path.read_text`` to return the Tutorial fixture
    * load via ``RehuDocument.load``
    * verify type/id, the primary-source-derived title/publisher/url, and the list fields
    """
    doc = load_doc(mocker, TUTORIAL)
    assert doc.path == FAKE_PATH
    assert doc.core["type"] == "tutorial"
    assert doc.format_version == 2
    assert doc.type == "tutorial"
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
    assert saved["core"]["sources"][0]["title"] == "Renamed Title"
    assert saved["core"]["sources"][0]["some_future_source_key"] == "kept verbatim"
    assert saved["core"]["some_future_core_key"] == "kept verbatim"
    assert saved["tutorial"] == {"format_version": 1, "complete": True, "users": {"admin": {"rating": 4}}}
    assert saved["some_future_key"] == {"nested": [1, 2, 3]}
    assert saved["core"]["updated"] == TUTORIAL["core"]["updated"]  # saving does not auto-touch timestamps yet


def test_a_constructed_document_always_reports_the_version_it_actually_is() -> None:
    """Every document reports a usable version, whatever it was built from
    ([[data-model#schema-version]]).

    A payload cannot stay unstamped or mis-stamped: the migrator repairs the stamp on the way in, so no
    caller ever holds a document whose reported version disagrees with its layout. That is what lets
    :meth:`save` be a plain dump and ``RehuDocumentModel.locked`` trust the number.

    **Test steps:**

    * construct documents from an unstamped payload, an old-stamped one, and a malformed-stamp one
    * verify each reports the current version
    * verify a newer file keeps its own version -- repairing must never mean lowering
    """
    assert RehuDocument({"type": "tutorial"}).format_version == CURRENT_FORMAT_VERSION
    assert RehuDocument({"format_version": 1, "type": "tutorial"}).format_version == CURRENT_FORMAT_VERSION
    assert RehuDocument({"format_version": "junk"}).format_version == CURRENT_FORMAT_VERSION

    newer = CURRENT_FORMAT_VERSION + 1
    assert RehuDocument({"format_version": newer, "core": {}}).format_version == newer


def test_on_disk_format_version_reports_the_file_not_the_payload(mocker: MockerFixture) -> None:
    """``on_disk_format_version`` is the **file**'s version, which is what says an upgrade is pending
    ([[data-model#schema-version]], #89).

    Loading upgrades the payload, so :attr:`~RehuDocument.format_version` is always current and cannot
    answer "is the file out of date". The two differ exactly while an older file is open and unsaved.

    **Test steps:**

    * load a v1 file, and verify the payload reads current while the file still reads v1
    * load a current file, and verify the two agree
    * load a file whose stamp is malformed, and verify it reads ``0`` -- a file that exists and is out of
      date, so its upgrade is pending like any other, rather than crashing the read
      ([[data-model#write-integrity]])
    """
    older = load_doc(mocker, {"format_version": 1, "type": "tutorial", "tutorial": {"rating": 4}})
    assert older.format_version == CURRENT_FORMAT_VERSION
    assert older.on_disk_format_version == 1

    current = load_doc(mocker, {"format_version": CURRENT_FORMAT_VERSION, "core": {"type": "tutorial"}})
    assert current.on_disk_format_version == CURRENT_FORMAT_VERSION

    malformed = load_doc(mocker, {"format_version": "v1", "type": "tutorial"})
    assert malformed.on_disk_format_version == 0


def test_load_warns_about_a_file_with_a_core_block_but_no_version(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    """A **file** carrying ``core`` without a ``format_version`` is self-contradictory and says so
    ([[data-model#schema-version]]).

    ``core`` arrived with format v2 and saving has stamped since v1, so no build ever wrote such a file.
    It is read anyway -- carried verbatim, never refused -- but silently treating it as a v2 file would
    let a broken one pass for a good one.

    Only files are suspect: an in-memory payload has no stamp until the migrator adds one, so
    constructing one directly must stay quiet.

    **Test steps:**

    * load a file with a ``core`` block and no version, and verify it warns and still reads
    * construct the same payload in memory and verify it does not warn
    """
    with caplog.at_level(logging.WARNING):
        doc = load_doc(mocker, {"core": {"type": "tutorial"}})
    assert doc.type == "tutorial"
    assert "no usable format_version" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        RehuDocument({"core": {"type": "tutorial"}})
    assert not caplog.text


def test_on_disk_format_version_is_none_when_no_file_exists() -> None:
    """``None`` means **no `.rehu` to upgrade**, which is not the same as ``0`` ([[data-model#schema-version]]).

    ``0`` says a file exists and is unstamped -- older, and upgradeable. ``None`` says there is nothing
    there. Collapsing them would make an upgrade look pending on a document that was never written: a new
    document's payload is unstamped, so a naive read of its own data would report ``0``. Being handed a
    path does not help either -- a path is a destination, not a file (`create_new`) -- and a
    ``.tc``-derived document's path is a `.tc`, with no `.rehu` at it
    ([[acquisition-tooling#tc-to-rehu]]).

    **Test steps:**

    * verify a new document reads ``None``, with and without a path
    * verify a ``.tc``-derived document reads ``None`` even though it has a path and a current payload
    """
    assert RehuDocument({}).on_disk_format_version is None
    assert RehuDocument({}, Path("/fake/never-written.rehu")).on_disk_format_version is None

    tc_backed = RehuDocument({"core": {"type": "tutorial"}}, Path("/fake/info.tc"), legacy_tc=True)
    assert tc_backed.format_version == CURRENT_FORMAT_VERSION
    assert tc_backed.on_disk_format_version is None


def test_saving_updates_on_disk_format_version_to_what_was_written(mocker: MockerFixture) -> None:
    """Saving is what makes the file current, so it is what clears the pending upgrade (#89).

    **Test steps:**

    * load a v1 file and verify an upgrade reads as pending
    * save it, and verify the file's version now matches the payload's
    """
    doc = load_doc(mocker, {"format_version": 1, "type": "tutorial"})
    mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    assert doc.on_disk_format_version == 1

    doc.save()

    assert doc.on_disk_format_version == CURRENT_FORMAT_VERSION


def test_a_failed_save_leaves_on_disk_format_version_describing_the_real_file(mocker: MockerFixture) -> None:
    """A save that raises must not claim the file was upgraded ([[data-model#write-integrity]]).

    The old file is still the one on disk, so the pending upgrade is still pending.

    **Test steps:**

    * load a v1 file and make the atomic write fail
    * verify the save raises and the file's recorded version is untouched
    """
    doc = load_doc(mocker, {"format_version": 1, "type": "tutorial"})
    mocker.patch("rehuco_core.rehu_document.atomic_write_text", side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        doc.save()

    assert doc.on_disk_format_version == 1


def test_reload_adopts_the_version_the_file_now_has(mocker: MockerFixture) -> None:
    """A reload picks up an out-of-band change ([[data-model#write-integrity]]), including one that
    rewrote the file at a different version.

    **Test steps:**

    * load a v1 file, then have the file on disk change to the current version underneath it
    * reload, and verify the recorded file version follows
    """
    doc = load_doc(mocker, {"format_version": 1, "type": "tutorial"})
    assert doc.on_disk_format_version == 1

    mocker.patch.object(
        Path,
        "read_text",
        return_value=json.dumps({"format_version": CURRENT_FORMAT_VERSION, "core": {"type": "tutorial"}}),
    )
    doc.reload()

    assert doc.on_disk_format_version == CURRENT_FORMAT_VERSION


def test_format_version_defensively_coerces_a_malformed_value() -> None:
    """A non-``int`` (or ``bool``) stored ``format_version`` reads back as ``0`` rather than raising or
    returning the malformed value ([[data-model#write-integrity]]).

    Reached only by writing junk into :attr:`~RehuDocument.data` *after* construction, since the migrator
    repairs a malformed stamp on the way in -- but ``data`` is public and mutable, so the accessor still
    must not raise on one. ``bool`` counts as malformed despite being an ``int`` subclass.

    **Test steps:**

    * construct a document, then corrupt its stored ``format_version`` directly
    * verify the accessor reads ``0`` for a string and for a bool
    """
    doc = RehuDocument({"type": "tutorial"})

    doc.data["format_version"] = "v1"
    assert doc.format_version == 0

    doc.data["format_version"] = True
    assert doc.format_version == 0


def saved_json(doc: RehuDocument, mocker: MockerFixture) -> dict[str, Any]:
    """Save ``doc`` with the write mocked out and return the JSON it produced, key order intact.

    :param doc: the document to save.
    :param mocker: pytest-mock fixture.
    :returns: the parsed written JSON.
    """
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    doc.save(FAKE_PATH)
    return json.loads(mock_write.call_args[0][1])


def test_serialize_matches_exactly_what_save_writes(mocker: MockerFixture) -> None:
    """``serialize`` returns byte-for-byte what ``save`` hands ``atomic_write_text`` -- the read-only
    source view (#111) shows exactly what a save would write.

    **Test steps:**

    * load the Tutorial fixture and capture its ``serialize()`` text
    * save it with the write mocked out
    * verify the captured text equals the exact string ``save`` passed the writer
    """
    doc = load_doc(mocker, TUTORIAL)
    text = doc.serialize()
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.save(FAKE_PATH)

    assert mock_write.call_args[0][1] == text


def test_serialize_renders_a_locked_document_that_save_would_refuse() -> None:
    """``serialize`` never checks the lock state, unlike ``save`` -- a document save refuses still has a
    live in-memory payload worth showing (#111).

    **Test steps:**

    * build a locked stub standing in for an unreadable file (a save-blocking lock)
    * verify ``save`` refuses it, but ``serialize`` still renders its (migrated, stamped) content
    """
    doc = RehuDocument.locked_stub_for_error(FAKE_PATH, FileNotFoundError("missing"))
    with pytest.raises(RehuFormatError):
        doc.save()

    text = doc.serialize()
    assert '"format_version"' in text
    assert text.endswith("\n")


def test_save_writes_a_canonical_key_order(mocker: MockerFixture) -> None:
    """The file is laid out in one canonical order ([[field-schema#example-files]]).

    ``format_version`` leads (it describes the file), then ``core``, then the **active** plugin block
    (the one the ``type`` names, right after the core it belongs to), then every remaining top-level key
    alphabetically. Inside ``core``, :data:`CORE_LEADING_KEYS` lead -- what a reader opening a `.rehu`
    by hand looks for first, ending with ``sources``, which carries the title -- and the rest sort, so an
    unrecognized field is never *misplaced*, merely late.

    **Test steps:**

    * save a document whose keys were inserted in a deliberately jumbled order
    * verify the written top level (active ``tutorial`` block ahead of the alphabetized rest) and ``core``
      both come out canonical
    """
    doc = RehuDocument(
        {
            "core": {
                "extra_tags": ["x"],
                "sources": [{"title": "T", "primary": True}],
                "updated": "2026-06-20T14:12:00Z",
                "authors": ["A"],
                "type": "tutorial",
                "created": "2026-01-15T09:30:00Z",
                "id": "abc",
            },
            "reference_images": {"images_count": 12},
            "tutorial": {"rating": 4},
            "daz3d": {"sku": "1"},
        }
    )

    saved = saved_json(doc, mocker)

    assert list(saved) == ["format_version", "core", "tutorial", "daz3d", "reference_images"]
    assert list(saved["core"]) == ["type", "id", "created", "updated", "sources", "authors", "extra_tags"]


def test_save_orders_the_active_block_and_leaves_inactive_blocks_untouched(mocker: MockerFixture) -> None:
    """The active block is ordered, led by its own ``format_version``; an inactive block is copied
    exactly as found ([[plugins#plugin-blocks]]).

    An inactive block is payload this file is only custodian of, so "carried verbatim" is honoured
    literally -- reordering it would churn bytes this document has no business churning, to reorganize
    fields it does not understand.

    **Test steps:**

    * save a tutorial-typed document with a jumbled active block and a jumbled inactive one
    * verify the active block is ordered and the inactive block's own order survives
    """
    doc = RehuDocument(
        {
            "core": {"type": "tutorial"},
            "tutorial": {"online": False, "complete": True, "format_version": 1},
            "daz3d": {"sku": "1", "figures": ["G8F"], "format_version": 0},
        }
    )

    saved = saved_json(doc, mocker)

    assert list(saved["tutorial"]) == ["format_version", "complete", "online"]
    assert list(saved["daz3d"]) == ["sku", "figures", "format_version"]


def test_save_orders_the_active_blocks_users_map_too(mocker: MockerFixture) -> None:
    """The active block's ``users`` map (#98, [[field-schema#per-user-shared]]) is ordered one level
    deeper too: usernames alphabetically, and each user's own fields alphabetically -- the same
    canonical-order guarantee every other key in the file gets (#105).

    **Test steps:**

    * save a document whose active block's ``users`` map has jumbled usernames and jumbled per-user fields
    * verify both the usernames and each user's fields come back alphabetical
    """
    doc = RehuDocument(
        {
            "core": {"type": "tutorial"},
            "tutorial": {
                "format_version": 1,
                "users": {
                    "bob": {"viewed": True, "favorite": False, "keep": True, "todo": False, "rating": 2},
                    "alice": {"rating": 4, "favorite": True},
                },
            },
        }
    )

    saved = saved_json(doc, mocker)

    assert list(saved["tutorial"]["users"]) == ["alice", "bob"]
    assert list(saved["tutorial"]["users"]["alice"]) == ["favorite", "rating"]
    assert list(saved["tutorial"]["users"]["bob"]) == ["favorite", "keep", "rating", "todo", "viewed"]


def test_save_leaves_a_malformed_users_map_or_per_user_value_untouched(mocker: MockerFixture) -> None:
    """A ``users`` map (or a per-user value within it) that isn't an object is passed through as-is
    rather than crashing ([[data-model#write-integrity]]) -- the same tolerance the block-ordering
    routine gives a malformed block.

    Both blocks are pinned at the current block ``format_version`` -- otherwise construction's
    v0->v1 migration would itself overwrite ``users`` (a v0 block never legitimately has one) before
    save ever sees it, testing the migration's own tolerance instead of :meth:`__ordered_users_map`'s.

    **Test steps:**

    * save one document whose ``users`` map is a non-object, and another whose ``users`` map holds a
      non-object per-user value
    * verify both reach the file unchanged
    """
    malformed_map = RehuDocument(
        {"core": {"type": "tutorial"}, "tutorial": {"format_version": 1, "users": "not-an-object"}}
    )
    malformed_user = RehuDocument(
        {"core": {"type": "tutorial"}, "tutorial": {"format_version": 1, "users": {"alice": "not-an-object"}}}
    )

    assert saved_json(malformed_map, mocker)["tutorial"]["users"] == "not-an-object"
    assert saved_json(malformed_user, mocker)["tutorial"]["users"] == {"alice": "not-an-object"}


def test_save_passes_a_malformed_block_through_untouched(mocker: MockerFixture) -> None:
    """A block that isn't an object is written back as-is rather than dropped or coerced
    ([[data-model#write-integrity]]).

    Ordering must not become a way to lose content: a malformed block is still the file's, and silently
    discarding it on the way out is exactly the loss the round-trip rule forbids
    ([[data-model#schema-version]]).

    **Test steps:**

    * save a document whose ``core`` and whose active block are both non-objects
    * verify each reaches the file with its value intact
    """
    doc = RehuDocument({"core": "not-an-object", "tutorial": ["not", "an", "object"]})

    saved = saved_json(doc, mocker)

    assert saved["core"] == "not-an-object"
    assert saved["tutorial"] == ["not", "an", "object"]


def test_writing_a_common_field_replaces_a_malformed_core_block(mocker: MockerFixture) -> None:
    """Editing a common field on a document whose ``core`` is malformed installs a fresh block rather
    than crashing ([[data-model#write-integrity]]).

    The malformed value is not content anyone can keep once the core is being written to -- unlike a
    *plugin* block, which is carried verbatim precisely because this build does not understand it, the
    core is this build's own.

    **Test steps:**

    * construct a document whose ``core`` is a string, and set a common field
    * verify a real core block now holds it, and the document saves
    """
    doc = RehuDocument({"core": "not-an-object"})

    doc.title = "Brand New"

    assert doc.core == {"sources": [{"title": "Brand New", "primary": True}]}
    assert saved_json(doc, mocker)["core"]["sources"][0]["title"] == "Brand New"


def test_two_documents_with_the_same_fields_save_identically_however_they_were_built(
    mocker: MockerFixture,
) -> None:
    """Key order follows from the schema, not from a document's history.

    The reason to impose order at the write rather than let insertion order stand: a converted ``.tc``
    appends ``id``/``created`` after building its core, while a migrated v1 file inherits whatever order
    that file happened to have. Same fields, same file.

    **Test steps:**

    * build the same resource twice -- once from a v1 payload, once field-by-field in a different order
    * verify both save to byte-identical JSON
    """
    from_v1 = RehuDocument(
        {"format_version": 1, "id": "abc", "extra_tags": ["x"], "type": "tutorial", "authors": ["A"]}
    )

    built = RehuDocument({"core": {"type": "tutorial"}})
    built.authors = ["A"]
    built.extra_tags = ["x"]
    built.data["core"]["id"] = "abc"

    assert saved_json(from_v1, mocker) == saved_json(built, mocker)
    assert list(saved_json(from_v1, mocker)["core"]) == list(saved_json(built, mocker)["core"])


def test_saving_an_older_document_writes_the_current_format_version(mocker: MockerFixture) -> None:
    """A file loaded at an older ``format_version`` is written back at
    ``CURRENT_FORMAT_VERSION`` -- the upgrade-on-write half of [[data-model#schema-version]].

    Asserted end-to-end, through the file, because that is the contract; *where* the stamp gets applied
    is an internal matter (the migrator does it on load, so :meth:`save` merely dumps an
    already-consistent payload) and this test should keep passing if that ever moves again.

    **Test steps:**

    * load a document whose ``format_version`` is below the current one (and one with the key absent)
    * save each
    * verify the saved JSON's ``format_version`` is ``CURRENT_FORMAT_VERSION``
    """
    for original in (CURRENT_FORMAT_VERSION - 1, None):
        data = {"type": "tutorial"} if original is None else {"type": "tutorial", "format_version": original}
        doc = load_doc(mocker, data)
        mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

        doc.save()

        saved = json.loads(mock_write.call_args[0][1])
        assert saved["format_version"] == CURRENT_FORMAT_VERSION


def test_saving_a_newer_document_does_not_downgrade_its_format_version(mocker: MockerFixture) -> None:
    """A file loaded at a *newer* ``format_version`` than this build understands is written back with
    that version untouched -- lowering it would mislabel a file that still carries fields from that
    newer schema ([[data-model#schema-version]]'s "must fail safe, not lossy" rule).

    **Test steps:**

    * load a document whose ``format_version`` is above the current one
    * save it
    * verify the saved JSON's ``format_version`` is still the newer, unlowered value
    """
    newer_version = CURRENT_FORMAT_VERSION + 1
    doc = load_doc(mocker, {"type": "tutorial", "format_version": newer_version})
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
    """Malformed non-object entries in ``sources`` are skipped, not crashed on
    ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a document whose ``sources`` mixes a bare string with a real source object
    * verify the title comes from the first *object* entry, past the junk
    """
    doc = RehuDocument({"sources": ["junk", {"title": "Ok"}]})
    assert doc.title == "Ok"


def test_primary_source_is_none_when_no_entry_is_an_object() -> None:
    """A ``sources`` list holding only non-object junk yields no primary source, and empty accessors
    ([[data-model#write-integrity]]).

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
    doc = RehuDocument({"type": "tutorial"})
    doc.title = "Brand New"
    assert doc.sources == [{"title": "Brand New", "primary": True}]


def test_publisher_setter_creates_primary_source_when_absent() -> None:
    """Setting the publisher on a source-less document creates a flagged primary entry.

    **Test steps:**

    * construct a document with no ``sources``
    * assign a publisher
    * verify a single primary source with that publisher now exists
    """
    doc = RehuDocument({"type": "tutorial"})
    doc.publisher = "Brand New Publisher"
    assert doc.sources == [{"publisher": "Brand New Publisher", "primary": True}]


def test_url_setter_creates_primary_source_when_absent() -> None:
    """Setting the url on a source-less document creates a flagged primary entry.

    **Test steps:**

    * construct a document with no ``sources``
    * assign a url
    * verify a single primary source with that url now exists
    """
    doc = RehuDocument({"type": "tutorial"})
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


def test_authors_getter_preserves_strings_and_records() -> None:
    """A plain-string entry passes through and a ``{name, url}`` record is preserved
    ([[field-schema#authors]]) -- the getter no longer stringifies every entry.

    **Test steps:**

    * construct a document whose ``authors`` mixes a string, a name+url record, and a comma-bearing string
    * verify the getter yields each entry unchanged, record intact
    """
    doc = RehuDocument({"authors": ["A", {"name": "B", "url": "https://b.example"}, "C, D"]})
    assert doc.authors == ["A", {"name": "B", "url": "https://b.example"}, "C, D"]


@mark.parametrize(
    "entry",
    [
        param(42, id="number"),
        param(None, id="none"),
        param(["nested"], id="list"),
        param({"url": "https://x.example"}, id="record-without-name"),
        param({"name": 5}, id="record-with-non-string-name"),
    ],
)
def test_authors_getter_skips_malformed_entries(entry: Any) -> None:
    """A malformed entry is skipped, the same coercion ``sources`` applies to a non-object entry
    ([[data-model#write-integrity]]) -- the getter never crashes on a value's type.

    **Test steps:**

    * construct a document whose ``authors`` surrounds one malformed entry with valid names
    * verify the getter drops only the malformed entry
    """
    doc = RehuDocument({"authors": ["Before", entry, "After"]})
    assert doc.authors == ["Before", "After"]


def test_authors_getter_returns_empty_for_a_non_list() -> None:
    """A non-list ``authors`` value coerces to an empty list ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a document whose ``authors`` is a string, not a list
    * verify the getter yields an empty list
    """
    doc = RehuDocument({"core": {"authors": "not-a-list"}, "format_version": 2})
    assert not doc.authors


def test_authors_setter_reduces_a_bare_name_record_to_a_string() -> None:
    """A record whose only meaningful key is ``name`` is stored as a plain string -- canonical
    minimal form ([[field-schema#authors]]).

    **Test steps:**

    * set ``authors`` to a name-only record, a record with an empty url, and a record with a non-string url
    * verify each is stored as the bare name string
    """
    doc = RehuDocument({})
    doc.authors = [{"name": "X"}, {"name": "Y", "url": ""}, {"name": "Z", "url": 7}]
    assert doc.authors == ["X", "Y", "Z"]


def test_authors_setter_keeps_a_record_that_carries_a_url() -> None:
    """A record with a non-empty string ``url`` stays a record, reduced to just ``name`` and ``url``
    ([[field-schema#authors]]).

    **Test steps:**

    * set ``authors`` to a record carrying a url alongside an extra key
    * verify the stored entry keeps name and url and drops the extra key
    """
    doc = RehuDocument({})
    doc.authors = [{"name": "X", "url": "https://x.example", "note": "dropped"}]
    assert doc.authors == [{"name": "X", "url": "https://x.example"}]


def test_authors_round_trip_leaves_an_untouched_mixed_list_byte_identical(mocker: MockerFixture) -> None:
    """A mixed string/record ``authors`` list survives save unchanged when nothing edits it
    ([[data-model#write-integrity]]) -- reading it never rewrites the backing store.

    **Test steps:**

    * construct a v2 document whose ``core.authors`` mixes a string, a record, and a comma-bearing string
    * read the getter (which coerces on read), then save
    * verify the written ``core.authors`` equals the original list exactly
    """
    authors = ["A", {"name": "B", "url": "https://b.example"}, "C, D"]
    doc = RehuDocument({"core": {"type": "tutorial", "authors": authors}, "format_version": 2})
    _ = doc.authors  # a read must not mutate the backing store

    saved = saved_json(doc, mocker)

    assert saved["core"]["authors"] == authors


@mark.parametrize(
    ("authors", "expected"),
    [
        param([], True, id="empty"),
        param(["A", "B"], True, id="all-plain-strings"),
        param(["A", {"name": "B", "url": "https://b.example"}], False, id="a-record"),
        param(["A", "C, D"], False, id="a-comma-bearing-name"),
    ],
)
def test_authors_comma_editable(authors: list[Any], expected: bool) -> None:
    """The predicate is true iff every entry is a plain string with no comma ([[field-schema#authors]]).

    **Test steps:**

    * call ``authors_comma_editable`` on all-strings, a record-bearing list, and a comma-bearing list
    * verify each verdict matches the lossless-round-trip rule
    """
    assert authors_comma_editable(authors) is expected


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


@mark.parametrize("attr", [param("created", id="created"), param("updated", id="updated")])
def test_record_timestamp_defaults_to_empty_when_absent(attr: str) -> None:
    """``created``/``updated`` default to an empty string when the key is absent.

    **Test steps:**

    * construct a document with neither key
    * verify the attribute reads ``""``
    """
    doc = RehuDocument({})
    assert getattr(doc, attr) == ""


@mark.parametrize("attr", [param("created", id="created"), param("updated", id="updated")])
def test_record_timestamp_setter_replaces_the_value(attr: str) -> None:
    """Setting ``created``/``updated`` replaces the stored datetime.

    **Test steps:**

    * construct a document with an existing value
    * assign a new value
    * verify the document reflects it
    """
    doc = RehuDocument({attr: "2024-01-01T00:00:00Z"})
    setattr(doc, attr, "2025-03-08T12:00:00Z")
    assert getattr(doc, attr) == "2025-03-08T12:00:00Z"


# region Optional scalars (#100)

# The eight optional scalars read as ``None`` when absent -- absent is not 0/"" ([[field-schema#deferred-items]]).
# Seven are integers living in three places; this table maps each to *where* a raw on-disk value must be
# planted, so one parametrized suite can exercise every field's absent/null/value/malformed contract
# uniformly (``released`` is a string and tested on its own below). ``OPTIONAL_INT_ATTRS`` drops the
# location for the cases where only the getter/setter name matters (planting nothing, or writing through the
# typed accessor, which routes to the right place itself).
OPTIONAL_INT_SCALAR_SPECS: Final = (
    ("original_size", "core"),
    ("current_size", "core"),
    ("original_duration", "block"),
    ("current_duration", "block"),
    ("advertised_duration", "block"),
    ("images_count", "block"),
    ("rating", "user"),
)
OPTIONAL_INT_SCALARS: Final = [param(attr, location, id=attr) for attr, location in OPTIONAL_INT_SCALAR_SPECS]
OPTIONAL_INT_ATTRS: Final = [param(attr, id=attr) for attr, _location in OPTIONAL_INT_SCALAR_SPECS]


def scalar_doc(location: str, key: str, value: Any, path: Path | None = None) -> RehuDocument:
    """Build a Tutorial document carrying a raw ``value`` under ``key`` at ``location`` -- the common core
    (``core``), the active block's shared fields (``block``), or this user's submap (``user``).

    :param location: where to plant the value (``core`` / ``block`` / ``user``).
    :param key: the scalar's key.
    :param value: the raw on-disk value to store (an int, ``None`` for JSON ``null``, or malformed).
    :param path: the document's path, for the save-round-trip tests; ``None`` for read-only checks.
    :returns: the constructed document.
    """
    core: dict[str, Any] = {"type": "tutorial"}
    block: dict[str, Any] = {"format_version": 1}
    if location == "core":
        core[key] = value
    elif location == "block":
        block[key] = value
    else:  # user
        block["users"] = {"admin": {key: value}}
    return RehuDocument({"core": core, "tutorial": block}, path)


def scalar_container(source: dict[str, Any], location: str) -> dict[str, Any]:
    """The sub-object holding a scalar at ``location``, in a raw ``.rehu`` dict (``data`` or saved JSON)."""
    if location == "core":
        return source.get("core", {})
    block = source.get("tutorial", {})
    return block if location == "block" else block.get("users", {}).get("admin", {})


@mark.parametrize("attr", OPTIONAL_INT_ATTRS)
def test_optional_int_scalar_reads_none_when_absent(attr: str) -> None:
    """An optional integer scalar reads ``None`` when absent -- absent is not ``0`` -- and does not lock
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * construct a Tutorial document that carries no value for ``attr``
    * verify the getter is ``None`` and no lock reason is raised
    """
    doc = RehuDocument({"core": {"type": "tutorial"}, "tutorial": {"format_version": 1}})
    assert getattr(doc, attr) is None
    assert not doc.lock_reasons


@mark.parametrize(("attr", "location"), OPTIONAL_INT_SCALARS)
def test_optional_int_scalar_reads_a_stored_zero_honestly(attr: str, location: str) -> None:
    """A stored ``0`` reads back as ``0`` -- a genuine reading distinct from absent's ``None`` -- and does
    not lock ([[field-schema#deferred-items]]).

    **Test steps:**

    * store ``0`` for ``attr`` at its location
    * verify the getter is ``0`` (not ``None``) and no lock reason is raised
    """
    doc = scalar_doc(location, attr, 0)
    assert getattr(doc, attr) == 0
    assert not doc.lock_reasons


@mark.parametrize(("attr", "location"), OPTIONAL_INT_SCALARS)
def test_optional_int_scalar_reads_a_stored_value(attr: str, location: str) -> None:
    """A stored non-zero integer reads back unchanged.

    **Test steps:**

    * store a value for ``attr`` at its location
    * verify the getter returns it
    """
    doc = scalar_doc(location, attr, 4200)
    assert getattr(doc, attr) == 4200


@mark.parametrize(("attr", "location"), OPTIONAL_INT_SCALARS)
def test_optional_int_scalar_null_reads_none_and_does_not_lock(attr: str, location: str) -> None:
    """JSON ``null`` is accepted on read as ``None`` and does not lock -- it is the on-disk spelling of
    absent ([[field-schema#deferred-items]]).

    **Test steps:**

    * store JSON ``null`` for ``attr`` at its location
    * verify the getter is ``None`` and no lock reason is raised
    """
    doc = scalar_doc(location, attr, None)
    assert getattr(doc, attr) is None
    assert not doc.lock_reasons


@mark.parametrize(("attr", "location"), OPTIONAL_INT_SCALARS)
def test_optional_int_scalar_null_normalizes_away_on_save(attr: str, location: str, mocker: MockerFixture) -> None:
    """A document with a ``null`` optional scalar on disk saves **without** the key -- ``null`` is accepted
    on read but never written back ([[field-schema#deferred-items]]).

    **Test steps:**

    * construct a document whose ``attr`` is JSON ``null`` on disk, bound to a path
    * mock ``atomic_write_text`` to capture the saved JSON, and save
    * verify the saved container has no ``attr`` key
    """
    doc = scalar_doc(location, attr, None, FAKE_PATH)
    write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.save()

    saved = json.loads(write.call_args[0][1])
    assert attr not in scalar_container(saved, location)


@mark.parametrize(("attr", "location"), OPTIONAL_INT_SCALARS)
def test_optional_int_scalar_malformed_reads_none_and_locks(attr: str, location: str) -> None:
    """A present non-int coerces to ``None`` for display **and** locks the document with an
    ``INVALID_FIELD`` reason naming it, so an edit never saves the coerced ``None`` over the
    malformed-but-recoverable original ([[data-model#write-integrity]]).

    **Test steps:**

    * store a non-int (a string) for ``attr`` at its location
    * verify the getter is ``None``, the sole lock reason is ``INVALID_FIELD``, and it names ``attr``
    """
    doc = scalar_doc(location, attr, "junk")
    assert getattr(doc, attr) is None
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.INVALID_FIELD]
    assert attr in doc.lock_reasons[0].message


@mark.parametrize(("attr", "location"), OPTIONAL_INT_SCALARS)
def test_optional_int_scalar_malformed_refuses_to_save(attr: str, location: str, mocker: MockerFixture) -> None:
    """A malformed optional scalar's ``INVALID_FIELD`` lock makes ``save`` refuse, so the coerced ``None``
    never overwrites the recoverable original ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a document whose ``attr`` is malformed, bound to a path
    * mock ``atomic_write_text`` to prove it is never reached
    * verify ``save`` raises and nothing was written
    """
    write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    doc = scalar_doc(location, attr, "junk", FAKE_PATH)

    with pytest.raises(RehuFormatError, match="Refusing to save"):
        doc.save()
    write.assert_not_called()


def test_a_stored_bool_is_malformed_for_an_int_scalar() -> None:
    """A JSON ``true``/``false`` is not a whole number (``bool`` is an ``int`` subclass but excluded), so a
    scalar storing one reads ``None`` and locks ([[data-model#write-integrity]]).

    **Test steps:**

    * store ``True`` under ``original_size``
    * verify it reads ``None`` and the document locks ``INVALID_FIELD``
    """
    doc = RehuDocument({"core": {"type": "tutorial", "original_size": True}, "tutorial": {"format_version": 1}})
    assert doc.original_size is None
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.INVALID_FIELD]


@mark.parametrize("attr", OPTIONAL_INT_ATTRS)
def test_setting_an_optional_int_scalar_stores_the_value(attr: str) -> None:
    """Setting an optional scalar to an integer stores it.

    **Test steps:**

    * construct a document without ``attr``
    * assign a value through the typed setter
    * verify the getter reflects it
    """
    doc = RehuDocument({"core": {"type": "tutorial"}, "tutorial": {"format_version": 1}})
    setattr(doc, attr, 123)
    assert getattr(doc, attr) == 123


@mark.parametrize(("attr", "location"), OPTIONAL_INT_SCALARS)
def test_setting_an_optional_int_scalar_none_deletes_the_key(attr: str, location: str) -> None:
    """Setting an optional scalar to ``None`` deletes its key rather than writing ``null``
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * construct a document with a stored value for ``attr``
    * assign ``None`` through the typed setter
    * verify the getter is ``None`` and the key is gone from the backing data
    """
    doc = scalar_doc(location, attr, 7)
    setattr(doc, attr, None)
    assert getattr(doc, attr) is None
    assert attr not in scalar_container(doc.data, location)


def test_clearing_an_absent_per_user_rating_is_a_harmless_noop() -> None:
    """Clearing ``rating`` on a document that has no ``users`` map at all is a no-op, not a crash --
    :meth:`remove_active_user_field` tolerates an absent block/map/user ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a document with no per-user state
    * set ``rating`` to ``None``
    * verify it stays ``None`` and no ``users`` map was created
    """
    doc = RehuDocument({"core": {"type": "tutorial"}, "tutorial": {"format_version": 1}})
    doc.rating = None
    assert doc.rating is None
    assert "users" not in doc.data["tutorial"]


def test_a_negative_rating_round_trips(mocker: MockerFixture) -> None:
    """A negative rating survives a save/reload -- ``0`` is a genuine rating, so *unrated* is ``None`` and a
    negative value must never be mistaken for empty ([[field-schema#deferred-items]]).

    **Test steps:**

    * construct a document rated ``-3``, bound to a path
    * verify the getter reads ``-3``, then save and re-read the captured JSON
    * verify the saved and reloaded rating are both ``-3``
    """
    doc = scalar_doc("user", "rating", -3, FAKE_PATH)
    assert doc.rating == -3
    write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.save()

    saved = json.loads(write.call_args[0][1])
    assert saved["tutorial"]["users"]["admin"]["rating"] == -3
    assert RehuDocument(saved).rating == -3


def test_released_reads_none_when_absent() -> None:
    """``released`` reads ``None`` when absent -- absent is not ``""`` ([[field-schema#deferred-items]])."""
    assert RehuDocument({"core": {"type": "tutorial"}}).released is None


def test_released_reads_the_stored_string() -> None:
    """A stored partial-precision date reads back unchanged."""
    assert RehuDocument({"core": {"type": "tutorial", "released": "2025-03"}}).released == "2025-03"


def test_released_null_reads_none_and_does_not_lock() -> None:
    """JSON ``null`` for ``released`` reads as ``None`` and does not lock ([[field-schema#deferred-items]])."""
    doc = RehuDocument({"core": {"type": "tutorial", "released": None}})
    assert doc.released is None
    assert not doc.lock_reasons


def test_released_null_normalizes_away_on_save(mocker: MockerFixture) -> None:
    """A ``null`` ``released`` on disk saves without the key -- ``null`` is never written back
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * construct a document whose ``released`` is JSON ``null``, bound to a path
    * mock ``atomic_write_text`` and save
    * verify the saved core has no ``released`` key
    """
    doc = RehuDocument({"core": {"type": "tutorial", "released": None}}, FAKE_PATH)
    write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.save()

    assert "released" not in json.loads(write.call_args[0][1])["core"]


def test_released_malformed_reads_none_and_locks() -> None:
    """A present non-string ``released`` coerces to ``None`` for display and locks ``INVALID_FIELD``
    ([[data-model#write-integrity]]).

    **Test steps:**

    * store a list under ``released``
    * verify it reads ``None`` and the sole lock reason is ``INVALID_FIELD`` naming ``released``
    """
    doc = RehuDocument({"core": {"type": "tutorial", "released": [2025]}})
    assert doc.released is None
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.INVALID_FIELD]
    assert "released" in doc.lock_reasons[0].message


def test_setting_released_none_deletes_the_key() -> None:
    """Setting ``released`` to ``None`` deletes the key rather than writing ``null``
    ([[field-schema#deferred-items]]).

    **Test steps:**

    * construct a document with a stored ``released``
    * assign ``None``
    * verify it reads ``None`` and the key is gone
    """
    doc = RehuDocument({"core": {"type": "tutorial", "released": "2025"}})
    doc.released = None
    assert doc.released is None
    assert "released" not in doc.data["core"]


# endregion


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


@mark.parametrize(
    ("stored", "expected"),
    [
        param("line one\r\nline two", "line one\nline two", id="crlf"),
        param("line one\rline two", "line one\nline two", id="bare-cr"),
        param("line one\nline two", "line one\nline two", id="already-lf"),
        param("one\r\ntwo\rthree\nfour", "one\ntwo\nthree\nfour", id="mixed"),
    ],
)
def test_description_normalizes_line_endings_to_lf(stored: str, expected: str) -> None:
    """``description`` reads back with every CRLF/bare-CR line ending normalized to LF, regardless
    of which platform wrote the file, so editing reads the same either way.

    **Test steps:**

    * construct a document with ``description`` stored using CRLF, bare CR, LF, or a mix
    * verify it reads back LF-only
    """
    doc = RehuDocument({"description": stored})
    assert doc.description == expected


def test_description_does_not_mutate_the_backing_data_on_read() -> None:
    """Reading ``description`` normalizes the returned value only -- the backing dict (what a
    ``save()`` of an otherwise-untouched document would write back out) keeps the original,
    un-normalized line endings until something actually calls the setter.

    **Test steps:**

    * construct a document with a CRLF-terminated ``description``
    * read the property once
    * verify the backing dict's raw value is still CRLF
    """
    doc = RehuDocument({"core": {"description": "line one\r\nline two"}})

    assert doc.description == "line one\nline two"
    assert doc.core["description"] == "line one\r\nline two"


def test_hidden_images_defaults_to_empty_when_absent_or_malformed() -> None:
    """``hidden_images`` reads as an empty list when the key is missing or not a list
    ([[data-model#write-integrity]]).

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
    doc = RehuDocument({"type": "tutorial"})
    with pytest.raises(ValueError, match="No path given"):
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
        Path, "read_text", return_value=json.dumps({"type": "tutorial", "authors": ["Reloaded Author"]})
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
    doc = RehuDocument({"type": "tutorial"})
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


def test_active_block_key_is_the_type_itself() -> None:
    """The active block's key **is** the resource ``type``, normalized ([[plugins#plugin-blocks]]).

    **Test steps:**

    * verify a main-key type names its own block
    * verify an alias type resolves to its plugin's main key
    * verify a type no installed plugin claims still names its own block, verbatim
    * verify a typeless document yields an empty key
    """
    assert RehuDocument({"type": "tutorial"}).active_block_key == "tutorial"
    assert RehuDocument({"type": "ReferenceImages"}).active_block_key == "reference_images"
    assert RehuDocument({"type": "audiopack"}).active_block_key == "audiopack"
    assert RehuDocument({}).active_block_key == ""


def test_active_field_reads_from_the_active_block() -> None:
    """``active_field`` reads a key out of the active plugin block ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a Tutorial document carrying a ``tutorial`` block with a shared field
    * verify the stored key reads back, and an absent key returns the given default
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1, "complete": True}})
    assert doc.active_field("complete") is True
    assert doc.active_field("missing", 0) == 0


def test_active_field_defaults_when_block_is_absent_or_malformed() -> None:
    """``active_field`` returns the default when the block is missing or not an object
    ([[data-model#write-integrity]]).

    **Test steps:**

    * verify a document with no block returns the default
    * verify a document whose block is a non-object returns the default (malformed, skipped)
    """
    assert RehuDocument({"type": "tutorial"}).active_field("rating", 0) == 0
    assert RehuDocument({"type": "tutorial", "tutorial": "junk"}).active_field("rating", 0) == 0
    assert RehuDocument({"type": "tutorial", "tutorial": "junk"}).active_block == {}


def test_set_active_field_updates_an_existing_block() -> None:
    """``set_active_field`` writes into an existing block, leaving its other keys intact.

    **Test steps:**

    * construct a Tutorial document with a ``tutorial`` block
    * set a new value on one key
    * verify the key updated and the block's ``format_version`` is untouched
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1, "complete": False}})
    doc.set_active_field("complete", True)
    assert doc.data["tutorial"] == {"format_version": 1, "complete": True}


def test_set_active_field_creates_the_block_when_absent() -> None:
    """``set_active_field`` installs a fresh block keyed by ``type`` when none exists, stamped with the
    plugin's current block ``format_version`` at creation ([[data-model#schema-version]]'s
    stamp-where-known rule, #134) -- unstamped, it would read as v0 on the next load and be run through
    migrations current-layout data never earned.

    **Test steps:**

    * construct a Tutorial document with no plugin block
    * set a type-field value
    * verify a ``tutorial`` block now holds it, stamped at the plugin's current block version
    """
    doc = RehuDocument({"type": "tutorial"})
    doc.set_active_field("complete", False)
    assert doc.data["tutorial"] == {"format_version": current_block_version("tutorial"), "complete": False}


def test_set_active_field_replaces_a_malformed_block() -> None:
    """``set_active_field`` replaces a non-object block with a fresh one rather than crashing
    ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a Tutorial document whose ``tutorial`` block is a non-object
    * set a type-field value
    * verify the malformed block was replaced by a fresh, current-stamped object holding it (#134)
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": "junk"})
    doc.set_active_field("rating", 3)
    assert doc.data["tutorial"] == {"format_version": current_block_version("tutorial"), "rating": 3}


def test_a_mid_session_type_switch_round_trips_with_the_block_stamped_and_users_intact(
    mocker: MockerFixture,
) -> None:
    """A block created by a mid-session type switch + edit saves **stamped**, so reloading the file runs
    no migration over it and its ``users`` map survives -- the #134 data-loss chain, closed end-to-end.

    Unstamped, the saved block would resolve to v0 on the next load and the v0->v1 step would rebuild
    ``users`` from the (empty) inline strays -- silently losing the record the save had just written.

    **Test steps:**

    * load a tutorial-typed document, switch its type to ``reference_images``, and file a per-user edit
    * save, and verify the written block carries the plugin's current block ``format_version``
    * load the written payload back and verify the per-user record is intact
    """
    doc = load_doc(mocker, {"core": {"type": "tutorial"}, "tutorial": {"format_version": 1}})
    doc.set_active_type("reference_images")
    doc.set_active_user_field("rating", 5)

    saved = saved_json(doc, mocker)
    assert saved["reference_images"]["format_version"] == current_block_version("reference_images")

    reloaded = RehuDocument(saved)
    assert reloaded.active_user_field("rating") == 5
    assert reloaded.active_block["users"] == {"admin": {"rating": 5}}


def test_remove_active_field_deletes_a_present_key() -> None:
    """``remove_active_field`` deletes a key from the block and reports it was present.

    **Test steps:**

    * construct a Tutorial document whose block holds an extra (unknown) key
    * remove that key
    * verify it returns ``True`` and the key is gone while the rest of the block is intact
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1, "complete": True, "mystery": 42}})
    assert doc.remove_active_field("mystery") is True
    assert doc.data["tutorial"] == {"format_version": 1, "complete": True}


def test_remove_active_field_is_a_noop_when_absent() -> None:
    """``remove_active_field`` reports ``False`` when the key or block is absent, changing nothing.

    **Test steps:**

    * a Tutorial document with a block missing the key -> ``False``
    * a document with no block at all -> ``False``
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1, "complete": True}})
    assert doc.remove_active_field("mystery") is False
    assert doc.data["tutorial"] == {"format_version": 1, "complete": True}

    blockless = RehuDocument({"type": "tutorial"})
    assert blockless.remove_active_field("mystery") is False


def test_remove_block_drops_a_whole_inactive_block() -> None:
    """``remove_block`` deletes an inactive block wholesale and reports it was present
    ([[plugins#fallback-editor]], #84).

    The block-level sibling of ``remove_active_field`` -- the explicit *drop* of a foreign block the file
    was merely custodian of, leaving the active block and the rest of the document intact.

    **Test steps:**

    * a tutorial document also carrying a foreign ``reference_images`` block
    * remove that block
    * verify it returns ``True``, the block is gone, and the active ``tutorial`` block is untouched
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}, "reference_images": {"images_count": 12}})
    assert doc.remove_block("reference_images") is True
    assert "reference_images" not in doc.data
    assert "tutorial" in doc.data


def test_remove_block_refuses_the_active_block_and_is_a_noop_when_absent() -> None:
    """``remove_block`` never drops the active block or a reserved key, and reports ``False`` for an
    absent or non-object key ([[plugins#fallback-editor]], #84).

    A file always keeps the block its own ``type`` names, and ``core``/``format_version`` are not blocks,
    so each is refused rather than deleted -- the backstop that keeps the drop affordance from ever
    reaching into the active identity or the common core.

    **Test steps:**

    * the active ``tutorial`` block -> ``False``, still present
    * the reserved ``core`` key -> ``False``, still present
    * an absent key, and a stray non-object top-level key -> ``False``, unchanged
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}, "stray": "not a block"})
    assert doc.remove_block("tutorial") is False
    assert "tutorial" in doc.data
    assert doc.remove_block("core") is False
    assert "core" in doc.data
    assert doc.remove_block("absent") is False
    assert doc.remove_block("stray") is False
    assert doc.data["stray"] == "not a block"


def test_plugin_blocks_classifies_the_types_block_active_and_every_other_inactive() -> None:
    """The ``type`` names the one active block; every other block is inactive ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a tutorial-typed document also carrying a ``reference_images`` and a ``daz3d`` block
    * verify all three are enumerated, in document order
    * verify only the ``tutorial`` block is active, and ``inactive_blocks`` is the other two
    """
    doc = RehuDocument(
        {
            "type": "tutorial",
            "tutorial": {"rating": 4},
            "reference_images": {"images_count": 12},
            "daz3d": {"sku": "12345"},
        }
    )
    assert [(block.key, block.active) for block in doc.plugin_blocks()] == [
        ("tutorial", True),
        ("reference_images", False),
        ("daz3d", False),
    ]
    assert [block.key for block in doc.inactive_blocks()] == ["reference_images", "daz3d"]
    assert doc.plugin_blocks()[0].fields == {"format_version": 1, "users": {"admin": {"rating": 4}}}


def test_an_installed_plugins_block_is_inactive_when_the_type_does_not_name_it() -> None:
    """A ``reference_images`` block inside an ``audiopack``-typed file is inactive **even though** the
    reference-images plugin is installed here ([[plugins#plugin-blocks]]'s sharp edge).

    Installed-ness only decides whether the *active* block renders richly; it never promotes an
    inactive block to active. Conversely ``audiopack`` has no plugin here at all, and is active anyway
    -- the type decides, not the registry.

    **Test steps:**

    * verify the reference-images plugin really is installed in the default registry
    * construct an ``audiopack``-typed document carrying an ``audiopack`` and a ``reference_images`` block
    * verify the uninstalled ``audiopack`` block is the active one
    * verify the installed-plugin ``reference_images`` block is inactive
    """
    assert "reference_images" in DEFAULT_PLUGIN_REGISTRY
    assert "audiopack" not in DEFAULT_PLUGIN_REGISTRY

    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}, "reference_images": {"images_count": 12}})
    assert doc.active_block_key == "audiopack"
    assert doc.active_block == {"bitrate": 320}
    assert [block.key for block in doc.inactive_blocks()] == ["reference_images"]


def test_plugins_exposes_the_registry_the_document_was_opened_with() -> None:
    """``plugins`` returns the very registry the document was constructed with, by identity
    ([[plugins#core-vs-plugin]]).

    Exposed so a caller building a type selector reads the actual installed set the switch will normalize
    against, rather than a global -- a document opened with a custom registry reports that one.

    **Test steps:**

    * construct a document with an explicit, non-default registry
    * verify ``plugins`` is that exact registry
    * verify a default-registry document reports the shipped default
    """
    custom = PluginRegistry([TUTORIAL_PLUGIN])
    assert RehuDocument({"type": "tutorial"}, plugins=custom).plugins is custom
    assert RehuDocument({"type": "tutorial"}).plugins is DEFAULT_PLUGIN_REGISTRY


def test_a_non_object_top_level_key_is_not_a_plugin_block() -> None:
    """A block is a keyed **object**; a stray scalar or list is an ordinary unknown key
    ([[plugins#plugin-blocks]]).

    This is the distinction that makes enumeration possible at all -- without it a block and a stray
    top-level value are the same thing.

    **Test steps:**

    * construct a document carrying an unknown scalar, an unknown list, and one real block
    * verify only the block is enumerated
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}, "stray_scalar": 42, "stray_list": [1, 2, 3]})
    assert [block.key for block in doc.plugin_blocks()] == ["tutorial"]


def test_alias_type_and_block_key_normalize_to_the_declared_main_key() -> None:
    """A plugin declares its keys; storing rewrites an alias to the main one ([[plugins#plugin-blocks]]).

    The ``type``'s value and its block's key are the same token, so one alias list normalizes both.

    **Test steps:**

    * construct a document using tc4's ``ReferenceImages`` type spelling and the ``refimages`` block alias
    * verify both normalized to the declared main key ``reference_images``
    * verify the block's contents survived the rename, and that no sibling block was disturbed
    """
    doc = RehuDocument(
        {"core": {"type": "ReferenceImages"}, "refimages": {"images_count": 12}, "tutorial": {"rating": 1}}
    )
    assert doc.core["type"] == "reference_images"
    assert doc.active_block_key == "reference_images"
    assert doc.active_block == {"images_count": 12, "format_version": 1, "users": {"admin": {}}}
    assert doc.data["tutorial"] == {"rating": 1}
    assert "refimages" not in doc.data


def test_normalization_leaves_an_alias_block_alone_when_the_main_key_is_taken() -> None:
    """An alias block never clobbers an existing main-keyed block ([[plugins#plugin-blocks]]).

    It keeps its own spelling, and is therefore simply a different key -- so it classifies inactive and
    is carried verbatim, which is exactly what foreign payload should do.

    **Test steps:**

    * construct a document carrying **both** ``reference_images`` and its ``refimages`` alias
    * verify the main-keyed block is untouched and active
    * verify the alias-keyed block kept its key, is inactive, and kept its contents
    """
    doc = RehuDocument(
        {
            "type": "reference_images",
            "reference_images": {"images_count": 12},
            "refimages": {"images_count": 99},
        }
    )
    assert doc.active_block == {"images_count": 12, "format_version": 1, "users": {"admin": {}}}
    assert [(block.key, block.fields) for block in doc.inactive_blocks()] == [("refimages", {"images_count": 99})]


def test_save_writes_the_active_block_and_every_inactive_block_verbatim(mocker: MockerFixture) -> None:
    """Save carries everything -- the active block plus every inactive block ([[plugins#plugin-blocks]]).

    The carry-only half of the persistence invariant: nothing is lost. Claim-tracking and the
    drop-on-abandon rule are #82's, so with no type switching every block simply survives.

    **Test steps:**

    * load a tutorial-typed document that also carries ``reference_images`` and ``daz3d`` blocks
    * edit the active block, then save
    * verify the edit landed and both inactive blocks were written back byte-for-byte
    """
    data = {
        "type": "tutorial",
        "tutorial": {"rating": 4},
        "reference_images": {"images_count": 12},
        "daz3d": {"sku": "12345", "figures": ["G8F"]},
    }
    doc = load_doc(mocker, data)
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.set_active_field("complete", True)
    doc.save()

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["tutorial"] == {"format_version": 1, "complete": True, "users": {"admin": {"rating": 4}}}
    assert saved["reference_images"] == {"images_count": 12}
    assert saved["daz3d"] == {"sku": "12345", "figures": ["G8F"]}


def test_save_normalizes_alias_spellings_on_disk(mocker: MockerFixture) -> None:
    """Storing rewrites an alias to its main key -- the rename/migration path
    ([[plugins#plugin-blocks]]).

    **Test steps:**

    * load a document written with tc4's ``Tutorial`` type spelling
    * save it untouched
    * verify the file now carries the declared main key, for both ``type`` and the block
    """
    doc = load_doc(mocker, {"core": {"type": "Tutorial"}, "Tutorial": {"rating": 4}})
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.save()

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["core"]["type"] == "tutorial"
    assert saved["tutorial"] == {"format_version": 1, "users": {"admin": {"rating": 4}}}
    assert "Tutorial" not in saved


# region Block persistence invariant (#82, [[plugins#plugin-blocks]])
#
# The single-active-type, claim-then-abandon rule that governs save: a block is written iff it is the
# active type's block, or it is foreign payload never made active this session. A block made active this
# session and then abandoned is *dropped*. The same key has opposite fates depending solely on "was it
# ever active this session" -- the worked example's steps 1 and 4 encode exactly that contrast.


def saved_blocks(doc: RehuDocument) -> dict[str, Any]:
    """The plugin blocks a save would write, keyed by name, read straight off ``serialize()``.

    ``serialize()`` is byte-for-byte what :meth:`RehuDocument.save` writes ([[plugins#plugin-blocks]]),
    so it applies the persistence invariant without a mocked disk. ``core`` and ``format_version`` are
    dropped, leaving just the plugin blocks whose presence or absence the invariant decides.

    :param doc: the document to serialize.
    :returns: the written plugin blocks, name -> fields.
    """
    written = json.loads(doc.serialize())
    return {key: value for key, value in written.items() if key not in ("core", "format_version")}


def test_the_opening_type_is_claimed_from_the_start() -> None:
    """A block active from the document's first moment counts as claimed ([[plugins#plugin-blocks]]).

    It has "been active this session" as much as one switched to later -- which is what arms the *former*
    active type to drop once abandoned (the worked example's step 1).

    **Test steps:**

    * construct a tutorial-typed document also carrying a foreign ``reference_images`` block
    * verify only the opening type is claimed, the foreign block is not
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}, "reference_images": {"images_count": 12}})
    assert doc.claimed_block_keys == frozenset({"tutorial"})


def test_a_typeless_or_locked_document_claims_nothing() -> None:
    """A document with no active type claims nothing -- there is no block to claim ([[plugins#plugin-blocks]]).

    **Test steps:**

    * a typeless document has an empty claim set
    * an empty (locked-stub-shaped) document has an empty claim set
    """
    assert RehuDocument({}).claimed_block_keys == frozenset()
    assert RehuDocument({"tutorial": {"rating": 4}}).claimed_block_keys == frozenset()


def test_set_active_type_claims_the_new_type_and_normalizes_an_alias() -> None:
    """Switching type claims the newly-active block, an alias claiming its main key ([[plugins#plugin-blocks]]).

    Making a block active "claims" it; the requested spelling is normalized so ``type`` and its block key
    stay one token and an alias claims exactly what its main spelling would.

    **Test steps:**

    * construct a tutorial-typed document
    * switch to the ``ReferenceImages`` alias
    * verify ``type`` and the claim both normalized to the ``reference_images`` main key
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}})
    doc.set_active_type("ReferenceImages")
    assert doc.type == "reference_images"
    assert doc.active_block_key == "reference_images"
    assert doc.claimed_block_keys == frozenset({"tutorial", "reference_images"})


def test_set_active_type_to_empty_stores_the_type_but_claims_nothing() -> None:
    """Clearing the active type stores it verbatim and claims nothing -- there is no block to claim
    ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a tutorial-typed document (``tutorial`` claimed from the start)
    * switch to an empty type
    * verify the type cleared and no new claim was made -- only the earlier ``tutorial`` remains claimed
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"complete": True}})
    doc.set_active_type("")
    assert doc.type == ""
    assert doc.claimed_block_keys == frozenset({"tutorial"})


def test_set_active_type_refuses_a_reserved_key() -> None:
    """Switching to a reserved key is refused -- ``core`` and ``format_version`` are grammar, not
    resource types, and storing one as the type would build, from a live session, the same
    refused-on-reopen state construction refuses in a payload (#135).

    **Test steps:**

    * construct a tutorial-typed document
    * for each reserved key, verify the switch raises ``ValueError`` naming the key as reserved
    * verify the type and the claim set are left untouched by the refused switches
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"complete": True}})
    for reserved in sorted(RESERVED_KEYS):
        with pytest.raises(ValueError, match=f"{reserved!r} is a reserved key"):
            doc.set_active_type(reserved)
    assert doc.type == "tutorial"
    assert doc.claimed_block_keys == frozenset({"tutorial"})


def test_a_never_claimed_foreign_block_is_carried_on_save() -> None:
    """Foreign payload never made active is carried verbatim -- the file is its custodian
    ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a tutorial-typed document carrying an untouched ``reference_images`` block
    * verify, without any type switching, both the active and the foreign block are written
    * verify the foreign block is classified inactive, unclaimed, and not dropped
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"complete": True}, "reference_images": {"images_count": 12}})
    assert set(saved_blocks(doc)) == {"tutorial", "reference_images"}
    assert saved_blocks(doc)["reference_images"] == {"images_count": 12}

    foreign = next(block for block in doc.inactive_blocks() if block.key == "reference_images")
    assert (foreign.active, foreign.claimed, foreign.dropped_on_save) == (False, False, False)


def test_a_claimed_then_abandoned_block_is_dropped_on_save() -> None:
    """A block made active this session and then abandoned is dropped on save ([[plugins#plugin-blocks]]).

    By switching to it and away, the user asserted the file is no longer that type. This is the
    wrong-but-plausible "save the current type" rule's opposite for the abandoned *former* type: it must
    be actively dropped, not merely left unwritten by accident.

    **Test steps:**

    * construct an audiopack-typed document (no plugin installed for it -- active anyway)
    * switch to ``tutorial``, abandoning ``audiopack``
    * verify ``audiopack`` is now claimed, inactive, and flagged to drop
    * verify the save writes ``tutorial`` but not ``audiopack``
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}, "tutorial": {"complete": True}})
    doc.set_active_type("tutorial")

    abandoned = next(block for block in doc.inactive_blocks() if block.key == "audiopack")
    assert (abandoned.active, abandoned.claimed, abandoned.dropped_on_save) == (False, True, True)
    assert set(saved_blocks(doc)) == {"tutorial"}


def test_switching_back_before_save_resurrects_a_hidden_block() -> None:
    """A dropped block stays resurrectable in memory until close ([[plugins#plugin-blocks]]).

    The drop is a save-*time* filter, not a mutation of ``data`` -- so switching the type back before
    saving makes the block active, hence written, again, with its contents intact. Switching type back and
    forth within a session is non-destructive until save.

    **Test steps:**

    * construct an audiopack-typed document and switch away to ``tutorial`` (audiopack would drop)
    * switch back to ``audiopack`` before any save
    * verify the audiopack block is active again, its contents survived, and it is written on save
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}, "tutorial": {"complete": True}})
    doc.set_active_type("tutorial")
    doc.set_active_type("audiopack")

    assert doc.active_block_key == "audiopack"
    assert doc.active_block == {"bitrate": 320}
    assert saved_blocks(doc)["audiopack"] == {"bitrate": 320}


def test_the_worked_example_carries_then_drops_the_same_key_by_claim_status() -> None:
    """The four-step worked example, verified step by step ([[plugins#plugin-blocks]]).

    Type starts at ``audiopack``; the file also holds an untouched ``reference_images`` block. The same
    key (``reference_images``) has **opposite fates** in steps 1 and 4, decided solely by "was it ever
    active this session": never-claimed carries, claimed-then-abandoned drops.

    **Test steps:**

    * step 1 -- switch to ``tutorial``: ``audiopack`` (former active, abandoned) drops; ``reference_images``
      (never active) is carried; the save writes ``tutorial`` + ``reference_images``
    * step 2 -- switch back to ``audiopack``: the in-memory ``audiopack`` revives, written again
    * step 3 -- switch to ``reference_images``: it becomes active; the save writes **only** ``reference_images``
    * step 4 -- switch away to ``audiopack``: ``reference_images`` is now claimed-and-abandoned and the save
      **deletes** it -- the opposite of step 1 for the very same key
    """
    doc = RehuDocument(
        {
            "type": "audiopack",
            "audiopack": {"bitrate": 320},
            "reference_images": {"images_count": 12},
        }
    )

    # step 1: switch to tutorial (create its block so the save has one to write)
    doc.set_active_type("tutorial")
    doc.set_active_field("complete", True)
    assert set(saved_blocks(doc)) == {"tutorial", "reference_images"}, "audiopack dropped, reference_images carried"
    assert saved_blocks(doc)["reference_images"] == {"images_count": 12}

    # step 2: switch back to audiopack -- the hidden block revives
    doc.set_active_type("audiopack")
    assert doc.active_block == {"bitrate": 320}
    assert set(saved_blocks(doc)) == {"audiopack", "reference_images"}, "tutorial now the abandoned one"

    # step 3: switch to reference_images -- it becomes active, the sole survivor
    doc.set_active_type("reference_images")
    assert set(saved_blocks(doc)) == {"reference_images"}

    # step 4: switch away -- reference_images is now claimed-and-abandoned, and is deleted
    doc.set_active_type("audiopack")
    assert "reference_images" not in saved_blocks(doc), "same key that step 1 carried is now dropped"
    assert set(saved_blocks(doc)) == {"audiopack"}


def test_reload_resets_session_claims_to_the_freshly_read_type(mocker: MockerFixture) -> None:
    """Revert begins a clean session: the claim set re-seeds from the on-disk type ([[plugins#plugin-blocks]]).

    Reverting discards this session's edits, type switches included, so a type switched to and abandoned
    is forgotten -- the block is back to whatever the file says it is.

    **Test steps:**

    * load an audiopack-typed document and switch to ``tutorial`` (claiming both)
    * reload (revert) from the unchanged file
    * verify the claim set is back to just the on-disk ``audiopack``
    """
    doc = load_doc(mocker, {"type": "audiopack", "audiopack": {"bitrate": 320}})
    doc.set_active_type("tutorial")
    assert doc.claimed_block_keys == frozenset({"audiopack", "tutorial"})

    doc.reload()
    assert doc.active_block_key == "audiopack"
    assert doc.claimed_block_keys == frozenset({"audiopack"})


def test_claims_persist_across_a_save_so_a_dropped_block_stays_dropped(mocker: MockerFixture) -> None:
    """A save does not reset the session -- its claims (and drops) carry on unchanged ([[plugins#plugin-blocks]]).

    The deliberate answer to "what does save (or save-as) do to the claim set": nothing. A block dropped
    on one save is not resurrected by the save itself; only switching its type back, or a reload, changes
    its fate.

    **Test steps:**

    * construct an audiopack-typed document, switch to ``tutorial`` (abandoning audiopack), and save
    * verify that first save dropped ``audiopack``
    * save again to a different path (save-as)
    * verify the claim set is unchanged and audiopack is still dropped by the second save
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}, "tutorial": {"complete": True}})
    doc.set_active_type("tutorial")
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    doc.save(Path("/fake/first.rehu"))
    assert "audiopack" not in json.loads(mock_write.call_args[0][1])

    doc.save(Path("/fake/second.rehu"))
    assert doc.claimed_block_keys == frozenset({"audiopack", "tutorial"})
    assert "audiopack" not in json.loads(mock_write.call_args[0][1])


# The discard log (#86): a save that drops a claimed-then-abandoned block records the *fact* of the
# drop -- block key and the document it left -- to the activity log ([[sync#overview]]), so it stays
# traceable even though the values are gone by design. The trigger must fire *exactly* when the invariant
# drops a claimed block: never for a carried never-claimed block, never on a read-only preview, and never on
# a write that failed -- a wrong trigger is a silent audit failure.


def discard_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The discard-log records captured so far -- the entries emitted per dropped block (#86).

    :param caplog: the log-capture fixture.
    :returns: the records whose message is a block discard, in emission order.
    """
    return [record for record in caplog.records if "discarded on save" in record.getMessage()]


def test_a_save_that_drops_a_claimed_block_records_the_discard(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    """A save that drops a claimed-then-abandoned block records the discard (#86, [[plugins#plugin-blocks]]).

    The safety net for the claim rule: making a block active arms its deletion on abandon, so the *fact* of
    the drop is logged -- block key and the document it left -- even though the values are gone by design
    ([[sync#overview]]). Only the fact, not the values: this is an audit trail, not an undo.

    **Test steps:**

    * construct an audiopack-typed document, switch to ``tutorial`` (abandoning audiopack), and save
    * verify the save dropped ``audiopack`` from the written file
    * verify exactly one discard was logged, at INFO, naming the block and the document it left
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}, "tutorial": {"complete": True}})
    doc.set_active_type("tutorial")
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    with caplog.at_level(logging.INFO, logger="rehuco_core.rehu_document"):
        doc.save(Path("/fake/info.rehu"))

    assert "audiopack" not in json.loads(mock_write.call_args[0][1])
    records = discard_records(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.INFO
    assert "audiopack" in records[0].getMessage()
    assert str(Path("/fake/info.rehu")) in records[0].getMessage()


def test_the_discard_log_records_every_dropped_block(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    """Each block a single save drops gets its own discard record (#86, [[plugins#plugin-blocks]]).

    Abandoning more than one type in a session leaves several claimed-then-abandoned blocks; a save drops
    them all and records each, so the audit trail is complete rather than reporting only the first.

    **Test steps:**

    * construct an audiopack-typed document also holding ``tutorial`` and ``reference_images`` blocks
    * switch to ``tutorial`` then to ``reference_images`` -- audiopack and tutorial are now both abandoned
    * save, and verify only ``reference_images`` survives
    * verify both abandoned blocks were logged, one record each
    """
    doc = RehuDocument(
        {
            "type": "audiopack",
            "audiopack": {"bitrate": 320},
            "tutorial": {"complete": True},
            "reference_images": {"images_count": 12},
        }
    )
    doc.set_active_type("tutorial")
    doc.set_active_type("reference_images")
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    with caplog.at_level(logging.INFO, logger="rehuco_core.rehu_document"):
        doc.save(Path("/fake/info.rehu"))

    assert set(json.loads(mock_write.call_args[0][1])) == {"format_version", "core", "reference_images"}
    logged = {record.getMessage().split(" block", 1)[0] for record in discard_records(caplog)}
    assert logged == {"audiopack", "tutorial"}


def test_a_save_that_carries_a_never_claimed_block_records_no_discard(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    """Carrying a never-claimed foreign block records no discard (#86, [[plugins#plugin-blocks]]).

    The trigger fires *exactly* when the invariant drops a claimed block, never when a never-claimed block
    is carried verbatim -- the same key that would be logged once abandoned is silent while it is merely
    custodial payload. A wrong trigger here would be a silent audit failure.

    **Test steps:**

    * construct a tutorial-typed document carrying an untouched foreign ``reference_images`` block
    * save without any type switching (the foreign block is carried, nothing dropped)
    * verify the foreign block was written and no discard was logged
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"complete": True}, "reference_images": {"images_count": 12}})
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    with caplog.at_level(logging.INFO, logger="rehuco_core.rehu_document"):
        doc.save(Path("/fake/info.rehu"))

    assert "reference_images" in json.loads(mock_write.call_args[0][1])
    assert discard_records(caplog) == []


def test_serialize_never_records_a_discard(caplog: pytest.LogCaptureFixture) -> None:
    """A read-only preview renders the invariant but records no discard (#86, #111).

    ``serialize()`` applies the same drop filter as ``save()`` so the source dock (#111) shows byte-for-byte
    what a save would write, but it touches no disk and discards nothing -- logging a discard there would
    cry one that never happened. Only a real save records; the block stays resurrectable.

    **Test steps:**

    * construct an audiopack-typed document and switch to ``tutorial`` (audiopack would drop on save)
    * serialize it (a preview), verifying audiopack is filtered out of the rendered text
    * verify no discard was logged -- nothing was actually dropped
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}, "tutorial": {"complete": True}})
    doc.set_active_type("tutorial")

    with caplog.at_level(logging.INFO, logger="rehuco_core.rehu_document"):
        rendered = json.loads(doc.serialize())

    assert "audiopack" not in rendered
    assert discard_records(caplog) == []


def test_a_failed_save_records_no_discard(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    """A save whose write fails records no discard (#86, [[plugins#plugin-blocks]]).

    The discard is logged only *after* the write succeeds: a write that raises dropped nothing on disk, so
    recording one would be a false audit entry. The document keeps the block, still resurrectable.

    **Test steps:**

    * construct an audiopack-typed document and switch to ``tutorial`` (audiopack armed to drop)
    * make ``atomic_write_text`` raise, and attempt the save
    * verify the save raised and no discard was logged
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}, "tutorial": {"complete": True}})
    doc.set_active_type("tutorial")
    mocker.patch("rehuco_core.rehu_document.atomic_write_text", side_effect=OSError("disk full"))

    with caplog.at_level(logging.INFO, logger="rehuco_core.rehu_document"), pytest.raises(OSError):
        doc.save(Path("/fake/info.rehu"))

    assert discard_records(caplog) == []


# endregion


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


def test_load_refuses_a_payload_with_an_over_long_integer(mocker: MockerFixture) -> None:
    """A ``.rehu`` is untrusted outside input, so a payload the parser cannot survive is **refused**
    rather than escaping as whatever it raised ([[data-model#write-integrity]]).

    An over-long integer literal trips CPython's integer-digit limit, which raises a bare ``ValueError``
    -- not the ``JSONDecodeError`` one would expect ``json.loads`` to be limited to. Left uncaught it
    surfaces as a crash in the agent instead of a refused file.

    Fed a real payload because that limit is a documented, platform-independent 4300 digits
    (``sys.int_info.str_digits_check_threshold``) -- unlike the recursion case below.

    Not a size defence -- the real sanity caps are #88.

    **Test steps:**

    * mock ``Path.read_text`` to return a number no ``int`` will accept
    * verify it comes back as :class:`RehuFormatError`, chained from the ``ValueError``
    """
    mocker.patch.object(Path, "read_text", return_value='{"format_version": ' + "9" * 5000 + "}")

    with pytest.raises(RehuFormatError) as exc_info:
        RehuDocument.load(FAKE_PATH)

    assert isinstance(exc_info.value.__cause__, ValueError)


def test_load_refuses_a_payload_that_exhausts_the_parsers_stack(mocker: MockerFixture) -> None:
    """A payload deep enough to exhaust the parser's stack is refused, not propagated as a
    ``RecursionError`` ([[data-model#write-integrity]]).

    **The error is injected rather than provoked with a deeply-nested payload, deliberately.** How deep
    is "too deep" is a property of the *platform*, not of this code: CPython's JSON scanner guards on
    real C-stack headroom rather than on ``sys.getrecursionlimit()`` (10,000 levels parse happily under
    a limit of 1000), so the threshold moves with the stack the OS hands the interpreter. A literal
    payload therefore asserts CPython's limits on one machine -- it passed on Linux and Windows and
    failed on macOS, whose larger stack swallowed 100,000 levels without complaint.

    What this module owes the caller is not "N levels raise" but "**whatever the parser raises, the file
    is refused**", and that is what is checked here.

    **Test steps:**

    * make the parser raise ``RecursionError``, as an over-deep payload would on some platform
    * verify it comes back as :class:`RehuFormatError`, chained from it
    """
    mocker.patch.object(Path, "read_text", return_value='{"core": {}}')
    mocker.patch("rehuco_core.rehu_document.json.loads", side_effect=RecursionError("maximum recursion depth"))

    with pytest.raises(RehuFormatError) as exc_info:
        RehuDocument.load(FAKE_PATH)

    assert isinstance(exc_info.value.__cause__, RecursionError)


def test_load_rejects_non_object(mocker: MockerFixture) -> None:
    """A ``.rehu`` whose top-level JSON is not an object is rejected.

    **Test steps:**

    * mock ``Path.read_text`` to return a JSON array
    * verify loading raises :class:`RehuFormatError`
    """
    mocker.patch.object(Path, "read_text", return_value="[1, 2, 3]")
    with pytest.raises(RehuFormatError):
        RehuDocument.load(FAKE_PATH)


# region Reserved-key misuse (#90, [[data-model#rehu-format]])


def test_format_version_holding_an_object_is_refused() -> None:
    """A ``format_version`` that holds an object is someone else's plugin data mistaken for the
    version stamp -- refused rather than silently restamped away on migration.

    **Test steps:**

    * construct a document whose ``format_version`` is an object
    * verify it raises :class:`RehuFormatError` naming the key
    """
    with pytest.raises(RehuFormatError, match="'format_version' holds an object"):
        RehuDocument({"format_version": {"some": "plugin data"}, "core": {"type": "tutorial"}})


def test_core_type_naming_format_version_is_refused() -> None:
    """A ``core.type`` naming ``format_version`` treats a reserved key as a resource type, which it
    is not -- refused rather than silently making the ``format_version`` block the active one.

    **Test steps:**

    * construct a document whose ``core.type`` is ``"format_version"``
    * verify it raises :class:`RehuFormatError` naming the offending value
    """
    with pytest.raises(RehuFormatError, match="'type' is 'format_version'"):
        RehuDocument({"format_version": 2, "core": {"type": "format_version"}})


def test_core_type_naming_core_is_refused() -> None:
    """A ``core.type`` naming ``core`` itself is refused the same way -- the core block is never a
    candidate type ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a document whose ``core.type`` is ``"core"``
    * verify it raises :class:`RehuFormatError` naming the offending value
    """
    with pytest.raises(RehuFormatError, match="'type' is 'core'"):
        RehuDocument({"format_version": 2, "core": {"type": "core"}})


def test_flat_v1_type_naming_format_version_is_refused() -> None:
    """The flat-v1 spelling of the reserved-type misuse (#135): a pre-migration top-level ``type``
    naming ``format_version``. Let through, the v1->v2 step moves it into the fresh ``core`` block and
    the first active-block write replaces the file's version stamp with a block -- saved, the file
    reads as v0 and this same build refuses it on reopen.

    **Test steps:**

    * construct a document from the flat, unstamped payload ``{"type": "format_version"}``
    * verify it raises :class:`RehuFormatError` naming the offending value
    """
    with pytest.raises(RehuFormatError, match="'type' is 'format_version'"):
        RehuDocument({"type": "format_version"})


def test_flat_v1_type_naming_core_is_refused() -> None:
    """The other reserved spelling through the same flat-v1 door (#135): ``{"type": "core"}`` would
    make the common core the *active block*, landing every plugin-field write inside ``core``.

    **Test steps:**

    * construct a document from the flat, unstamped payload ``{"type": "core"}``
    * verify it raises :class:`RehuFormatError` naming the offending value
    """
    with pytest.raises(RehuFormatError, match="'type' is 'core'"):
        RehuDocument({"type": "core"})


def test_a_stray_top_level_type_beside_an_existing_core_is_carried_not_refused() -> None:
    """A top-level ``type`` naming a reserved key *beside* an existing ``core`` block is not the
    flat-v1 spelling -- the v1->v2 step declines to move it (a self-contradictory v2-without-a-stamp),
    so it never becomes the document's type and is carried verbatim like any unknown key (#135,
    [[data-model#schema-version]]).

    **Test steps:**

    * construct a document whose payload has both a ``core`` block and a stray top-level ``type``
    * verify construction succeeds and the type still reads off ``core``
    * verify the stray key survives to the serialized file
    """
    doc = RehuDocument({"core": {"type": "tutorial"}, "type": "format_version"})
    assert doc.type == "tutorial"
    assert json.loads(doc.serialize())["type"] == "format_version"


def test_the_combined_reserved_key_misuse_is_refused() -> None:
    """The issue's own worked repro: both defects in one payload, `format_version` holding an object
    *and* `core.type` naming a reserved key. Refused before either can destroy the other.

    **Test steps:**

    * construct the combined malformed payload
    * verify it raises :class:`RehuFormatError`
    """
    with pytest.raises(RehuFormatError):
        RehuDocument({"format_version": {"some": "plugin data"}, "core": {"type": "format_version"}})


def test_reserved_key_misuse_is_refused_from_load_too(mocker: MockerFixture) -> None:
    """The same refusal applies through :meth:`RehuDocument.load`, not just direct construction --
    ``load`` doesn't catch the new raise, so it propagates to :meth:`RehuDocument.open_or_locked`
    exactly like an unparseable file does.

    **Test steps:**

    * mock ``Path.read_text`` to return the malformed JSON on disk
    * verify loading raises :class:`RehuFormatError`
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps({"format_version": {"x": 1}}))
    with pytest.raises(RehuFormatError, match="'format_version' holds an object"):
        RehuDocument.load(FAKE_PATH)


def test_reserved_key_misuse_locks_the_document_via_open_or_locked(mocker: MockerFixture) -> None:
    """Routed through :meth:`RehuDocument.open_or_locked`, a reserved-key misuse becomes an
    ``INVALID_FILE``-locked stub, the same as any other unparseable ``.rehu``
    ([[data-model#write-integrity]]) -- this is what carries the message to the agent's banner (#94)
    with no further agent-side work.

    **Test steps:**

    * mock ``Path.read_text`` to return the malformed JSON on disk
    * verify the returned document is an empty, load-failed stub whose lock reason carries the message
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps({"format_version": 2, "core": {"type": "core"}}))
    doc = RehuDocument.open_or_locked(FAKE_PATH)
    assert doc.load_failed is True
    assert doc.lock_reasons[0].kind is LockReasonKind.INVALID_FILE
    assert "'type' is 'core'" in doc.lock_reasons[0].message


# endregion


# region Lock reasons ([[data-model#write-integrity]])


def test_a_normal_document_has_no_lock_reasons() -> None:
    """A well-formed, current-version document is freely editable: no reasons, not a load failure.

    **Test steps:**

    * construct a document from the well-formed :data:`TUTORIAL` payload
    * verify ``lock_reasons`` is empty and ``load_failed`` is ``False``
    """
    doc = RehuDocument(json.loads(json.dumps(TUTORIAL)))
    assert not doc.lock_reasons
    assert doc.load_failed is False


def test_a_newer_format_version_locks_with_a_named_reason() -> None:
    """A file written by a newer build locks with the ``NEWER_FORMAT`` reason
    ([[data-model#schema-version]]).

    **Test steps:**

    * construct a document whose ``format_version`` is above what this build understands
    * verify the sole reason is ``NEWER_FORMAT`` and carries a message
    """
    doc = RehuDocument({"format_version": CURRENT_FORMAT_VERSION + 1})
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.NEWER_FORMAT]
    assert doc.lock_reasons[0].message


def test_a_legacy_tc_document_locks_with_a_named_reason() -> None:
    """A ``.tc``-mapped document with no ``.rehu`` yet locks with the ``LEGACY_TC`` reason
    ([[acquisition-tooling#tc-to-rehu]]).

    **Test steps:**

    * construct a document flagged ``legacy_tc`` at the current version
    * verify the sole reason is ``LEGACY_TC``
    """
    doc = RehuDocument({"type": "tutorial"}, legacy_tc=True)
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.LEGACY_TC]


@mark.parametrize(
    "authors",
    [
        param("Solo Author", id="not-a-list"),
        param(["Valid", 42], id="malformed-entry-among-valid"),
        param([{"url": "https://x.example"}], id="record-without-a-name"),
    ],
)
def test_a_present_but_uncoercible_authors_field_locks_as_invalid_field(authors: Any) -> None:
    """An owned field present but failing coercion loads locked with the ``INVALID_FIELD`` reason naming
    it, so an edit can never save the coerced default over the malformed original
    ([[data-model#write-integrity]]); the getter still coerces for *display*.

    **Test steps:**

    * construct a document whose ``authors`` is present but not skip-clean
    * verify the sole reason is ``INVALID_FIELD`` and names ``authors``
    * verify the getter still returns a coerced (non-crashing) reading
    """
    doc = RehuDocument({"core": {"authors": authors}})
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.INVALID_FIELD]
    assert "authors" in doc.lock_reasons[0].message
    # reading still coerces (never crashes on the value's type) -- the lock guards *writing*, not display
    assert isinstance(doc.authors, list)


@mark.parametrize(
    "authors",
    [
        param(["A", {"name": "B", "url": "https://b.example"}], id="strings-and-records"),
        param([], id="empty-list"),
    ],
)
def test_valid_authors_do_not_lock(authors: Any) -> None:
    """A well-formed ``authors`` (names and ``{name, url}`` records) is not an ``INVALID_FIELD``
    ([[field-schema#authors]]).

    **Test steps:**

    * construct a document whose ``authors`` entries are all skip-clean
    * verify no lock reason is produced
    """
    assert not RehuDocument({"core": {"authors": authors}}).lock_reasons


def test_an_absent_authors_field_does_not_lock() -> None:
    """A field that is merely *absent* reads as a clean default and does not lock -- only a
    present-but-uncoercible one does ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a document with no ``authors`` key at all
    * verify no lock reason is produced
    """
    assert not RehuDocument({"core": {"type": "tutorial"}}).lock_reasons


def test_open_or_locked_returns_a_missing_stub_for_a_vanished_file(mocker: MockerFixture) -> None:
    """A file that is gone opens as an empty ``MISSING`` stub bound to the path, never raising
    ([[data-model#write-integrity]]).

    **Test steps:**

    * mock the filesystem so reading raises ``FileNotFoundError``
    * call ``open_or_locked``
    * verify an empty document bound to the path came back, locked ``MISSING``, flagged ``load_failed``
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))

    doc = RehuDocument.open_or_locked(FAKE_PATH)

    assert doc.path == FAKE_PATH
    assert doc.core == {}
    assert doc.load_failed is True
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.MISSING]


def test_open_or_locked_returns_an_invalid_file_stub_for_unparseable_content(mocker: MockerFixture) -> None:
    """A file that cannot be parsed opens as an empty ``INVALID_FILE`` stub whose message carries the
    parser's own text ([[data-model#write-integrity]]).

    **Test steps:**

    * mock the filesystem to serve malformed JSON
    * call ``open_or_locked``
    * verify the sole reason is ``INVALID_FILE`` with a non-empty message
    """
    mocker.patch.object(Path, "read_text", return_value="{not valid json")

    doc = RehuDocument.open_or_locked(FAKE_PATH)

    assert doc.load_failed is True
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.INVALID_FILE]
    assert doc.lock_reasons[0].message


def test_open_or_locked_returns_a_genuinely_loaded_document_on_success(mocker: MockerFixture) -> None:
    """When the file reads cleanly, ``open_or_locked`` returns the loaded document, not a stub.

    **Test steps:**

    * mock the filesystem to serve a valid payload
    * call ``open_or_locked``
    * verify the document loaded its fields and is not a load failure
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))

    doc = RehuDocument.open_or_locked(FAKE_PATH)

    assert doc.load_failed is False
    assert not doc.lock_reasons
    assert doc.title == "Intro to Sculpting"


def test_save_refuses_while_load_failed(mocker: MockerFixture) -> None:
    """A load-failure stub refuses to save, so an empty document never clobbers the broken/absent file
    ([[data-model#write-integrity]]).

    **Test steps:**

    * build a ``MISSING`` stub via ``open_or_locked``
    * mock ``atomic_write_text`` to prove it is never reached
    * verify ``save()`` raises and nothing was written
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))
    write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    doc = RehuDocument.open_or_locked(FAKE_PATH)

    with pytest.raises(RehuFormatError, match="Refusing to save"):
        doc.save()
    write.assert_not_called()


def test_save_refuses_while_a_field_is_invalid(mocker: MockerFixture) -> None:
    """An ``INVALID_FIELD`` document refuses to save, so the coerced default never overwrites the
    malformed-but-recoverable original ([[data-model#write-integrity]]).

    **Test steps:**

    * construct a document with a present-but-uncoercible ``authors``
    * mock ``atomic_write_text`` to prove it is never reached
    * verify ``save()`` raises and nothing was written
    """
    write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    doc = RehuDocument({"core": {"authors": 42}}, FAKE_PATH)

    with pytest.raises(RehuFormatError, match="Refusing to save"):
        doc.save()
    write.assert_not_called()


def test_reload_of_a_vanished_file_locks_in_place_without_raising(mocker: MockerFixture) -> None:
    """Reverting onto a file that has since vanished locks the document in place rather than raising --
    the fix-retry loop ([[data-model#write-integrity]]).

    **Test steps:**

    * load a normal document
    * make the file vanish, then ``reload()``
    * verify it did not raise, is now an empty ``MISSING`` load failure
    """
    doc = load_doc(mocker, TUTORIAL)
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))

    doc.reload()

    assert doc.load_failed is True
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.MISSING]
    assert doc.core == {}


def test_reload_after_a_fix_drops_the_lock(mocker: MockerFixture) -> None:
    """Once the file reads cleanly again, ``reload()`` refills the data and drops the load-failure lock --
    the other half of the fix-retry loop ([[data-model#write-integrity]]).

    **Test steps:**

    * build a ``MISSING`` stub via ``open_or_locked``
    * make the path now read as a valid payload, then ``reload()``
    * verify the lock is gone, ``load_failed`` is ``False``, and the fields are seeded
    """
    mocker.patch.object(Path, "read_text", side_effect=FileNotFoundError("gone"))
    doc = RehuDocument.open_or_locked(FAKE_PATH)
    assert doc.load_failed is True

    mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))
    doc.reload()

    assert doc.load_failed is False
    assert not doc.lock_reasons
    assert doc.title == "Intro to Sculpting"


# endregion


# region Per-plugin-block format version (#81, #98, [[plugins#plugin-blocks]])


def test_constructing_a_document_stamps_and_migrates_an_unstamped_active_block() -> None:
    """An active block for an installed plugin that has never been stamped reads as v0 and is carried up
    to that plugin's current version at construction, mirroring the file-wide upgrade-on-load step
    ([[plugins#plugin-blocks]]).

    Exercised against the **real** tutorial plugin, now at block v1: an unstamped block runs its v0->v1
    step (the per-user relocation, [[field-schema#per-user-shared]]) and is stamped ``1``.

    **Test steps:**

    * construct a tutorial-typed document whose block carries no ``format_version``
    * verify the per-user ``rating`` moved under the default user and the block is stamped v1
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}})
    assert doc.active_block == {"format_version": 1, "users": {"admin": {"rating": 4}}}


def test_an_uninstalled_active_type_is_never_stamped() -> None:
    """A type no installed plugin declares is never migrated -- construction skips it before it ever
    reaches a chain, so its block is left exactly as constructed ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a document whose active type has no installed plugin
    * verify its block gained no stamp
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"bitrate": 320}})
    assert doc.active_block == {"bitrate": 320}


def test_an_inactive_blocks_version_is_never_touched() -> None:
    """An inactive block belonging to an installed plugin is carried verbatim, unstamped -- this build
    has no standing to restamp a block that is not the one the document's ``type`` names
    ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a reference-images-typed document also carrying an unstamped ``tutorial`` block
    * verify the inactive ``tutorial`` block gained no stamp
    """
    doc = RehuDocument({"type": "reference_images", "reference_images": {}, "tutorial": {"rating": 4}})
    assert doc.data["tutorial"] == {"rating": 4}


def test_a_block_newer_than_the_plugin_understands_locks_and_is_carried_verbatim() -> None:
    """An active block whose own ``format_version`` outruns the installed plugin locks with
    ``NEWER_BLOCK_FORMAT`` and is never restamped ([[plugins#plugin-blocks]]).

    **Test steps:**

    * construct a tutorial-typed document whose block is stamped above what the plugin understands
    * verify the sole reason is ``NEWER_BLOCK_FORMAT``, naming the block and both versions
    * verify the block's own stamp and fields are untouched
    """
    doc = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 5, "rating": 4}})
    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.NEWER_BLOCK_FORMAT]
    message = doc.lock_reasons[0].message
    assert "tutorial" in message and "5" in message
    assert doc.active_block == {"format_version": 5, "rating": 4}


def test_a_block_at_or_below_the_plugins_version_does_not_lock() -> None:
    """A block at (or predating) what its plugin understands is not ``NEWER_BLOCK_FORMAT``.

    **Test steps:**

    * construct a tutorial-typed document whose block is at v0, the plugin's own current version
    * verify no lock reason is produced
    """
    assert not RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}}).lock_reasons


def test_an_uninstalled_active_type_never_locks_on_block_version() -> None:
    """With no plugin installed for the active key, there is no ``current_block_version`` to compare
    against, so ``NEWER_BLOCK_FORMAT`` never fires ([[plugins#plugin-blocks]]) -- the fallback-editor
    path handles an uninstalled type instead.

    **Test steps:**

    * construct a document whose active type has no installed plugin, block stamped arbitrarily high
    * verify no lock reason is produced
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"format_version": 99}})
    assert not doc.lock_reasons


def test_on_disk_active_block_format_version_reports_the_file_not_the_payload(mocker: MockerFixture) -> None:
    """``on_disk_active_block_format_version`` is the on-disk block's version, distinct from the
    already-upgraded in-memory one -- the per-block sibling of ``on_disk_format_version``
    ([[plugins#plugin-blocks]], #89).

    **Test steps:**

    * load a document whose block predates its plugin
    * verify the in-memory block reads current while the on-disk figure still reads the old value
    """
    doc = load_doc(mocker, {"type": "tutorial", "tutorial": {"rating": 4}})
    assert doc.active_block == {"format_version": 1, "users": {"admin": {"rating": 4}}}
    assert doc.on_disk_active_block_format_version == 0


def test_on_disk_active_block_format_version_is_none_with_no_block_or_no_file(mocker: MockerFixture) -> None:
    """``None`` distinguishes "nothing to compare" from "a block exists and is old"
    ([[plugins#plugin-blocks]]), the same distinction :attr:`~rehuco_core.RehuDocument.on_disk_format_version`
    draws for the file-wide stamp.

    **Test steps:**

    * verify a document constructed without a path has no on-disk block figure
    * verify a loaded document with no active block at all has none either
    """
    assert RehuDocument({"type": "tutorial", "tutorial": {"rating": 4}}).on_disk_active_block_format_version is None
    assert load_doc(mocker, {"type": "tutorial"}).on_disk_active_block_format_version is None


def test_active_block_upgrade_pending_true_only_when_the_on_disk_block_is_old(mocker: MockerFixture) -> None:
    """:attr:`~rehuco_core.RehuDocument.active_block_upgrade_pending` folds the on-disk-vs-plugin
    comparison into one question, so a caller offering a single "Upgrade" action never has to know which
    layer is stale ([[plugins#plugin-blocks]], #89).

    **Test steps:**

    * load a document whose block predates its plugin -- pending
    * load one already at its plugin's version -- not pending
    """
    behind = load_doc(mocker, {"type": "tutorial", "tutorial": {"rating": 4}})
    assert behind.active_block_upgrade_pending is True

    current = load_doc(mocker, {"type": "tutorial", "tutorial": {"format_version": 1, "rating": 4}})
    assert current.active_block_upgrade_pending is False


def test_saving_an_upgraded_block_clears_the_pending_flag(mocker: MockerFixture) -> None:
    """Saving is what upgrades a document, block included -- the same "there is no separate migrate
    call" contract the file-wide stamp already has (:meth:`~rehuco_core.RehuDocument.save`).

    **Test steps:**

    * load a document whose block predates its plugin, confirming it starts pending
    * save, and verify the pending flag clears
    """
    doc = load_doc(mocker, {"type": "tutorial", "tutorial": {"rating": 4}})
    assert doc.active_block_upgrade_pending is True

    mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    doc.save()

    assert doc.active_block_upgrade_pending is False


# endregion


# region Per-user block state (#98, [[field-schema#per-user-shared]])


def test_active_user_field_reads_the_current_users_nested_value() -> None:
    """``active_user_field`` reads a value nested under ``active_block["users"][<username>]`` for this
    document's own username ([[field-schema#per-user-shared]]).

    **Test steps:**

    * construct an ``admin`` document whose v1 block holds a per-user ``rating``
    * verify the nested value reads back, and an absent per-user key returns the given default
    """
    doc = RehuDocument(
        {"type": "tutorial", "tutorial": {"format_version": 1, "users": {"admin": {"rating": 4}}}},
        username="admin",
    )
    assert doc.active_user_field("rating") == 4
    assert doc.active_user_field("missing", 0) == 0


def test_active_user_field_defaults_when_the_user_map_or_block_is_absent_or_malformed() -> None:
    """A per-user read falls back to the default whenever the block, the ``users`` map, this user, or the
    key is absent -- or any of them is malformed ([[field-schema#per-user-shared]],
    [[data-model#write-integrity]]).

    **Test steps:**

    * read with no block, no ``users`` map, this user absent, and a malformed ``users`` / user value
    * verify each reads the default rather than crashing
    """
    assert RehuDocument({"type": "tutorial"}, username="admin").active_user_field("rating", 0) == 0
    no_map = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1}}, username="admin")
    assert no_map.active_user_field("rating", 0) == 0
    other_user = RehuDocument(
        {"type": "tutorial", "tutorial": {"format_version": 1, "users": {"bob": {"rating": 9}}}},
        username="admin",
    )
    assert other_user.active_user_field("rating", 0) == 0
    bad_map = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1, "users": "junk"}}, username="admin")
    assert bad_map.active_user_field("rating", 0) == 0
    bad_user = RehuDocument(
        {"type": "tutorial", "tutorial": {"format_version": 1, "users": {"admin": "junk"}}}, username="admin"
    )
    assert bad_user.active_user_field("rating", 0) == 0


def test_set_active_user_field_creates_the_nested_maps_on_write() -> None:
    """``set_active_user_field`` installs the block, the ``users`` map, and this user's sub-map on demand
    ([[field-schema#per-user-shared]]).

    **Test steps:**

    * construct an ``admin`` document with no plugin block at all
    * write a per-user field
    * verify the whole nested path was created under the active block
    """
    doc = RehuDocument({"type": "tutorial"}, username="admin")
    doc.set_active_user_field("rating", 5)
    assert doc.data["tutorial"]["users"] == {"admin": {"rating": 5}}

    # a second write reuses the existing ``users`` map and user sub-map rather than recreating them
    doc.set_active_user_field("viewed", True)
    assert doc.data["tutorial"]["users"] == {"admin": {"rating": 5, "viewed": True}}


def test_set_active_user_field_replaces_a_malformed_users_map_or_sub_map() -> None:
    """A ``users`` map or per-user sub-map that is present but not an object is replaced rather than
    crashed on, the same defensive write ``set_active_field`` gives a malformed block
    ([[data-model#write-integrity]]).

    **Test steps:**

    * write a per-user field into a block whose ``users`` value is a non-object
    * write one into a block whose user sub-map is a non-object
    * verify each malformed value was replaced by a fresh nested map holding the write
    """
    bad_map = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1, "users": "junk"}}, username="admin")
    bad_map.set_active_user_field("rating", 5)
    assert bad_map.data["tutorial"]["users"] == {"admin": {"rating": 5}}

    bad_user = RehuDocument(
        {"type": "tutorial", "tutorial": {"format_version": 1, "users": {"admin": "junk"}}}, username="admin"
    )
    bad_user.set_active_user_field("rating", 5)
    assert bad_user.data["tutorial"]["users"] == {"admin": {"rating": 5}}


def test_per_user_writes_from_two_identities_do_not_collide() -> None:
    """Two identities writing the same block file into distinct sub-maps, so one user's flags never
    misfile against another's -- the multi-user guard the whole design turns on
    ([[field-schema#per-user-shared]]).

    **Test steps:**

    * over one shared block, write a per-user ``rating`` as ``alice`` and another as ``bob``
    * verify each landed under only its own username, and reading one identity never sees the other's
    """
    data: dict[str, Any] = {"type": "tutorial", "tutorial": {"format_version": 1}}
    RehuDocument(data, username="alice").set_active_user_field("rating", 1)
    RehuDocument(data, username="bob").set_active_user_field("rating", 2)

    assert data["tutorial"]["users"] == {"alice": {"rating": 1}, "bob": {"rating": 2}}
    assert RehuDocument(data, username="alice").active_user_field("rating") == 1
    assert RehuDocument(data, username="bob").active_user_field("rating") == 2


def test_per_user_accessors_go_through_active_block_for_an_uninstalled_type() -> None:
    """The per-user accessors build on :attr:`~rehuco_core.RehuDocument.active_block`, so a type whose
    plugin isn't installed here still reads and writes sanely -- no crash, present values read, absent
    ones default ([[field-schema#per-user-shared]], [[plugins#plugin-blocks]]).

    **Test steps:**

    * read a present per-user value from an uninstalled type's block (never migrated, carried verbatim)
    * read an absent one, and read from a document with no block at all
    """
    doc = RehuDocument({"type": "audiopack", "audiopack": {"users": {"admin": {"rating": 7}}}}, username="admin")
    assert doc.active_user_field("rating", 0) == 7
    assert doc.active_user_field("missing", 0) == 0
    assert RehuDocument({"type": "audiopack"}, username="admin").active_user_field("rating", 0) == 0


def test_username_defaults_to_admin_and_is_reported() -> None:
    """A document with no configured identity resolves per-user state to ``admin``, the spec's fallback
    ([[field-schema#per-user-shared]]); :attr:`~rehuco_core.RehuDocument.username` reports whichever
    identity is in force.

    **Test steps:**

    * verify a document constructed with no username reports ``admin`` and reads that user's state
    * verify an explicit username is reported and used
    """
    default = RehuDocument({"type": "tutorial", "tutorial": {"format_version": 1, "users": {"admin": {"rating": 3}}}})
    assert default.username == "admin"
    assert default.active_user_field("rating") == 3

    explicit = RehuDocument({"type": "tutorial"}, username="alice")
    assert explicit.username == "alice"
    explicit.set_active_user_field("rating", 8)
    assert explicit.data["tutorial"]["users"] == {"alice": {"rating": 8}}


# endregion
