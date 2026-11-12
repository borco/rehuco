"""Tests for NewRootPresetsPage: the default root layouts a new root can start with (#578, #637)."""

from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.root_catalog_settings import (
    DEFAULT_ROOT_LAYOUTS,
    RootLayout,
    shared_root_catalog_settings,
)
from rehuco_agent.settings.ui import new_root_presets_page
from rehuco_agent.settings.ui.default_root_layouts_editor import DefaultRootLayoutsEditor
from rehuco_agent.settings.ui.new_root_presets_page import NewRootPresetsPage
from rehuco_agent.settings.ui.settings_page import ExternallySavedPage, SettingsPage

from rehuco_agent_tests.conftest import FakeSettings


@fixture(name="stored")
def stored_fixture(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so an Apply never touches real storage.

    :param mocker: pytest-mock fixture.
    :returns: the store the page writes to.
    """
    fake = FakeSettings()
    mocker.patch.object(new_root_presets_page, "persistent_settings", return_value=fake)
    return fake


@fixture(name="page")
def page_fixture(qtbot: QtBot, stored: FakeSettings) -> NewRootPresetsPage:
    """A page seeded from the shared setting.

    :param qtbot: pytest-qt fixture.
    :param stored: the store an Apply writes to.
    :returns: the page.
    """
    del stored
    built = NewRootPresetsPage()
    qtbot.addWidget(built)
    return built


def layouts_editor(page: NewRootPresetsPage) -> DefaultRootLayoutsEditor:
    """The page's default root layouts.

    :param page: the page.
    :returns: the editor.
    """
    found = page.findChild(DefaultRootLayoutsEditor)
    assert found is not None
    return found


def test_the_page_is_a_settings_page_and_says_when_it_is_saved_elsewhere(page: NewRootPresetsPage) -> None:
    """The dialog treats it as any page, and the optional hook is how it hears of *New layout…*.

    **Test steps:**

    * check the page against the two protocols
    * verify both hold
    """
    assert isinstance(page, SettingsPage)
    assert isinstance(page, ExternallySavedPage)


def test_the_default_layouts_are_staged_applied_dropped_and_seeded(
    page: NewRootPresetsPage, stored: FakeSettings
) -> None:
    """The presets are staged like any setting: an edit dirties the page, Apply saves it, Reset and Defaults put back
    the saved and the shipped presets (#578).

    **Test steps:**

    * verify the page shows the saved layouts; stage two layouts and verify the page dirty and the setting unchanged
    * apply, and verify the setting, the store and a clean page
    * stage none, drop it, and verify the saved layouts are back; seed the defaults and verify the shipped ones staged
    """
    settings = shared_root_catalog_settings()
    assert layouts_editor(page).layouts == DEFAULT_ROOT_LAYOUTS
    assert not page.is_dirty()
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


def test_applying_no_layouts_saves_the_shipped_one(page: NewRootPresetsPage) -> None:
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


def test_the_page_says_so_when_a_layout_is_saved_from_the_add_roots_dialog(
    qtbot: QtBot, page: NewRootPresetsPage
) -> None:
    """*New layout…* saves at once, behind the page's back, so the page is told to be rebased.

    **Test steps:**

    * change the shared layouts as the dialog does
    * verify the page said the saved values changed
    """
    with qtbot.waitSignal(page.saved_changed, timeout=1000):
        shared_root_catalog_settings().default_layouts = (RootLayout("New"),)
