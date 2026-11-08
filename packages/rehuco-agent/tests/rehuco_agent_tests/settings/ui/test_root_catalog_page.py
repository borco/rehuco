"""Tests for RootCatalogPage: the Root Catalog settings page (#457)."""

from PySide6.QtWidgets import QCheckBox
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.root_catalog_settings import (
    DEFAULT_ROOT_LAYOUTS,
    RootLayout,
    shared_root_catalog_settings,
)
from rehuco_agent.settings.ui import root_catalog_page
from rehuco_agent.settings.ui.default_root_layouts_editor import DefaultRootLayoutsEditor
from rehuco_agent.settings.ui.root_catalog_page import RootCatalogPage
from rehuco_agent.settings.ui.settings_page import ExternallySavedPage, SettingsPage

from rehuco_agent_tests.conftest import FakeSettings


@fixture(name="stored")
def stored_fixture(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so an Apply never touches real storage.

    :param mocker: pytest-mock fixture.
    :returns: the store the page writes to.
    """
    fake = FakeSettings()
    mocker.patch.object(root_catalog_page, "persistent_settings", return_value=fake)
    return fake


@fixture(name="page")
def page_fixture(qtbot: QtBot, stored: FakeSettings) -> RootCatalogPage:
    """A page seeded from the shared setting.

    :param qtbot: pytest-qt fixture.
    :param stored: the store an Apply writes to.
    :returns: the page.
    """
    del stored
    built = RootCatalogPage()
    qtbot.addWidget(built)
    return built


def box(page: RootCatalogPage) -> QCheckBox:
    """The page's one checkbox.

    :param page: the page.
    :returns: the box.
    """
    found = page.findChild(QCheckBox, "auto_preview_check_box")
    assert found is not None
    return found


def test_the_page_is_a_settings_page_and_says_when_it_is_saved_elsewhere(page: RootCatalogPage) -> None:
    """The dialog treats it as any page, and the optional hook is how it hears of a menu change.

    **Test steps:**

    * check the page against the two protocols
    * verify both hold
    """
    assert isinstance(page, SettingsPage)
    assert isinstance(page, ExternallySavedPage)


def test_a_fresh_page_shows_the_saved_choice_and_is_clean(page: RootCatalogPage) -> None:
    """Nothing staged yet: the box shows what is applied.

    **Test steps:**

    * build the page over the default setting
    * verify the box is checked and the page is clean
    """
    assert box(page).isChecked()
    assert not page.is_dirty()


def test_a_staged_edit_makes_the_page_dirty_until_it_is_applied(page: RootCatalogPage, stored: FakeSettings) -> None:
    """Ticking the box is an edit; Apply makes it the setting, persists it, and the page is clean again.

    **Test steps:**

    * untick the box, verify the page is dirty and the setting unchanged
    * apply, verify the setting is off, it was written to the store, and the page is clean
    """
    settings = shared_root_catalog_settings()
    box(page).setChecked(False)

    assert page.is_dirty()
    assert settings.auto_preview is True

    page.save_changes()

    assert settings.auto_preview is False
    assert not page.is_dirty()
    stored.beginGroup("root_catalog")
    assert stored.value("auto_preview") is False


def test_dropping_a_staged_edit_shows_the_saved_choice_again(page: RootCatalogPage) -> None:
    """Reset puts back what is applied.

    **Test steps:**

    * untick the box and drop the edit
    * verify the box is checked again and the page is clean
    """
    box(page).setChecked(False)

    page.drop_changes()

    assert box(page).isChecked()
    assert not page.is_dirty()


def test_the_factory_choice_is_staged_over_a_saved_one(page: RootCatalogPage) -> None:
    """Defaults stage the factory value like typing: nothing is saved until Apply decides.

    **Test steps:**

    * apply a choice of off, then ask for the defaults
    * verify the box is checked, the page is dirty, and the setting is still off
    """
    box(page).setChecked(False)
    page.save_changes()

    page.seed_defaults()

    assert box(page).isChecked()
    assert page.is_dirty()
    assert shared_root_catalog_settings().auto_preview is False


def test_the_page_says_so_whenever_the_saved_choice_changes(qtbot: QtBot, page: RootCatalogPage) -> None:
    """The menu applies the setting at once: the page, which saves on Apply, is told so it can be rebased.

    **Test steps:**

    * change the shared setting as the menu does, and then apply the page
    * verify the page said the saved choice changed each time
    """
    settings = shared_root_catalog_settings()

    with qtbot.waitSignal(page.saved_changed, timeout=1000):
        settings.auto_preview = False

    box(page).setChecked(True)
    with qtbot.waitSignal(page.saved_changed, timeout=1000):
        page.save_changes()


def layouts_editor(page: RootCatalogPage) -> DefaultRootLayoutsEditor:
    """The page's default root layouts.

    :param page: the page.
    :returns: the editor.
    """
    found = page.findChild(DefaultRootLayoutsEditor)
    assert found is not None
    return found


def test_the_default_layouts_are_staged_applied_dropped_and_seeded(page: RootCatalogPage, stored: FakeSettings) -> None:
    """The default root layouts are staged like the box: an edit dirties the page, Apply saves it, Reset and Defaults
    put back the saved and the shipped layouts (#578).

    **Test steps:**

    * verify the page shows the saved layouts; stage two layouts and verify the page dirty and the setting unchanged
    * apply, and verify the setting, the store and a clean page
    * stage none, drop it, and verify the saved layouts are back; seed the defaults and verify the shipped ones staged
    """
    settings = shared_root_catalog_settings()
    assert layouts_editor(page).layouts == DEFAULT_ROOT_LAYOUTS
    staged = (RootLayout("Deep", {"tutorial": "{authors}/{title}"}, {}), *DEFAULT_ROOT_LAYOUTS)

    layouts_editor(page).layouts = staged
    assert page.is_dirty()
    assert settings.default_layouts == DEFAULT_ROOT_LAYOUTS

    page.save_changes()
    assert settings.default_layouts == staged
    assert not page.is_dirty()
    stored.beginGroup("root_catalog")
    assert stored.value("default_layouts/1/label") == "Deep"
    stored.endGroup()

    layouts_editor(page).layouts = ()
    page.drop_changes()
    assert layouts_editor(page).layouts == staged

    page.seed_defaults()
    assert layouts_editor(page).layouts == DEFAULT_ROOT_LAYOUTS
    assert page.is_dirty()


def test_applying_no_layouts_saves_the_shipped_one(page: RootCatalogPage) -> None:
    """A folder always needs a layout, so an emptied list is applied as the shipped one.

    **Test steps:**

    * stage no layouts and apply
    * verify the setting holds the shipped layout
    """
    layouts_editor(page).layouts = ()

    page.save_changes()

    assert shared_root_catalog_settings().default_layouts == DEFAULT_ROOT_LAYOUTS
    assert layouts_editor(page).layouts == DEFAULT_ROOT_LAYOUTS
    assert not page.is_dirty()


def test_the_page_says_so_when_a_layout_is_saved_from_the_add_roots_dialog(qtbot: QtBot, page: RootCatalogPage) -> None:
    """*New layout…* saves at once, behind the page's back, so the page is told to be rebased.

    **Test steps:**

    * change the shared layouts as the dialog does
    * verify the page said the saved values changed
    """
    with qtbot.waitSignal(page.saved_changed, timeout=1000):
        shared_root_catalog_settings().default_layouts = (RootLayout("New"),)
