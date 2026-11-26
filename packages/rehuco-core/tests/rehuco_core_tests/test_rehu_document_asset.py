"""Tests for the asset type's declaration, its block's value rules and its typed accessors (#674).

Every field of the ``asset`` block is optional and a missing one reads as *not known* ([[assets#block]]); a present
value the getter cannot read locks the document, so an edit never saves the coerced value over the original
([[data-model#write-integrity]]).
"""

import json
from pathlib import Path
from typing import Any, Final

from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import (
    ASSET_KINDS,
    ASSET_PLUGIN,
    DEFAULT_PLUGIN_REGISTRY,
    AssetLicense,
    LockReasonKind,
    RehuDocument,
    current_block_version,
)

from rehuco_core_tests.test_rehu_document import FAKE_PATH, mock_writes

SCALARS: Final = (
    ("kind", "texture"),
    ("source_updated", "2025-03"),
    ("advertised_version", "1.2"),
    ("current_version", "1.1"),
    ("advertised_size", 1_048_576),
    ("advertised_triangles", "12-14"),
    ("advertised_texture_size", "1024,2048"),
    ("triangles", 12_000),
    ("texture_size", 4096),
    ("acquired", "2024-11-02"),
)
"""Each optional scalar accessor, with a value it reads back as stored."""

MALFORMED_SCALARS: Final = (
    ("kind", "lamp", "one of the asset kinds"),
    ("kind", 3, "one of the asset kinds"),
    ("advertised_version", 1.2, "a string"),
    ("advertised_triangles", 12, "a string"),
    ("advertised_texture_size", [1024], "a string"),
    ("source_updated", 2025, "a date string"),
    ("acquired", ["2024"], "a date string"),
    ("advertised_size", "1 GB", "a whole number"),
    ("triangles", True, "a whole number"),
    ("texture_size", 4096.0, "a whole number"),
)
"""A present value each scalar's getter cannot read, and what its lock message says the value should have been."""

COLLECTIONS: Final = (
    ("formats", ["fbx", "blend"], []),
    ("compatibility", {"blender": ">=4,<5", "unreal": "5.1-5.6"}, {}),
)
"""Each list or map accessor, a value it reads back as stored, and what it reads when absent."""

MALFORMED_COLLECTIONS: Final = (
    ("formats", ["fbx", 3], ["fbx"], "a list of strings"),
    ("formats", "fbx", [], "a list of strings"),
    ("formats", None, [], "a list of strings"),
    ("compatibility", {"blender": "4", "unreal": 5}, {"blender": "4"}, "a map of strings"),
    ("compatibility", ["blender"], {}, "a map of strings"),
)
"""A present list or map the getter must read past: the stored value, what it reads as, and the lock message's
expectation."""


def asset_doc(fields: dict[str, Any], path: Path | None = None) -> RehuDocument:
    """Build an asset document whose active block carries ``fields``.

    :param fields: the block's own fields, as stored.
    :param path: the path to bind the document to, for the tests that save.
    :returns: the document.
    """
    return RehuDocument({"format_version": 2, "core": {"type": "asset"}, "asset": fields}, path)


# region declaration
def test_the_asset_type_is_installed_under_its_key_and_alias() -> None:
    """``asset`` is a built-in type, and ``Asset`` normalizes to it ([[assets#block]]).

    **Test steps:**

    * resolve both spellings against the default registry
    * verify both name the asset declaration and the main key is ``asset``
    """
    assert DEFAULT_PLUGIN_REGISTRY.resolve("asset") is ASSET_PLUGIN
    assert DEFAULT_PLUGIN_REGISTRY.resolve("Asset") is ASSET_PLUGIN
    assert DEFAULT_PLUGIN_REGISTRY.main_key("Asset") == "asset"


def test_the_asset_type_takes_only_the_shared_fields_an_asset_has() -> None:
    """An asset declares ``rating``, ``online``, ``favorite`` and ``collections`` from the shared set and leaves out
    what describes content being studied ([[assets#block]]).

    **Test steps:**

    * read the asset declaration's field names
    * verify the four shared fields are in it and ``complete``, ``keep`` and ``learning_paths`` are not
    """
    names = DEFAULT_PLUGIN_REGISTRY.field_names("asset")

    assert {"rating", "online", "favorite", "collections"} <= set(names)
    assert not {"complete", "keep", "learning_paths"} & set(names)


