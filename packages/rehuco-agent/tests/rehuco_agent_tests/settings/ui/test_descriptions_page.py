"""Tests for DescriptionsPage: the Descriptions settings category page (#26, #47, #76)."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import description_editor_settings, markdown_rendering_settings
from rehuco_agent.settings.description_editor_settings import (
    DescriptionEditorSettings,
    shared_description_editor_settings,
)
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_agent.settings.ui import descriptions_page
from rehuco_agent.settings.ui.descriptions_page import DescriptionsPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter


# region fixtures
# Mirrors test_markdown_rendering_settings.py's (and conftest.py's) FakeSettings exactly -- kept as
# a separate copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""

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


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on every module that imported its own reference to it: the two shared settings modules
    (used by their singletons' lazy loads) and the page module itself (used by
    :meth:`DescriptionsPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(description_editor_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(descriptions_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear both shared settings singletons before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_markdown_rendering_settings.cache_clear()
    shared_description_editor_settings.cache_clear()
    yield
    shared_markdown_rendering_settings.cache_clear()
    shared_description_editor_settings.cache_clear()


# endregion


def test_starts_with_the_shared_settings_current_values(qtbot: QtBot) -> None:
    """A freshly-built page's fields reflect the shared settings' current values.

    **Test steps:**

    * seed the shared settings with non-default values
    * build the page
    * verify each field shows the seeded value
    """
    settings = shared_markdown_rendering_settings()
    settings.engine = "mistletoe"
    settings.markdown_css = "markdown-css"
    settings.mistletoe_css = "mistletoe-css"

    page = DescriptionsPage()
    qtbot.addWidget(page)

    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert ui.mistletoe_engine_radio_button.isChecked()
    assert ui.css_edit.toPlainText() == "mistletoe-css"


def test_switching_engine_shows_the_other_engines_css_draft(qtbot: QtBot) -> None:
    """Switching the engine radio swaps the CSS editor to that engine's own draft.

    **Test steps:**

    * seed distinct CSS for both engines (starting on markdown)
    * build the page and switch to mistletoe
    * verify the editor now shows the mistletoe CSS
    * switch back to markdown
    * verify the editor shows the markdown CSS again
    """
    settings = shared_markdown_rendering_settings()
    settings.markdown_css = "markdown-css"
    settings.mistletoe_css = "mistletoe-css"

    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.mistletoe_engine_radio_button.setChecked(True)
    assert ui.css_edit.toPlainText() == "mistletoe-css"

    ui.markdown_engine_radio_button.setChecked(True)
    assert ui.css_edit.toPlainText() == "markdown-css"


def test_editing_css_preserves_the_other_engines_draft(qtbot: QtBot) -> None:
    """Editing one engine's CSS doesn't disturb the other engine's already-staged draft.

    **Test steps:**

    * build the page, edit the markdown CSS, switch to mistletoe and edit its CSS too
    * switch back to markdown
    * verify the markdown edit survived
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.css_edit.setPlainText("edited-markdown-css")
    ui.mistletoe_engine_radio_button.setChecked(True)
    ui.css_edit.setPlainText("edited-mistletoe-css")

    ui.markdown_engine_radio_button.setChecked(True)

    assert ui.css_edit.toPlainText() == "edited-markdown-css"


def test_is_dirty_is_false_right_after_construction(qtbot: QtBot) -> None:
    """A freshly-built page (nothing edited yet) is not dirty.

    **Test steps:**

    * build the page
    * verify ``is_dirty`` is ``False``
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)

    assert page.is_dirty() is False


def test_is_dirty_is_true_after_an_edit(qtbot: QtBot) -> None:
    """Editing any field makes the page dirty.

    **Test steps:**

    * build the page and switch the engine radio
    * verify ``is_dirty`` is ``True``
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.mistletoe_engine_radio_button.setChecked(True)

    assert page.is_dirty() is True


