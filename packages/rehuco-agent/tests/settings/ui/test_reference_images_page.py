"""Tests for ReferenceImagesPage: the Reference Images settings category page (#222, #231)."""

from collections.abc import Iterator
from typing import Any

from borco_pyside.widgets import StringListEditor
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import main_rc  # noqa: F401  # pylint: disable=unused-import  # registers :/icons/...
from rehuco_agent.settings import reference_images_settings
from rehuco_agent.settings.reference_images_settings import ReferenceImagesSettings, shared_reference_images_settings
from rehuco_agent.settings.ui import reference_images_page
from rehuco_agent.settings.ui.reference_images_page import ReferenceImagesPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_core import CONTENT_IMAGE_EXTENSIONS


# region fixtures
# Mirrors test_reference_images_settings.py's FakeSettings exactly -- kept as a separate copy rather
# than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see
    ``test_reference_images_settings.py`` for the full rationale)."""

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
    (used by :func:`shared_reference_images_settings`'s lazy load) and the page module itself (used
    by :meth:`ReferenceImagesPage.save_changes`).
    """
    fake = FakeSettings()
    mocker.patch.object(reference_images_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(reference_images_page, "persistent_settings", return_value=fake)
    return fake


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the shared settings singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_reference_images_settings.cache_clear()
    yield
    shared_reference_images_settings.cache_clear()


def page_ui(page: ReferenceImagesPage) -> Any:
    """The page's generated UI object, for reaching its widgets.

    :param page: the page to reach into.
    :returns: the ``Ui_ReferenceImagesPage`` instance.
    """
    return page._ReferenceImagesPage__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def extensions_editor(page: ReferenceImagesPage) -> StringListEditor:
    """The page's extension list editor.

    :param page: the page to reach into.
    :returns: the `StringListEditor` holding the recognized formats.
    """
    return page_ui(page).extensions_editor


def listed_extensions(page: ReferenceImagesPage) -> tuple[str, ...]:
    """The formats the page currently shows, in order.

    :param page: the page to read.
    :returns: every entry's text.
    """
    return extensions_editor(page).values


# endregion

# region what the page shows


def test_starts_on_the_shipped_formats_on_a_fresh_install(qtbot: QtBot) -> None:
    """With nothing persisted, the list shows the formats actually in force -- not an empty list (#231).

    The page carries no Default/Custom pair any more, so showing the effective set is what tells the
    user which formats are counted.

    **Test steps:**

    * build the page against empty persistent storage
    * verify it lists core's shipped set and is clean
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    assert listed_extensions(page) == CONTENT_IMAGE_EXTENSIONS
    assert page.is_dirty() is False


def test_restores_the_saved_formats(qtbot: QtBot) -> None:
    """A freshly-built page reflects what was saved, in order.

    **Test steps:**

    * seed the shared settings with two formats of the user's own
    * build the page
    * verify it lists exactly those two and is clean
    """
    shared_reference_images_settings().extensions = (".bmp", ".tif")
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    assert listed_extensions(page) == (".bmp", ".tif")
    assert page.is_dirty() is False


# endregion

# region the list editor


def test_the_editors_reset_fills_the_list_with_the_shipped_formats(qtbot: QtBot) -> None:
    """Reset is what the Default radio used to be: the shipped set, on request (#231).

    **Test steps:**

    * seed the shared settings with one format of the user's own and build the page
    * fire the editor's Reset action
    * verify the shipped set is listed
    """
    shared_reference_images_settings().extensions = (".bmp",)
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    extensions_editor(page).item_actions.reset_action.trigger()

    assert listed_extensions(page) == CONTENT_IMAGE_EXTENSIONS


def test_every_editor_action_wears_one_of_this_apps_icons(qtbot: QtBot) -> None:
    """The widget ships none, so a page that forgot to dress it would show eight blank buttons (#231).

    **Test steps:**

    * build the page
    * verify all eight of the editor's actions carry an icon
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    editor = extensions_editor(page)

    actions = (
        editor.item_actions.insert_action,
        editor.item_actions.edit_action,
        editor.item_actions.delete_action,
        editor.item_actions.reset_action,
        editor.ordering_actions.move_to_top_action,
        editor.ordering_actions.move_up_action,
        editor.ordering_actions.move_down_action,
        editor.ordering_actions.move_to_bottom_action,
    )
    assert [action.icon().isNull() for action in actions] == [False] * 8


def test_editing_the_list_makes_the_page_dirty(qtbot: QtBot) -> None:
    """Whatever the editor holds is what Save would write, so a change to it is a change to the page.

    **Test steps:**

    * build the page and drop a format out of the editor
    * verify the page went dirty
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    extensions_editor(page).values = CONTENT_IMAGE_EXTENSIONS[1:]

    assert page.is_dirty() is True


# endregion

# region save and drop


def test_save_pushes_the_staged_formats_and_persists_them(qtbot: QtBot, fake_persistent_settings: FakeSettings) -> None:
    """``save_changes`` writes the staged list into the shared settings and to storage.

    **Test steps:**

    * build the page and replace the shipped set with one format of the user's own
    * call ``save_changes``
    * verify the shared settings hold it, the page is clean, and a fresh load agrees
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = (".bmp",)

    page.save_changes()

    assert shared_reference_images_settings().content_image_extensions == (".bmp",)
    assert page.is_dirty() is False

    reloaded = ReferenceImagesSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.extensions == (".bmp",)


def test_saving_normalizes_the_typing_on_screen(qtbot: QtBot) -> None:
    """``BMP`` is stored as ``.bmp``, and the page is reloaded so it shows what is actually matched.

    Normalizing is the settings object's, not the editor's -- the editor holds what was typed (#231).

    **Test steps:**

    * build the page and stage messily-typed formats, one blank and one duplicate among them
    * call ``save_changes``
    * verify what was saved and what is shown are the same normalized list
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = ("BMP ", "", ".bmp", "tif")

    page.save_changes()

    assert shared_reference_images_settings().extensions == (".bmp", ".tif")
    assert listed_extensions(page) == (".bmp", ".tif")
    assert page.is_dirty() is False


def test_saving_an_emptied_list_restores_the_shipped_formats_on_screen(qtbot: QtBot) -> None:
    """Emptying the list means the shipped formats, and the page shows that rather than a lie.

    **Test steps:**

    * build the page and empty the editor
    * call ``save_changes``
    * verify the shipped set is both in force and back on screen, and the page is clean
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = ()

    page.save_changes()

    assert shared_reference_images_settings().content_image_extensions == CONTENT_IMAGE_EXTENSIONS
    assert listed_extensions(page) == CONTENT_IMAGE_EXTENSIONS
    assert page.is_dirty() is False


def test_drop_changes_reverts_the_staged_list(qtbot: QtBot) -> None:
    """``drop_changes`` refills the editor from the shared settings -- a revert, not a no-op.

    **Test steps:**

    * seed the shared settings with two formats and build the page
    * stage a different list entirely
    * call ``drop_changes``
    * verify the seeded pair is back and the page is clean
    """
    shared_reference_images_settings().extensions = (".bmp", ".tif")
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    extensions_editor(page).values = (".psd",)

    page.drop_changes()

    assert listed_extensions(page) == (".bmp", ".tif")
    assert page.is_dirty() is False


# endregion

# region the page shell


def test_title_is_reference_images(qtbot: QtBot) -> None:
    """The page's category-tree title is "Reference Images".

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    assert page.title == "Reference Images"


def test_the_wrapping_note_is_never_clipped_at_any_width(qtbot: QtBot) -> None:
    """The note gets the height its text needs at the width it is given, and gives it back on widening.

    Same guard as `ExcludedFilesPage`'s: a plain wrapping `QLabel` hints as though its text were one wide
    line, and the frame sized from that hint paints the paragraph past its border (#226, fixed in #229).

    **Test steps:**

    * build the page and resize it through a range of widths, narrow and wide, then back
    * verify at every step that the note is at least as tall as its text needs
    * verify a width seen before gets exactly the height it got the first time
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    label = page_ui(page).note_label
    page.show()

    first_seen: dict[int, int] = {}
    for width in (320, 900, 420, 640, 320, 900):
        page.setGeometry(0, 0, width, 700)
        page_ui(page).main_layout.activate()
        assert label.height() >= label.heightForWidth(label.width()), f"note clipped at page width {width}"
        assert first_seen.setdefault(width, label.height()) == label.height(), f"height ratcheted at {width}"


def test_frame_filter_discovers_the_pages_frame_and_its_text(qtbot: QtBot) -> None:
    """A `SettingsFrameFilter` finds the page's labeled frame and filters it by its text (#67).

    Guards the page's ``.ui`` frame structure: the content-images frame must be a discoverable
    top-level frame whose gathered caption text drives the filter.

    **Test steps:**

    * build a frame filter over the page, then filter by the header's text
    * verify the frame stays shown; filter by a non-matching term and verify it hides
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    frame_filter = SettingsFrameFilter(page, page.title)
    ui = page_ui(page)

    frame_filter.apply("image extensions", show_full_on_title_match=False)
    assert ui.content_images_frame.isVisibleTo(page) is True

    frame_filter.apply("no-such-term", show_full_on_title_match=False)
    assert ui.content_images_frame.isVisibleTo(page) is False


# endregion
