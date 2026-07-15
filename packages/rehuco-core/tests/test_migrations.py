"""Tests for the read-time format migrations ([[data-model#schema-version]])."""

import json
from pathlib import Path
from typing import Any, Final

from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import CURRENT_FORMAT_VERSION, RehuDocument, migrate_rehu_data

# A format-v1 document: the common fields still at the top level, beside the plugin blocks
# ([[data-model#rehu-format]]).
V1: Final = {
    "format_version": 1,
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "tutorial",
    "sources": [{"title": "Intro to Sculpting", "primary": True}],
    "authors": ["First Author"],
    "released": "2025-03",
    "description": "Some description.",
    "advertised_tags": ["sculpting"],
    "extra_tags": ["rework"],
    "original_size": 5368709120,
    "current_size": 1073741824,
    "created": "2026-01-15T09:30:00Z",
    "updated": "2026-06-20T14:12:00Z",
    "hidden_images": ["info03.jpg"],
    "tutorial": {"rating": 4},
    "reference_images": {"images_count": 12},
}


def v1_copy(**overrides: Any) -> dict[str, Any]:
    """Build a fresh, mutable copy of :data:`V1`.

    Migrations mutate their payload in place, so each test needs its own.

    :param overrides: keys to add or replace on the copy.
    :returns: the copied payload.
    """
    return {**V1, **overrides}


