"""Tests for MainWindowSettings: MainWindow's persisted geometry and outer dock layout.

The state lives in a JSON file (#404); conftest's autouse ``state_files`` keeps it in memory (see
``test_document_session_settings.py`` for the same rationale).
"""

import json

from rehuco_agent.settings.main_window_settings import WINDOW_VERSION, MainWindowSettings, main_window_state_path

from rehuco_agent_tests.conftest import MemoryStateFiles


def test_save_then_load_round_trips_the_geometry() -> None:
    """Saving and reloading reproduces the same geometry bytes.

    **Test steps:**

    * set some geometry bytes and save
    * load into a fresh instance from the same settings stand-in
    * verify the geometry came back unchanged
    """
    window_settings = MainWindowSettings(geometry=b"some-geometry-blob")

    window_settings.save()

    restored = MainWindowSettings()
    restored.load()

    assert restored.geometry == b"some-geometry-blob"


def test_load_defaults_to_empty_geometry_when_the_file_holds_none(state_files: MemoryStateFiles) -> None:
    """A file that holds no geometry clears the one the instance had, rather than leaving it (#483).

    **Test steps:**

    * seed an instance with geometry, and a file stamped with the version and nothing else
    * load the file
    * verify the geometry is empty
    """
    state_files.files[main_window_state_path()] = json.dumps({"version": WINDOW_VERSION})
    window_settings = MainWindowSettings(geometry=b"stale")

    window_settings.load()

    assert window_settings.geometry == b""


def test_save_then_load_round_trips_the_outer_layout() -> None:
    """Saving and reloading reproduces the same outer layout tree (#102).

    **Test steps:**

    * set an outer layout tree and save
    * load into a fresh instance from the same settings stand-in
    * verify the tree came back unchanged
    """
    layout = {
        "format": 1,
        "main": {"area": [{"name": "documents_dock", "closed": False}, {"name": "log_dock", "closed": True}]},
    }
    window_settings = MainWindowSettings(outer_layout=layout)

    window_settings.save()

    restored = MainWindowSettings()
    restored.load()

    assert restored.outer_layout == layout


def test_a_stored_outer_layout_that_is_not_a_tree_reads_as_none(state_files: MemoryStateFiles) -> None:
    """An outer layout stored as anything but a JSON object reads as no layout, leaving the window's own (#102).

    **Test steps:**

    * seed a file whose outer layout is a string, the way an opaque blob was stored
    * load into a fresh instance
    * verify the outer layout is ``None`` and the geometry beside it still loads
    """
    state_files.files[main_window_state_path()] = json.dumps(
        {"version": 1, "geometry": "Z2VvbWV0cnk=", "outer_layout": "c29tZS1ibG9i"}
    )

    window_settings = MainWindowSettings()
    window_settings.load()

    assert window_settings.outer_layout is None
    assert window_settings.geometry == b"geometry"


def test_load_defaults_to_no_outer_layout_when_the_file_holds_none(state_files: MemoryStateFiles) -> None:
    """A file that holds no outer layout clears the one the instance had (#483).

    **Test steps:**

    * seed an instance with an outer layout, and a file stamped with the version and nothing else
    * load the file
    * verify the outer layout is ``None``
    """
    state_files.files[main_window_state_path()] = json.dumps({"version": WINDOW_VERSION})
    window_settings = MainWindowSettings(outer_layout={"format": 1, "main": {"area": []}})

    window_settings.load()

    assert window_settings.outer_layout is None


def test_save_then_load_round_trips_the_toolbars_state() -> None:
    """Saving and reloading reproduces the same toolbar-layout bytes.

    **Test steps:**

    * set some toolbars-state bytes and save
    * load into a fresh instance from the same settings stand-in
    * verify the toolbars state came back unchanged
    """
    window_settings = MainWindowSettings(toolbars_state=b"some-toolbars-state-blob")

    window_settings.save()

    restored = MainWindowSettings()
    restored.load()

    assert restored.toolbars_state == b"some-toolbars-state-blob"


def test_load_defaults_to_empty_toolbars_state_when_the_file_holds_none(state_files: MemoryStateFiles) -> None:
    """A file that holds no toolbars state clears the one the instance had (#483).

    **Test steps:**

    * seed an instance with toolbars state, and a file stamped with the version and nothing else
    * load the file
    * verify the toolbars state is empty
    """
    state_files.files[main_window_state_path()] = json.dumps({"version": WINDOW_VERSION})
    window_settings = MainWindowSettings(toolbars_state=b"stale")

    window_settings.load()

    assert window_settings.toolbars_state == b""


def test_load_with_no_file_leaves_nothing_saved() -> None:
    """A first run, or a deleted file, has no window state (#404, #483).

    **Test steps:**

    * seed an instance with geometry, an outer layout and toolbars state, with nothing saved
    * load it
    * verify all three are gone
    """
    window_settings = MainWindowSettings(
        geometry=b"stale", outer_layout={"format": 1, "main": {"area": []}}, toolbars_state=b"stale"
    )

    window_settings.load()

    assert window_settings.geometry == b""
    assert window_settings.outer_layout is None
    assert window_settings.toolbars_state == b""


def test_a_file_of_another_version_reads_as_nothing_saved(state_files: MemoryStateFiles) -> None:
    """A window file written by a build of another version is ignored whole, not half-read (#404, #483).

    **Test steps:**

    * seed a file one version ahead, holding good geometry, an outer layout and toolbars state
    * load it into an instance already holding values
    * verify every field went, and nothing of the file's was taken
    """
    state_files.files[main_window_state_path()] = json.dumps(
        {
            "version": WINDOW_VERSION + 1,
            "geometry": "Z2VvbWV0cnk=",
            "outer_layout": {"format": 1, "main": {"area": []}},
            "toolbars_state": "dG9vbGJhcnM=",
        }
    )
    window_settings = MainWindowSettings(geometry=b"stale", outer_layout={"format": 1}, toolbars_state=b"stale")

    window_settings.load()

    assert window_settings == MainWindowSettings()


def test_a_damaged_blob_reads_as_empty(state_files: MemoryStateFiles) -> None:
    """One blob that is not valid base64 costs only itself (#404).

    **Test steps:**

    * seed a file with good geometry and a damaged toolbar blob
    * verify the geometry loads and the toolbars are empty
    """
    state_files.files[main_window_state_path()] = json.dumps(
        {"version": 1, "geometry": "Z2VvbWV0cnk=", "toolbars_state": "not base64!"}
    )

    window_settings = MainWindowSettings()
    window_settings.load()

    assert window_settings.geometry == b"geometry"
    assert window_settings.toolbars_state == b""


# pylint: enable=duplicate-code
