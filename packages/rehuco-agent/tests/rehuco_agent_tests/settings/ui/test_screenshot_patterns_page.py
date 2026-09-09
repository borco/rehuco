"""Tests for ScreenshotPatternsPage, its one-column patterns editor, and its try-it table (#53, #287)."""

from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import screenshot_patterns_settings
from rehuco_agent.settings.screenshot_patterns_settings import DEFAULT_SAMPLES, shared_screenshot_patterns_settings
from rehuco_agent.settings.ui import screenshot_patterns_page
from rehuco_agent.settings.ui.screenshot_name_patterns_editor import ScreenshotNamePatternsEditor
from rehuco_agent.settings.ui.screenshot_name_patterns_model import PATTERN_COLUMN, ScreenshotNamePatternsModel
from rehuco_agent.settings.ui.screenshot_patterns_page import ScreenshotPatternsPage
from rehuco_agent.settings.ui.screenshot_try_it_editor import ScreenshotTryItEditor
from rehuco_agent.settings.ui.screenshot_try_it_model import FILENAME_COLUMN, NOT_A_SCREENSHOT, SLOT_COLUMN
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePattern

# region Sample settings backend
# Mirrors test_screenshot_patterns_settings.py's FakeSettings -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code


class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802  (Qt API name)
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code

# endregion

# region fixtures


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module (used
    by :func:`shared_screenshot_patterns_settings`'s lazy load) and the page module itself (used by
    :meth:`ScreenshotPatternsPage.save_changes`).

    :param mocker: pytest-mock fixture.
    :returns: the stand-in every read and write lands in.
    """
    fake = FakeSettings()
    mocker.patch.object(screenshot_patterns_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(screenshot_patterns_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Any:
    """Drop the process-wide settings instance around every test, so none inherits another's."""
    shared_screenshot_patterns_settings.cache_clear()
    yield
    shared_screenshot_patterns_settings.cache_clear()


@fixture(name="page")
def fixture_page(qtbot: QtBot) -> ScreenshotPatternsPage:
    """A page built over the isolated settings.

    :param qtbot: pytest-qt fixture, which owns the widget's lifetime.
    :returns: the page.
    """
    page = ScreenshotPatternsPage()
    qtbot.addWidget(page)
    return page


def editor_of(page: ScreenshotPatternsPage) -> ScreenshotNamePatternsEditor:
    """The page's patterns editor, reached through its name-mangled UI attribute.

    :param page: the page.
    :returns: the editor.
    """
    return page._ScreenshotPatternsPage__ui.patterns_editor  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def model_of(page: ScreenshotPatternsPage) -> ScreenshotNamePatternsModel:
    """The patterns model behind the page's editor, at its concrete type.

    The base editor knows only ``QAbstractItemModel``, so the narrowing is asserted here rather than
    repeated at each cell-level assertion below.

    :param page: the page.
    :returns: the model.
    """
    model = editor_of(page).model
    assert isinstance(model, ScreenshotNamePatternsModel)
    return model


def try_it_editor_of(page: ScreenshotPatternsPage) -> ScreenshotTryItEditor:
    """The page's try-it editor, reached through its name-mangled UI attribute.

    :param page: the page.
    :returns: the editor.
    """
    return page._ScreenshotPatternsPage__ui.try_it_editor  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def slot_shown(page: ScreenshotPatternsPage, row: int) -> str:
    """What the try-it table shows in ``row``'s slot cell.

    :param page: the page.
    :param row: the try-it row.
    :returns: the slot text.
    """
    model = try_it_editor_of(page).model
    return model.data(model.index(row, SLOT_COLUMN))


# endregion

# region What the page shows


