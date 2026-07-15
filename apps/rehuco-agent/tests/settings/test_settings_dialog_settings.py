"""Tests for SettingsDialogSettings: the settings dialog's persisted filter state (#76).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_document_session_settings.py``
for the same rationale) rather than a real one or ``tmp_path``.
"""

from typing import Any

from pytest import fixture
from rehuco_agent.settings.settings_dialog_settings import SettingsDialogSettings


# region fixtures
# Mirrors test_main_window_settings.py's FakeSettings exactly -- kept as a separate copy rather
# than a shared fixture module, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`SettingsDialogSettings.load`/:meth:`~SettingsDialogSettings.save` call them
    by name.
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


def test_save_then_load_round_trips_the_filter_text_and_both_toggles(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the filter text and both toggles, independently.

    **Test steps:**

    * save some filter text, with one toggle checked and the other not
    * load into a fresh instance from the same settings stand-in
    * verify each value came back as it was saved
    """
    dialog_settings = SettingsDialogSettings(filter_text="engine", show_full_page_on_title_match=True)

    dialog_settings.save(settings)  # type: ignore[arg-type]

    restored = SettingsDialogSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.filter_text == "engine"
    assert restored.show_full_page_on_title_match is True
    assert restored.show_full_group_on_title_match is False


def test_load_defaults_to_no_filter_and_unchecked_toggles_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had the filter saved leaves it empty and both toggles off.

    **Test steps:**

    * load into a fresh (non-default) instance from an empty settings stand-in
    * verify the filter text is empty and both toggles are unchecked
    """
    dialog_settings = SettingsDialogSettings(
        filter_text="engine", show_full_page_on_title_match=True, show_full_group_on_title_match=True
    )

    dialog_settings.load(settings)  # type: ignore[arg-type]

    assert dialog_settings.filter_text == ""
    assert dialog_settings.show_full_page_on_title_match is False
    assert dialog_settings.show_full_group_on_title_match is False


# pylint: enable=duplicate-code
