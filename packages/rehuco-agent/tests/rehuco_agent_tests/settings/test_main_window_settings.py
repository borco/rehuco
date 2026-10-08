"""Tests for MainWindowSettings: MainWindow's persisted geometry and outer dock layout.

The state lives in a JSON file (#404); conftest's autouse ``state_files`` keeps it in memory (see
``test_document_session_settings.py`` for the same rationale).
"""

import json

from rehuco_agent.settings.main_window_settings import (
    OUTER_DOCKS_STATE_VERSION,
    MainWindowSettings,
    main_window_state_path,
)

from rehuco_agent_tests.conftest import MemoryStateFiles


# region fixtures
def overwrite_outer_version(state_files: MemoryStateFiles, version: int) -> None:
    """Rewrite the stored outer dock version, as a file written by another build would carry.

    :param state_files: the in-memory files.
    :param version: what to say it was saved under.
    """
    path = main_window_state_path()
    values = json.loads(state_files.files[path])
    values["outer_docks_state_version"] = version
    state_files.files[path] = json.dumps(values)


# endregion


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


def test_load_defaults_to_empty_geometry_when_nothing_was_saved() -> None:
    """Loading from settings that never had geometry saved yields empty bytes, not an error.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the geometry is empty
    """
    window_settings = MainWindowSettings()

    window_settings.load()

    assert window_settings.geometry == b""


def test_save_then_load_round_trips_the_outer_docks_state() -> None:
    """Saving and reloading reproduces the same outer dock-layout bytes.

    **Test steps:**

    * set some outer dock state bytes and save
    * load into a fresh instance from the same settings stand-in
    * verify the outer dock state came back unchanged
    """
    window_settings = MainWindowSettings(outer_docks_state=b"some-docks-state-blob")

    window_settings.save()

    restored = MainWindowSettings()
    restored.load()

    assert restored.outer_docks_state == b"some-docks-state-blob"


def test_load_discards_outer_docks_state_saved_under_a_different_version(state_files: MemoryStateFiles) -> None:
    """A saved outer dock state whose version doesn't match the current one is ignored on load.

    **Test steps:**

    * save an outer dock state, then overwrite its stored version to something else
    * load into a fresh instance
    * verify the outer dock state comes back empty, not the stale bytes
    """
    MainWindowSettings(outer_docks_state=b"stale-blob").save()
    overwrite_outer_version(state_files, OUTER_DOCKS_STATE_VERSION + 1)

    restored = MainWindowSettings()
    restored.load()

    assert restored.outer_docks_state == b""


def test_load_defaults_to_empty_outer_docks_state_when_nothing_was_saved() -> None:
    """Loading from settings that never had an outer dock state saved yields empty bytes.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the outer dock state is empty
    """
    window_settings = MainWindowSettings()

    window_settings.load()

    assert window_settings.outer_docks_state == b""


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


def test_load_defaults_to_empty_toolbars_state_when_nothing_was_saved() -> None:
    """Loading from settings that never had a toolbars state saved yields empty bytes.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the toolbars state is empty
    """
    window_settings = MainWindowSettings()

    window_settings.load()

    assert window_settings.toolbars_state == b""


def test_save_then_load_round_trips_the_task_queue_state() -> None:
    """Saving and reloading reproduces the Tasks dock's nested-shell bytes (#276).

    **Test steps:**

    * set some task queue state bytes and save
    * load into a fresh instance from the same settings stand-in
    * verify the state came back unchanged
    """
    window_settings = MainWindowSettings(task_queue_state=b"some-task-queue-blob")

    window_settings.save()

    restored = MainWindowSettings()
    restored.load()

    assert restored.task_queue_state == b"some-task-queue-blob"


def test_the_task_queue_state_survives_a_foreign_outer_docks_version(state_files: MemoryStateFiles) -> None:
    """It is kept when the *outer* dock version is discarded, because it carries a version of its own.

    That guard is about the outer dock set; the nested shell's own blob answers for itself
    (:data:`~rehuco_agent.tasks.task_queue_widget.STATE_VERSION`), so dropping it here would throw away a
    perfectly readable answer.

    **Test steps:**

    * save both states, then overwrite the stored outer version
    * load into a fresh instance
    * verify the outer state is gone and the task queue state is not
    """
    saved = MainWindowSettings(outer_docks_state=b"stale-blob", task_queue_state=b"some-task-queue-blob")
    saved.save()
    overwrite_outer_version(state_files, OUTER_DOCKS_STATE_VERSION + 1)

    restored = MainWindowSettings()
    restored.load()

    assert restored.outer_docks_state == b""
    assert restored.task_queue_state == b"some-task-queue-blob"


def test_load_defaults_to_empty_task_queue_state_when_nothing_was_saved() -> None:
    """Loading from settings that never had a task queue state saved yields empty bytes.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the task queue state is empty
    """
    window_settings = MainWindowSettings()

    window_settings.load()

    assert window_settings.task_queue_state == b""


def test_load_with_no_file_leaves_nothing_saved() -> None:
    """A first run, or a deleted file, has no window state (#404).

    **Test steps:**

    * load into an instance that already holds geometry, with nothing saved
    * verify the geometry is gone
    """
    window_settings = MainWindowSettings(geometry=b"stale")

    window_settings.load()

    assert window_settings.geometry == b""


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
