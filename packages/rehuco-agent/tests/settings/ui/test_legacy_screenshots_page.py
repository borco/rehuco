"""Tests for LegacyScreenshotsPage and its two-column rules editor (#53)."""

from typing import Any

from PySide6.QtCore import Qt
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import legacy_screenshots_settings
from rehuco_agent.settings.legacy_screenshots_settings import shared_legacy_screenshots_settings
from rehuco_agent.settings.ui import legacy_screenshots_page
from rehuco_agent.settings.ui.legacy_screenshot_rules_editor import LegacyScreenshotRulesEditor
from rehuco_agent.settings.ui.legacy_screenshot_rules_model import (
    COVER_COLUMN,
    MISSING_COVER_REASON,
    MISSING_PLACEHOLDER_REASON,
    PLACEHOLDER_IN_COVER_REASON,
    REST_COLUMN,
    LegacyScreenshotRulesModel,
)
from rehuco_agent.settings.ui.legacy_screenshots_page import LegacyScreenshotsPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_core import LEGACY_SCREENSHOT_RULES, LegacyScreenshotRule

# region Sample settings backend
# Mirrors test_legacy_screenshots_settings.py's array-capable FakeSettings -- kept as a separate copy
# rather than a shared import, matching this codebase's settings-test convention.
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

    def beginWriteArray(self, key: str, size: int = -1) -> None:  # noqa: N802
        del size
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

    def __full_key(self, key: str) -> str:
        """The storage key for ``key``: array-indexed while inside an array, else group-scoped."""
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
    by :func:`shared_legacy_screenshots_settings`'s lazy load) and the page module itself (used by
    :meth:`LegacyScreenshotsPage.save_changes`).

    :param mocker: pytest-mock fixture.
    :returns: the stand-in every read and write lands in.
    """
    fake = FakeSettings()
    mocker.patch.object(legacy_screenshots_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(legacy_screenshots_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Any:
    """Drop the process-wide settings instance around every test, so none inherits another's."""
    shared_legacy_screenshots_settings.cache_clear()
    yield
    shared_legacy_screenshots_settings.cache_clear()


@fixture(name="page")
def fixture_page(qtbot: QtBot) -> LegacyScreenshotsPage:
    """A page built over the isolated settings.

    :param qtbot: pytest-qt fixture, which owns the widget's lifetime.
    :returns: the page.
    """
    page = LegacyScreenshotsPage()
    qtbot.addWidget(page)
    return page


def editor_of(page: LegacyScreenshotsPage) -> LegacyScreenshotRulesEditor:
    """The page's rules editor, reached through its name-mangled UI attribute.

    :param page: the page.
    :returns: the editor.
    """
    return page._LegacyScreenshotsPage__ui.rules_editor  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def model_of(page: LegacyScreenshotsPage) -> LegacyScreenshotRulesModel:
    """The rules model behind the page's editor, at its concrete type.

    The base editor knows only ``QAbstractItemModel``, so the narrowing is asserted here rather than
    repeated at each cell-level assertion below.

    :param page: the page.
    :returns: the model.
    """
    model = editor_of(page).model
    assert isinstance(model, LegacyScreenshotRulesModel)
    return model


# endregion

# region What the page shows


def test_a_fresh_install_shows_the_shipped_rules(page: LegacyScreenshotsPage) -> None:
    """Nothing saved is the shipped set, and nothing to save.

    **Test steps:**

    * build a page over empty storage
    * verify it shows the shipped rules and is not dirty
    """
    assert editor_of(page).values == LEGACY_SCREENSHOT_RULES
    assert page.is_dirty() is False


def test_the_editor_shows_a_cover_and_a_rest_column(page: LegacyScreenshotsPage) -> None:
    """Two columns, because a rule is a cover and a template -- which is what lets two rules differ
    only in their cover.

    **Test steps:**

    * read the editor's model header
    * verify both columns and their titles
    """
    model = editor_of(page).model

    assert model.columnCount() == 2
    assert model.headerData(COVER_COLUMN, Qt.Orientation.Horizontal) == "Cover"
    assert model.headerData(REST_COLUMN, Qt.Orientation.Horizontal) == "Rest"


def test_the_ordering_column_is_shown(page: LegacyScreenshotsPage) -> None:
    """Order decides which rule claims a folder, so the move buttons are part of the page.

    **Test steps:**

    * verify the ordering column is not hidden
    """
    assert editor_of(page).ordering_actions.isHidden() is False


def test_every_action_wears_an_icon(page: LegacyScreenshotsPage) -> None:
    """The editor ships no icons; the page's `apply_item_action_icons` is what dresses it.

    **Test steps:**

    * verify each action armed on the view carries a non-null icon
    """
    actions = editor_of(page).view.actions()

    assert actions
    assert all(not action.icon().isNull() for action in actions)


def test_the_page_filters_by_its_two_frames(page: LegacyScreenshotsPage) -> None:
    """A page filters by its labeled top-level frames, and implements nothing itself for it.

    **Test steps:**

    * build a frame filter over the page
    * filter by each frame's header and verify only that frame stays shown
    * filter by a non-matching term and verify both hide
    """
    ui = page._LegacyScreenshotsPage__ui  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    frame_filter = SettingsFrameFilter(page, page.title)

    frame_filter.apply("legacy screenshot rules", show_full_on_title_match=False)
    assert ui.rules_frame.isVisibleTo(page) is True
    assert ui.tie_break_frame.isVisibleTo(page) is False

    frame_filter.apply("always applied", show_full_on_title_match=False)
    assert ui.tie_break_frame.isVisibleTo(page) is True
    assert ui.rules_frame.isVisibleTo(page) is False

    frame_filter.apply("nothing on this page", show_full_on_title_match=False)
    assert ui.rules_frame.isVisibleTo(page) is False
    assert ui.tie_break_frame.isVisibleTo(page) is False


