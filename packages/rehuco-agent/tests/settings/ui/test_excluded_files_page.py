"""Tests for ExcludedFilesPage: the Excluded Files settings category page (#226)."""

from collections.abc import Iterator
from typing import Any

from borco_pyside.widgets import StringListEditor
from PySide6.QtCore import Qt
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
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


def patterns_editor(page: ExcludedFilesPage) -> StringListEditor:
    """The page's pattern list editor.

    :param page: the page to reach into.
    :returns: the `StringListEditor` holding the junk-file globs.
    """
    return page_ui(page).patterns_editor


def listed_patterns(page: ExcludedFilesPage) -> tuple[str, ...]:
    """The patterns the page currently shows, in order.

    :param page: the page to read.
    :returns: every entry's text.
    """
    return patterns_editor(page).values


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

    assert listed_patterns(page) == EXCLUDED_FILE_PATTERNS
    assert page.is_dirty() is False


def test_the_structural_exclusions_are_shown_but_not_offered(qtbot: QtBot) -> None:
    """The structural tier is a read-only summary: never a list entry, so it cannot be removed (#226).

    Those files change at any moment, so letting a user add the ``.rehu`` back would mean recomputing
    every size and checksum after an ordinary metadata edit ([[data-model#checksums]]).

    **Test steps:**

    * build the page
    * verify the summary names the record, the screenshots, the manifest and the conversion backups,
      written from the constants
    * verify none of those shapes appears in the editable list
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    summary = page_ui(page).structural_patterns_label.text()
    assert "<record>.rehu — every resource record found while scanning" in summary
    assert "<record>NN with .jpg, .jpeg, .png, .gif, .webp" in summary
    assert "<record> with .checksum, .md5, .sfv, .sha1, .sha224, .sha256, .sha384, .sha512" in summary
    assert "anything ending in .orig — the backups a conversion keeps" in summary
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

    assert listed_patterns(page) == ("*.tmp", "Thumbs.db")
    assert page.is_dirty() is False


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
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    patterns_editor(page).reset_action.trigger()

    assert listed_patterns(page) == EXCLUDED_FILE_PATTERNS


def test_every_editor_action_wears_one_of_this_apps_icons(qtbot: QtBot) -> None:
    """The widget ships none, so a page that forgot to dress it would show eight blank buttons (#231).

    **Test steps:**

    * build the page
    * verify all eight of the editor's actions carry an icon
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
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


def test_editing_the_list_makes_the_page_dirty(qtbot: QtBot) -> None:
    """Whatever the editor holds is what Save would write, so a change to it is a change to the page.

    **Test steps:**

    * build the page and drop a pattern out of the editor
    * verify the page went dirty
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)

    patterns_editor(page).values = EXCLUDED_FILE_PATTERNS[1:]

    assert page.is_dirty() is True


# endregion

# region save and drop


def test_save_pushes_the_staged_patterns_and_persists_them(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` writes the staged list into the shared settings and to storage (#226).

    **Test steps:**

    * build the page and replace every shipped pattern with one of the user's own
    * call ``save_changes``
    * verify the shared settings hold it, the page is clean, and a fresh load agrees
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    patterns_editor(page).values = ("*.tmp",)

    page.save_changes()

    assert shared_excluded_files_settings().excluded_file_patterns == ("*.tmp",)
    assert page.is_dirty() is False

    reloaded = ExcludedFilesSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.patterns == ("*.tmp",)


def test_saving_an_emptied_list_restores_the_defaults_on_screen(qtbot: QtBot) -> None:
    """Emptying the list means the shipped patterns, and the page shows that rather than a lie (#226).

    **Test steps:**

    * build the page and empty the editor
    * call ``save_changes``
    * verify the shipped defaults are both in force and back on screen, and the page is clean
    """
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
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
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    patterns_editor(page).values = ("*.tmp", "", "*.tmp")

    page.save_changes()

    assert shared_excluded_files_settings().patterns == ("*.tmp",)
    assert listed_patterns(page) == ("*.tmp",)
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
    page = ExcludedFilesPage()
    qtbot.addWidget(page)
    patterns_editor(page).values = ("*.partial",)

    page.drop_changes()

    assert listed_patterns(page) == ("*.tmp", "Thumbs.db")
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
