"""Tests for ReferenceImagesPage: the Reference Images settings category page (#222)."""

from collections.abc import Iterator
from typing import Any

from PySide6.QtCore import Qt
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings import reference_images_settings
from rehuco_agent.settings.reference_images_settings import ReferenceImagesSettings, shared_reference_images_settings
from rehuco_agent.settings.ui import reference_images_page
from rehuco_agent.settings.ui.reference_images_page import ReferenceImagesPage
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_core import CONTENT_IMAGE_EXTENSIONS


# region fixtures
# Mirrors test_identity_page.py's (and conftest.py's) FakeSettings exactly -- kept as a separate copy
# rather than a shared import, matching this codebase's settings-test convention.
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


# endregion


def test_starts_on_the_default_choice_on_a_fresh_install(qtbot: QtBot) -> None:
    """With nothing persisted, the page starts on Default: custom unchecked and its edit disabled.

    **Test steps:**

    * build the page against empty persistent storage
    * verify the Default radio is checked, the custom radio isn't, and the custom edit is disabled
      and empty
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    ui = page_ui(page)
    assert ui.default_radio_button.isChecked() is True
    assert ui.custom_radio_button.isChecked() is False
    assert ui.custom_extensions_edit.isEnabled() is False
    assert ui.custom_extensions_edit.text() == ""


def test_the_default_label_shows_cores_set_and_is_selectable(qtbot: QtBot) -> None:
    """The label beside Default shows core's set -- written from the constant, not restated in the
    ``.ui`` -- and is text-selectable so it can be copied into the custom list (#222).

    **Test steps:**

    * build the page
    * verify the label's text is the formatted default set
    * verify its interaction flags allow selecting the text by mouse
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    label = page_ui(page).default_extensions_label
    assert label.text() == ".jpg, .jpeg, .png, .webp, .avif"
    assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_restores_the_saved_custom_choice(qtbot: QtBot) -> None:
    """A freshly-built page reflects a saved Custom selection: radio checked, edit enabled and filled.

    **Test steps:**

    * seed the shared settings with the custom choice and a known list
    * build the page
    * verify the Custom radio is checked and the edit is enabled and holds the list
    """
    shared_reference_images_settings().use_custom_extensions = True
    shared_reference_images_settings().custom_extensions = "bmp, tif"

    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    ui = page_ui(page)
    assert ui.custom_radio_button.isChecked() is True
    assert ui.custom_extensions_edit.isEnabled() is True
    assert ui.custom_extensions_edit.text() == "bmp, tif"


def test_restores_the_custom_text_even_while_default_is_selected(qtbot: QtBot) -> None:
    """A saved custom list comes back into the (disabled) edit even when Default is the saved choice --
    the list survives without being the selected source (#222).

    **Test steps:**

    * seed the shared settings with the default choice but a filled custom list
    * build the page
    * verify Default is checked while the disabled custom edit still holds the list
    """
    shared_reference_images_settings().custom_extensions = "bmp, tif"

    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    ui = page_ui(page)
    assert ui.default_radio_button.isChecked() is True
    assert ui.custom_extensions_edit.isEnabled() is False
    assert ui.custom_extensions_edit.text() == "bmp, tif"


def test_checking_custom_enables_the_edit_and_default_disables_it(qtbot: QtBot) -> None:
    """The custom edit is live exactly while Custom is the selected choice.

    **Test steps:**

    * build the page and check the Custom radio
    * verify the edit enables
    * check the Default radio back
    * verify the edit disables
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)

    ui.custom_radio_button.setChecked(True)
    assert ui.custom_extensions_edit.isEnabled() is True

    ui.default_radio_button.setChecked(True)
    assert ui.custom_extensions_edit.isEnabled() is False


def test_is_dirty_is_false_right_after_construction(qtbot: QtBot) -> None:
    """A freshly-built page (nothing edited yet) is not dirty.

    **Test steps:**

    * build the page
    * verify ``is_dirty`` is ``False``
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    assert page.is_dirty() is False


def test_is_dirty_is_true_after_switching_the_choice(qtbot: QtBot) -> None:
    """Switching the radio choice makes the page dirty.

    **Test steps:**

    * build the page and check the Custom radio
    * verify ``is_dirty`` is ``True``
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    page_ui(page).custom_radio_button.setChecked(True)

    assert page.is_dirty() is True


def test_is_dirty_is_true_after_editing_the_custom_list(qtbot: QtBot) -> None:
    """Editing the custom list makes the page dirty, whichever choice is selected -- the text is part
    of what Save persists either way.

    **Test steps:**

    * build the page and change the custom edit while Default stays checked
    * verify ``is_dirty`` is ``True``
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    page_ui(page).custom_extensions_edit.setText("bmp")

    assert page.is_dirty() is True


def test_save_changes_updates_the_shared_settings_and_persists(
    qtbot: QtBot, fake_persistent_settings: FakeSettings
) -> None:
    """``save_changes`` pushes the staged choice and custom text into the shared settings object and
    persists them, custom text verbatim.

    **Test steps:**

    * build the page, check Custom, and type a messy list
    * call ``save_changes``
    * verify the shared settings hold both as staged, the page is clean, and a fresh load agrees
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.custom_radio_button.setChecked(True)
    ui.custom_extensions_edit.setText("BMP , tif,")

    page.save_changes()

    assert shared_reference_images_settings().use_custom_extensions is True
    assert shared_reference_images_settings().custom_extensions == "BMP , tif,"
    assert shared_reference_images_settings().content_image_extensions == (".bmp", ".tif")
    assert page.is_dirty() is False

    reloaded = ReferenceImagesSettings()
    reloaded.load(fake_persistent_settings)  # type: ignore[arg-type]
    assert reloaded.use_custom_extensions is True
    assert reloaded.custom_extensions == "BMP , tif,"


def test_saving_the_default_choice_keeps_the_typed_custom_list(qtbot: QtBot) -> None:
    """Saving with Default selected still persists whatever sits in the custom edit -- so a later
    switch to Custom finds the list where it was left (#222).

    **Test steps:**

    * build the page, type a custom list, switch back to Default, and save
    * verify the shared settings keep the text while the effective set stays core's
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.custom_radio_button.setChecked(True)
    ui.custom_extensions_edit.setText("bmp")
    ui.default_radio_button.setChecked(True)

    page.save_changes()

    assert shared_reference_images_settings().use_custom_extensions is False
    assert shared_reference_images_settings().custom_extensions == "bmp"
    assert shared_reference_images_settings().content_image_extensions == CONTENT_IMAGE_EXTENSIONS


def test_drop_changes_reverts_both_the_choice_and_the_custom_list(qtbot: QtBot) -> None:
    """``drop_changes`` reverts the radio choice and the custom text back to the shared settings'.

    **Test steps:**

    * seed the shared settings with the custom choice and a known list, build the page
    * switch to Default and overtype the list
    * call ``drop_changes``
    * verify the Custom radio and the seeded list are back and the page is clean
    """
    shared_reference_images_settings().use_custom_extensions = True
    shared_reference_images_settings().custom_extensions = "bmp, tif"
    page = ReferenceImagesPage()
    qtbot.addWidget(page)
    ui = page_ui(page)
    ui.default_radio_button.setChecked(True)
    ui.custom_extensions_edit.setText("unsaved, psd")

    page.drop_changes()

    assert ui.custom_radio_button.isChecked() is True
    assert ui.custom_extensions_edit.isEnabled() is True
    assert ui.custom_extensions_edit.text() == "bmp, tif"
    assert page.is_dirty() is False


def test_title_is_reference_images(qtbot: QtBot) -> None:
    """The page's category-tree title is "Reference Images".

    **Test steps:**

    * construct the page
    * verify ``title``
    """
    page = ReferenceImagesPage()
    qtbot.addWidget(page)

    assert page.title == "Reference Images"


def test_frame_filter_discovers_the_pages_frame_and_its_text(qtbot: QtBot) -> None:
    """A `SettingsFrameFilter` finds the page's labeled frame and filters it by its text (#67).

    Guards the page's ``.ui`` frame structure: the content-images frame must be a discoverable
    top-level frame whose gathered caption text (the header and the radio captions) drives the filter.

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
