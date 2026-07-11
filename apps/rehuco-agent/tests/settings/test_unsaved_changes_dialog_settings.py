"""Tests for UnsavedChangesDialogSettings: the unsaved-changes dialog's persisted geometry.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_document_session_settings.py``
for the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.settings.unsaved_changes_dialog_settings import UnsavedChangesDialogSettings


# region fixtures
# Mirrors test_main_window_settings.py's FakeSettings exactly -- kept as a separate copy rather
# than a shared fixture module since MainWindowSettings and UnsavedChangesDialogSettings
# themselves are deliberately separate classes (see main_window_settings.py).
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`UnsavedChangesDialogSettings.load`/:meth:`~UnsavedChangesDialogSettings.save`
    call them by name.
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
    dialog_settings = UnsavedChangesDialogSettings(geometry=b"some-geometry-blob")

    dialog_settings.save(settings)  # type: ignore[arg-type]

    restored = UnsavedChangesDialogSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.geometry == b"some-geometry-blob"


def test_load_defaults_to_empty_geometry_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had geometry saved yields empty bytes, not an error.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify the geometry is empty
    """
    dialog_settings = UnsavedChangesDialogSettings()

    dialog_settings.load(settings)  # type: ignore[arg-type]

    assert dialog_settings.geometry == b""


# pylint: enable=duplicate-code