def test_a_fresh_install_shows_the_shipped_patterns_and_the_seeded_samples(page: ScreenshotPatternsPage) -> None:
    """Nothing saved is the shipped set and the seeded samples, and nothing to save.

    **Test steps:**

    * build a page over empty storage
    * verify it shows the shipped patterns, the seeded samples, and is not dirty
    """
    assert editor_of(page).values == SCREENSHOT_NAME_PATTERNS
    assert try_it_editor_of(page).values == DEFAULT_SAMPLES
    assert page.is_dirty() is False


def test_the_ordering_column_is_shown(page: ScreenshotPatternsPage) -> None:
    """Order decides which pattern matches first, so the move buttons are part of the page.

    **Test steps:**

    * verify the ordering column is not hidden
    """
    assert editor_of(page).ordering_actions.isHidden() is False


def test_every_action_wears_an_icon(page: ScreenshotPatternsPage) -> None:
    """The base editor ships no icons; `apply_item_action_icons` is what dresses both editors here.

    **Test steps:**

    * verify each action armed on either view carries a non-null icon
    """
    for editor in (editor_of(page), try_it_editor_of(page)):
        actions = editor.view.actions()

        assert actions
        assert all(not action.icon().isNull() for action in actions)


def test_editing_a_pattern_marks_only_the_patterns_frame_dirty(page: ScreenshotPatternsPage) -> None:
    """The frame highlight follows the edit: a pattern change paints its own frame, and not the try-it
    frame whose slot column merely re-evaluates -- a derived column is not an edit.

    **Test steps:**

    * build a frame filter over the clean page and verify nothing is dirty
    * edit the pattern the first seeded sample matched
    * verify the patterns frame alone is reported dirty
    """
    ui = page._ScreenshotPatternsPage__ui  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    frame_filter = SettingsFrameFilter(page, "Screenshot Patterns")
    assert not frame_filter.dirty_frames()

    model = model_of(page)
    model.setData(model.index(0, PATTERN_COLUMN), r"^shot-(\d+)$")

    assert slot_shown(page, 0) == NOT_A_SCREENSHOT
    assert frame_filter.dirty_frames() == [ui.patterns_frame]


def test_editing_a_sample_marks_only_the_try_it_frame_dirty(page: ScreenshotPatternsPage) -> None:
    """A sample is a staged value like a pattern, so its frame paints the same way when it changes.

    **Test steps:**

    * build a frame filter over the clean page
    * retype a sample filename
    * verify the try-it frame alone is reported dirty
    """
    ui = page._ScreenshotPatternsPage__ui  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    frame_filter = SettingsFrameFilter(page, "Screenshot Patterns")

    model = try_it_editor_of(page).model
    model.setData(model.index(0, FILENAME_COLUMN), "shot-3.jpg")

    assert frame_filter.dirty_frames() == [ui.try_it_frame]


def test_the_page_filters_by_its_three_frames(page: ScreenshotPatternsPage) -> None:
    """A page filters by its labeled top-level frames, and implements nothing itself for it.

    **Test steps:**

    * build a frame filter over the page
    * filter by each frame's header and verify only that frame stays shown
    * filter by a non-matching term and verify all three hide
    """
    ui = page._ScreenshotPatternsPage__ui  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    frame_filter = SettingsFrameFilter(page, "Screenshot Patterns")

    frame_filter.apply("screenshot name patterns", show_full_on_title_match=False)
    assert ui.patterns_frame.isVisibleTo(page) is True
    assert ui.tie_break_frame.isVisibleTo(page) is False
    assert ui.try_it_frame.isVisibleTo(page) is False

    frame_filter.apply("always applied", show_full_on_title_match=False)
    assert ui.tie_break_frame.isVisibleTo(page) is True
    assert ui.patterns_frame.isVisibleTo(page) is False
    assert ui.try_it_frame.isVisibleTo(page) is False

    frame_filter.apply("try it", show_full_on_title_match=False)
    assert ui.try_it_frame.isVisibleTo(page) is True
    assert ui.patterns_frame.isVisibleTo(page) is False
    assert ui.tie_break_frame.isVisibleTo(page) is False

    frame_filter.apply("nothing on this page", show_full_on_title_match=False)
    assert ui.patterns_frame.isVisibleTo(page) is False
    assert ui.tie_break_frame.isVisibleTo(page) is False
    assert ui.try_it_frame.isVisibleTo(page) is False


