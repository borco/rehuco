"""Tests for DefaultLayoutSettings: the saved default document dock layout of each type (#62, #320, #354).

The layouts live in one JSON file per group (#404); conftest's autouse ``state_files`` keeps them in memory (see
``test_document_session_settings.py`` for the same rationale).
"""

import json

from rehuco_agent.settings.default_layout_settings import (
    GROUP,
    PREVIEW_LAYOUT_GROUP,
    DefaultLayoutSettings,
    default_layouts_path,
    shared_default_layout_settings,
    shared_default_layout_settings_in,
)

from rehuco_agent_tests.conftest import MemoryStateFiles


def test_the_states_round_trip_through_storage(state_files: MemoryStateFiles) -> None:
    """Each type's blob is saved to the group's file and read back unchanged.

    **Test steps:**

    * save a settings object holding two types' states
    * verify the group's file was written
    * load a fresh one and verify it came back unchanged
    """
    saved = DefaultLayoutSettings(states={"tutorial": b"tutorial blob", "reference_images": b"pack blob"})
    saved.save()

    assert list(state_files.files) == [default_layouts_path(GROUP)]

    loaded = DefaultLayoutSettings()
    loaded.load()

    assert loaded == saved


def test_loading_with_no_file_yields_no_default() -> None:
    """A first run has no file, and must not read as a real saved default.

    **Test steps:**

    * load into an instance holding a state, with nothing ever saved
    * verify the result equals a default-constructed settings object
    """
    loaded = DefaultLayoutSettings(states={"tutorial": b"stale"})
    loaded.load()

    assert loaded == DefaultLayoutSettings()


def test_saving_drops_a_reset_type() -> None:
    """A type popped from the states leaves storage on the next save.

    **Test steps:**

    * save two types, load them back, pop one and save again
    * verify a fresh load holds only the other
    """
    DefaultLayoutSettings(states={"tutorial": b"t", "reference_images": b"r"}).save()
    loaded = DefaultLayoutSettings()
    loaded.load()
    assert loaded.states == {"tutorial": b"t", "reference_images": b"r"}

    loaded.states.pop("tutorial")
    loaded.save()

    again = DefaultLayoutSettings()
    again.load()
    assert again.states == {"reference_images": b"r"}


def test_the_empty_types_state_round_trips() -> None:
    """The empty type -- a document with no type -- keeps its default, keyed by ``""`` (#354).

    **Test steps:**

    * save a settings object holding the empty type's state and a tutorial's
    * load a fresh one and verify it came back unchanged
    """
    saved = DefaultLayoutSettings(states={"": b"untyped blob", "tutorial": b"tutorial blob"})
    saved.save()

    loaded = DefaultLayoutSettings()
    loaded.load()

    assert loaded == saved


def test_an_empty_stored_state_reads_as_no_default(state_files: MemoryStateFiles) -> None:
    """A type whose stored blob is empty or damaged has no default, the same as a type never saved.

    **Test steps:**

    * seed a file with an empty blob, a damaged one and a good one
    * verify only the good one is loaded
    """
    state_files.files[default_layouts_path(GROUP)] = json.dumps(
        {"version": 1, "states": {"collection": "", "broken": "not base64!", "tutorial": "dGFi"}}
    )

    loaded = DefaultLayoutSettings()
    loaded.load()

    assert loaded.states == {"tutorial": b"tab"}


def test_a_file_that_holds_no_states_reads_as_no_default(state_files: MemoryStateFiles) -> None:
    """A hand-damaged file costs the defaults and nothing else (#404).

    **Test steps:**

    * seed a file whose ``states`` is a list
    * verify nothing is loaded
    """
    state_files.files[default_layouts_path(GROUP)] = json.dumps({"version": 1, "states": ["tutorial"]})

    loaded = DefaultLayoutSettings()
    loaded.load()

    assert not loaded.states


def test_the_shared_instance_is_the_same_object_every_time() -> None:
    """A document's Save must be what the next opened document reads, not a disconnected copy (#62).

    **Test steps:**

    * ask for the shared instance twice
    * verify both calls answered the same object
    """
    assert shared_default_layout_settings() is shared_default_layout_settings()


def test_a_group_of_its_own_round_trips_beside_the_documents_group() -> None:
    """A settings object with a group of its own stores and loads only its own file, and leaves the Documents dock's
    defaults alone (#380).

    **Test steps:**

    * save a Documents settings object and one under another group, each holding a tutorial's state
    * verify each landed in its own file
    * load a fresh one of the other group and verify it read only its own state
    """
    DefaultLayoutSettings(states={"tutorial": b"documents blob"}).save()
    DefaultLayoutSettings(group="rehuco_layout", states={"tutorial": b"own blob"}).save()

    assert default_layouts_path(GROUP) != default_layouts_path("rehuco_layout")

    loaded = DefaultLayoutSettings(group="rehuco_layout")
    loaded.load()
    documents = DefaultLayoutSettings()
    documents.load()

    assert loaded.states == {"tutorial": b"own blob"}
    assert documents.states == {"tutorial": b"documents blob"}


def test_each_group_has_its_own_shared_instance() -> None:
    """The Documents dock's shared instance is the one its group names, and another group's is a different object,
    loaded from its own file (#380).

    **Test steps:**

    * save a state under another group
    * verify the Documents instance is the one kept for its group
    * verify the other group's instance is a different object holding only its own state
    """
    DefaultLayoutSettings(group="rehuco_layout", states={"tutorial": b"own blob"}).save()

    documents = shared_default_layout_settings()
    own = shared_default_layout_settings_in("rehuco_layout")

    assert documents is shared_default_layout_settings_in(GROUP)
    assert own is not documents
    assert own.states == {"tutorial": b"own blob"}
    assert not documents.states


def test_the_preview_layouts_have_a_file_of_their_own() -> None:
    """The preview's per-type arrangements are kept apart from the type defaults (#39, #404).

    **Test steps:**

    * ask for both groups' paths
    * verify they are different files in the same folder
    """
    defaults, preview = default_layouts_path(GROUP), default_layouts_path(PREVIEW_LAYOUT_GROUP)

    assert defaults != preview
    assert defaults.parent == preview.parent
