"""Tests for ScrapersTableModel: the Scrapers page's table, with its checkable Use browser column
(#269, #278)."""

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor
from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.colors import ERROR_COLOR, WARNING_COLOR
from rehuco_agent.scraping.registry import ScraperRow
from rehuco_agent.scraping.role_report import RoleState
from rehuco_agent.settings.ui.scrapers_table_model import (
    COLUMN_COUNT,
    COLUMN_TITLES,
    ERROR_COLUMN,
    NO_SCRAPERS_TEXT,
    ROLE_ICON_ROLE,
    ROLE_ICONS,
    ROLE_TOOLTIPS,
    SCRAPER_NAME_COLUMN,
    SCRAPER_ROLE_COLUMN,
    SOURCE_COLUMN,
    USE_BROWSER_COLUMN,
    WIZARD_ROLE_COLUMN,
    ScrapersTableModel,
)

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

SCRAPER_ROW = ScraperRow(
    key="rehuco_user_scrapers.art_scraper.ArtScraper",
    label="ArtStation",
    publisher="ArtStation Inc",
    site_name="ArtStation",
    site_url="https://www.artstation.com",
    source="art_scraper.py",
    needs_browser=False,
    error=None,
)
SAME_LABEL_AND_PUBLISHER_ROW = ScraperRow(
    key="rehuco_user_scrapers.udemy_scraper.Udemy",
    label="Udemy",
    publisher="Udemy",
    site_name="Udemy",
    site_url="https://www.udemy.com",
    source="udemy_scraper.py",
    needs_browser=False,
    error=None,
)
NEEDS_BROWSER_ROW = ScraperRow(
    key="rehuco_user_scrapers.gated_scraper.Gated",
    label="Gated",
    publisher="Gated Inc",
    site_name="Gated",
    site_url="https://gated.example.com",
    source="gated_scraper.py",
    needs_browser=True,
    error=None,
)
EMPTY_ROW = ScraperRow(
    key=None, label="", publisher="", site_name="", site_url="", source="helpers.py", needs_browser=False, error=None
)
BROKEN_ROW = ScraperRow(
    key=None,
    label="",
    publisher="",
    site_name="",
    site_url="",
    source="broken.py",
    needs_browser=False,
    error="SyntaxError: bad",
)