# endregion

# region Editing, saving and dropping the patterns


def test_a_row_saving_would_drop_is_not_yet_a_change(page: ScreenshotPatternsPage) -> None:
    """A blank or half-typed pattern does not make the page dirty, because applying would not change
    what is saved -- and while *Apply changes as they're made* is on, the dialog commits any dirty
    page, which would tear the fresh row out from under its open cell (#53).

    **Test steps:**

    * insert a blank pattern and verify the page stays clean
    * type half of a broken pattern and verify it still does
    * complete a compilable pattern and verify the page is dirty exactly then
    """
    model = model_of(page)
    row = model.insert(-1)
    assert page.is_dirty() is False

    model.setData(model.index(row, PATTERN_COLUMN), "[")
    assert page.is_dirty() is False

    model.setData(model.index(row, PATTERN_COLUMN), "^shot-(\\d+)$")
    assert page.is_dirty() is True


def test_an_edit_makes_the_page_dirty(page: ScreenshotPatternsPage) -> None:
    """Dirtiness is the staged list against what a scan would read, polled rather than signalled.

    **Test steps:**

    * replace the staged patterns
    * verify the page reports itself dirty
    """
    editor_of(page).values = (ScreenshotNamePattern(r"^shot-(\d+)$"),)

    assert page.is_dirty() is True


def test_saving_persists_the_patterns_and_settles_the_page(page: ScreenshotPatternsPage) -> None:
    """Save is what makes the staged patterns the ones the next conversion is handed.

    **Test steps:**

    * stage a pattern set and save it
    * verify the shared settings hold it and the page is no longer dirty
    """
    editor_of(page).values = (ScreenshotNamePattern(r"^shot-(\d+)$"),)

    page.save_changes()

    saved = shared_screenshot_patterns_settings().screenshot_name_patterns
    assert saved == (ScreenshotNamePattern(r"^shot-(\d+)$"),)
    assert page.is_dirty() is False


def test_saving_reloads_what_normalizing_actually_kept(page: ScreenshotPatternsPage) -> None:
    """A page still showing what was typed would disagree with every scan.

    **Test steps:**

    * stage a good pattern alongside one that cannot compile, and save
    * verify the page comes back showing only the pattern that survived
    """
    editor_of(page).values = (
        ScreenshotNamePattern(r"^shot-(\d+)$"),
        ScreenshotNamePattern("["),
    )

    page.save_changes()

    assert editor_of(page).values == (ScreenshotNamePattern(r"^shot-(\d+)$"),)


def test_saving_an_emptied_list_restores_the_shipped_patterns(page: ScreenshotPatternsPage) -> None:
    """Recognizing nothing is not an answer a conversion could act on.

    **Test steps:**

    * empty the editor and save
    * verify the shipped patterns come back
    """
    editor_of(page).values = ()

    page.save_changes()

    assert editor_of(page).values == SCREENSHOT_NAME_PATTERNS


def test_dropping_changes_reverts_to_the_saved_patterns(page: ScreenshotPatternsPage) -> None:
    """Cancel is the staged edits going away, not the saved ones.

    **Test steps:**

    * stage a change, then drop it
    * verify the saved set is back
    """
    editor_of(page).values = (ScreenshotNamePattern(r"^shot-(\d+)$"),)

    page.drop_changes()

    assert editor_of(page).values == SCREENSHOT_NAME_PATTERNS


