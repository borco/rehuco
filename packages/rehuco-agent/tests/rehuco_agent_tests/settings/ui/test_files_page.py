"""Tests for FilesPage: the Files settings category page (#226, #291, #298, #312, #313)."""

from collections.abc import Iterator
from typing import Any

from borco_pyside.widgets import StringListEditor
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import deletion_settings, excluded_files_settings
from rehuco_agent.settings.deletion_settings import (
    WITHOUT_ASKING_BOXES,
    DeletionKind,
    DeletionSettings,
    shared_deletion_settings,
)
from rehuco_agent.settings.excluded_files_settings import ExcludedFilesSettings, shared_excluded_files_settings
from rehuco_agent.settings.ui import files_page
from rehuco_agent.settings.ui.files_page import FilesPage
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
        self.__data[self.__group + key] = value  # pylint: disable=unsupported-assignment-operation

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(autouse=True)
def fake_persistent_settings(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so save/load never touch real storage.

    Patched on every module holding its own reference to it: the page itself (used by
    :meth:`FilesPage.save_changes`) and each of the two settings modules whose shared instance the
    page reads -- the excluded-file patterns and the deletion policy (#291, #298, #312).
    """
    fake = FakeSettings()
    mocker.patch.object(excluded_files_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(deletion_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(files_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Drop every process-wide instance around each test, so none inherits another's staged state."""
    shared_excluded_files_settings.cache_clear()
    shared_deletion_settings.cache_clear()
    yield
    shared_excluded_files_settings.cache_clear()
    shared_deletion_settings.cache_clear()


@fixture
def page(qtbot: QtBot) -> FilesPage:
    """A freshly-built page, seeded from the (isolated) shared settings.

    :param qtbot: pytest-qt fixture.
    :returns: the page under test.
    """
    built = FilesPage()
    qtbot.addWidget(built)
    return built


def page_ui(page: FilesPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_FilesPage`` instance.
    """
    return page._FilesPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def patterns_editor(page: FilesPage) -> StringListEditor:
    """The page's pattern list editor.

    :param page: the page to reach into.
    :returns: the `StringListEditor` holding the junk-file globs.
    """
    return page_ui(page).patterns_editor


def listed_patterns(page: FilesPage) -> tuple[str, ...]:
    """The patterns the page currently shows, in order.

    :param page: the page to read.
    :returns: every entry's text.
    """
    return patterns_editor(page).values


def recycle_bin_check_box(page: FilesPage) -> QCheckBox:
    """The page's Recycle Bin toggle.

    :param page: the page under test.
    :returns: the check box staging whether a delete goes through the Recycle Bin.
    """
    box = page.findChild(QCheckBox, "use_recycle_bin_check_box")
    assert isinstance(box, QCheckBox)
    return box


def without_asking_check_box(page: FilesPage, name: str) -> QCheckBox:
    """One of the page's two *without asking* toggles (#312).

    :param page: the page under test.
    :param name: the settings field it stages -- ``clear_backups_without_asking`` or
        ``delete_images_without_asking``.
    :returns: that check box.
    """
    box = page.findChild(QCheckBox, f"{name}_check_box")
    assert isinstance(box, QCheckBox)
    return box


# endregion

# region deleting files (#291, #298, #312)


def test_the_page_starts_on_the_saved_recycle_bin_choice(page: FilesPage) -> None:
    """A fresh page shows the shared settings' choice, on by default.

    **Test steps:**

    * build a page over settings that were never saved
    * verify the check box is checked and nothing reads as pending
    """
    assert recycle_bin_check_box(page).isChecked() is True
    assert not page.is_dirty()


def test_restores_the_saved_recycle_bin_choice(qtbot: QtBot) -> None:
    """A freshly-built page reflects what was saved.

    **Test steps:**

    * turn the setting off in the shared settings
    * build the page
    * verify the check box shows it unchecked and the page is clean
    """
    shared_deletion_settings().use_recycle_bin = False
    built = FilesPage()
    qtbot.addWidget(built)

    assert recycle_bin_check_box(built).isChecked() is False
    assert not built.is_dirty()


def test_toggling_the_recycle_bin_choice_makes_the_page_dirty(page: FilesPage) -> None:
    """Turning the Recycle Bin off is a staged change until it is applied.

    **Test steps:**

    * uncheck the Recycle Bin toggle
    * verify the page is dirty and the shared settings are untouched
    """
    recycle_bin_check_box(page).setChecked(False)

    assert page.is_dirty()
    assert shared_deletion_settings().use_recycle_bin is True


def test_save_changes_pushes_the_recycle_bin_choice_into_the_shared_settings(
    page: FilesPage, fake_persistent_settings: FakeSettings
) -> None:
    """Applying writes the staged choice into the shared settings and persists it.

    **Test steps:**

    * uncheck the Recycle Bin toggle and apply
    * verify the shared settings hold it, the page is clean, and a reload agrees
    """
    recycle_bin_check_box(page).setChecked(False)

    page.save_changes()

    assert shared_deletion_settings().use_recycle_bin is False
    assert not page.is_dirty()

    reloaded = DeletionSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.use_recycle_bin is False


def test_drop_changes_reverts_the_staged_recycle_bin_choice(page: FilesPage) -> None:
    """Resetting the page discards a staged Recycle Bin toggle along with everything else.

    **Test steps:**

    * uncheck the toggle without applying, then reset
    * verify it is back on the saved (checked) value
    """
    recycle_bin_check_box(page).setChecked(False)

    page.drop_changes()

    assert recycle_bin_check_box(page).isChecked() is True
    assert not page.is_dirty()


WITHOUT_ASKING_FIELDS = ("clear_backups_without_asking", "delete_images_without_asking")


@mark.parametrize("kind", list(DeletionKind))
def test_each_without_asking_box_is_worded_as_the_confirmations_table_says(page: FilesPage, kind: DeletionKind) -> None:
    """The permanent-delete confirmations carry this page's boxes **verbatim** (#313), and the
    wording lives in two places -- the ``.ui`` and `WITHOUT_ASKING_BOXES` -- so this is what keeps
    them from drifting.

    **Test steps:**

    * look the kind's box up in the table and on the page
    * verify the page's text is the table's label, and the table's field is the box the page stages
    """
    box = WITHOUT_ASKING_BOXES[kind]

    assert without_asking_check_box(page, box.field).text() == box.label


@mark.parametrize("field", WITHOUT_ASKING_FIELDS)
def test_the_without_asking_boxes_start_unchecked(page: FilesPage, field: str) -> None:
    """The safer, ask-first default is off for both kinds of file (#312).

    **Test steps:**

    * build a page over settings that were never saved
    * verify the box is unchecked and nothing reads as pending
    """
    assert without_asking_check_box(page, field).isChecked() is False
    assert not page.is_dirty()


@mark.parametrize("field", WITHOUT_ASKING_FIELDS)
def test_the_without_asking_boxes_are_independent_of_the_recycle_bin_choice(qtbot: QtBot, field: str) -> None:
    """Neither box depends on the Recycle Bin one: a permanent delete happens with the bin off *and*
    as the fallback with it on, and the box silences the question either way (#312).

    **Test steps:**

    * turn the Recycle Bin off in the shared settings, then build the page
    * verify the box is still enabled
    """
    shared_deletion_settings().use_recycle_bin = False
    built = FilesPage()
    qtbot.addWidget(built)

    assert without_asking_check_box(built, field).isEnabled() is True


@mark.parametrize("field", WITHOUT_ASKING_FIELDS)
def test_restores_a_saved_without_asking_choice(qtbot: QtBot, field: str) -> None:
    """A freshly-built page reflects what was saved.

    **Test steps:**

    * turn the choice on in the shared settings
    * build the page
    * verify the box shows it checked and the page is clean
    """
    setattr(shared_deletion_settings(), field, True)
    built = FilesPage()
    qtbot.addWidget(built)

    assert without_asking_check_box(built, field).isChecked() is True
    assert not built.is_dirty()


@mark.parametrize("field", WITHOUT_ASKING_FIELDS)
def test_toggling_a_without_asking_box_makes_the_page_dirty(page: FilesPage, field: str) -> None:
    """Checking it is a staged change until it is applied.

    **Test steps:**

    * check the box
    * verify the page is dirty and the shared settings are untouched
    """
    without_asking_check_box(page, field).setChecked(True)

    assert page.is_dirty()
    assert getattr(shared_deletion_settings(), field) is False


@mark.parametrize("field", WITHOUT_ASKING_FIELDS)
def test_save_changes_pushes_a_without_asking_choice_into_the_shared_settings(
    page: FilesPage, fake_persistent_settings: FakeSettings, field: str
) -> None:
    """Applying writes the staged choice into the shared settings and persists it.

    **Test steps:**

    * check the box and apply
    * verify the shared settings hold it, the page is clean, and a reload agrees
    """
    without_asking_check_box(page, field).setChecked(True)

    page.save_changes()

    assert getattr(shared_deletion_settings(), field) is True
    assert not page.is_dirty()

    reloaded = DeletionSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert getattr(reloaded, field) is True


@mark.parametrize("field", WITHOUT_ASKING_FIELDS)
def test_drop_changes_reverts_a_staged_without_asking_choice(page: FilesPage, field: str) -> None:
    """Resetting the page discards a staged toggle along with everything else.

    **Test steps:**

    * check the box without applying, then reset
    * verify it is back on the saved (unchecked) value
    """
    without_asking_check_box(page, field).setChecked(True)

    page.drop_changes()

    assert without_asking_check_box(page, field).isChecked() is False
    assert not page.is_dirty()


# endregion

# region the two exclusion tiers


def test_starts_on_the_shipped_defaults_on_a_fresh_install(page: FilesPage) -> None:
    """With nothing persisted, the list shows the patterns actually in force -- not an empty list.

    **Test steps:**

    * build the page against empty persistent storage
    * verify it lists the shipped defaults and is clean
    """
    assert listed_patterns(page) == EXCLUDED_FILE_PATTERNS
    assert page.is_dirty() is False


def test_the_structural_exclusions_are_shown_but_not_offered(page: FilesPage) -> None:
    """The structural tier is a read-only summary: never a list entry, so it cannot be removed (#226).

    Those files change at any moment, so letting a user add the ``.rehu`` back would mean recomputing
    every size and checksum after an ordinary metadata edit ([[data-model#checksums]]).

    **Test steps:**

    * build the page
    * verify the summary names the record, the screenshots, the manifest and the conversion backups,
      written from the constants
    * verify none of those shapes appears in the editable list
    """
    summary = page_ui(page).structural_patterns_label.text()
    assert "<record>.rehu — every resource record found while scanning" in summary
    assert "<record>NN with .jpg, .jpeg, .png, .gif, .webp" in summary
    assert "<record> with .checksum, .md5, .sfv, .sha1, .sha224, .sha256, .sha384, .sha512" in summary
    assert "anything ending in .orig — the backups a conversion keeps" in summary
    assert not any("rehu" in pattern or "sfv" in pattern for pattern in listed_patterns(page))


def test_the_structural_summary_is_selectable(page: FilesPage) -> None:
    """It is text the user may want to copy into a note, so it is selectable rather than inert.

    **Test steps:**

    * build the page
    * verify the summary label's interaction flags allow selecting the text by mouse
    """
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
    built = FilesPage()
    qtbot.addWidget(built)

    assert listed_patterns(built) == ("*.tmp", "Thumbs.db")
    assert built.is_dirty() is False


# endregion

# region the list editor


def test_the_editor_restores_the_shipped_patterns_not_an_empty_list(qtbot: QtBot) -> None:
    """Reset is a user who emptied the list's only way back, so it restores what the app ships (#226).

    **Test steps:**

    * seed the shared settings with one pattern of the user's own and build the page
    * fire the editor's Reset action
    * verify the shipped patterns are listed
    """
    shared_excluded_files_settings().patterns = ("*.tmp",)
    built = FilesPage()
    qtbot.addWidget(built)

    patterns_editor(built).reset_action.trigger()

    assert listed_patterns(built) == EXCLUDED_FILE_PATTERNS


def test_every_editor_action_wears_one_of_this_apps_icons(page: FilesPage) -> None:
    """The widget ships none, so a page that forgot to dress it would show eight blank buttons (#231).

    **Test steps:**

    * build the page
    * verify all eight of the editor's actions carry an icon
    """
    editor = patterns_editor(page)

    actions = (
        editor.item_actions.insert_action,
        editor.item_actions.edit_action,
        editor.item_actions.delete_action,
        editor.reset_action,
        editor.ordering_actions.move_to_top_action,
        editor.ordering_actions.move_up_action,
        editor.ordering_actions.move_down_action,
        editor.ordering_actions.move_to_bottom_action,
    )
    assert [action.icon().isNull() for action in actions] == [False] * 8


def test_editing_the_list_makes_the_page_dirty(page: FilesPage) -> None:
    """Whatever the editor holds is what Save would write, so a change to it is a change to the page.

    **Test steps:**

    * build the page and drop a pattern out of the editor
    * verify the page went dirty
    """
    patterns_editor(page).values = EXCLUDED_FILE_PATTERNS[1:]

    assert page.is_dirty() is True


def test_a_row_saving_would_drop_is_not_yet_a_change(page: FilesPage) -> None:
    """A blank insert does not make the page dirty, because applying would not change what is saved --
    and while *Apply changes as they're made* is on, the dialog commits any dirty page, which would
    tear the fresh row out from under its open cell (#53).

    **Test steps:**

    * insert a blank row and verify the page stays clean
    * fill it and verify the page is dirty exactly then
    """
    editor = patterns_editor(page)

    editor.values = (*EXCLUDED_FILE_PATTERNS, "")
    assert page.is_dirty() is False

    editor.values = (*EXCLUDED_FILE_PATTERNS, "*.part")
    assert page.is_dirty() is True


# endregion

# region save and drop


def test_save_pushes_the_staged_patterns_and_persists_them(
    page: FilesPage, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` writes the staged list into the shared settings and to storage (#226).

    **Test steps:**

    * build the page and replace every shipped pattern with one of the user's own
    * call ``save_changes``
    * verify the shared settings hold it, the page is clean, and a fresh load agrees
    """
    patterns_editor(page).values = ("*.tmp",)

    page.save_changes()

    assert shared_excluded_files_settings().excluded_file_patterns == ("*.tmp",)
    assert page.is_dirty() is False

    reloaded = ExcludedFilesSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.patterns == ("*.tmp",)


def test_saving_an_emptied_list_restores_the_defaults_on_screen(page: FilesPage) -> None:
    """Emptying the list means the shipped patterns, and the page shows that rather than a lie (#226).

    **Test steps:**

    * build the page and empty the editor
    * call ``save_changes``
    * verify the shipped defaults are both in force and back on screen, and the page is clean
    """
    patterns_editor(page).values = ()

    page.save_changes()

    assert shared_excluded_files_settings().excluded_file_patterns == EXCLUDED_FILE_PATTERNS
    assert listed_patterns(page) == EXCLUDED_FILE_PATTERNS
    assert page.is_dirty() is False


def test_saving_normalizes_blanks_and_duplicates_on_screen(qtbot: QtBot) -> None:
    """A blanked or duplicated entry is dropped on save, and the page is reloaded so it shows that.

    Normalizing is the settings object's, not the editor's -- the editor holds what was typed (#231).

    **Test steps:**

    * build the page over a pair of patterns, then stage a blank and a duplicate
    * call ``save_changes``
    * verify what was saved and what is shown are the same de-duplicated list
    """
    shared_excluded_files_settings().patterns = ("*.tmp", "Thumbs.db")
    built = FilesPage()
    qtbot.addWidget(built)
    patterns_editor(built).values = ("*.tmp", "", "*.tmp")

    built.save_changes()

    assert shared_excluded_files_settings().patterns == ("*.tmp",)
    assert listed_patterns(built) == ("*.tmp",)
    assert built.is_dirty() is False


def test_save_changes_also_persists_the_recycle_bin_choice(page: FilesPage) -> None:
    """One ``save_changes`` writes both settings objects, since they are both this page's own (#298).

    **Test steps:**

    * stage a pattern-list edit and a Recycle Bin toggle together, then apply once
    * verify both shared settings hold their staged choice
    """
    patterns_editor(page).values = ("*.tmp",)
    recycle_bin_check_box(page).setChecked(False)

    page.save_changes()

    assert shared_excluded_files_settings().excluded_file_patterns == ("*.tmp",)
    assert shared_deletion_settings().use_recycle_bin is False
    assert page.is_dirty() is False


def test_drop_changes_reverts_the_staged_list(qtbot: QtBot) -> None:
    """``drop_changes`` refills the editor from the shared settings -- a revert, not a no-op.

    **Test steps:**

    * seed the shared settings with two patterns and build the page
    * stage a different list entirely
    * call ``drop_changes``
    * verify the seeded pair is back and the page is clean
    """
    shared_excluded_files_settings().patterns = ("*.tmp", "Thumbs.db")
    built = FilesPage()
    qtbot.addWidget(built)
    patterns_editor(built).values = ("*.partial",)

    built.drop_changes()

    assert listed_patterns(built) == ("*.tmp", "Thumbs.db")
    assert built.is_dirty() is False


# endregion

# region the page shell


def test_the_wrapping_notes_are_never_clipped_at_any_width(page: FilesPage) -> None:
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
    ui = page_ui(page)
    page.show()

    first_seen: dict[int, tuple[int, ...]] = {}
    for width in (320, 900, 420, 640, 320, 900):
        page.setGeometry(0, 0, width, 700)
        ui.main_layout.activate()
        for label in (ui.structural_note_label, ui.patterns_note_label):
            assert label.height() >= label.heightForWidth(label.width()), (
                f"{label.objectName()} clipped at page width {width}"
            )
        heights = (ui.structural_note_label.height(), ui.patterns_note_label.height())
        assert first_seen.setdefault(width, heights) == heights, f"heights ratcheted at page width {width}"


def test_frame_filter_discovers_all_three_frames_independently(page: FilesPage) -> None:
    """The three blocks are separate top-level frames, so each filters on its own text (#67).

    Guards the page's ``.ui`` frame structure: searching for one block must not drag the other two
    along with it.

    **Test steps:**

    * build a frame filter over the page
    * filter by the deletion header and verify only that frame stays shown
    * filter by the patterns header and verify only that frame stays shown
    * filter by the structural header and verify only that frame stays shown
    * filter by a non-matching term and verify all three hide
    """
    frame_filter = SettingsFrameFilter(page, "Files")
    ui = page_ui(page)

    frame_filter.apply("deleting files", show_full_on_title_match=False)
    assert ui.deletion_frame.isVisibleTo(page) is True
    assert ui.patterns_frame.isVisibleTo(page) is False
    assert ui.structural_frame.isVisibleTo(page) is False

    frame_filter.apply("excluded file patterns", show_full_on_title_match=False)
    assert ui.patterns_frame.isVisibleTo(page) is True
    assert ui.deletion_frame.isVisibleTo(page) is False
    assert ui.structural_frame.isVisibleTo(page) is False

    frame_filter.apply("always excluded", show_full_on_title_match=False)
    assert ui.structural_frame.isVisibleTo(page) is True
    assert ui.deletion_frame.isVisibleTo(page) is False
    assert ui.patterns_frame.isVisibleTo(page) is False

    frame_filter.apply("no-such-term", show_full_on_title_match=False)
    assert ui.deletion_frame.isVisibleTo(page) is False
    assert ui.patterns_frame.isVisibleTo(page) is False
    assert ui.structural_frame.isVisibleTo(page) is False


# endregion