def test_a_document_switched_to_asset_writes_an_asset_block(mocker: MockerFixture) -> None:
    """A tutorial switched to ``asset`` saves its fields into an ``asset`` block, stamped as this build reads it.

    **Test steps:**

    * switch a fresh tutorial document to ``asset`` and set its kind
    * save with the writers mocked
    * verify the saved type, the block's kind and its stamp
    """
    doc = RehuDocument({"format_version": 2, "core": {"type": "tutorial"}}, FAKE_PATH)
    write, _ = mock_writes(mocker)

    doc.set_active_type("asset")
    doc.kind = "pack"
    doc.save()

    saved = json.loads(write.call_args[0][1])
    assert saved["core"]["type"] == "asset"
    assert saved["asset"] == {"format_version": current_block_version("asset"), "kind": "pack"}


def test_an_asset_block_newer_than_this_build_locks() -> None:
    """An ``asset`` block stamped past what this build reads locks as newer -- the no-chain path
    ([[plugins#plugin-blocks]]).

    **Test steps:**

    * build an asset document whose block is stamped one above this build's head
    * verify the document carries a newer-block-format reason
    """
    doc = asset_doc({"format_version": current_block_version("asset") + 1})

    assert [reason.kind for reason in doc.lock_reasons] == [LockReasonKind.NEWER_BLOCK_FORMAT]


# endregion


# region scalars
@mark.parametrize(("attr", "_value"), [param(attr, value, id=attr) for attr, value in SCALARS])
def test_an_absent_scalar_reads_none_and_does_not_lock(attr: str, _value: Any) -> None:
    """A missing field reads ``None`` -- not known, never ``0`` or ``""`` ([[assets#block]]).

    :param attr: the accessor's name.
    :param _value: unused here.
    """
    doc = asset_doc({})

    assert getattr(doc, attr) is None
    assert not doc.lock_reasons


@mark.parametrize(("attr", "value"), [param(attr, value, id=attr) for attr, value in SCALARS])
def test_a_stored_scalar_reads_back_as_stored(attr: str, value: Any) -> None:
    """A well-formed value reads back verbatim and does not lock.

    :param attr: the accessor's name.
    :param value: the stored value.
    """
    doc = asset_doc({attr: value})

    assert getattr(doc, attr) == value
    assert not doc.lock_reasons


@mark.parametrize("kind", [param(kind, id=kind) for kind in ASSET_KINDS])
def test_every_listed_kind_is_read(kind: str) -> None:
    """Each value of the closed list reads back, ``decal``, ``brush`` and ``unknown`` included ([[assets#kind]]).

    :param kind: one listed kind.
    """
    doc = asset_doc({"kind": kind})

    assert doc.kind == kind
    assert not doc.lock_reasons


@mark.parametrize(
    ("attr", "value", "expected"),
    [param(attr, value, expected, id=f"{attr}-{value!r}") for attr, value, expected in MALFORMED_SCALARS],
)
def test_a_malformed_scalar_reads_none_and_locks(attr: str, value: Any, expected: str) -> None:
    """A present value the getter cannot read reads ``None`` and locks, naming the key and what it should be.

    **Test steps:**

    * build an asset document carrying the malformed value
    * verify the getter reads ``None``, the value is untouched, and one invalid-field reason names the key

    :param attr: the accessor's name.
    :param value: the malformed stored value.
    :param expected: what the lock message says the value should have been.
    """
    doc = asset_doc({attr: value})

    assert getattr(doc, attr) is None
    assert doc.active_block[attr] == value
    assert [(reason.kind, reason.message.split(" (")[0]) for reason in doc.lock_reasons] == [
        (LockReasonKind.INVALID_FIELD, f"{attr}: present but not {expected}")
    ]


@mark.parametrize(("attr", "_value"), [param(attr, value, id=attr) for attr, value in SCALARS])
def test_a_null_scalar_normalizes_away_on_save(mocker: MockerFixture, attr: str, _value: Any) -> None:
    """A JSON ``null`` reads ``None``, does not lock, and saves as no key at all -- ``None`` is never written.

    **Test steps:**

    * build an asset document whose field is ``null``, bound to a path
    * save with the writers mocked
    * verify it did not lock and the saved block has no such key

    :param mocker: pytest-mock fixture.
    :param attr: the accessor's name.
    :param _value: unused here.
    """
    doc = asset_doc({attr: None}, FAKE_PATH)
    write, _ = mock_writes(mocker)

    assert not doc.lock_reasons
    doc.save()

    assert attr not in json.loads(write.call_args[0][1])["asset"]


