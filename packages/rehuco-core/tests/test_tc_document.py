"""Tests for the .tc -> .rehu mapping ([[acquisition-tooling#tc-to-rehu]])."""

from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_core import CURRENT_FORMAT_VERSION, RehuDocument, RehuFormatError, TcDocument, load_tc, tc_to_rehu_data

FAKE_PATH: Final = Path("/fake/info.tc")

# A real tc4 Tutorial .tc, shaped like resource-hub/tests/data/tc_samples/tutorial.tc.
TUTORIAL_TC: Final = """
type: Tutorial
publisher: Some Publisher
collection: Some Collection
collection_index: 3
title: Some Title
author: [Author 1, Author 2]
released: 2026.01
duration: 445500
original_size: 0
current_size: 0
level: [beginner, intermediate, advanced, any]
url: https://foo/bar
rating: 5
complete: true
todo: true
viewed: true
keep: true
online: true
tags: [tag 1, tag 2]
extraTags: [extra tag 1, extra tag 2, extra tag 3]
learning_paths:
  - Some learning path 1
  - Some learning path 2
"""

# Shaped like resource-hub/tests/data/tc_samples/reference_images.tc -- carries a leaked `duration`.
REFERENCE_IMAGES_TC: Final = """
type: ReferenceImages
publisher: Some Publisher
collection: ""
collection_index: 0
title: Some Title
author: [Author 1]
released: "2026.01.01"
duration: 720
original_size: 0
current_size: 0
url: https://foo/bar
rating: -5
complete: false
todo: true
viewed: true
keep: true
online: true
tags: [tag 1]
extraTags: []
learning_paths: []
"""

# Shaped like resource-hub/tests/data/tc_samples/collection.tc -- carries resource fields a
# Collection shouldn't declare, to prove they're dropped on import.
COLLECTION_TC: Final = """
type: Collection
publisher: Some Publisher
collection: ""
collection_index: 0
title: Some Title
author: [Author 1, Author 2]
released: "2026.01"
duration: 445500
original_size: 0
current_size: 0
url: http://foo/bar
rating: 0
complete: true
todo: true
viewed: true
keep: true
online: true
tags: [tag 1, tag 2]
extraTags: []
"""


def load_tc_doc(mocker: MockerFixture, content: str) -> RehuDocument:
    """Mock ``Path.read_text`` and load a ``RehuDocument`` from ``content`` via :func:`load_tc`.

    :param mocker: pytest-mock fixture.
    :param content: the ``.tc`` file's raw YAML text.
    :returns: the mapped document.
    """
    mocker.patch.object(Path, "read_text", return_value=content)
    return load_tc(FAKE_PATH)


def test_tutorial_mapping(mocker: MockerFixture) -> None:
    """A Tutorial ``.tc`` maps sources, authors, duration, level, collections, and learning paths.

    **Test steps:**

    * mock ``Path.read_text`` to return :data:`TUTORIAL_TC`
    * load via :func:`load_tc`
    * verify the target shape ([[field-schema#field-mapping]]) and :attr:`RehuDocument.legacy_tc`
    """
    doc = load_tc_doc(mocker, TUTORIAL_TC)
    assert doc.legacy_tc is True
    assert doc.format_version == CURRENT_FORMAT_VERSION
    assert doc.type == "tutorial"
    assert doc.id == ""
    assert doc.title == "Some Title"
    assert doc.publisher == "Some Publisher"
    assert doc.url == "https://foo/bar"
    assert doc.primary_source is not None
    assert doc.primary_source["primary"] is True
    assert doc.authors == ["Author 1", "Author 2"]
    assert doc.released == "2026.01"
    assert doc.advertised_tags == ["tag 1", "tag 2"]
    assert doc.extra_tags == ["extra tag 1", "extra tag 2", "extra tag 3"]

    assert doc.active_block_key == "tutorial"
    block = doc.active_block
    # shared fields stay inline in the block ([[field-schema#per-user-shared]])
    assert block["complete"] is True
    assert block["online"] is True
    assert block["original_duration"] == 445500
    assert block["level"] == ["beginner", "intermediate", "advanced", "any"]
    assert block["collections"] == [{"title": "Some Collection", "index": 3}]
    # per-user fields nest under ``users[<username>]``, keyed by the import identity (default ``admin``)
    assert block["users"] == {
        "admin": {
            "favorite": False,
            "keep": True,
            "learning_paths": [
                {"title": "Some learning path 1", "index": 1, "visibility": "private"},
                {"title": "Some learning path 2", "index": 2, "visibility": "private"},
            ],
            "rating": 5,
            "todo": True,
            "viewed": True,
        }
    }
    # the importer emits block layout v1 directly ([[field-schema#per-user-shared]]), so construction
    # finds it already current and never re-migrates it -- not a tc4 field, but not stray either
    assert block["format_version"] == 1


