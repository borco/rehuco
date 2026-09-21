"""Tests for LocationTemplatesPage: one resource type's rename-suggestion patterns, with a Try-it
preview (#322).
"""

from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import location_templates_settings
from rehuco_agent.settings.location_templates_settings import (
    NAME_SUGGESTION_PATTERNS,
    UNKNOWN_PLACEHOLDER_PROBLEM,
    shared_location_templates_settings,
)
from rehuco_agent.settings.ui import location_templates_page
from rehuco_agent.settings.ui.location_template_patterns_editor import LocationTemplatePatternsEditor
from rehuco_agent.settings.ui.location_template_patterns_model import PATTERN_COLUMN, LocationTemplatePatternsModel
from rehuco_agent.settings.ui.location_templates_page import DEFAULT_SAMPLE, LocationTemplatesPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter

# region Sample settings backend
# Mirrors test_screenshot_patterns_settings.py's FakeSettings -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code


class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__prefixes: list[str] = []

    @property
    def __prefix(self) -> str:
        return "".join(self.__prefixes)

    def beginGroup(self, name: str) -> None:  # noqa: N802  (Qt API name)
        self.__prefixes.append(f"{name}/")

    def endGroup(self) -> None:  # noqa: N802
        if self.__prefixes:
            self.__prefixes.pop()

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__prefix + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__prefix + key, default)

    def childGroups(self) -> list[str]:  # noqa: N802
        prefix = self.__prefix
        nested = (key[len(prefix) :] for key in self.__data if key.startswith(prefix))
        return sorted({rest.split("/")[0] for rest in nested if "/" in rest})

    def remove(self, key: str) -> None:
        full = self.__prefix + key
        for stored in list(self.__data):
            if stored == full or stored.startswith(full + "/") or (not key and stored.startswith(full)):
                del self.__data[stored]


# pylint: enable=duplicate-code

# endregion