@mark.parametrize(("attr", "value"), [param(attr, value, id=attr) for attr, value in SCALARS])
def test_a_scalar_setter_writes_and_none_removes(attr: str, value: Any) -> None:
    """A setter writes into the active block, and ``None`` removes the key rather than storing ``null``.

    :param attr: the accessor's name.
    :param value: the value to write.
    """
    doc = asset_doc({})

    setattr(doc, attr, value)
    assert doc.active_block[attr] == value

    setattr(doc, attr, None)
    assert attr not in doc.active_block


# endregion


# region lists and maps
@mark.parametrize(("attr", "_value", "empty"), [param(*spec, id=spec[0]) for spec in COLLECTIONS])
def test_an_absent_list_or_map_reads_empty(attr: str, _value: Any, empty: Any) -> None:
    """A missing list or map reads empty and does not lock.

    :param attr: the accessor's name.
    :param _value: unused here.
    :param empty: the empty reading.
    """
    doc = asset_doc({})

    assert getattr(doc, attr) == empty
    assert not doc.lock_reasons


@mark.parametrize(("attr", "value", "_empty"), [param(*spec, id=spec[0]) for spec in COLLECTIONS])
def test_a_list_or_map_reads_back_and_its_setter_writes_a_copy(attr: str, value: Any, _empty: Any) -> None:
    """A stored list or map reads back as stored; the setter stores its own copy of what it is handed.

    **Test steps:**

    * verify a stored value reads back without locking
    * write the value through the setter, then change the caller's object
    * verify the block kept the value as written

    :param attr: the accessor's name.
    :param value: the stored value.
    :param _empty: unused here.
    """
    assert getattr(asset_doc({attr: value}), attr) == value
    doc = asset_doc({})
    handed = value.copy()

    setattr(doc, attr, handed)
    handed.clear()

    assert doc.active_block[attr] == value
    assert not doc.lock_reasons


@mark.parametrize(("attr", "value", "empty"), [param(*row, id=row[0]) for row in COLLECTIONS])
def test_setting_a_list_or_map_empty_removes_its_key(attr: str, value: Any, empty: Any) -> None:
    """An emptied list or map leaves the block: a missing field is *not known*, and an empty one says no more (#678).

    **Test steps:**

    * over an asset holding the value, set it empty through the setter
    * verify the key is gone, the accessor reads empty and nothing locks
    """
    doc = asset_doc({attr: value})

    setattr(doc, attr, empty)

    assert attr not in doc.active_block
    assert getattr(doc, attr) == empty
    assert not doc.lock_reasons


@mark.parametrize(
    ("attr", "value", "reads", "expected"),
    [param(*spec, id=f"{spec[0]}-{spec[1]!r}") for spec in MALFORMED_COLLECTIONS],
)
def test_a_malformed_list_or_map_reads_its_clean_entries_and_locks(
    attr: str, value: Any, reads: Any, expected: str
) -> None:
    """A list or map holding what its getter cannot read reads only the clean entries and locks, naming the key.

    :param attr: the accessor's name.
    :param value: the malformed stored value.
    :param reads: what the getter reads it as.
    :param expected: what the lock message says the value should have been.
    """
    doc = asset_doc({attr: value})

    assert getattr(doc, attr) == reads
    assert [(reason.kind, reason.message.split(" (")[0]) for reason in doc.lock_reasons] == [
        (LockReasonKind.INVALID_FIELD, f"{attr}: present but not {expected}")
    ]


STORED_LICENSES: Final = [{"license": "fab-standard", "url": "https://www.fab.com/eula"}, {"license": "fab-ue-only"}]
"""Two licenses as the block stores them: one with the address of its terms, one with none."""

MALFORMED_LICENSES: Final = (
    param([{"license": "fab-standard"}, {"license": "fab-standard", "url": "x"}], [0], id="a-repeated-id"),
    param([{"license": ""}, {"license": "fab-ue-only"}], [1], id="an-empty-id"),
    param([{"license": 7}, {"license": "fab-ue-only"}], [1], id="an-id-not-a-string"),
    param([{"license": "fab-standard", "url": 404}], [], id="a-url-not-a-string"),
    param([{"license": "fab-standard", "url": None}], [0], id="a-null-url"),
    param([{"license": "fab-standard", "note": "x"}], [0], id="a-key-of-its-own"),
    param(["fab-standard"], [], id="an-entry-not-an-object"),
    param("fab-standard", [], id="not-a-list"),
    param(None, [], id="null"),
)
"""A stored ``licenses`` the getter must read past, and the places of the entries it reads."""


