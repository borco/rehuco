"""Tests for RootLayoutTemplatesPage: the library of root path templates, with its Try-it preview (#637)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.location_replacements_settings import shared_location_replacements_settings
from rehuco_agent.settings.location_templates_settings import DEFAULT_SAMPLE
from rehuco_agent.settings.root_layout_templates_settings import (
    REFUSED_TEMPLATES,
    shared_root_layout_templates_settings,
)
from rehuco_agent.settings.ui import root_layout_templates_page
from rehuco_agent.settings.ui.location_template_patterns_editor import LocationTemplatePatternsEditor
from rehuco_agent.settings.ui.root_layout_templates_page import NO_TEMPLATES, RootLayoutTemplatesPage
from rehuco_agent.settings.ui.settings_page import SettingsPage
from rehuco_core import ReplacementRule

from rehuco_agent_tests.conftest import FakeSettings


@fixture(name="stored")
def stored_fixture(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so an Apply never touches real storage.

    :param mocker: pytest-mock fixture.
    :returns: the store the page writes to.
    """
    fake = FakeSettings()
    mocker.patch.object(root_layout_templates_page, "persistent_settings", return_value=fake)
    return fake


@fixture(name="page")
def page_fixture(qtbot: QtBot, stored: FakeSettings) -> RootLayoutTemplatesPage:
    """A page over the shared settings.

    :param qtbot: pytest-qt fixture.
    :param stored: the store an Apply writes to.
    :returns: the page.
    """
    del stored
    built = RootLayoutTemplatesPage()
    qtbot.addWidget(built)
    return built


def editor(page: RootLayoutTemplatesPage) -> LocationTemplatePatternsEditor:
    """The page's templates list.

    :param page: the page.
    :returns: the list.
    """
    found = page.findChild(LocationTemplatePatternsEditor)
    assert found is not None
    return found


def result(page: RootLayoutTemplatesPage) -> str:
    """What Try it shows.

    :param page: the page.
    :returns: the preview text.
    """
    found = page.findChild(QLabel, "try_it_result_label")
    assert found is not None
    return found.text()


def sample_edit(page: RootLayoutTemplatesPage, field: str) -> QLineEdit:
    """One field of the Try-it sample record.

    :param page: the page.
    :param field: the field's name: ``title``, ``publisher``, ``authors``, ``year`` or ``count``.
    :returns: its edit.
    """
    found = page.findChild(QLineEdit, f"sample_{field}_edit")
    assert found is not None
    return found


def test_a_fresh_page_is_a_clean_settings_page_with_no_template_and_no_reset(page: RootLayoutTemplatesPage) -> None:
    """The library ships empty, so there is nothing to reset to and Try it says so (#637).

    **Test steps:**

    * build the page over the shipped settings
    * verify it is a settings page, clean, shows no templates, the shipped sample, a preview saying there are none, and
      hides Reset
    """
    assert isinstance(page, SettingsPage)
    assert not page.is_dirty()
    assert editor(page).values == ()
    assert sample_edit(page, "title").text() == DEFAULT_SAMPLE[0]
    assert result(page) == NO_TEMPLATES
    assert not editor(page).item_actions.reset_action.isVisible()


def test_staged_templates_and_sample_dirty_the_page_until_applied_and_are_normalized(
    page: RootLayoutTemplatesPage, stored: FakeSettings
) -> None:
    """Apply saves the library without blanks and repeats -- keeping a typo and ``*`` -- and the sample with it (#637).

    **Test steps:**

    * stage templates with a blank, a ``*``, a repeat and a typo, and verify the page dirty and nothing saved
    * apply, and verify the settings, the store, a clean page and the list showing the normalized rows
    * change only the sample, and verify the page dirty
    """
    settings = shared_root_layout_templates_settings()
    editor(page).values = ("{authors}/{title}", "", "*", "{authors}/{title}", "{author}")

    assert page.is_dirty()
    assert not settings.templates

    page.save_changes()

    assert settings.templates == ("{authors}/{title}", "*", "{author}")
    assert not page.is_dirty()
    assert editor(page).values == ("{authors}/{title}", "*", "{author}")
    stored.beginGroup("root_layout_templates")
    assert stored.value("templates") == ["{authors}/{title}", "*", "{author}"]
    stored.endGroup()

    sample_edit(page, "title").setText("Another")
    assert page.is_dirty()