def test_reference_images_mapping_drops_leaked_duration(mocker: MockerFixture) -> None:
    """A ReferenceImages ``.tc`` maps to the ``reference_images`` block, dropping the leaked `duration`.

    **Test steps:**

    * mock ``Path.read_text`` to return :data:`REFERENCE_IMAGES_TC`
    * load via :func:`load_tc`
    * verify the leaked `duration` produced no ``original_duration``, ``images_count`` is omitted
      entirely (never derived from it, never fabricated as ``null``), and per-user flags nest under
      ``users`` at block v1
    """
    doc = load_tc_doc(mocker, REFERENCE_IMAGES_TC)
    assert doc.type == "reference_images"
    assert doc.active_block_key == "reference_images"
    block = doc.active_block
    assert block["format_version"] == 1
    assert block["complete"] is False
    assert block["collections"] == []
    assert block["users"] == {
        "admin": {
            "favorite": False,
            "keep": True,
            "learning_paths": [],
            "rating": -5,
            "todo": True,
            "viewed": True,
        }
    }
    # ``images_count`` is shared, new, and empty on import -- *omitted*, filled later by scanning, never the
    # leaked tc4 `duration` and never fabricated as ``null`` ([[field-schema#duration-size]],
    # [[field-schema#deferred-items]])
    assert "images_count" not in block
    assert "original_duration" not in block
    assert "level" not in block
    assert "rating" not in block  # moved under ``users``, not left inline


def test_collection_mapping_has_no_plugin_block(mocker: MockerFixture) -> None:
    """A Collection ``.tc`` drops every resource field, even ones present in the YAML.

    **Test steps:**

    * mock ``Path.read_text`` to return :data:`COLLECTION_TC` (which carries rating/booleans/etc)
    * load via :func:`load_tc`
    * verify only common-core fields survive -- no ``collection``/``tutorial``/``reference_images``
      block at all ([[field-schema#resource-types]])
    """
    doc = load_tc_doc(mocker, COLLECTION_TC)
    assert doc.type == "collection"
    assert doc.title == "Some Title"
    assert doc.original_size == 0
    assert "tutorial" not in doc.data
    assert "reference_images" not in doc.data
    assert "collection" not in doc.data
    assert doc.active_block == {}
    assert doc.plugin_blocks() == []


def test_empty_tc_maps_to_a_blank_default_document(mocker: MockerFixture) -> None:
    """An empty ``.tc`` file is a valid blank document, not an error -- tc4 can leave a 0-byte `info.tc`.

    **Test steps:**

    * mock ``Path.read_text`` to return an empty string
    * load via :func:`load_tc`
    * verify it defaults to an empty Tutorial with a blank primary source, rather than raising
    """
    doc = load_tc_doc(mocker, "")
    assert doc.legacy_tc is True
    assert doc.type == "tutorial"
    assert doc.title == ""
    assert doc.primary_source == {"title": "", "publisher": "", "url": "", "primary": True}
    assert doc.active_block["complete"] is True
    assert doc.active_block["collections"] == []


def test_missing_or_unrecognized_type_defaults_to_tutorial(mocker: MockerFixture) -> None:
    """A missing or unrecognized ``type`` defaults to ``Tutorial``, matching tc4's own lenient default.

    **Test steps:**

    * load a ``.tc`` with no ``type`` key at all
    * load a ``.tc`` with an unrecognized ``type`` value
    * verify both default to the tutorial type rather than raising
    """
    assert load_tc_doc(mocker, "title: No Type").type == "tutorial"
    assert load_tc_doc(mocker, "type: SomethingElse\ntitle: Bad Type").type == "tutorial"


def test_invalid_yaml_raises_rehu_format_error(mocker: MockerFixture) -> None:
    """Malformed YAML or a non-mapping top level raises ``RehuFormatError``, mirroring ``RehuDocument.load``.

    **Test steps:**

    * load unparseable YAML (unterminated flow sequence) -> expect ``RehuFormatError``
    * load a YAML scalar (not a mapping) -> expect ``RehuFormatError``
    """
    mocker.patch.object(Path, "read_text", return_value="tags: [unterminated")
    with pytest.raises(RehuFormatError):
        load_tc(FAKE_PATH)

    mocker.patch.object(Path, "read_text", return_value="just a string")
    with pytest.raises(RehuFormatError):
        load_tc(FAKE_PATH)


