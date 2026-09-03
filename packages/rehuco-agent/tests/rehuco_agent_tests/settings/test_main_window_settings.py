"""Tests for MainWindowSettings: MainWindow's persisted geometry and outer dock layout.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_document_session_settings.py``
for the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.settings.main_window_settings import OUTER_DOCKS_STATE_VERSION, MainWindowSettings


# region fixtures
# Mirrors test_unsaved_changes_dialog_settings.py's FakeSettings exactly -- kept as a separate
# copy rather than a shared fixture module since MainWindowSettings and UnsavedChangesDialogSettings
# themselves are deliberately separate classes (see main_window_settings.py).
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`MainWindowSettings.load`/:meth:`~MainWindowSettings.save` call them by name.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# endregion


def test_save_then_load_round_trips_the_geometry(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same geometry bytes.

    **Test steps:**

    * set some geometry bytes and save
    * load into a fresh instance from the same settings stand-in
    * verify the geometry came back unchanged
    """
    window_settings = MainWindowSettings(geometry=b"some-geometry-blob")

    window_settings.save(settings)  # type: ignore[arg-type]

    restored = MainWindowSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.geometry == b"some-geometry-blob"


def test_load_defaults_to_empty_geometry_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had geometry saved yields empty bytes, not an error.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the geometry is empty
    """
    window_settings = MainWindowSettings()

    window_settings.load(settings)  # type: ignore[arg-type]

    assert window_settings.geometry == b""


def test_save_then_load_round_trips_the_outer_docks_state(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same outer dock-layout bytes.

    **Test steps:**

    * set some outer dock state bytes and save
    * load into a fresh instance from the same settings stand-in
    * verify the outer dock state came back unchanged
    """
    window_settings = MainWindowSettings(outer_docks_state=b"some-docks-state-blob")

    window_settings.save(settings)  # type: ignore[arg-type]

    restored = MainWindowSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.outer_docks_state == b"some-docks-state-blob"


def test_load_discards_outer_docks_state_saved_under_a_different_version(settings: FakeSettings) -> None:
    """A saved outer dock state whose version doesn't match the current one is ignored on load.

    **Test steps:**

    * save an outer dock state, then overwrite its stored version to something else
    * load into a fresh instance
    * verify the outer dock state comes back empty, not the stale bytes
    """
    MainWindowSettings(outer_docks_state=b"stale-blob").save(settings)  # type: ignore[arg-type]
    settings.setValue("main_window/outer_docks_state_version", OUTER_DOCKS_STATE_VERSION + 1)

    restored = MainWindowSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.outer_docks_state == b""


def test_load_defaults_to_empty_outer_docks_state_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had an outer dock state saved yields empty bytes.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the outer dock state is empty
    """
    window_settings = MainWindowSettings()

    window_settings.load(settings)  # type: ignore[arg-type]

    assert window_settings.outer_docks_state == b""


def test_save_then_load_round_trips_the_toolbars_state(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same toolbar-layout bytes.

    **Test steps:**

    * set some toolbars-state bytes and save
    * load into a fresh instance from the same settings stand-in
    * verify the toolbars state came back unchanged
    """
    window_settings = MainWindowSettings(toolbars_state=b"some-toolbars-state-blob")

    window_settings.save(settings)  # type: ignore[arg-type]

    restored = MainWindowSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.toolbars_state == b"some-toolbars-state-blob"


def test_load_defaults_to_empty_toolbars_state_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had a toolbars state saved yields empty bytes.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the toolbars state is empty
    """
    window_settings = MainWindowSettings()

    window_settings.load(settings)  # type: ignore[arg-type]

    assert window_settings.toolbars_state == b""


# pylint: enable=duplicate-code