def test_dropping_changes_shows_the_saved_state_and_defaults_stage_the_shipped_one(
    page: RootLayoutTemplatesPage,
) -> None:
    """Reset puts back what is applied; Defaults stage the empty library and the shipped sample, saving nothing (#637).

    **Test steps:**

    * apply a template and a sample, stage another, and drop the changes
    * verify the applied ones are back
    * seed the defaults and verify the empty library and shipped sample staged, the page dirty and the setting kept
    """
    editor(page).values = ("{title}",)
    sample_edit(page, "title").setText("Kept")
    page.save_changes()
    editor(page).values = ("{publisher}/{title}",)
    sample_edit(page, "title").setText("Lost")

    page.drop_changes()

    assert editor(page).values == ("{title}",)
    assert sample_edit(page, "title").text() == "Kept"
    assert not page.is_dirty()

    page.seed_defaults()

    assert editor(page).values == ()
    assert sample_edit(page, "title").text() == DEFAULT_SAMPLE[0]
    assert page.is_dirty()
    assert shared_root_layout_templates_settings().templates == ("{title}",)


def test_try_it_shows_the_path_each_valid_template_gives_the_sample_or_why_it_gives_none(
    page: RootLayoutTemplatesPage,
) -> None:
    """Each valid template is a line: its path, one folder per ``/`` level; or the empty placeholders that forbid it,
    or the level that renders to nothing; an invalid one is left out (#637).

    **Test steps:**

    * stage four templates -- a two-level one, one naming an empty publisher, one with two empty fields, a typo -- and a
      sample with no publisher, year or count
    * verify the two-level path, the publisher named as empty, both fields named, and no line for the typo
    * empty the title and verify the level that renders to nothing is said
    """
    sample_edit(page, "publisher").setText("")
    sample_edit(page, "year").setText("")
    sample_edit(page, "count").setText("")
    editor(page).values = ("{authors}/{title}", "{publisher}/{title}", "{publisher}/{year}", "{author}/{title}")

    assert result(page).splitlines() == [
        "{authors}/{title} → Jane Doe, John Roe/Sample Title",
        "{publisher}/{title}: publisher is empty",
        "{publisher}/{year}: publisher, year are empty",
    ]

    sample_edit(page, "title").setText("")
    editor(page).values = ("{{{title}}}/{{{authors}}}",)

    assert result(page) == "{{{title}}}/{{{authors}}}: a folder level renders to nothing"


def test_try_it_applies_the_saved_location_replacements_and_follows_their_change(page: RootLayoutTemplatesPage) -> None:
    """The path goes through the saved Location Replacements, as a root's destination does, and the preview follows an
    applied change of them (#637).

    **Test steps:**

    * stage a template over a title holding a colon, with the default replacements, and read the preview
    * apply a replacement of the colon by an underscore, and read it again
    * verify the first reads a hyphen where the colon was and the second the underscore
    """
    sample_edit(page, "title").setText("Part: One")
    editor(page).values = ("{title}",)
    assert result(page) == "{title} → Part - One"

    shared_location_replacements_settings().rules = (ReplacementRule(": ", "_"),)

    assert result(page) == "{title} → Part_One"


def test_a_star_row_is_flagged_with_its_reason_and_gets_no_try_it_line(page: RootLayoutTemplatesPage) -> None:
    """The root editor always offers ``*``, so a ``*`` row is shown in the warning colour with that as its tooltip, and
    Try it says nothing of it (#637).

    **Test steps:**

    * stage a valid template and a ``*`` row
    * verify the ``*`` row has the warning colour and the reason, and the valid one neither
    * verify Try it has one line, the valid template's
    """
    editor(page).values = ("{title}", "*")
    model = editor(page).model
    valid, star = model.index(0, 0), model.index(1, 0)

    assert star.data(Qt.ItemDataRole.ForegroundRole) is not None
    assert star.data(Qt.ItemDataRole.ToolTipRole) == REFUSED_TEMPLATES["*"]
    assert editor(page).refused == REFUSED_TEMPLATES
    assert valid.data(Qt.ItemDataRole.ForegroundRole) is None
    assert result(page) == "{title} → Sample Title"