def test_the_page_names_itself(page: LegacyScreenshotsPage) -> None:
    """The category-tree label.

    **Test steps:**

    * read the title
    """
    assert page.title == "Legacy Screenshots"


# endregion

# region Editing, saving and dropping


def test_a_row_saving_would_drop_is_not_yet_a_change(page: LegacyScreenshotsPage) -> None:
    """A blank or half-typed rule does not make the page dirty, because applying would not change
    what is saved -- and while *Apply changes as they're made* is on, the dialog commits any dirty
    page, which would tear the fresh row out from under its open cell (#53).

    **Test steps:**

    * insert a blank rule and verify the page stays clean
    * type its cover only and verify it still does
    * complete the rule and verify the page is dirty exactly then
    """
    model = model_of(page)
    row = model.insert(-1)
    assert page.is_dirty() is False

    model.setData(model.index(row, COVER_COLUMN), "shot-1")
    assert page.is_dirty() is False

    model.setData(model.index(row, REST_COLUMN), "shot-#")
    assert page.is_dirty() is True


def test_an_edit_makes_the_page_dirty(page: LegacyScreenshotsPage) -> None:
    """Dirtiness is the staged list against what a scan would read, polled rather than signalled.

    **Test steps:**

    * replace the staged rules
    * verify the page reports itself dirty
    """
    editor_of(page).values = (LegacyScreenshotRule("shot-1", "shot-#"),)

    assert page.is_dirty() is True


def test_saving_persists_the_rules_and_settles_the_page(page: LegacyScreenshotsPage) -> None:
    """Save is what makes the staged rules the ones the next conversion is handed.

    **Test steps:**

    * stage a rule set and save it
    * verify the shared settings hold it and the page is no longer dirty
    """
    rules = (LegacyScreenshotRule("shot-1", "shot-#"),)
    editor_of(page).values = rules

    page.save_changes()

    assert shared_legacy_screenshots_settings().legacy_screenshot_rules == rules
    assert page.is_dirty() is False


def test_saving_reloads_what_normalizing_actually_kept(page: LegacyScreenshotsPage) -> None:
    """A page still showing what was typed would disagree with every scan.

    **Test steps:**

    * stage a good rule alongside one that cannot compile, and save
    * verify the page comes back showing only the rule that survived
    """
    editor_of(page).values = (
        LegacyScreenshotRule("shot-1", "shot-#"),
        LegacyScreenshotRule("cover", "no-number"),
    )

    page.save_changes()

    assert editor_of(page).values == (LegacyScreenshotRule("shot-1", "shot-#"),)


def test_saving_an_emptied_list_restores_the_shipped_rules(page: LegacyScreenshotsPage) -> None:
    """Recognizing nothing is not an answer a conversion could act on.

    **Test steps:**

    * empty the editor and save
    * verify the shipped rules come back
    """
    editor_of(page).values = ()

    page.save_changes()

    assert editor_of(page).values == LEGACY_SCREENSHOT_RULES


def test_dropping_changes_reverts_to_the_saved_rules(page: LegacyScreenshotsPage) -> None:
    """Cancel is the staged edits going away, not the saved ones.

    **Test steps:**

    * stage a change, then drop it
    * verify the saved set is back
    """
    editor_of(page).values = (LegacyScreenshotRule("shot-1", "shot-#"),)

    page.drop_changes()

    assert editor_of(page).values == LEGACY_SCREENSHOT_RULES


def test_reset_restores_the_shipped_rules(page: LegacyScreenshotsPage) -> None:
    """Reset is the shipped set, offered because there genuinely is a default to go back to.

    **Test steps:**

    * stage a different set
    * trigger the reset action
    * verify the shipped rules are shown
    """
    editor = editor_of(page)
    editor.values = (LegacyScreenshotRule("shot-1", "shot-#"),)

    editor.item_actions.reset_action.trigger()

    assert editor.values == LEGACY_SCREENSHOT_RULES


# endregion

# region What the editor flags


def test_a_half_typed_rule_is_flagged_rather_than_refused(page: LegacyScreenshotsPage) -> None:
    """Nothing refuses a keystroke -- a rule is half-typed for as long as it takes to type it.

    **Test steps:**

    * stage rules with a blank cover, a cover holding the placeholder, and a rest with no placeholder
    * verify each cell explains itself
    """
    model = model_of(page)
    editor_of(page).values = (
        LegacyScreenshotRule("", "shot-#"),
        LegacyScreenshotRule("sh#t", "shot-#"),
        LegacyScreenshotRule("shot-1", "shot"),
    )

    assert model.invalid_reason(0, COVER_COLUMN) == MISSING_COVER_REASON
    assert model.invalid_reason(1, COVER_COLUMN) == PLACEHOLDER_IN_COVER_REASON
    assert model.invalid_reason(2, REST_COLUMN) == MISSING_PLACEHOLDER_REASON


def test_a_usable_rule_is_flagged_nowhere(page: LegacyScreenshotsPage) -> None:
    """The flag is about what a scan would refuse, so a rule it would accept carries none.

    **Test steps:**

    * stage a compilable rule
    * verify neither cell has a reason
    """
    model = model_of(page)
    editor_of(page).values = (LegacyScreenshotRule("shot-1", "shot-#"),)

    assert model.invalid_reason(0, COVER_COLUMN) == ""
    assert model.invalid_reason(0, REST_COLUMN) == ""


# endregion