def test_reset_restores_the_shipped_patterns(page: ScreenshotPatternsPage) -> None:
    """Reset is the shipped set, offered because there genuinely is a default to go back to.

    **Test steps:**

    * stage a different set
    * trigger the reset action
    * verify the shipped patterns are shown
    """
    editor = editor_of(page)
    editor.values = (ScreenshotNamePattern(r"^shot-(\d+)$"),)

    editor.item_actions.reset_action.trigger()

    assert editor.values == SCREENSHOT_NAME_PATTERNS


# endregion

# region Editing, saving and dropping the samples


def test_a_blank_sample_row_is_not_yet_a_change(page: ScreenshotPatternsPage) -> None:
    """An inserted, still-empty sample does not make the page dirty, for the same reason a blank
    pattern does not: saving would drop it, and an auto-applying dialog would tear it out mid-typing.

    **Test steps:**

    * insert a blank sample and verify the page stays clean
    * type a name into it and verify the page is dirty exactly then
    """
    model = try_it_editor_of(page).model
    row = model.rowCount()
    model.insertRow(row)
    assert page.is_dirty() is False

    model.setData(model.index(row, FILENAME_COLUMN), "shot-3.jpg")
    assert page.is_dirty() is True


def test_saving_persists_the_samples_and_settles_the_page(page: ScreenshotPatternsPage) -> None:
    """The samples are saved with the patterns: a set worth checking against is worth keeping.

    **Test steps:**

    * stage a sample list and save it
    * verify the shared settings hold it and the page is no longer dirty
    """
    try_it_editor_of(page).values = ("shot-3.jpg", "cover.png")

    page.save_changes()

    assert shared_screenshot_patterns_settings().screenshot_samples == ("shot-3.jpg", "cover.png")
    assert page.is_dirty() is False


def test_saving_reloads_the_samples_normalizing_actually_kept(page: ScreenshotPatternsPage) -> None:
    """Blank and repeated samples are dropped on save, and the table shows what was kept.

    **Test steps:**

    * stage a sample list holding a blank and a repeat, and save
    * verify the table comes back showing the survivors
    """
    try_it_editor_of(page).values = (" shot-3.jpg ", "", "shot-3.jpg", "cover.png")

    page.save_changes()

    assert try_it_editor_of(page).values == ("shot-3.jpg", "cover.png")


def test_saving_an_emptied_sample_list_restores_the_seeded_samples(page: ScreenshotPatternsPage) -> None:
    """An empty try-it table shows nothing, so emptying it means the seeded samples instead.

    **Test steps:**

    * empty the try-it table and save
    * verify the seeded samples come back
    """
    try_it_editor_of(page).values = ()

    page.save_changes()

    assert try_it_editor_of(page).values == DEFAULT_SAMPLES


def test_dropping_changes_reverts_to_the_saved_samples(page: ScreenshotPatternsPage) -> None:
    """Cancel drops the staged samples along with the staged patterns.

    **Test steps:**

    * stage a sample change, then drop it
    * verify the saved samples are back
    """
    try_it_editor_of(page).values = ("shot-3.jpg",)

    page.drop_changes()

    assert try_it_editor_of(page).values == DEFAULT_SAMPLES


def test_reset_restores_the_seeded_samples(page: ScreenshotPatternsPage) -> None:
    """Reset on the try-it table is the seeded samples, which are what the page seeds it with.

    **Test steps:**

    * stage a different sample list
    * trigger the reset action
    * verify the seeded samples are shown
    """
    editor = try_it_editor_of(page)
    editor.values = ("shot-3.jpg",)

    editor.item_actions.reset_action.trigger()

    assert editor.values == DEFAULT_SAMPLES


# endregion

# region The try-it table follows the patterns


def test_the_seeded_samples_evaluate_under_the_shipped_patterns(page: ScreenshotPatternsPage) -> None:
    """The seeded rows show the convention working, not "not a screenshot" three times.

    **Test steps:**

    * read every seeded row's slot cell
    * verify each resolves to the slot its name carries
    """
    assert [slot_shown(page, row) for row in range(len(DEFAULT_SAMPLES))] == ["00", "03", "07"]


