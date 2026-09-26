"""Tests for LocationReplacementsPage: the global replacement-rule table settings page (#350)."""

from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import location_replacements_settings
from rehuco_agent.settings.location_replacements_settings import (
    DEFAULT_RULES,
    ReplacementRule,
    shared_location_replacements_settings,
)
from rehuco_agent.settings.ui import location_replacements_page
from rehuco_agent.settings.ui.location_replacements_editor import LocationReplacementsEditor
from rehuco_agent.settings.ui.location_replacements_model import TEXT_COLUMN, LocationReplacementsModel
from rehuco_agent.settings.ui.location_replacements_page import LocationReplacementsPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter

# region Sample settings backend
# Mirrors test_location_templates_page.py's FakeSettings -- kept as a separate copy rather than a shared
# import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code


class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/array/value API."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""
        self.__array_key = ""
        self.__array_index = 0
        self.__in_array = False

    def beginGroup(self, name: str) -> None:  # noqa: N802  (Qt API name)
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def beginWriteArray(self, key: str) -> None:  # noqa: N802
        self.__array_key = self.__group + key
        self.__in_array = True
        self.__data[f"{self.__array_key}/size"] = 0

    def beginReadArray(self, key: str) -> int:  # noqa: N802
        self.__array_key = self.__group + key
        self.__in_array = True
        return self.__data.get(f"{self.__array_key}/size", 0)

    def setArrayIndex(self, index: int) -> None:  # noqa: N802
        self.__array_index = index
        size_key = f"{self.__array_key}/size"
        self.__data[size_key] = max(self.__data.get(size_key, 0), index + 1)

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__full_key(key)] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__full_key(key), default)

    def endArray(self) -> None:  # noqa: N802
        self.__in_array = False
        self.__array_key = ""

    def remove(self, key: str) -> None:
        """Drop ``key`` and everything under it from the open group, as ``QSettings`` does."""
        full = self.__group + key
        for stored in list(self.__data):
            if stored == full or stored.startswith(full + "/"):
                del self.__data[stored]

    def __full_key(self, key: str) -> str:
        if self.__in_array:
            return f"{self.__array_key}/{self.__array_index}/{key}"
        return self.__group + key


# pylint: enable=duplicate-code

# endregion