def test_the_mapping_stamps_the_current_format_but_mints_no_resource_bookkeeping() -> None:
    """The mapped object is stamped with the current format, yet carries no ``id``/``created``/``updated``
    ([[acquisition-tooling#tc-to-rehu]], [[data-model#schema-version]]).

    The two are different kinds of fact and that is the whole distinction: ``format_version`` describes
    the *encoding* this function just built, so it can only be current and writing it down is free. The
    others describe the *resource* and are an importer's to mint -- an ``id`` minted here would be a new
    UUID on every open.

    **Test steps:**

    * map a ``.tc`` dict
    * verify it is stamped at the current version, so it needs no migration to be read
    * verify no resource bookkeeping was invented
    """
    data = tc_to_rehu_data({"type": "Tutorial", "title": "Some Title"})

    assert data["format_version"] == CURRENT_FORMAT_VERSION
    assert "id" not in data["core"]
    assert "created" not in data["core"]
    assert "updated" not in data["core"]


def test_legacy_size_and_duration_string_fallback() -> None:
    """tc4's legacy human-readable size/duration strings parse the same as its C++ fallback.

    **Test steps:**

    * map a ``.tc`` dict with string-valued ``original_size``/``current_size``/``duration``
    * verify each parses to the expected byte/second count (``Tutorial::parsedFileSize``/``parsedDuration``)
    """
    data = tc_to_rehu_data(
        {
            "type": "Tutorial",
            "original_size": "1.5 GB",
            "current_size": "500 MB",
            "duration": "2h 15m",
        }
    )
    assert data["core"]["original_size"] == int(1.5 * 1000**3)
    assert data["core"]["current_size"] == int(500 * 1000**2)
    assert data["tutorial"]["original_duration"] == 2 * 3600 + 15 * 60


def test_legacy_size_string_edge_cases() -> None:
    """A blank, non-numeric, or unrecognized-suffix size string falls back to ``0``.

    **Test steps:**

    * map ``.tc`` dicts with an empty string, a non-numeric magnitude, and an unrecognized suffix
    * verify each parses to ``0`` (``Tutorial::parsedFileSize``'s own fallback-to-zero behavior)
    """
    assert tc_to_rehu_data({"original_size": ""})["core"]["original_size"] == 0
    assert tc_to_rehu_data({"original_size": "not-a-number GB"})["core"]["original_size"] == 0
    assert tc_to_rehu_data({"original_size": "5 XB"})["core"]["original_size"] == 0


def test_legacy_duration_string_edge_cases() -> None:
    """An unrecognized token in a duration string contributes nothing to the total.

    **Test steps:**

    * map a ``.tc`` Tutorial dict whose ``duration`` mixes a recognized token with an unrecognized one
    * verify only the recognized token's seconds are counted (``Tutorial::parsedDuration``)
    """
    data = tc_to_rehu_data({"type": "Tutorial", "duration": "1h junk"})
    assert data["tutorial"]["original_duration"] == 3600


def test_tc_document_data_and_type_properties() -> None:
    """``TcDocument.data`` and ``.type`` expose the parsed mapping and resolved type.

    **Test steps:**

    * construct a ``TcDocument`` directly from a plain dict
    * verify ``data`` returns it verbatim and ``type`` resolves to the recognized value
    """
    raw = {"type": "ReferenceImages", "title": "Some Title"}
    doc = TcDocument(raw)
    assert doc.data == raw
    assert doc.type == "ReferenceImages"


def test_the_username_threads_from_load_tc_into_the_users_map(mocker: MockerFixture) -> None:
    """The identity given to :func:`load_tc` reaches the block's ``users`` key end to end, and the mapped
    document reports it as its own ([[field-schema#per-user-shared]]).

    **Test steps:**

    * mock ``Path.read_text`` to return :data:`TUTORIAL_TC` and load with an explicit username
    * verify the per-user flags landed under that username and nowhere else, and the document adopts it
    """
    mocker.patch.object(Path, "read_text", return_value=TUTORIAL_TC)
    doc = load_tc(FAKE_PATH, username="alice")

    assert doc.username == "alice"
    block = doc.active_block
    assert set(block["users"]) == {"alice"}
    assert block["users"]["alice"]["rating"] == 5


def test_tc_to_rehu_data_files_per_user_flags_under_the_given_username() -> None:
    """``tc_to_rehu_data`` files the imported per-user flags under the supplied username, and mints
    ``favorite`` as ``False`` regardless of any tc4 value -- it is new to rehuco with no tc4 source key
    ([[field-schema#per-user-shared]]).

    **Test steps:**

    * map a Tutorial ``.tc`` dict (with a stray ``favorite``) under an explicit username
    * verify the per-user subset landed under only that username, and ``favorite`` is minted ``False``
    """
    data = tc_to_rehu_data({"type": "Tutorial", "rating": 3, "favorite": True}, username="bob")

    users = data["tutorial"]["users"]
    assert set(users) == {"bob"}
    assert users["bob"]["rating"] == 3
    assert users["bob"]["favorite"] is False
    assert data["tutorial"]["format_version"] == 1
