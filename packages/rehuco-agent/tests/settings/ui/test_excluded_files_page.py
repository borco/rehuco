"""Tests for ExcludedFilesPage: the Excluded Files settings category page (#226)."""

from collections.abc import Iterator
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/...
from rehuco_agent.settings import excluded_files_settings
from rehuco_agent.settings.excluded_files_settings import ExcludedFilesSettings, shared_excluded_files_settings
from rehuco_agent.settings.ui import excluded_files_page
from rehuco_agent.settings.ui.excluded_files_page import ExcludedFilesPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_core import EXCLUDED_FILE_PATTERNS


# region fixtures
# Mirrors test_reference_images_page.py's (and conftest.py's) FakeSettings exactly -- kept as a separate
# copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_excluded_files_settings.py`` for the full rationale)."""

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

    Patched on both modules that imported their own reference to it: the shared settings module
    (used by :func:`shared_excluded_files_settings`'s lazy load) and the page module itself (used by
    :meth:`ExcludedFilesPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(excluded_files_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(excluded_files_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the shared settings singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_excluded_files_settings.cache_clear()
    yield
    shared_excluded_files_settings.cache_clear()


def page_ui(page: ExcludedFilesPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_ExcludedFilesPage`` instance.
    """
    return page._ExcludedFilesPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def listed_patterns(page: ExcludedFilesPage) -> list[str]:
    """The patterns the page currently shows, in order.

    :param page: the page to read.
    :returns: every row's text.
    """
    widget = page_ui(page).patterns_list
    return [widget.item(row).text() for row in range(widget.count())]


# endregion

# region the two tiers


def test_starts_on_the_shipped_defaults_on_a_fresh_install(qtbot: QtBot) -> None:
    """With nothing persisted, the list shows the patterns actually in force -- not an empty list.

    **Test steps:**

    * build the page against empty persistent storage
    * verify it lists the shipped defaults and is clean
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    assert listed_patterns(page) == list(EXCLUDED_FILE_PATTERNS)
    assert page.is_dirty() is False


def test_the_structural_exclusions_are_shown_but_not_offered(qtbot: QtBot) -> None:
    """The structural tier is a read-only summary: never a list entry, so it cannot be removed (#226).

    Those files change at any moment, so letting a user add the ``.rehu`` back would mean recomputing
    every size and checksum after an ordinary metadata edit ([[data-model#checksums]]).

    **Test steps:**

    * build the page
    * verify the summary names the record, the screenshots and the manifest, written from the constants
    * verify none of those shapes appears in the editable list
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    summary = page_ui(page).structural_patterns_label.text()
    assert "<record>.rehu — every resource record found while scanning" in summary
    assert "<record>NN with .jpg, .jpeg, .png, .gif, .webp" in summary
    assert "<record> with .sfv, .md5, .sha256" in summary
    assert not any("rehu" in pattern or "sfv" in pattern for pattern in listed_patterns(page))


def test_the_structural_summary_is_selectable(qtbot: QtBot) -> None:
    """It is text the user may want to copy into a note, so it is selectable rather than inert.

    **Test steps:**

    * build the page
    * verify the summary label's interaction flags allow selecting the text by mouse
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    label = page_ui(page).structural_patterns_label
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_restores_the_saved_patterns(qtbot: QtBot) -> None:
    """A freshly-built page reflects what was saved, in order.

    **Test steps:**

    * seed the shared settings with two patterns of the user's own
    * build the page
    * verify it lists exactly those two and is clean
    """
    shared_excluded_files_settings().patterns = ("*.tmp", "Thumbs.db")
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    assert listed_patterns(page) == ["*.tmp", "Thumbs.db"]
    assert page.is_dirty() is False


# endregion

# region add, edit, remove


def test_add_appends_the_typed_pattern_and_clears_the_field(qtbot: QtBot) -> None:
    """Add takes the typed pattern, appends it, and leaves the field ready for the next one.

    **Test steps:**

    * build the page, type ``*.tmp`` and click Add
    * verify the pattern was appended, the field is empty, and the page is dirty
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.new_pattern_edit.setText("*.tmp")

    ui.add_button.click()

    assert listed_patterns(page) == [*EXCLUDED_FILE_PATTERNS, "*.tmp"]
    assert ui.new_pattern_edit.text() == ""
    assert page.is_dirty() is True


def test_pressing_enter_in_the_field_adds_the_pattern(qtbot: QtBot) -> None:
    """Typing and pressing Enter is the same gesture as clicking Add.

    **Test steps:**

    * build the page, type ``*.tmp`` into the field and press Enter
    * verify the pattern was appended
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.new_pattern_edit.setText("*.tmp")

    ui.new_pattern_edit.returnPressed.emit()

    assert listed_patterns(page) == [*EXCLUDED_FILE_PATTERNS, "*.tmp"]


def test_pressing_enter_with_nothing_typed_adds_nothing(qtbot: QtBot) -> None:
    """Enter in an empty field is a gesture the field cannot refuse, so Add itself has to.

    **Test steps:**

    * build the page and press Enter with the field blank
    * verify the list is unchanged and the page is still clean
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    page_ui(page).new_pattern_edit.returnPressed.emit()

    assert listed_patterns(page) == list(EXCLUDED_FILE_PATTERNS)
    assert page.is_dirty() is False


def test_add_is_disabled_for_a_blank_or_duplicate_pattern(qtbot: QtBot) -> None:
    """Nothing to add, or already listed under some casing, means the button is off.

    **Test steps:**

    * build the page and verify Add is disabled with the field empty
    * type whitespace, then an existing pattern in another casing, and verify it stays disabled
    * type a new pattern and verify it enables
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.add_button.isEnabled() is False

    ui.new_pattern_edit.setText("   ")
    assert ui.add_button.isEnabled() is False

    ui.new_pattern_edit.setText("THUMBS.DB")
    assert ui.add_button.isEnabled() is False

    ui.new_pattern_edit.setText("*.tmp")
    assert ui.add_button.isEnabled() is True


def test_remove_drops_the_selected_pattern(qtbot: QtBot) -> None:
    """Remove takes out the selected row and nothing else.

    **Test steps:**

    * build the page and select the first row
    * click Remove
    * verify that pattern is gone and the rest are untouched
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.patterns_list.setCurrentRow(0)

    ui.remove_button.click()

    assert listed_patterns(page) == list(EXCLUDED_FILE_PATTERNS[1:])


def test_edit_opens_the_selected_row_for_editing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Edit starts the same in-place edit a double-click does, on the selected row.

    **Test steps:**

    * build the page, select the second row and spy on the list's ``editItem``
    * click Edit
    * verify the selected item was the one handed to ``editItem``
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.patterns_list.setCurrentRow(1)
    edit_item = mocker.patch.object(QListWidget, "editItem")

    ui.edit_button.click()

    edit_item.assert_called_once_with(ui.patterns_list.item(1))


def test_edit_and_remove_do_nothing_without_a_selection(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Both act on a selected row, so a click arriving without one is a no-op rather than a crash.

    **Test steps:**

    * build the page and clear the selection
    * fire both actions' ``triggered`` signals directly, past their disabled state
    * verify no edit was started and the list is unchanged
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.patterns_list.setCurrentRow(-1)
    edit_item = mocker.patch.object(QListWidget, "editItem")

    ui.edit_button.defaultAction().triggered.emit()
    ui.remove_button.defaultAction().triggered.emit()

    edit_item.assert_not_called()
    assert listed_patterns(page) == list(EXCLUDED_FILE_PATTERNS)


def test_edit_and_remove_are_disabled_without_a_selection(qtbot: QtBot) -> None:
    """Both act on the selected row, so both are off until there is one.

    **Test steps:**

    * build the page and verify Edit and Remove start disabled
    * select a row and verify both enable
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    assert ui.edit_button.isEnabled() is False
    assert ui.remove_button.isEnabled() is False

    ui.patterns_list.setCurrentRow(0)

    assert ui.edit_button.isEnabled() is True
    assert ui.remove_button.isEnabled() is True


def test_patterns_are_editable_in_place(qtbot: QtBot) -> None:
    """Editing is retyping a row, so every row carries the editable flag a double-click needs.

    **Test steps:**

    * build the page
    * verify every row is flagged editable
    * retype the first row and verify the page went dirty
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    widget = page_ui(page).patterns_list

    assert all(widget.item(row).flags() & Qt.ItemFlag.ItemIsEditable for row in range(widget.count()))

    widget.item(0).setText("*.partial")

    assert listed_patterns(page)[0] == "*.partial"
    assert page.is_dirty() is True


def test_restore_defaults_brings_the_shipped_list_back(qtbot: QtBot) -> None:
    """A user who emptied the list has no other way back, so the button is the way (#226).

    **Test steps:**

    * seed the shared settings with one pattern of the user's own and build the page
    * click Restore Defaults
    * verify the shipped patterns are listed
    """
    shared_excluded_files_settings().patterns = ("*.tmp",)
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    page_ui(page).restore_defaults_button.click()

    assert listed_patterns(page) == list(EXCLUDED_FILE_PATTERNS)


# endregion

# region save and drop


def test_save_pushes_the_staged_patterns_and_persists_them(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` writes the staged list into the shared settings and to storage (#226).

    **Test steps:**

    * build the page, remove every shipped pattern and add one of the user's own
    * call ``save_changes``
    * verify the shared settings hold it, the page is clean, and a fresh load agrees
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.patterns_list.clear()
    ui.new_pattern_edit.setText("*.tmp")
    ui.add_button.click()

    page.save_changes()

    assert shared_excluded_files_settings().excluded_file_patterns == ("*.tmp",)
    assert page.is_dirty() is False

    reloaded = ExcludedFilesSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.patterns == ("*.tmp",)


def test_saving_an_emptied_list_restores_the_defaults_on_screen(qtbot: QtBot) -> None:
    """Emptying the list means the shipped patterns, and the page shows that rather than a lie (#226).

    **Test steps:**

    * build the page and clear every row
    * call ``save_changes``
    * verify the shipped defaults are both in force and back on screen, and the page is clean
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    page_ui(page).patterns_list.clear()

    page.save_changes()

    assert shared_excluded_files_settings().excluded_file_patterns == EXCLUDED_FILE_PATTERNS
    assert listed_patterns(page) == list(EXCLUDED_FILE_PATTERNS)
    assert page.is_dirty() is False


def test_saving_normalizes_blanks_and_duplicates_on_screen(qtbot: QtBot) -> None:
    """A blanked or duplicated row is dropped on save, and the page is reloaded so it shows that.

    **Test steps:**

    * build the page over a single pattern, blank one row and duplicate another
    * call ``save_changes``
    * verify what was saved and what is shown are the same de-duplicated list
    """
    shared_excluded_files_settings().patterns = ("*.tmp", "Thumbs.db")
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    widget = page_ui(page).patterns_list
    widget.item(1).setText("")
    widget.addItem("*.tmp")

    page.save_changes()

    assert shared_excluded_files_settings().patterns == ("*.tmp",)
    assert listed_patterns(page) == ["*.tmp"]
    assert page.is_dirty() is False


def test_drop_changes_reverts_the_staged_list(qtbot: QtBot) -> None:
    """``drop_changes`` refills the list from the shared settings -- a revert, not a no-op.

    **Test steps:**

    * seed the shared settings with two patterns and build the page
    * remove one, add another, and type into the entry field
    * call ``drop_changes``
    * verify the seeded pair is back, the field is empty, and the page is clean
    """
    shared_excluded_files_settings().patterns = ("*.tmp", "Thumbs.db")
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.patterns_list.takeItem(0)
    ui.new_pattern_edit.setText("*.partial")
    ui.add_button.click()
    ui.new_pattern_edit.setText("half-typed")

    page.drop_changes()

    assert listed_patterns(page) == ["*.tmp", "Thumbs.db"]
    assert ui.new_pattern_edit.text() == ""
    assert page.is_dirty() is False


# endregion

# region the page shell


def test_title_is_excluded_files(qtbot: QtBot) -> None:
    """The page's category-tree title is "Excluded Files".

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    assert page.title == "Excluded Files"


def test_the_wrapping_notes_are_never_clipped_at_any_width(qtbot: QtBot) -> None:
    """Each note gets the height its text needs at the width it is given, and gives it back on widening.

    Guards the defect this page shipped with: the frames were sized from a ``sizeHint`` computed as
    though a wrapping label were one wide line, so the note painted past its frame's border. The notes
    are `WrappingLabel`s now and the page computes nothing (#229). Giving the height *back* is asserted
    too, not just never-clipped: `WrappingLabel` measures its own width -- the very move #229 warns
    ratchets a hand-declared height upward forever -- and a ratcheted label is too tall, which
    never-clipped alone would wave through. So a revisited width must reproduce its first visit's
    heights exactly.

    **Test steps:**

    * build the page and resize it through a range of widths, narrow and wide, then back
    * verify at every step that each note is at least as tall as its text needs
    * verify a width seen before gets exactly the heights it got the first time
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    page.show()

    first_seen: dict[int, tuple[int, ...]] = {}
    for width in (320, 900, 420, 640, 320, 900):
        page.setGeometry(0, 0, width, 700)
        page_ui(page).main_layout.activate()
        for label in (ui.structural_note_label, ui.patterns_note_label):
            assert label.height() >= label.heightForWidth(label.width()), (
                f"{label.objectName()} clipped at page width {width}"
            )
        heights = (ui.structural_note_label.height(), ui.patterns_note_label.height())
        assert first_seen.setdefault(width, heights) == heights, f"heights ratcheted at page width {width}"


def test_the_pattern_list_grows_with_its_rows_instead_of_scrolling_them(qtbot: QtBot) -> None:
    """The list is sized to its patterns, so the page scrolls rather than the list inside it (#229).

    A list that scrolls inside a page that scrolls is two vertical scrollbars, and a list the user has
    to scroll *to* before they can scroll *in*.

    **Test steps:**

    * build the page and add twenty patterns to its list
    * verify the list asked for more height and never grew a scrollbar of its own
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    listing = page_ui(page).patterns_list
    before = listing.sizeHint().height()

    for index in range(20):
        listing.addItem(f"*.extra{index}")

    assert listing.sizeHint().height() > before
    assert listing.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_the_pattern_list_stays_at_the_top_of_its_frame_however_short_it_is(qtbot: QtBot) -> None:
    """A short list sits under its title, not floating in the middle of the frame (#229).

    The list is sized to its rows, so it is shorter than the button column it shares its grid span
    with -- and a layout centres a short item in its span unless told otherwise.

    **Test steps:**

    * show the page, then empty the list and refill it
    * verify its top edge lines up with the first tool button's at both lengths
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    page.resize(600, 700)
    page.show()

    for patterns in ((), ("*.tmp", "*.bak", "*.log")):
        ui.patterns_list.clear()
        ui.patterns_list.addItems(patterns)
        ui.main_layout.activate()
        assert ui.patterns_list.geometry().top() == ui.edit_button.geometry().top(), (
            f"list not top-aligned with {len(patterns)} patterns"
        )


def test_frame_filter_discovers_both_frames_independently(qtbot: QtBot) -> None:
    """The two tiers are separate top-level frames, so each filters on its own text (#67).

    Guards the page's ``.ui`` frame structure: searching for the editable list must not drag the
    read-only structural summary along with it.

    **Test steps:**

    * build a frame filter over the page
    * filter by the patterns header and verify only that frame stays shown
    * filter by the structural header and verify the other one shows instead
    * filter by a non-matching term and verify both hide
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, page.title)
    ui = page_ui(page)

    frame_filter.apply("excluded file patterns", show_full_on_title_match=False)
    assert ui.patterns_frame.isVisibleTo(page) is True
    assert ui.structural_frame.isVisibleTo(page) is False

    frame_filter.apply("always excluded", show_full_on_title_match=False)
    assert ui.structural_frame.isVisibleTo(page) is True
    assert ui.patterns_frame.isVisibleTo(page) is False

    frame_filter.apply("no-such-term", show_full_on_title_match=False)
    assert ui.patterns_frame.isVisibleTo(page) is False
    assert ui.structural_frame.isVisibleTo(page) is False


# endregion