# region fixtures


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module (used
    by :func:`shared_location_replacements_settings`'s lazy load) and the page module itself (used by
    :meth:`LocationReplacementsPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(location_replacements_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(location_replacements_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Any:
    """Drop the process-wide settings instance around every test, so none inherits another's."""
    shared_location_replacements_settings.cache_clear()
    yield
    shared_location_replacements_settings.cache_clear()


@fixture(name="page")
def fixture_page(qtbot: QtBot) -> LocationReplacementsPage:
    """A page built over the isolated settings.

    :param qtbot: pytest-qt fixture, which owns the widget's lifetime.
    :returns: the page.
    """
    page = LocationReplacementsPage()
    qtbot.addWidget(page)
    return page


def editor_of(page: LocationReplacementsPage) -> LocationReplacementsEditor:
    """The page's rules editor, reached through its name-mangled UI attribute.

    :param page: the page.
    :returns: the editor.
    """
    return page._LocationReplacementsPage__ui.rules_editor  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def model_of(page: LocationReplacementsPage) -> LocationReplacementsModel:
    """The rules model behind the page's editor, at its concrete type.

    :param page: the page.
    :returns: the model.
    """
    model = editor_of(page).model
    assert isinstance(model, LocationReplacementsModel)
    return model


# endregion

# region What the page shows


def test_a_fresh_install_shows_the_shipped_rules(page: LocationReplacementsPage) -> None:
    """Nothing saved is the shipped seed, and nothing to save.

    **Test steps:**

    * build a page over empty storage
    * verify it shows the shipped rules and is not dirty
    """
    assert editor_of(page).values == DEFAULT_RULES
    assert page.is_dirty() is False


def test_editing_a_rule_marks_the_rules_frame_dirty(page: LocationReplacementsPage) -> None:
    """The frame highlight follows the edit.

    **Test steps:**

    * build a frame filter over the clean page and verify nothing is dirty
    * edit the first rule's text
    * verify the rules frame alone is reported dirty
    """
    ui = page._LocationReplacementsPage__ui  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    frame_filter = SettingsFrameFilter(page, "Location Replacements")
    assert not frame_filter.dirty_frames()

    model = model_of(page)
    model.setData(model.index(0, TEXT_COLUMN), "::")

    assert frame_filter.dirty_frames() == [ui.rules_frame]


def test_the_ordering_column_is_shown(page: LocationReplacementsPage) -> None:
    """Rules apply in table order, so the move buttons are part of the page.

    **Test steps:**

    * verify the ordering column is not hidden
    """
    assert editor_of(page).ordering_actions.isHidden() is False


# endregion

# region Editing, saving and dropping the rules


def test_an_edit_makes_the_page_dirty(page: LocationReplacementsPage) -> None:
    """Dirtiness is the staged table against the stored one.

    **Test steps:**

    * replace the staged rules
    * verify the page reports itself dirty
    """
    editor_of(page).values = (ReplacementRule(":", "-"),)

    assert page.is_dirty() is True


def test_saving_persists_the_rules_and_settles_the_page(page: LocationReplacementsPage) -> None:
    """Save is what makes the staged rules the ones the next rendered location goes through.

    **Test steps:**

    * stage a rule and save it
    * verify the shared settings hold it, and the page is no longer dirty
    """
    editor_of(page).values = (ReplacementRule(":", "-"),)

    page.save_changes()

    assert shared_location_replacements_settings().rules == (ReplacementRule(":", "-"),)
    assert page.is_dirty() is False


def test_saving_keeps_an_empty_text_rule_flagged(page: LocationReplacementsPage) -> None:
    """An empty-text row is kept, flagged, never dropped on save -- a typo is fixed in place.

    **Test steps:**

    * stage a rule with empty text and save
    * verify the row is still there, flagged, and the page is settled
    """
    editor_of(page).values = (ReplacementRule("", "-"),)

    page.save_changes()

    assert editor_of(page).values == (ReplacementRule("", "-"),)
    assert model_of(page).invalid_reason(0) != ""
    assert page.is_dirty() is False


def test_saving_an_emptied_table_is_a_real_saved_choice(page: LocationReplacementsPage) -> None:
    """Unlike a location pattern list, deleting every rule and saving is respected -- not repopulated
    with the shipped seed.

    **Test steps:**

    * empty the editor and save
    * verify the shared settings hold no rules
    """
    editor_of(page).values = ()

    page.save_changes()

    assert shared_location_replacements_settings().rules == ()
    assert editor_of(page).values == ()


def test_dropping_changes_reverts_to_the_saved_rules(page: LocationReplacementsPage) -> None:
    """Cancel is the staged edits going away, not the saved ones.

    **Test steps:**

    * stage a change, then drop it
    * verify the shipped set is back
    """
    editor_of(page).values = (ReplacementRule(":", "-"),)

    page.drop_changes()

    assert editor_of(page).values == DEFAULT_RULES


def test_seed_defaults_stages_the_shipped_rules_over_saved_ones(page: LocationReplacementsPage) -> None:
    """``seed_defaults`` shows the shipped set as a staged edit against whatever was saved.

    **Test steps:**

    * save a custom rule and drop into it
    * call ``seed_defaults``
    * verify the shipped rules are shown, and the page is dirty
    """
    editor_of(page).values = (ReplacementRule("_", " "),)
    page.save_changes()
    page.drop_changes()
    assert editor_of(page).values == (ReplacementRule("_", " "),)

    page.seed_defaults()

    assert editor_of(page).values == DEFAULT_RULES
    assert page.is_dirty() is True


def test_the_editors_defaults_can_be_read_back(page: LocationReplacementsPage) -> None:
    """What Reset restores is readable off the editor too, not just settable.

    **Test steps:**

    * set the editor's defaults to a custom set
    * verify reading them back answers the same set
    """
    editor = editor_of(page)
    editor.defaults = (ReplacementRule("_", " "),)

    assert editor.defaults == (ReplacementRule("_", " "),)


def test_reset_restores_the_shipped_rules(page: LocationReplacementsPage) -> None:
    """Reset is the shipped set, offered because there genuinely is a default to go back to.

    **Test steps:**

    * stage a different set
    * trigger the reset action
    * verify the shipped rules are shown
    """
    editor = editor_of(page)
    editor.values = (ReplacementRule("_", " "),)

    editor.item_actions.reset_action.trigger()

    assert editor.values == DEFAULT_RULES


# endregion
