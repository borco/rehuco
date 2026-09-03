"""Tests for DockableDialogSettings: persisted visibility/restore-on-start state.

Uses a hand-rolled in-memory stand-in for ``QSettings`` rather than a real one or ``tmp_path``.
"""

from typing import Any

from borco_pyside.dialogs import DockableDialogSettings
from pytest import fixture


# region fixtures
# Mirrors test_dockable_dialog_manager.py's FakeSettings exactly -- kept as a separate copy rather
# than a shared import, matching this codebase's settings-test convention (see e.g.
# test_main_window_settings.py / test_unsaved_changes_dialog_settings.py).
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`DockableDialogSettings.load`/:meth:`~DockableDialogSettings.save` call them by
    name.
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


# pylint: enable=duplicate-code
# endregion


def test_save_then_load_round_trips_the_values(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same visible/restore_on_start values.

    **Test steps:**

    * save non-default values under a group
    * load into a fresh instance from the same group
    * verify both values came back unchanged
    """
    dialog_settings = DockableDialogSettings(visible=True, restore_on_start=True)

    dialog_settings.save(settings, "some_dialog")  # type: ignore[arg-type]

    restored = DockableDialogSettings()
    restored.load(settings, "some_dialog")  # type: ignore[arg-type]

    assert restored.visible is True
    assert restored.restore_on_start is True


def test_load_defaults_to_false_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from a group that never had anything saved yields both defaults False, not an error.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify both values are ``False``
    """
    dialog_settings = DockableDialogSettings()

    dialog_settings.load(settings, "never_saved")  # type: ignore[arg-type]

    assert dialog_settings.visible is False
    assert dialog_settings.restore_on_start is False


def test_different_groups_do_not_collide(settings: FakeSettings) -> None:
    """Two dialogs saved under different groups don't clobber each other's values.

    **Test steps:**

    * save distinct values for two different groups
    * load each back into a fresh instance
    * verify each restores its own group's values, not the other's
    """
    DockableDialogSettings(visible=True, restore_on_start=False).save(settings, "dialog_a")  # type: ignore[arg-type]
    DockableDialogSettings(visible=False, restore_on_start=True).save(settings, "dialog_b")  # type: ignore[arg-type]

    restored_a = DockableDialogSettings()
    restored_a.load(settings, "dialog_a")  # type: ignore[arg-type]
    restored_b = DockableDialogSettings()
    restored_b.load(settings, "dialog_b")  # type: ignore[arg-type]

    assert (restored_a.visible, restored_a.restore_on_start) == (True, False)
    assert (restored_b.visible, restored_b.restore_on_start) == (False, True)