def test_licenses_read_back_as_entries_and_their_setter_writes_the_block() -> None:
    """``licenses`` reads its entries in order, a missing ``url`` as ``None``, and the setter writes them as stored
    (#705).

    **Test steps:**

    * verify a stored list reads back as its entries, without locking
    * write those entries to an empty asset through the setter
    * verify the block holds the list as stored
    """
    entries = [AssetLicense("fab-standard", "https://www.fab.com/eula"), AssetLicense("fab-ue-only")]
    assert asset_doc({"licenses": STORED_LICENSES}).licenses == entries
    doc = asset_doc({})

    doc.licenses = entries

    assert doc.active_block["licenses"] == STORED_LICENSES
    assert not doc.lock_reasons


def test_setting_no_licenses_removes_the_key() -> None:
    """An emptied ``licenses`` leaves the block, as an emptied ``formats`` does.

    **Test steps:**

    * over an asset holding two licenses, set none
    * verify the key is gone, the accessor reads empty and nothing locks
    """
    doc = asset_doc({"licenses": STORED_LICENSES})

    doc.licenses = []

    assert "licenses" not in doc.active_block
    assert doc.licenses == []
    assert not doc.lock_reasons


@mark.parametrize(("stored", "kept"), MALFORMED_LICENSES)
def test_a_licenses_list_read_past_reads_its_clean_entries_and_locks(stored: Any, kept: list[int]) -> None:
    """A ``licenses`` holding what its getter cannot read -- an entry of the wrong shape, an id twice -- reads only the
    first clean entry of each id and locks, naming the key.

    :param stored: the stored value.
    :param kept: the places of the entries it reads.
    """
    doc = asset_doc({"licenses": stored})

    assert doc.licenses == [AssetLicense.from_data(stored[index]) for index in kept]
    assert [(reason.kind, reason.message.split(" (")[0]) for reason in doc.lock_reasons] == [
        (LockReasonKind.INVALID_FIELD, "licenses: present but not a list of licenses, each with its own id")
    ]


def test_license_ids_differing_by_case_are_two_licenses() -> None:
    """An id is compared exactly, as a store spells it: ``fab-standard`` and ``FAB-STANDARD`` are two entries, and
    nothing locks.

    **Test steps:**

    * build an asset holding both spellings
    * verify both read and nothing locks
    """
    doc = asset_doc({"licenses": [{"license": "fab-standard"}, {"license": "FAB-STANDARD"}]})

    assert doc.licenses == [AssetLicense("fab-standard"), AssetLicense("FAB-STANDARD")]
    assert not doc.lock_reasons


# endregion


# region other types
OTHER_TYPE_FIELDS: Final = {
    "kind": "lecture",
    "licenses": {"id": 1},
    "formats": "duf",
    "compatibility": ["4"],
    "triangles": "many",
    "acquired": None,
}
"""Asset-named keys holding what an asset block would lock on, or drop: each means something of its own elsewhere."""


@mark.parametrize("resource_type", [param("tutorial", id="another-installed-type"), param("daz3d", id="not-installed")])
def test_asset_rules_leave_another_types_block_alone(mocker: MockerFixture, resource_type: str) -> None:
    """A block of a type that does not declare the asset fields is neither locked nor rewritten for carrying keys
    of the same names ([[assets#block]]).

    **Test steps:**

    * build a document of another type whose block holds asset-named keys with values an asset would refuse
    * verify it carries no lock reason
    * save with the writers mocked, and verify every such key was written back as it was, the ``null`` included

    :param mocker: pytest-mock fixture.
    :param resource_type: a type that declares none of the asset fields.
    """
    block = {"format_version": current_block_version(resource_type), **OTHER_TYPE_FIELDS}
    doc = RehuDocument({"format_version": 2, "core": {"type": resource_type}, resource_type: block}, FAKE_PATH)
    write, _ = mock_writes(mocker)

    assert not doc.lock_reasons
    doc.save()

    saved = json.loads(write.call_args[0][1])[resource_type]
    assert {key: saved[key] for key in OTHER_TYPE_FIELDS} == OTHER_TYPE_FIELDS


# endregion