@fixture
def model(qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> ScrapersTableModel:
    """A model holding one scraper, one browser-only scraper, one empty row, one broken row, and one
    scraper whose label and publisher are the same word."""
    del qtbot
    built = delete_at_teardown(ScrapersTableModel())
    built.set_rows((SCRAPER_ROW, NEEDS_BROWSER_ROW, EMPTY_ROW, BROKEN_ROW, SAME_LABEL_AND_PUBLISHER_ROW))
    return built


def test_set_rows_resets_to_the_new_rows(qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> None:
    """Replacing the rows is one model reset carrying the new count (#269).

    **Test steps:**

    * build an empty model and verify it has no rows and the fixed column count
    * set four rows inside a reset and verify the count
    """
    built = delete_at_teardown(ScrapersTableModel())
    assert built.rowCount() == 0
    assert built.columnCount() == COLUMN_COUNT

    with qtbot.waitSignal(built.modelReset):
        built.set_rows((SCRAPER_ROW, NEEDS_BROWSER_ROW, EMPTY_ROW, BROKEN_ROW))

    assert built.rowCount() == 4
    assert built.rowCount(built.index(0, 0)) == 0
    assert built.columnCount(built.index(0, 0)) == 0


def test_headers_are_the_column_titles_and_nothing_else(model: ScrapersTableModel) -> None:
    """Horizontal display headers read the titles; anything else is `None` (#269).

    **Test steps:**

    * read every horizontal header, a vertical one, a non-display role and an out-of-range section
    """
    horizontal = Qt.Orientation.Horizontal
    assert [model.headerData(column, horizontal) for column in range(COLUMN_COUNT)] == list(COLUMN_TITLES)
    assert model.headerData(0, Qt.Orientation.Vertical) is None
    assert model.headerData(0, horizontal, Qt.ItemDataRole.ToolTipRole) is None
    assert model.headerData(COLUMN_COUNT, horizontal) is None


def test_cells_show_the_scraper_the_source_and_the_error(model: ScrapersTableModel) -> None:
    """Each column reads its own fact off the row (#269, #278).

    **Test steps:**

    * read the Scraper/Source/Error columns of a scraper row, the empty row and the broken row
    """

    def cell(row: int, column: int) -> object:
        return model.data(model.index(row, column))

    assert cell(0, SCRAPER_NAME_COLUMN) == "ArtStation"
    assert cell(0, SOURCE_COLUMN) == "art_scraper.py"
    assert cell(0, ERROR_COLUMN) == ""
    assert cell(2, SCRAPER_NAME_COLUMN) == NO_SCRAPERS_TEXT
    assert cell(3, ERROR_COLUMN) == "SyntaxError: bad"


def test_a_scraper_naming_itself_as_its_own_publisher_shows_just_the_label(model: ScrapersTableModel) -> None:
    """A scraper whose `publisher` repeats its `label` (Udemy names both the same) shows plainly --
    ``"Udemy"``, not the redundant ``"Udemy (Udemy)"`` (#278).

    **Test steps:**

    * read the Scraper column of a row whose label and publisher are the same word
    """
    assert model.data(model.index(4, SCRAPER_NAME_COLUMN)) == "Udemy"


def test_only_an_error_cell_is_tinted(model: ScrapersTableModel) -> None:
    """The error column of a broken row is drawn in the error color; every other cell, and every other
    role, answers nothing (#269).

    **Test steps:**

    * read the foreground of the broken row's error cell, a clean row's error cell and another column
    * read an unrelated role and an invalid index
    """
    foreground = Qt.ItemDataRole.ForegroundRole
    assert model.data(model.index(3, ERROR_COLUMN), foreground) == QBrush(QColor(ERROR_COLOR))
    assert model.data(model.index(0, ERROR_COLUMN), foreground) is None
    assert model.data(model.index(3, SCRAPER_NAME_COLUMN), foreground) is None
    assert model.data(model.index(0, SCRAPER_NAME_COLUMN), Qt.ItemDataRole.ToolTipRole) is None
    assert model.data(QModelIndex()) is None


def test_the_error_cell_carries_its_full_message_as_a_tooltip(model: ScrapersTableModel) -> None:
    """The Error column is nowhere near wide enough for a real import error, and the row delegate
    elides what it draws -- the tooltip is where the whole message lives (#278).

    **Test steps:**

    * read the tooltip of the broken row's error cell and of a clean row's
    """
    tooltip = Qt.ItemDataRole.ToolTipRole
    assert model.data(model.index(3, ERROR_COLUMN), tooltip) == "SyntaxError: bad"
    assert model.data(model.index(0, ERROR_COLUMN), tooltip) is None


def test_the_use_browser_column_carries_no_text_alignment_role(model: ScrapersTableModel) -> None:
    """Centering the checkbox is the row delegate's own job now
    (`~rehuco_agent.settings.ui.scrapers_checkbox_delegate.ScrapersCheckboxDelegate`, which paints it directly via
    `QStyle.drawPrimitive` at a manually-computed centered rect), not something the base delegate reads
    off a `Qt.ItemDataRole.TextAlignmentRole` -- so the model answers that role for neither column
    (#278).

    **Test steps:**

    * read the text-alignment role of a Use browser cell and a text cell
    * verify neither carries one
    """
    assert model.data(model.index(0, USE_BROWSER_COLUMN), Qt.ItemDataRole.TextAlignmentRole) is None
    assert model.data(model.index(0, SCRAPER_NAME_COLUMN), Qt.ItemDataRole.TextAlignmentRole) is None


def test_a_needs_browser_scraper_is_checked_and_disabled(model: ScrapersTableModel) -> None:
    """A `ScraperRow.needs_browser` scraper's checkbox reads checked, and cannot be unchecked (#278).

    **Test steps:**

    * read the check state and flags of the browser-only row's Use browser cell
    """
    index = model.index(1, USE_BROWSER_COLUMN)
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    flags = model.flags(index)
    assert flags & Qt.ItemFlag.ItemIsUserCheckable
    assert not flags & Qt.ItemFlag.ItemIsEnabled


def test_an_optional_scraper_starts_unchecked_and_toggles(model: ScrapersTableModel) -> None:
    """A scraper that does not need the browser starts unchecked, and ticking it stages the key (#278).

    **Test steps:**

    * read the initial check state and flags of the plain row's Use browser cell
    * tick it via setData
    * verify the staged set and the check state
    """
    index = model.index(0, USE_BROWSER_COLUMN)
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked
    flags = model.flags(index)
    assert flags & Qt.ItemFlag.ItemIsUserCheckable
    assert flags & Qt.ItemFlag.ItemIsEnabled

    assert model.setData(index, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole) is True

    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert model.browser_scrapers() == {SCRAPER_ROW.key}


def test_unchecking_a_staged_scraper_removes_it(model: ScrapersTableModel) -> None:
    """Unticking a previously-ticked optional scraper removes it from the staged set (#278).

    **Test steps:**

    * set the staged set to hold the plain scraper's key
    * untick its cell
    * verify the staged set no longer holds it
    """
    assert model.setData(
        model.index(0, USE_BROWSER_COLUMN), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole
    )

    assert model.setData(
        model.index(0, USE_BROWSER_COLUMN), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole
    )

    assert model.browser_scrapers() == frozenset()


def test_a_needs_browser_checkbox_cannot_be_unchecked_through_setdata(model: ScrapersTableModel) -> None:
    """Forcing `setData` on a `needs_browser` row's checkbox is refused (#278).

    **Test steps:**

    * try to uncheck the browser-only row's cell
    * verify it is refused and the check state is unchanged
    """
    index = model.index(1, USE_BROWSER_COLUMN)

    assert model.setData(index, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole) is False

    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked


def test_a_row_with_no_scraper_has_no_checkbox(model: ScrapersTableModel) -> None:
    """An empty or broken row's Use browser cell is not checkable, and answers no check state (#278).

    **Test steps:**

    * read the flags and check state of the empty and broken rows' Use browser cells
    """
    for row in (2, 3):
        index = model.index(row, USE_BROWSER_COLUMN)
        assert not model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable
        assert model.data(index, Qt.ItemDataRole.CheckStateRole) is None
        assert model.setData(index, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole) is False


def test_flags_for_other_columns_are_left_alone(model: ScrapersTableModel) -> None:
    """Every column but Use browser gets the base flags, untouched -- never checkable, regardless of
    the row's `needs_browser` or `key` (#278).

    **Test steps:**

    * read the flags of a Scraper-column cell
    * verify it is not checkable
    """
    index = model.index(0, SCRAPER_NAME_COLUMN)

    assert not model.flags(index) & Qt.ItemFlag.ItemIsUserCheckable


def test_setdata_outside_the_use_browser_column_or_wrong_role_is_refused(model: ScrapersTableModel) -> None:
    """`setData` is refused for any column but Use browser, and for any role but `CheckStateRole`,
    before it ever looks at the row itself (#278).

    **Test steps:**

    * try `setData` on a Scraper-column cell with `CheckStateRole`
    * try `setData` on the Use browser cell with `EditRole`
    * verify both are refused
    """
    wrong_column = model.index(0, SCRAPER_NAME_COLUMN)
    assert model.setData(wrong_column, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole) is False

    wrong_role = model.index(0, USE_BROWSER_COLUMN)
    assert model.setData(wrong_role, Qt.CheckState.Checked.value, Qt.ItemDataRole.EditRole) is False


def test_set_rows_keeps_the_staged_browser_scrapers(model: ScrapersTableModel) -> None:
    """A Reload's `set_rows` does not discard an unsaved tick (#278).

    **Test steps:**

    * tick the plain scraper
    * replace the rows
    * verify the staged set still holds it
    """
    model.setData(model.index(0, USE_BROWSER_COLUMN), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)

    model.set_rows((SCRAPER_ROW, NEEDS_BROWSER_ROW, EMPTY_ROW, BROKEN_ROW))

    assert SCRAPER_ROW.key in model.browser_scrapers()


def test_set_browser_scrapers_replaces_the_staged_set(model: ScrapersTableModel) -> None:
    """`set_browser_scrapers` replaces the staged set wholesale, e.g. from saved settings (#278).

    **Test steps:**

    * stage the plain scraper via setData
    * call ``set_browser_scrapers`` with an empty set
    * verify it is no longer ticked
    """
    model.setData(model.index(0, USE_BROWSER_COLUMN), Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)

    model.set_browser_scrapers(frozenset())

    assert model.browser_scrapers() == frozenset()


# region Roles, warnings and notes (#683)

BOTH_ROLES_ROW = ScraperRow(
    key="rehuco_user_scrapers.shop.Shop",
    label="Shop",
    publisher="Shop",
    site_name="Shop",
    site_url="https://shop.example.com",
    source="shop.py",
    needs_browser=False,
    error=None,
    scraper=RoleState.OK,
    wizard=RoleState.ERROR,
)
WIZARD_ONLY_ROW = ScraperRow(
    key=None,
    label="",
    publisher="",
    site_name="Built-in Shop",
    site_url="",
    source="Built-in",
    needs_browser=False,
    error=None,
    wizard=RoleState.OVERRIDDEN_OK,
    note="Replaced by the one in shop.py",
)
NOTHING_ROW = ScraperRow(
    key=None,
    label="",
    publisher="",
    site_name="",
    site_url="",
    source="helpers.py",
    needs_browser=False,
    error=None,
    warning="Declares neither a scraper nor a scraper wizard.",
)


@fixture
def roles_model(qtbot: QtBot, delete_at_teardown: DeleteAtTeardown) -> ScrapersTableModel:
    """A model holding a class in both roles, a replaced wizard and a file that declares nothing."""
    del qtbot
    built = delete_at_teardown(ScrapersTableModel())
    built.set_rows((BOTH_ROLES_ROW, WIZARD_ONLY_ROW, NOTHING_ROW))
    return built


def test_a_role_cell_carries_the_glyph_of_how_the_class_fares(roles_model: ScrapersTableModel) -> None:
    """The Scraper and Wizard cells name the glyph of the class's state in that role, say it in a tooltip and show
    no text; a role the class does not declare, and every other column, has no glyph (#683).

    **Test steps:**

    * read the glyph, the tooltip and the text of both role cells of a class working as a scraper and broken as a
      wizard
    * read the glyphs of a wizard-only row and of a file's own row, and of a column of no role
    """

    def glyph(row: int, column: int) -> object:
        return roles_model.data(roles_model.index(row, column), ROLE_ICON_ROLE)

    tooltip = Qt.ItemDataRole.ToolTipRole
    assert glyph(0, SCRAPER_ROLE_COLUMN) == ROLE_ICONS[RoleState.OK]
    assert glyph(0, WIZARD_ROLE_COLUMN) == ROLE_ICONS[RoleState.ERROR]
    assert roles_model.data(roles_model.index(0, SCRAPER_ROLE_COLUMN), tooltip) == ROLE_TOOLTIPS[RoleState.OK]
    assert roles_model.data(roles_model.index(0, WIZARD_ROLE_COLUMN), tooltip) == ROLE_TOOLTIPS[RoleState.ERROR]
    assert roles_model.data(roles_model.index(0, SCRAPER_ROLE_COLUMN)) == ""
    assert glyph(1, SCRAPER_ROLE_COLUMN) is None
    assert glyph(1, WIZARD_ROLE_COLUMN) == ROLE_ICONS[RoleState.OVERRIDDEN_OK]
    assert glyph(2, SCRAPER_ROLE_COLUMN) is None
    assert glyph(2, WIZARD_ROLE_COLUMN) is None
    assert glyph(0, SOURCE_COLUMN) is None
    assert roles_model.data(roles_model.index(1, SCRAPER_ROLE_COLUMN), tooltip) is None


def test_every_role_state_has_a_glyph_and_a_tooltip() -> None:
    """No state is left without its glyph or its words (#683).

    **Test steps:**

    * verify both maps hold every state, each glyph a resource of its own
    """
    assert set(ROLE_ICONS) == set(RoleState) == set(ROLE_TOOLTIPS)
    assert len(set(ROLE_ICONS.values())) == len(RoleState)
    assert all(path.startswith(":/icons/module_") for path in ROLE_ICONS.values())


def test_the_error_column_says_a_warning_in_its_color_and_a_note_in_none(roles_model: ScrapersTableModel) -> None:
    """A file that declares nothing reads its warning in the warning color; what replaced a class is a note in the
    plain text color; both are whole in the tooltip (#683).

    **Test steps:**

    * read the text, the foreground and the tooltip of the Error cell of the file's row and of the replaced wizard's
    """
    foreground, tooltip = Qt.ItemDataRole.ForegroundRole, Qt.ItemDataRole.ToolTipRole
    warned, noted = roles_model.index(2, ERROR_COLUMN), roles_model.index(1, ERROR_COLUMN)

    assert roles_model.data(warned) == NOTHING_ROW.warning
    assert roles_model.data(warned, foreground) == QBrush(QColor(WARNING_COLOR))
    assert roles_model.data(warned, tooltip) == NOTHING_ROW.warning
    assert roles_model.data(noted) == WIZARD_ONLY_ROW.note
    assert roles_model.data(noted, foreground) is None
    assert roles_model.data(noted, tooltip) == WIZARD_ONLY_ROW.note


def test_a_row_with_no_working_scraper_is_named_and_has_no_checkbox(roles_model: ScrapersTableModel) -> None:
    """A wizard-only row shows its name, where a file's own row shows the dash, and offers no Use browser tick
    (#683).

    **Test steps:**

    * read the Name cell of the wizard-only row and of the file's row
    * read the wizard-only row's Use browser check state
    """
    assert roles_model.data(roles_model.index(1, SCRAPER_NAME_COLUMN)) == "Built-in Shop"
    assert roles_model.data(roles_model.index(2, SCRAPER_NAME_COLUMN)) == NO_SCRAPERS_TEXT
    assert roles_model.data(roles_model.index(1, USE_BROWSER_COLUMN), Qt.ItemDataRole.CheckStateRole) is None


# endregion
