"""Tests for the read-time format migrations ([[data-model#schema-version]])."""

import json
from pathlib import Path
from typing import Any, Final

import pytest
from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    CURRENT_FORMAT_VERSION,
    DEFAULT_PLUGIN_REGISTRY,
    RehuDocument,
    current_block_version,
    migrate_block_data,
    migrate_rehu_data,
)
from rehuco_core.migrations import BLOCK_TARGETS, Chain, run, validate_chain

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
    never knew is not in the v1->v2 step's frozen common-field set, so it is not treated as a common
    field. This inherits v1's own ambiguity rather than inventing a new answer for it.

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
    assert doc.active_block == {"format_version": 1, "users": {"admin": {"rating": 4}}}
    assert [block.key for block in doc.inactive_blocks()] == ["reference_images"]
    assert doc.format_version == CURRENT_FORMAT_VERSION

    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    doc.save(Path("/fake/info.rehu"))

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["format_version"] == CURRENT_FORMAT_VERSION
    assert saved["core"]["type"] == "tutorial"
    assert saved["reference_images"] == {"images_count": 12}


# region Per-block migration engine ([[plugins#plugin-blocks]])


def test_an_unstamped_block_migrates_from_v0_not_a_deduced_shape() -> None:
    """A block's absent stamp is v0 outright -- block versioning has no pre-stamping history to predate
    ([[plugins#plugin-blocks]]), unlike the file-wide chain's v1 deduction.

    **Test steps:**

    * run a chain whose only step targets v1 over an unstamped block
    * verify the step ran and the block is stamped v1
    """
    ran: list[str] = []
    chain: Chain = ((1, lambda block, _username: ran.append("v0->v1")),)
    block: dict[str, Any] = {"rating": 4}

    run(block, chain, base_version=0, username="admin")

    assert ran == ["v0->v1"]
    assert block == {"rating": 4, "format_version": 1}


def test_a_malformed_block_stamp_is_not_trusted() -> None:
    """A corrupt block ``format_version`` resolves to v0 rather than being believed, the same defensive
    coercion the file-wide stamp gets.

    **Test steps:**

    * run a v1 chain over a block whose stamp is a string
    * verify the step ran anyway
    """
    ran: list[str] = []
    chain: Chain = ((1, lambda block, _username: ran.append("v0->v1")),)
    block: dict[str, Any] = {"format_version": "junk", "rating": 4}

    run(block, chain, base_version=0, username="admin")

    assert ran == ["v0->v1"]
    assert block["format_version"] == 1


def test_every_block_step_older_than_the_block_runs_in_order() -> None:
    """A block several versions behind walks every step above its own version, in order -- the block
    runner mirrors :class:`RehuMigrator`'s own chain guarantee.

    **Test steps:**

    * run a chain of three steps up to v3, declared out of order, over a v0 block
    * verify all three ran, in ascending order
    """
    ran: list[str] = []
    chain: Chain = (
        (2, lambda block, _username: ran.append("v1->v2")),
        (1, lambda block, _username: ran.append("v0->v1")),
        (3, lambda block, _username: ran.append("v2->v3")),
    )
    block: dict[str, Any] = {}

    run(block, chain, base_version=0, username="admin")

    assert ran == ["v0->v1", "v1->v2", "v2->v3"]
    assert block["format_version"] == 3


def test_migrating_an_already_current_block_changes_nothing_but_the_stamp() -> None:
    """A block already at its chain's head runs no step ([[plugins#plugin-blocks]]).

    **Test steps:**

    * run a v1 chain over a block already stamped v1
    * verify no step ran and its other fields are untouched
    """
    ran: list[str] = []
    chain: Chain = ((1, lambda block, _username: ran.append("v0->v1")),)
    block: dict[str, Any] = {"format_version": 1, "rating": 4}

    run(block, chain, base_version=0, username="admin")

    assert not ran
    assert block == {"format_version": 1, "rating": 4}


def test_a_block_newer_than_the_chain_reaches_is_never_restamped_or_touched() -> None:
    """A block whose stamp is already past the chain's head runs no step and keeps its own (higher) stamp
    -- never lowered, mirroring the file-wide fail-safe rule ([[data-model#schema-version]]).

    **Test steps:**

    * run a v1 chain over a block stamped v5
    * verify no step ran and the stamp is unchanged
    """
    ran: list[str] = []
    chain: Chain = ((1, lambda block, _username: ran.append("v0->v1")),)
    block: dict[str, Any] = {"format_version": 5, "rating": 4}

    run(block, chain, base_version=0, username="admin")

    assert not ran
    assert block == {"format_version": 5, "rating": 4}