def test_the_try_it_table_refreshes_when_a_pattern_row_is_added(page: ScreenshotPatternsPage) -> None:
    """Adding a pattern that newly matches a sample updates that sample's slot immediately.

    **Test steps:**

    * stage a try-it sample no shipped pattern recognizes
    * verify it starts out unmatched
    * add a pattern that recognizes it
    * verify the slot column updates without an explicit reload
    """
    try_it_editor_of(page).values = ("shot-3.jpg",)
    assert slot_shown(page, 0) == NOT_A_SCREENSHOT

    patterns_model = model_of(page)
    row = patterns_model.insert(-1)
    patterns_model.setData(patterns_model.index(row, PATTERN_COLUMN), r"^shot-(\d+)$")

    assert slot_shown(page, 0) == "03"


def test_the_try_it_table_refreshes_when_a_pattern_row_is_edited(page: ScreenshotPatternsPage) -> None:
    """Editing an existing pattern's regex updates every sample's slot that depends on it.

    **Test steps:**

    * stage a single custom pattern and a matching try-it sample
    * edit the pattern so it no longer matches
    * verify the sample's slot falls back to "not a screenshot"
    """
    editor_of(page).values = (ScreenshotNamePattern(r"^shot-(\d+)$"),)
    try_it_editor_of(page).values = ("shot-3.jpg",)
    assert slot_shown(page, 0) == "03"

    patterns_model = model_of(page)
    patterns_model.setData(patterns_model.index(0, PATTERN_COLUMN), r"^frame-(\d+)$")

    assert slot_shown(page, 0) == NOT_A_SCREENSHOT


def test_the_try_it_table_refreshes_when_a_pattern_row_is_removed(page: ScreenshotPatternsPage) -> None:
    """Removing the one pattern that matched a sample updates its slot.

    **Test steps:**

    * stage a single custom pattern and a matching try-it sample
    * delete the pattern
    * verify the sample's slot falls back to "not a screenshot"
    """
    editor_of(page).values = (ScreenshotNamePattern(r"^shot-(\d+)$"),)
    try_it_editor_of(page).values = ("shot-3.jpg",)
    assert slot_shown(page, 0) == "03"

    model_of(page).delete(0)

    assert slot_shown(page, 0) == NOT_A_SCREENSHOT


def test_the_try_it_table_refreshes_when_a_pattern_row_is_reordered(page: ScreenshotPatternsPage) -> None:
    """Reordering can change which pattern matches first, so the slot column follows a move too.

    **Test steps:**

    * stage two patterns that both match one sample, disagreeing on its slot
    * verify the earlier pattern's answer shows
    * move it below the other and verify the slot column follows
    """
    editor_of(page).values = (
        ScreenshotNamePattern(r"^shot-(\d+)$"),
        ScreenshotNamePattern(r"^shot-03$"),
    )
    try_it_editor_of(page).values = ("shot-03.jpg",)
    assert slot_shown(page, 0) == "03"

    model_of(page).move_down(0)

    assert slot_shown(page, 0) == "00"


def test_the_try_it_table_refreshes_when_its_own_filename_row_is_edited(page: ScreenshotPatternsPage) -> None:
    """Typing a new sample filename shows its slot under the current pattern list right away.

    **Test steps:**

    * retype the first try-it sample to a name the shipped patterns do not recognize
    * verify its slot reads "not a screenshot"
    * retype it to a name a shipped pattern does recognize
    * verify the slot updates
    """
    model = try_it_editor_of(page).model

    model.setData(model.index(0, FILENAME_COLUMN), "not-a-pattern-at-all")
    assert slot_shown(page, 0) == NOT_A_SCREENSHOT

    model.setData(model.index(0, FILENAME_COLUMN), "cover.jpg")
    assert slot_shown(page, 0) == "00"


# endregion