# region fixtures


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on both modules that imported their own reference to it: the shared settings module (used
    by :func:`shared_location_templates_settings`'s lazy load) and the page module itself (used by
    :meth:`LocationTemplatesPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(location_templates_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(location_templates_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Any:
    """Drop the process-wide settings instance around every test, so none inherits another's."""
    shared_location_templates_settings.cache_clear()
    yield
    shared_location_templates_settings.cache_clear()


@fixture(name="page")
def fixture_page(qtbot: QtBot) -> LocationTemplatesPage:
    """A tutorial-type page built over the isolated settings.

    :param qtbot: pytest-qt fixture, which owns the widget's lifetime.
    :returns: the page.
    """
    page = LocationTemplatesPage("tutorial")
    qtbot.addWidget(page)
    return page


def editor_of(page: LocationTemplatesPage) -> LocationTemplatePatternsEditor:
    """The page's patterns editor, reached through its name-mangled UI attribute.

    :param page: the page.
    :returns: the editor.
    """
    return page._LocationTemplatesPage__ui.patterns_editor  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def model_of(page: LocationTemplatesPage) -> LocationTemplatePatternsModel:
    """The patterns model behind the page's editor, at its concrete type.

    :param page: the page.
    :returns: the model.
    """
    model = editor_of(page).model
    assert isinstance(model, LocationTemplatePatternsModel)
    return model


def try_it_text(page: LocationTemplatesPage) -> str:
    """The Try-it preview label's current text.

    :param page: the page.
    :returns: the preview text.
    """
    return page._LocationTemplatesPage__ui.try_it_result_label.text()  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


def sample_shown(page: LocationTemplatesPage) -> tuple[str, ...]:
    """The sample record as the page's four fields currently show it.

    :param page: the page.
    :returns: ``(title, publisher, authors, year)`` as typed.
    """
    ui = page._LocationTemplatesPage__ui  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    return tuple(
        edit.text()
        for edit in (ui.sample_title_edit, ui.sample_publisher_edit, ui.sample_authors_edit, ui.sample_year_edit)
    )


def set_sample_title(page: LocationTemplatesPage, title: str) -> None:
    """Retype the sample record's title field.

    :param page: the page.
    :param title: the new title.
    """
    page._LocationTemplatesPage__ui.sample_title_edit.setText(title)  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access


# endregion

# region What the page shows


def test_a_fresh_install_shows_the_shipped_patterns_and_the_seeded_sample(page: LocationTemplatesPage) -> None:
    """Nothing saved is the shipped set and the seeded sample record, and nothing to save.

    **Test steps:**

    * build a page over empty storage
    * verify it shows the shipped patterns, the seeded sample, and is not dirty
    """
    assert editor_of(page).values == NAME_SUGGESTION_PATTERNS
    assert sample_shown(page) == DEFAULT_SAMPLE
    assert page.is_dirty() is False


def test_editing_a_pattern_marks_only_the_patterns_frame_dirty(page: LocationTemplatesPage) -> None:
    """The frame highlight follows the edit: a pattern change paints its own frame, and not the Try-it
    frame whose preview merely re-evaluates -- a derived label is not an edit.

    **Test steps:**

    * build a frame filter over the clean page and verify nothing is dirty
    * edit the first pattern
    * verify the patterns frame alone is reported dirty
    """
    ui = page._LocationTemplatesPage__ui  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access
    frame_filter = SettingsFrameFilter(page, "Tutorials")
    assert not frame_filter.dirty_frames()

    model = model_of(page)
    model.setData(model.index(0, PATTERN_COLUMN), "{title} - archive")

    assert frame_filter.dirty_frames() == [ui.patterns_frame]


def test_editing_the_sample_marks_nothing_dirty(page: LocationTemplatesPage) -> None:
    """The sample record is scratch space, not a setting (#322): retyping it paints no frame and gives
    Apply nothing to do, since nothing the app does would change.

    **Test steps:**

    * build a frame filter over the clean page
    * retype the sample title
    * verify no frame is reported dirty and the page is not dirty
    """
    frame_filter = SettingsFrameFilter(page, "Tutorials")

    set_sample_title(page, "A Brand New Title")

    assert not frame_filter.dirty_frames()
    assert page.is_dirty() is False


def test_the_ordering_column_is_shown(page: LocationTemplatesPage) -> None:
    """Order decides which suggestion is offered first, so the move buttons are part of the page.

    **Test steps:**

    * verify the ordering column is not hidden
    """
    assert editor_of(page).ordering_actions.isHidden() is False


# endregion

# region Editing, saving and dropping the patterns


def test_a_blank_row_is_not_yet_a_change_but_a_typed_one_is(page: LocationTemplatesPage) -> None:
    """A blank pattern does not make the page dirty, because applying would not change what is saved.
    The first keystroke is a change, valid or not: saving keeps a broken row rather than dropping it.

    **Test steps:**

    * insert a blank pattern and verify the page stays clean
    * type an unknown-placeholder pattern and verify the page is dirty exactly then
    """
    model = model_of(page)
    row = model.insert(-1)
    assert page.is_dirty() is False

    model.setData(model.index(row, PATTERN_COLUMN), "{title} ({series})")
    assert page.is_dirty() is True


def test_an_unknown_placeholder_is_flagged_but_not_dropped_from_the_editor(page: LocationTemplatesPage) -> None:
    """An invalid row is colored and explained, never silently emptied (#322).

    **Test steps:**

    * stage a pattern naming an unknown placeholder
    * verify the row still holds it, and reports why it is invalid
    """
    model = model_of(page)
    row = model.insert(-1)
    model.setData(model.index(row, PATTERN_COLUMN), "{title} ({series})")

    assert model.entries[row] == "{title} ({series})"
    assert model.invalid_reason(row) != ""


def test_an_edit_makes_the_page_dirty(page: LocationTemplatesPage) -> None:
    """Dirtiness is the staged list against what this type's shared settings resolve to, polled rather
    than signalled.

    **Test steps:**

    * replace the staged patterns
    * verify the page reports itself dirty
    """
    editor_of(page).values = ("{title} - archive",)

    assert page.is_dirty() is True


def test_reordering_the_patterns_makes_the_page_dirty(page: LocationTemplatesPage) -> None:
    """Order is the order suggestions are offered in, so a move is a real edit (#322).

    **Test steps:**

    * move the first shipped pattern down one row
    * verify the page reports itself dirty, and the staged order changed
    """
    model_of(page).move_down(0)

    assert page.is_dirty() is True
    assert editor_of(page).values[1] == NAME_SUGGESTION_PATTERNS[0]


def test_removing_a_pattern_makes_the_page_dirty(page: LocationTemplatesPage) -> None:
    """Dropping a row stages a shorter list (#322).

    **Test steps:**

    * delete the first shipped pattern
    * verify the page reports itself dirty, and the staged list no longer holds it
    """
    model_of(page).delete(0)

    assert page.is_dirty() is True
    assert NAME_SUGGESTION_PATTERNS[0] not in editor_of(page).values


def test_saving_persists_the_patterns_under_this_types_key_and_settles_the_page(page: LocationTemplatesPage) -> None:
    """Save is what makes the staged patterns the ones the next suggestion is handed, for this page's
    type only.

    **Test steps:**

    * stage a pattern set and save it
    * verify the shared settings hold it under ``"tutorial"``, and the page is no longer dirty
    """
    editor_of(page).values = ("{title} - archive",)

    page.save_changes()

    assert shared_location_templates_settings().patterns_for("tutorial") == ("{title} - archive",)
    assert page.is_dirty() is False


def test_saving_one_type_does_not_disturb_another(page: LocationTemplatesPage) -> None:
    """A tutorial page's save never touches another type's entry (#322).

    **Test steps:**

    * customize the reference-images list directly on the shared settings
    * save the tutorial page's staged patterns
    * verify the reference-images list is unchanged
    """
    settings = shared_location_templates_settings()
    settings.patterns = {**settings.patterns, "reference_images": ("{publisher} - {title}",)}

    editor_of(page).values = ("{title} - archive",)
    page.save_changes()

    assert shared_location_templates_settings().patterns_for("reference_images") == ("{publisher} - {title}",)


def test_saving_keeps_an_invalid_row_flagged_and_out_of_the_effective_list(page: LocationTemplatesPage) -> None:
    """A typo is fixed in place, not retyped: Apply keeps the row, the page shows it red, and no
    document is offered it.

    **Test steps:**

    * stage a good pattern alongside one naming an unknown placeholder, and save
    * verify the page comes back showing both, the broken one flagged, and settled
    * verify the shared settings' effective list holds only the good one
    """
    editor_of(page).values = ("{title} - archive", "{title} ({series})")

    page.save_changes()

    assert editor_of(page).values == ("{title} - archive", "{title} ({series})")
    assert model_of(page).invalid_reason(1) != ""
    assert page.is_dirty() is False
    assert shared_location_templates_settings().patterns_for("tutorial") == ("{title} - archive",)


def test_saving_drops_a_blank_row(page: LocationTemplatesPage) -> None:
    """A page still showing a row saving dropped would disagree with the next Apply.

    **Test steps:**

    * stage a good pattern alongside a blank one, and save
    * verify the page comes back showing only the pattern
    """
    editor_of(page).values = ("{title} - archive", "")

    page.save_changes()

    assert editor_of(page).values == ("{title} - archive",)


def test_saving_an_emptied_list_restores_the_shipped_patterns(page: LocationTemplatesPage) -> None:
    """Offering nothing is not an answer a rename suggestion could act on.

    **Test steps:**

    * empty the editor and save
    * verify the shipped patterns come back
    """
    editor_of(page).values = ()

    page.save_changes()

    assert editor_of(page).values == NAME_SUGGESTION_PATTERNS


def test_dropping_changes_reverts_to_the_saved_patterns(page: LocationTemplatesPage) -> None:
    """Cancel is the staged edits going away, not the saved ones.

    **Test steps:**

    * stage a change, then drop it
    * verify the shipped set is back
    """
    editor_of(page).values = ("{title} - archive",)

    page.drop_changes()

    assert editor_of(page).values == NAME_SUGGESTION_PATTERNS


def test_reset_restores_the_shipped_patterns(page: LocationTemplatesPage) -> None:
    """Reset is the shipped set, offered because there genuinely is a default to go back to.

    **Test steps:**

    * stage a different set
    * trigger the reset action
    * verify the shipped patterns are shown
    """
    editor = editor_of(page)
    editor.values = ("{title} - archive",)

    editor.item_actions.reset_action.trigger()

    assert editor.values == NAME_SUGGESTION_PATTERNS


# endregion

# region The sample record is scratch, not a setting


def test_saving_and_dropping_leave_the_sample_as_typed(page: LocationTemplatesPage) -> None:
    """Apply and Reset act on settings; the sample record is neither saved nor reverted by them (#322).

    **Test steps:**

    * retype the sample title, then save and then drop
    * verify the typed title survived both, and nothing about it reached the shared settings
    """
    set_sample_title(page, "A Brand New Title")

    page.save_changes()
    assert sample_shown(page) == ("A Brand New Title", *DEFAULT_SAMPLE[1:])

    page.drop_changes()
    assert sample_shown(page) == ("A Brand New Title", *DEFAULT_SAMPLE[1:])
    assert not hasattr(shared_location_templates_settings(), "samples")


# endregion

# region The Try-it preview follows the patterns and the sample record


def test_the_try_it_preview_shows_one_line_per_pattern(page: LocationTemplatesPage) -> None:
    """One preview line per staged pattern, each naming the pattern and its result.

    **Test steps:**

    * stage two patterns
    * verify the preview holds exactly two lines, one per pattern
    """
    editor_of(page).values = ("{title}", "{publisher} - {title}")

    lines = try_it_text(page).splitlines()

    assert len(lines) == 2
    assert lines[0].startswith("{title} ")
    assert lines[1].startswith("{publisher} - {title} ")


def test_the_try_it_preview_refreshes_when_a_pattern_is_edited(page: LocationTemplatesPage) -> None:
    """Editing a pattern updates its preview line immediately.

    **Test steps:**

    * stage one pattern and read its preview line
    * edit the pattern
    * verify the preview line changed to match
    """
    editor_of(page).values = ("{title}",)
    before = try_it_text(page)

    model = model_of(page)
    model.setData(model.index(0, PATTERN_COLUMN), "{publisher} - {title}")

    assert try_it_text(page) != before
    assert try_it_text(page).startswith("{publisher} - {title} ")


def test_the_try_it_preview_refreshes_when_the_sample_record_is_edited(page: LocationTemplatesPage) -> None:
    """Editing the sample title changes what the preview shows the pattern resolving to.

    **Test steps:**

    * stage the plain ``{title}`` pattern and read its preview
    * retype the sample title field
    * verify the preview changed to the new title
    """
    editor_of(page).values = ("{title}",)
    before = try_it_text(page)

    set_sample_title(page, "A Brand New Title")

    after = try_it_text(page)
    assert after != before
    assert "A Brand New Title" in after


def test_the_try_it_preview_flags_a_pattern_naming_an_unknown_placeholder(page: LocationTemplatesPage) -> None:
    """An unresolvable pattern's preview line says why, rather than raising or going blank.

    **Test steps:**

    * stage a pattern naming an unknown placeholder
    * verify its preview line reports the pattern as invalid, with the settings module's reason
    """
    editor_of(page).values = ("{title} ({series})",)

    assert try_it_text(page) == f"{{title}} ({{series}}) → (invalid: {UNKNOWN_PLACEHOLDER_PROBLEM})"


def test_the_try_it_preview_merges_a_name_an_earlier_line_already_produced(page: LocationTemplatesPage) -> None:
    """Two patterns naming the sample the same way are offered once on a document, and the preview says
    which line already covered it rather than repeating the name.

    **Test steps:**

    * stage the plain title pattern and the optional-year one, then blank the sample year
    * verify the second line points at the first instead of repeating the name
    """
    editor_of(page).values = ("{title}", "{title}{{ [{year}]}}")
    page._LocationTemplatesPage__ui.sample_year_edit.setText("")  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert try_it_text(page).splitlines() == [
        f"{{title}} → {DEFAULT_SAMPLE[0]}",
        "{title}{{ [{year}]}} → (same as line 1)",
    ]


def test_the_try_it_preview_reports_a_pattern_that_names_nothing(page: LocationTemplatesPage) -> None:
    """An all-optional pattern whose groups all dropped says it named nothing, which a document would
    simply not offer.

    **Test steps:**

    * stage a pattern that is one optional group, then blank the field it depends on
    * verify the preview line reports an empty name
    """
    editor_of(page).values = ("{{{authors}}}",)
    page._LocationTemplatesPage__ui.sample_authors_edit.setText("")  # pyright: ignore[reportAttributeAccessIssue]  # pylint: disable=protected-access

    assert try_it_text(page) == "{{{authors}}} → (empty)"


@mark.parametrize("resource_type", ["tutorial", "reference_images", "collection"])
def test_each_type_reads_and_writes_only_its_own_entry(resource_type: str, qtbot: QtBot) -> None:
    """The same page class, parametrized by type, never leaks one type's patterns into another's
    (#322).

    **Test steps:**

    * customize every other type's list on the shared settings
    * build a page for ``resource_type`` and verify it shows the shipped defaults, unaffected
    """
    other_types = {"tutorial", "reference_images", "collection"} - {resource_type}
    settings = shared_location_templates_settings()
    settings.patterns = {other: ("{publisher} - {title}",) for other in other_types}

    page = LocationTemplatesPage(resource_type)
    qtbot.addWidget(page)

    assert editor_of(page).values == NAME_SUGGESTION_PATTERNS


# endregion