def test_save_changes_updates_the_shared_settings_and_persists(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` pushes every staged field into the shared settings object and persists it.

    **Test steps:**

    * build the page, switch engine, edit CSS
    * call ``save_changes``
    * verify the shared settings object reflects every change
    * verify a fresh load from the persisted store reflects them too
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.mistletoe_engine_radio_button.setChecked(True)
    ui.css_edit.setPlainText("new-mistletoe-css")

    page.save_changes()

    settings = shared_markdown_rendering_settings()
    assert settings.engine == "mistletoe"
    assert settings.mistletoe_css == "new-mistletoe-css"

    reloaded = type(settings)()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.engine == "mistletoe"
    assert reloaded.mistletoe_css == "new-mistletoe-css"


def test_save_changes_clears_dirty(qtbot: QtBot) -> None:
    """After ``save_changes``, the page is no longer dirty.

    **Test steps:**

    * build the page, edit a field, save
    * verify ``is_dirty`` is now ``False``
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.mistletoe_engine_radio_button.setChecked(True)

    page.save_changes()

    assert page.is_dirty() is False


def test_drop_changes_reverts_edits(qtbot: QtBot) -> None:
    """``drop_changes`` reverts every field back to the shared settings' current values.

    **Test steps:**

    * build the page and edit every field
    * call ``drop_changes``
    * verify every field is back to the (unsaved, still-default) shared settings values
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.mistletoe_engine_radio_button.setChecked(True)
    ui.css_edit.setPlainText("unsaved-css")

    page.drop_changes()

    assert ui.markdown_engine_radio_button.isChecked()
    assert ui.css_edit.toPlainText() == ""
    assert page.is_dirty() is False


def test_editor_check_boxes_start_with_the_shared_settings_current_values(qtbot: QtBot) -> None:
    """A freshly-built page's three editor checkboxes reflect the shared editor settings' current
    values (#69).

    **Test steps:**

    * seed the shared editor settings with everything off
    * build the page
    * verify every checkbox starts unchecked
    """
    settings = shared_description_editor_settings()
    settings.show_line_numbers = False
    settings.show_line_endings = False
    settings.wrap_long_lines = False

    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    assert ui.line_numbers_check_box.isChecked() is False
    assert ui.line_endings_check_box.isChecked() is False
    assert ui.wrap_long_lines_check_box.isChecked() is False


def test_toggling_an_editor_check_box_makes_the_page_dirty(qtbot: QtBot) -> None:
    """Toggling any of the three editor checkboxes makes the page dirty (#69).

    **Test steps:**

    * build the page and uncheck the wrap-long-lines checkbox
    * verify ``is_dirty`` is ``True``
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    ui.wrap_long_lines_check_box.setChecked(False)

    assert page.is_dirty() is True


def test_save_changes_updates_the_shared_editor_settings_and_persists(
    qtbot: QtBot, fake_persistent_settings: FakeSettings, mocker: MockerFixture
) -> None:
    """``save_changes`` pushes the staged editor checkboxes into the shared editor settings --
    firing its aggregate signal, which every open document's editor follows (#69) -- and persists
    them, independent of the rendering settings it also saves.

    **Test steps:**

    * build the page and connect a spy to the shared settings' aggregate signal
    * uncheck every editor checkbox and call ``save_changes``
    * verify the shared settings object reflects every change and the signal fired
    * verify a fresh load from the persisted store reflects them too
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    settings = shared_description_editor_settings()
    spy = mocker.Mock()
    settings.description_editor_changed.connect(spy)
    ui.line_numbers_check_box.setChecked(False)
    ui.line_endings_check_box.setChecked(False)
    ui.wrap_long_lines_check_box.setChecked(False)

    page.save_changes()

    assert settings.show_line_numbers is False
    assert settings.show_line_endings is False
    assert settings.wrap_long_lines is False
    assert spy.call_count == 3

    reloaded = DescriptionEditorSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.show_line_numbers is False
    assert reloaded.show_line_endings is False
    assert reloaded.wrap_long_lines is False


def test_drop_changes_reverts_the_editor_check_boxes(qtbot: QtBot) -> None:
    """``drop_changes`` reverts the three editor checkboxes back to the shared editor settings'
    current values (#69), independent of the rendering-settings fields it also reverts.

    **Test steps:**

    * build the page and uncheck every editor checkbox
    * call ``drop_changes``
    * verify every checkbox is back to the (unsaved, still-default) shared value: checked
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access
    ui.line_numbers_check_box.setChecked(False)
    ui.line_endings_check_box.setChecked(False)
    ui.wrap_long_lines_check_box.setChecked(False)

    page.drop_changes()

    assert ui.line_numbers_check_box.isChecked() is True
    assert ui.line_endings_check_box.isChecked() is True
    assert ui.wrap_long_lines_check_box.isChecked() is True
    assert page.is_dirty() is False


def test_title_is_descriptions(qtbot: QtBot) -> None:
    """The page's category-tree title is "Descriptions" (#76).

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)

    assert page.title == "Descriptions"


def test_frame_filter_discovers_the_pages_frames_and_their_text(qtbot: QtBot) -> None:
    """A `SettingsFrameFilter` finds the page's labeled frames and filters them by their text (#67).

    Guards the page's ``.ui`` frame structure: the engine frame must be a discoverable top-level
    frame whose gathered caption text drives the filter.

    **Test steps:**

    * build a frame filter over the page, then filter by an engine-only term
    * verify the engine frame stays shown
    * filter by a term the page holds nowhere
    * verify the engine frame is hidden
    """
    page = DescriptionsPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, page.title)
    ui = page._DescriptionsPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access

    frame_filter.apply("engine", show_full_on_title_match=False)

    assert ui.engine_frame.isVisibleTo(page) is True

    frame_filter.apply("thumbnail", show_full_on_title_match=False)

    assert ui.engine_frame.isVisibleTo(page) is False