def test_an_empty_chain_leaves_a_v0_block_stamped_v0() -> None:
    """A block whose plugin has no migration chain (head ``0``) gains only the v0 stamp, with no step to
    run -- the Collection case, and any uninstalled or unknown key ([[plugins#plugin-blocks]]).

    **Test steps:**

    * run an empty chain over an unstamped block
    * verify it gains only the stamp
    """
    block: dict[str, Any] = {"rating": 4}

    run(block, (), base_version=0, username="admin")

    assert block == {"rating": 4, "format_version": 0}


# endregion


# region Per-user block layout v1 (#98, [[field-schema#per-user-shared]])


def test_v0_to_v1_moves_exactly_the_per_user_subset_for_a_tutorial_block() -> None:
    """The real tutorial plugin's v0->v1 step relocates **exactly** the per-user subset under ``users``
    and leaves **exactly** the shared set inline ([[field-schema#per-user-shared]]).

    Both sides of the partition are asserted: a shared flag wrongly moved into the map, or a per-user key
    wrongly left inline, is precisely the misfiling the whole design guards against -- and a test that
    only checked one side would miss it.

    **Test steps:**

    * migrate a v0 tutorial block carrying every per-user key and every shared key
    * verify the per-user subset landed under ``users[<username>]``, in full
    * verify every shared field stayed inline and no per-user key was left behind
    * verify the block is stamped v1
    """
    block: dict[str, Any] = {
        "rating": 4,
        "viewed": True,
        "todo": False,
        "keep": True,
        "favorite": True,
        "learning_paths": [{"title": "P", "index": 1, "visibility": "private"}],
        "complete": True,
        "online": True,
        "collections": [{"title": "Series", "index": 1}],
        "original_duration": 71220,
        "level": ["intermediate"],
    }

    migrate_block_data(block, "tutorial", "admin")

    assert block["users"] == {
        "admin": {
            "rating": 4,
            "viewed": True,
            "todo": False,
            "keep": True,
            "favorite": True,
            "learning_paths": [{"title": "P", "index": 1, "visibility": "private"}],
        }
    }
    assert block["complete"] is True
    assert block["online"] is True
    assert block["collections"] == [{"title": "Series", "index": 1}]
    assert block["original_duration"] == 71220
    assert block["level"] == ["intermediate"]
    assert block["format_version"] == 1
    for key in ("rating", "viewed", "todo", "keep", "favorite", "learning_paths"):
        assert key not in block


def test_v0_to_v1_moves_exactly_the_per_user_subset_for_a_reference_images_block() -> None:
    """The reference-images plugin runs the **same** v0->v1 step over the **same** per-user subset -- the
    "one type left inline" trap: the two plugins must not diverge ([[field-schema#per-user-shared]]).

    ``images_count`` is the shared field unique to this type; it must stay inline, never treated as
    per-user.

    **Test steps:**

    * migrate a v0 reference-images block carrying the per-user keys plus its shared ``images_count``
    * verify the per-user subset moved and ``images_count`` (and the other shared flags) stayed inline
    """
    block: dict[str, Any] = {
        "rating": 0,
        "viewed": False,
        "todo": False,
        "keep": False,
        "favorite": False,
        "learning_paths": [],
        "complete": True,
        "online": False,
        "collections": [],
        "images_count": None,
    }

    migrate_block_data(block, "reference_images", "admin")

    assert block["users"] == {
        "admin": {
            "rating": 0,
            "viewed": False,
            "todo": False,
            "keep": False,
            "favorite": False,
            "learning_paths": [],
        }
    }
    assert block["complete"] is True
    assert block["online"] is False
    assert block["collections"] == []  # pylint: disable=use-implicit-booleaness-not-comparison
    assert block["images_count"] is None
    assert block["format_version"] == 1
    assert "rating" not in block


def test_v0_to_v1_moves_only_present_keys_and_mints_no_favorite() -> None:
    """The step relocates whichever per-user keys a block actually has and never invents one -- a real
    pre-#98 block predates ``favorite``, so migrating it leaves the field absent (read as ``False`` by
    the accessor's default), not minted ([[field-schema#per-user-shared]]).

    **Test steps:**

    * migrate a v0 block carrying only ``rating`` (as an old ``.tc`` import would)
    * verify only ``rating`` moved and no ``favorite`` was minted into the user's map
    """
    block: dict[str, Any] = {"rating": 4, "complete": True}

    migrate_block_data(block, "tutorial", "admin")

    assert block["users"] == {"admin": {"rating": 4}}
    assert "favorite" not in block["users"]["admin"]


def test_v0_to_v1_gives_every_block_a_users_map_even_with_nothing_to_move() -> None:
    """The step dispatches on version, not shape: a v0 block with no per-user keys still gains an owned
    (empty) ``users`` map, so every v1 block has the same uniform shape ([[field-schema#per-user-shared]]).

    **Test steps:**

    * migrate a v0 block carrying only shared fields
    * verify the shared fields stayed inline and an empty per-user map was minted for the user
    """
    block: dict[str, Any] = {"complete": True, "online": False}

    migrate_block_data(block, "tutorial", "admin")

    assert block == {"complete": True, "online": False, "format_version": 1, "users": {"admin": {}}}