def test_v1_common_fields_move_into_the_core_block() -> None:
    """A v1 document's top-level common fields are nested under ``core`` ([[data-model#rehu-format]]).

    **Test steps:**

    * migrate a v1 payload
    * verify every common field moved into ``core``, values intact
    * verify none of them are left at the top level
    """
    data = v1_copy()
    migrate_rehu_data(data)

    assert data["core"]["type"] == "tutorial"
    assert data["core"]["id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert data["core"]["sources"] == [{"title": "Intro to Sculpting", "primary": True}]
    assert data["core"]["hidden_images"] == ["info03.jpg"]
    assert data["core"]["original_size"] == 5368709120
    assert "type" not in data
    assert "sources" not in data


def test_migration_leaves_plugin_blocks_and_the_version_stamp_at_the_top_level() -> None:
    """Only the common fields move; blocks and ``format_version`` stay where they are
    ([[data-model#rehu-format]]).

    **Test steps:**

    * migrate a v1 payload carrying two plugin blocks
    * verify both blocks are still top-level, with their contents untouched
    * verify ``format_version`` stayed top-level and now records the version the payload actually is
    """
    data = v1_copy()
    migrate_rehu_data(data)

    assert data["tutorial"] == {"rating": 4}
    assert data["reference_images"] == {"images_count": 12}
    assert data["format_version"] == CURRENT_FORMAT_VERSION


def test_an_unknown_v1_scalar_moves_nowhere_and_an_unknown_object_stays_a_block() -> None:
    """The v1 recognition rule is applied verbatim, once ([[data-model#rehu-format]]).

    v1 called any top-level object-valued key a plugin block, so that is what they become; a key v1
    never knew is not in :data:`V1_COMMON_FIELD_KEYS`, so it is not treated as a common field. This
    inherits v1's own ambiguity rather than inventing a new answer for it.

    **Test steps:**

    * migrate a v1 payload with an unknown scalar and an unknown object at the top level
    * verify both stayed at the top level, untouched
    """
    data = v1_copy(stray_scalar=42, stray_object={"nested": True})
    migrate_rehu_data(data)

    assert data["stray_scalar"] == 42
    assert data["stray_object"] == {"nested": True}
    assert "stray_scalar" not in data["core"]


def test_every_step_older_than_the_payload_runs_so_a_chain_walks_them_all() -> None:
    """The dispatch runs **every** step above the payload's version, which is what lets a chain carry a
    document forward across more than one hop ([[data-model#schema-version]]).

    Pins the contract a second migration will rely on: ``migrate`` compares the version the payload came
    in at against each step's *target*, so a v1 payload satisfies ``< 2``, ``< 3``, ``< 4``... and walks
    them in order. This is why the entry version is never advanced between steps -- doing so would change
    nothing, since the comparison is against each target rather than a running value.

    Simulated with stand-in steps, because there is only one real migration today and the property worth
    protecting is the dispatch's, not that migration's.

    **Test steps:**

    * run the dispatch shape over stand-in steps for a payload at each version
    * verify every step above the entry version ran, in order, and none at or below it did
    """

    def steps_run_from(version: int) -> list[str]:
        ran: list[str] = []
        for target in (2, 3, 4):
            if version < target:
                ran.append(f"v{target - 1}->v{target}")
        return ran

    assert steps_run_from(1) == ["v1->v2", "v2->v3", "v3->v4"]
    assert steps_run_from(2) == ["v2->v3", "v3->v4"]
    assert not steps_run_from(4)
    assert not steps_run_from(99)  # a newer file is never "upgraded" downward


def test_the_v1_step_declines_a_payload_that_already_has_a_core_block() -> None:
    """The v1 -> v2 step **creates** ``core``, so it refuses a payload that already has one -- and that
    refusal is what stops it losing data.

    The rebuild folds every v1-named top-level key into a fresh ``core``. Run against a payload whose
    ``core`` is already taken, it would drop such a key entirely: here a plugin block keyed
    ``description`` (a v1 common field name) would simply cease to exist. Nothing produces this payload
    -- it is self-contradictory, since ``core`` implies v2 and v2 implies a stamp that would stop the
    step running -- but "no caller does this" is not a reason for a transformation to eat data when it
    does.

    **Test steps:**

    * migrate an unstamped payload carrying both a ``core`` block and a ``description`` plugin block
    * verify both survive untouched
    """
    data: dict[str, Any] = {"core": {"type": "tutorial"}, "description": {"plugin": "block"}}
    migrate_rehu_data(data)

    assert data["core"] == {"type": "tutorial"}
    assert data["description"] == {"plugin": "block"}


def test_migrating_an_already_current_document_changes_nothing() -> None:
    """Migrations are idempotent -- a v2 payload is left exactly as it is.

    **Test steps:**

    * migrate a v1 payload, snapshot the result, then migrate it again
    * verify the second run changed nothing
    """
    data = v1_copy()
    migrate_rehu_data(data)
    once = dict(data)

    migrate_rehu_data(data)

    assert data == once


def test_an_unstamped_flat_payload_is_migrated_even_though_it_reads_as_v0() -> None:
    """A payload with **no** ``format_version`` still migrates when it has the old flat shape
    ([[data-model#schema-version]]).

    An unstamped payload is v0, and v0 names no layout -- so its shape is what says which one it is.
    Dispatching on the stamp alone (``format_version == 1``) would skip this document silently: its
    ``type`` would read empty and its common fields would classify as plugin blocks.

    **Test steps:**

    * migrate a flat payload carrying no version stamp
    * verify its common fields moved into ``core``, its block stayed put, and it gained a stamp
    """
    data: dict[str, Any] = {"type": "tutorial", "authors": ["A"], "tutorial": {"rating": 4}}
    migrate_rehu_data(data)

    assert data == {
        "format_version": CURRENT_FORMAT_VERSION,
        "core": {"type": "tutorial", "authors": ["A"]},
        "tutorial": {"rating": 4},
    }


def test_a_malformed_stamp_is_not_trusted_and_the_payload_still_migrates() -> None:
    """A corrupt ``format_version`` resolves to v0 rather than being believed
    ([[data-model#schema-version]]).

    Matches `RehuDocument.format_version`'s own defensive coercion ([[data-model#write-integrity]]).
    Reading the stamp raw would
    make this file skip -- the key *is* present and its value simply isn't ``1`` -- and skip silently.

    **Test steps:**

    * migrate a flat payload whose stamp is a string
    * verify it was migrated anyway
    """
    data = v1_copy(format_version="v1")
    migrate_rehu_data(data)

    assert data["core"]["type"] == "tutorial"
    assert "type" not in data


@mark.parametrize(
    ("case", "data", "migrated"),
    [
        param("stamped v1", {"format_version": 1, "type": "tutorial"}, True, id="stamped-v1"),
        param("stamped newer", {"format_version": 99, "core": {}, "type": "x"}, False, id="stamped-newer"),
        param("unstamped, flat", {"type": "tutorial"}, True, id="unstamped-flat"),
        param("unstamped but has core", {"core": {"x": 1}, "type": "tutorial"}, False, id="unstamped-with-core"),
    ],
)
def test_only_a_payload_at_an_older_layout_is_restructured(case: str, data: dict[str, Any], migrated: bool) -> None:
    """Which step runs follows from the payload's version ([[data-model#schema-version]]).

    Observed through what the migration *does*, since resolution is the migrator's own business rather
    than a caller's question. The cases cover each way a payload can decline to be restructured: already
    current per its stamp, newer than this build, or already carrying a ``core`` block despite having no
    stamp -- the last being a contradictory payload the v1 step refuses rather than mangles.

    **Test steps:**

    * migrate each payload
    * verify only the ones at an older layout had their ``type`` moved into ``core``
    """
    migrate_rehu_data(data)

    assert ("type" not in data) is migrated, case


def test_an_unstamped_payload_that_has_a_core_block_is_stamped_but_left_alone() -> None:
    """A payload carrying ``core`` without a stamp is contradictory, and is neither restructured nor
    refused ([[data-model#schema-version]]).

    ``core`` arrived with v2 and every v2 build stamps, so no build wrote this. It is still read as well
    as it can be -- the layout is untouched, in particular the core block is not nested inside another
    one -- and stamped, so it stops claiming to be unversioned. `RehuDocument.load` logs the
    contradiction when such a payload comes from an actual file; an in-memory one is simply a payload
    that has not been stamped yet, which is normal.

    **Test steps:**

    * migrate a ``core``-carrying payload with no ``format_version``
    * verify the layout is untouched and it now carries the current stamp
    """
    data: dict[str, Any] = {"core": {"type": "tutorial", "authors": ["A"]}, "tutorial": {"rating": 4}}
    migrate_rehu_data(data)

    assert data == {
        "format_version": CURRENT_FORMAT_VERSION,
        "core": {"type": "tutorial", "authors": ["A"]},
        "tutorial": {"rating": 4},
    }


def test_an_empty_payload_gains_a_stamp_but_no_core_block() -> None:
    """A brand-new, empty document has nothing to move and gains no empty block for its trouble -- the
    accessors create ``core`` on demand when something is first written.

    It is still stamped: an empty document is a *current-format* document, and saying so costs nothing
    while leaving it unstamped would make the payload claim to be v0 ([[data-model#schema-version]]).

    **Test steps:**

    * migrate an empty payload
    * verify it gained only the stamp
    """
    data: dict[str, Any] = {}
    migrate_rehu_data(data)

    assert data == {"format_version": CURRENT_FORMAT_VERSION}


def test_loading_a_v1_file_migrates_it_and_saving_stamps_the_new_version(mocker: MockerFixture) -> None:
    """The end-to-end contract: a v1 file opens transparently, and the upgrade only reaches **disk** on
    save ([[data-model#schema-version]]).

    The document is fully upgraded the moment it exists -- layout and stamp both -- so nothing downstream
    ever handles a half-migrated payload. What waits for the save is only the *file*: opening a v1 file
    and closing it without editing leaves it exactly as it was.

    **Test steps:**

    * construct a document from a v1 payload
    * verify its common accessors read through the migrated core block, and it reports the new version
    * save, and verify the upgraded layout and its stamp reach disk together
    """
    doc = RehuDocument(v1_copy())
    assert doc.type == "tutorial"
    assert doc.title == "Intro to Sculpting"
    assert doc.authors == ["First Author"]
    assert doc.active_block == {"rating": 4}
    assert [block.key for block in doc.inactive_blocks()] == ["reference_images"]
    assert doc.format_version == CURRENT_FORMAT_VERSION

    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    doc.save(Path("/fake/info.rehu"))

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["format_version"] == CURRENT_FORMAT_VERSION
    assert saved["core"]["type"] == "tutorial"
    assert saved["reference_images"] == {"images_count": 12}