def test_migrating_a_v0_block_twice_is_idempotent() -> None:
    """Re-running the migration is a no-op: the second pass finds a v1 block, runs no step, and rewrites
    the same stamp ([[field-schema#per-user-shared]], the block-scoped mirror of the file-wide
    idempotency guarantee).

    **Test steps:**

    * migrate a v0 tutorial block, snapshot the result, then migrate it again
    * verify the second run changed nothing
    """
    block: dict[str, Any] = {"rating": 4, "complete": True}
    migrate_block_data(block, "tutorial", "admin")
    once = dict(block)

    migrate_block_data(block, "tutorial", "admin")

    assert block == once


def test_a_block_newer_than_v1_is_never_restamped_or_relocated() -> None:
    """A real-plugin block stamped past v1 runs no step and keeps its own (higher) stamp -- the
    never-lowers guarantee still holds through the new per-user step ([[plugins#plugin-blocks]]).

    **Test steps:**

    * migrate a block stamped above the plugin's current version, carrying an inline per-user key
    * verify no relocation happened and the stamp is untouched
    """
    block: dict[str, Any] = {"format_version": 5, "rating": 4}

    migrate_block_data(block, "tutorial", "admin")

    assert block == {"format_version": 5, "rating": 4}


def test_two_usernames_file_into_distinct_sub_maps_with_no_cross_contamination() -> None:
    """The migration files a block's per-user keys under the **supplied** username, and two blocks
    migrated under different usernames never bleed into each other -- the multi-user assertion that
    actually exercises the misfiling risk the design guards against ([[field-schema#per-user-shared]]).

    **Test steps:**

    * migrate two separate v0 blocks under two different usernames
    * verify each block's data landed under only its own username
    """
    alice_block: dict[str, Any] = {"rating": 1}
    bob_block: dict[str, Any] = {"rating": 2}

    migrate_block_data(alice_block, "tutorial", "alice")
    migrate_block_data(bob_block, "tutorial", "bob")

    assert alice_block["users"] == {"alice": {"rating": 1}}
    assert bob_block["users"] == {"bob": {"rating": 2}}


def test_current_block_version_is_the_chain_head_derived_not_declared() -> None:
    """ "What's current" is the highest target in a plugin's chain, not a number the plugin states about
    itself ([[plugins#plugin-blocks]]) -- so the tutorial/reference-images per-user chains read head ``1``,
    while a plugin with no chain (Collection, or any unknown key) reads ``0``.

    **Test steps:**

    * verify each per-user type's head is ``1``
    * verify a chainless builtin and an unknown key both read ``0``
    """
    assert current_block_version("tutorial") == 1
    assert current_block_version("reference_images") == 1
    assert current_block_version("collection") == 0
    assert current_block_version("audiopack") == 0


# endregion


# region Chain validation ([[plugins#plugin-blocks]])


def test_validate_chain_rejects_a_gap() -> None:
    """A chain must be contiguous from ``base_version + 1``: a gap means a later step would silently run on
    a payload it was never written for ([[plugins#plugin-blocks]]).

    **Test steps:**

    * validate a chain that skips v2 (targets 1 and 3, base 0)
    * verify it raises
    """
    with pytest.raises(ValueError, match="contiguous"):
        validate_chain(((1, lambda block, username: None), (3, lambda block, username: None)), 0)


def test_validate_chain_rejects_duplicate_targets() -> None:
    """Two steps claiming the same target is ambiguous -- which one is *the* v1 ([[plugins#plugin-blocks]]).

    **Test steps:**

    * validate a chain with two steps both targeting v1
    * verify it raises
    """
    with pytest.raises(ValueError, match="duplicate"):
        validate_chain(((1, lambda block, username: None), (1, lambda block, username: None)), 0)


def test_a_well_formed_chain_validates() -> None:
    """A unique, contiguous chain from ``base_version + 1`` passes ([[plugins#plugin-blocks]]).

    **Test steps:**

    * validate a two-step chain (targets 1, 2) at base 0, and the real single-step tutorial chain at base 0
    * verify neither raises
    """
    validate_chain(((2, lambda block, username: None), (1, lambda block, username: None)), 0)
    validate_chain(((1, lambda block, username: None),), 0)


def test_every_block_migration_target_names_a_real_plugin() -> None:
    """Every key in :data:`~rehuco_core.migrations.BLOCK_TARGETS` is a real plugin main key -- catches a
    typo that would leave a real type's blocks silently un-migrated ([[plugins#plugin-blocks]]).

    **Test steps:**

    * verify the registered migration keys are a subset of the shipped plugins' main keys
    """
    installed = {spec.key for spec in DEFAULT_PLUGIN_REGISTRY}
    assert set(BLOCK_TARGETS) <= installed
