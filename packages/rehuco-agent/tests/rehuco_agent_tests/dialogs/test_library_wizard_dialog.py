"""Tests for LibraryWizardDialog: the one dialog that starts a store's library scan into a root (#685)."""

from pathlib import Path
from typing import NamedTuple
from unittest.mock import Mock
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QPushButton
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.library_root_delegate import LOCATION_ROLE
from rehuco_agent.dialogs.library_wizard_dialog import START_TEXT, LibraryWizardDialog
from rehuco_agent.scraping.browser_fetcher import PersonaBrowser
from rehuco_agent.scraping.library_scan_job import LibraryScanTarget
from rehuco_agent.scraping.protocols import FetchError
from rehuco_agent.scraping.scraper_wizard import ScraperWizard
from rehuco_agent.settings.library_wizard_settings import LibraryWizardSettings
from rehuco_agent.settings.scrapers_settings import Browser
from rehuco_core import DEFAULT_LAYOUTS, MappedRoot

MODULE = "rehuco_agent.dialogs.library_wizard_dialog"
SITE_URL = "https://www.fab.com"


class Setup(NamedTuple):
    """What the dialog is built over."""

    fab: Mock
    other: Mock
    assets: MappedRoot
    videos: MappedRoot
    loose: MappedRoot
    unlabeled: MappedRoot
    cache: Path


def wizard_named(key: str, label: str) -> Mock:
    """A scraper wizard.

    :param key: its key.
    :param label: its label.
    :returns: the stand-in.
    """
    wizard = Mock(spec=ScraperWizard)
    wizard.key = key
    wizard.label = label
    return wizard


def mapped(tmp_path: Path, name: str, label: str, *, file: bool = True, layouts: dict | None = None) -> MappedRoot:
    """A root this machine reaches.

    :param tmp_path: the test's folder.
    :param name: the root's folder name.
    :param label: the root's label.
    :param file: whether it was read from a ``.rehuroot``.
    :param layouts: its layouts; the default's, which admit any type, when not given.
    :returns: the root.
    """
    return MappedRoot(
        uuid4(),
        label,
        f"//nas/{name}",
        tmp_path / name,
        file=tmp_path / f"{name}.rehuroot" if file else None,
        layouts=DEFAULT_LAYOUTS if layouts is None else layouts,
    )


@fixture(name="setup")
def fixture_setup(tmp_path: Path) -> Setup:
    """Two wizards, four roots -- one that takes an asset, one that takes only videos, one with no file, one with no
    label -- and a cache.

    :param tmp_path: pytest fixture.
    :returns: them.
    """
    fab = wizard_named("fab", "Fab")
    fab.site_url = SITE_URL
    return Setup(
        fab,
        wizard_named("other", "Other"),
        mapped(tmp_path, "assets", "Assets"),
        mapped(tmp_path, "videos", "Videos", layouts={"video": ("*",)}),
        mapped(tmp_path, "loose", "Loose", file=False),
        mapped(tmp_path, "unlabeled", ""),
        tmp_path / "cache.rehudb",
    )


def build(
    qtbot: QtBot, setup: Setup, settings: LibraryWizardSettings | None = None, *, wizards: bool = True
) -> LibraryWizardDialog:
    """The dialog over ``setup``.

    :param qtbot: pytest-qt fixture.
    :param setup: what it is built over.
    :param settings: the roots last used; none when not given.
    :param wizards: whether it is given the two wizards; none when not.
    :returns: the dialog.
    """
    dialog = LibraryWizardDialog(
        [setup.fab, setup.other] if wizards else [],
        [setup.assets, setup.videos, setup.loose, setup.unlabeled],
        setup.cache,
        settings or LibraryWizardSettings(),
    )
    qtbot.addWidget(dialog)
    return dialog


def combo(dialog: LibraryWizardDialog, name: str) -> QComboBox:
    """One of the dialog's combo boxes.

    :param dialog: the dialog.
    :param name: its object name.
    :returns: the combo box.
    """
    found = dialog.findChild(QComboBox, name)
    assert found is not None
    return found


def error_label(dialog: LibraryWizardDialog) -> QLabel:
    """The line under the Login button.

    :param dialog: the dialog.
    :returns: the label.
    """
    found = dialog.findChild(QLabel, "login_error_label")
    assert found is not None
    return found


def press_login(dialog: LibraryWizardDialog) -> None:
    """Click Login.

    :param dialog: the dialog.
    """
    button = dialog.findChild(QPushButton, "login_button")
    assert button is not None
    button.click()


def test_the_sites_are_the_wizards_in_order_and_the_first_is_chosen(qtbot: QtBot, setup: Setup) -> None:
    """The Site list names each wizard by its label, in the registry's order, and starts on the first.

    **Test steps:**

    * build the dialog over two wizards
    * verify the Site list holds their labels in order
    * verify the first is chosen, and is the dialog's wizard
    """
    dialog = build(qtbot, setup)

    site = combo(dialog, "site_combo")
    assert [site.itemText(row) for row in range(site.count())] == ["Fab", "Other"]
    assert site.currentIndex() == 0
    assert dialog.wizard is setup.fab


def test_a_root_that_takes_no_asset_is_listed_disabled_with_its_reason(qtbot: QtBot, setup: Setup) -> None:
    """A root whose layouts admit no asset, or that has no file to place records by, is listed but cannot be chosen.

    **Test steps:**

    * build the dialog over a root that takes an asset, one that takes only videos, and one with no file
    * verify all three are listed, with their label and their location
    * verify only the first is enabled
    * verify each refused root's tooltip says why, and the first has none
    """
    dialog = build(qtbot, setup)

    roots = combo(dialog, "root_combo").model()
    items = [roots.index(row, 0) for row in range(3)]
    assert [item.data() for item in items] == ["Assets", "Videos", "Loose"]
    assert [item.data(LOCATION_ROLE) for item in items] == [
        setup.assets.location,
        setup.videos.location,
        setup.loose.location,
    ]
    assert [bool(item.flags() & Qt.ItemFlag.ItemIsEnabled) for item in items] == [True, False, False]
    assert items[0].data(Qt.ItemDataRole.ToolTipRole) is None
    assert "does not take an asset" in items[1].data(Qt.ItemDataRole.ToolTipRole)
    assert "not read from a .rehuroot" in items[2].data(Qt.ItemDataRole.ToolTipRole)


def test_a_root_with_no_label_is_named_by_its_folder(qtbot: QtBot, setup: Setup) -> None:
    """A root that has no label is listed under its folder.

    **Test steps:**

    * build the dialog over a root with an empty label
    * verify its entry reads as its folder
    """
    dialog = build(qtbot, setup)

    assert combo(dialog, "root_combo").itemText(3) == str(setup.unlabeled.path)


def test_start_waits_for_a_root(qtbot: QtBot, setup: Setup) -> None:
    """Start is named for what it does, and is held back until a site and a root are chosen.

    **Test steps:**

    * build the dialog with no remembered root
    * verify Start reads *Start*, is disabled, and the dialog has no target
    * choose the root that takes an asset
    * verify Start is enabled
    """
    dialog = build(qtbot, setup)

    assert dialog.ok_button.text() == START_TEXT
    assert not dialog.ok_button.isEnabled()
    assert dialog.target is None
    combo(dialog, "root_combo").setCurrentIndex(0)
    assert dialog.ok_button.isEnabled()


def test_start_is_held_back_with_no_site(qtbot: QtBot, setup: Setup) -> None:
    """With no wizard installed there is nothing to start.

    **Test steps:**

    * build the dialog with no wizards
    * choose a root
    * verify the dialog has no wizard and no target, and Start is disabled
    """
    dialog = build(qtbot, setup, wizards=False)

    combo(dialog, "root_combo").setCurrentIndex(0)

    assert dialog.wizard is None
    assert dialog.target is None
    assert not dialog.ok_button.isEnabled()


def test_the_root_last_used_for_a_site_is_chosen_when_the_site_is(qtbot: QtBot, setup: Setup) -> None:
    """Each site brings back its own root.

    **Test steps:**

    * remember the assets root for Fab and the unlabeled one for the other site
    * build the dialog, and verify Fab's root is chosen
    * choose the other site, and verify its root is chosen
    * choose Fab again, and verify its root is chosen again
    """
    settings = LibraryWizardSettings({"fab": setup.assets.root_id, "other": setup.unlabeled.root_id})
    dialog = build(qtbot, setup, settings)
    site, root = combo(dialog, "site_combo"), combo(dialog, "root_combo")
    assert root.currentIndex() == 0

    site.setCurrentIndex(1)
    assert root.currentIndex() == 3

    site.setCurrentIndex(0)
    assert root.currentIndex() == 0


def test_a_root_that_can_no_longer_take_the_scan_is_not_chosen(qtbot: QtBot, setup: Setup) -> None:
    """A remembered root that is gone from the catalog, or no longer takes an asset, is left unchosen.

    **Test steps:**

    * remember the videos root, which takes no asset, for Fab and an id the catalog does not list for the other site
    * build the dialog, and verify no root is chosen for Fab
    * choose the other site, and verify no root is chosen
    * verify Start is disabled
    """
    settings = LibraryWizardSettings({"fab": setup.videos.root_id, "other": uuid4()})
    dialog = build(qtbot, setup, settings)
    root = combo(dialog, "root_combo")
    assert root.currentIndex() == -1

    combo(dialog, "site_combo").setCurrentIndex(1)

    assert root.currentIndex() == -1
    assert not dialog.ok_button.isEnabled()


def test_a_site_with_no_remembered_root_keeps_the_root_chosen(qtbot: QtBot, setup: Setup) -> None:
    """One root takes the items of several stores, so a root picked by hand outlives a change of site.

    **Test steps:**

    * build the dialog with no remembered root, and choose the assets root
    * choose the other site
    * verify the assets root is still chosen, Start is enabled, and the target names the other site
    """
    dialog = build(qtbot, setup)
    root = combo(dialog, "root_combo")
    root.setCurrentIndex(0)

    combo(dialog, "site_combo").setCurrentIndex(1)

    assert root.currentIndex() == 0
    assert dialog.ok_button.isEnabled()
    target = dialog.target
    assert target is not None
    assert (target.site_key, target.root_id) == ("other", setup.assets.root_id)


def test_the_target_is_what_was_chosen(qtbot: QtBot, setup: Setup) -> None:
    """The target names the site, the root, its file, the catalog's cache and whether the whole library is read again.

    **Test steps:**

    * choose the assets root
    * verify the target for a library read from where the records reach
    * tick Full rescan
    * verify the target asks for it
    """
    dialog = build(qtbot, setup)
    combo(dialog, "root_combo").setCurrentIndex(0)
    root_file = setup.assets.file
    assert root_file is not None
    expected = LibraryScanTarget("fab", setup.assets.root_id, "Assets", root_file, setup.cache)
    assert dialog.target == expected

    check = dialog.findChild(QCheckBox, "full_rescan_check")
    assert check is not None
    assert not check.isChecked()
    check.setChecked(True)

    assert dialog.target == LibraryScanTarget(
        "fab",
        setup.assets.root_id,
        "Assets",
        root_file,
        setup.cache,
        True,
    )


def test_an_unlabeled_root_is_named_by_its_folder_in_the_target(qtbot: QtBot, setup: Setup) -> None:
    """The scan's row names a root that has no label by its folder, as a scan of the root alone does.

    **Test steps:**

    * choose the unlabeled root
    * verify the target's root label is its folder
    """
    dialog = build(qtbot, setup)
    combo(dialog, "root_combo").setCurrentIndex(3)

    target = dialog.target
    assert target is not None
    assert target.root_label == str(setup.unlabeled.path)


def test_start_remembers_the_root_for_the_site(mocker: MockerFixture, qtbot: QtBot, setup: Setup) -> None:
    """Accepting saves the root under the site's key; the full-rescan box is not saved.

    **Test steps:**

    * choose the assets root and tick Full rescan
    * press Start
    * verify the dialog is accepted, the root is remembered for Fab alone, and the settings were saved
    """
    store = mocker.patch(f"{MODULE}.persistent_settings")
    save = mocker.patch.object(LibraryWizardSettings, "save")
    settings = LibraryWizardSettings()
    dialog = build(qtbot, setup, settings)
    combo(dialog, "root_combo").setCurrentIndex(0)
    check = dialog.findChild(QCheckBox, "full_rescan_check")
    assert check is not None
    check.setChecked(True)

    dialog.ok_button.click()

    assert dialog.result() == LibraryWizardDialog.DialogCode.Accepted
    assert settings.roots == {"fab": setup.assets.root_id}
    save.assert_called_once_with(store.return_value)


def test_cancel_remembers_nothing(mocker: MockerFixture, qtbot: QtBot, setup: Setup) -> None:
    """Closing the dialog without starting a scan leaves the remembered roots as they were.

    **Test steps:**

    * choose a root
    * reject the dialog
    * verify the roots were not changed and not saved
    """
    save = mocker.patch.object(LibraryWizardSettings, "save")
    settings = LibraryWizardSettings()
    dialog = build(qtbot, setup, settings)
    combo(dialog, "root_combo").setCurrentIndex(0)

    dialog.reject()

    assert not settings.roots
    save.assert_not_called()


def test_accepting_with_nothing_chosen_remembers_nothing(mocker: MockerFixture, qtbot: QtBot, setup: Setup) -> None:
    """A dialog accepted with no root chosen -- Start is disabled, but accept is public -- saves no root.

    **Test steps:**

    * accept the dialog with no root chosen
    * verify nothing was remembered or saved
    """
    save = mocker.patch.object(LibraryWizardSettings, "save")
    settings = LibraryWizardSettings()
    dialog = build(qtbot, setup, settings)

    dialog.accept()

    assert not settings.roots
    save.assert_not_called()


def test_login_opens_the_persona_browser_at_the_sites_page(mocker: MockerFixture, qtbot: QtBot, setup: Setup) -> None:
    """Login opens the persona browser, unautomated, on the settings' browser and the page of the store chosen.

    **Test steps:**

    * make the shared persona browser a stand-in
    * press Login with Fab chosen, whose wizard names a site
    * verify the browser was opened on the settings' browser, at that site
    * choose the other site, whose wizard names none, and press Login
    * verify the browser was opened on no page in particular
    * verify neither click showed a problem
    """
    persona = Mock(spec=PersonaBrowser)
    mocker.patch(f"{MODULE}.shared_persona_browser", return_value=persona)
    dialog = build(qtbot, setup)

    press_login(dialog)
    qtbot.waitUntil(lambda: persona.open_for_login.call_count == 1)
    combo(dialog, "site_combo").setCurrentIndex(1)
    press_login(dialog)
    qtbot.waitUntil(lambda: persona.open_for_login.call_count == 2)

    assert [call.args for call in persona.open_for_login.call_args_list] == [
        (Browser.FIREFOX, SITE_URL),
        (Browser.FIREFOX, None),
    ]
    assert error_label(dialog).isHidden()


def test_a_browser_that_cannot_be_opened_is_reported_in_the_dialog(
    mocker: MockerFixture, qtbot: QtBot, setup: Setup
) -> None:
    """A browser that is not there is said so under the Login button, with no second box over the dialog, and the
    next click starts clean.

    **Test steps:**

    * make opening the browser fail, and press Login
    * verify the reason shows under the button
    * make opening it work, and press Login again
    * verify the reason is gone
    """
    persona = Mock(spec=PersonaBrowser)
    persona.open_for_login.side_effect = FetchError("Could not open Firefox: not found")
    mocker.patch(f"{MODULE}.shared_persona_browser", return_value=persona)
    dialog = build(qtbot, setup)
    dialog.show()

    press_login(dialog)
    qtbot.waitUntil(error_label(dialog).isVisible)
    assert error_label(dialog).text() == "Could not open Firefox: not found"

    persona.open_for_login.side_effect = None
    press_login(dialog)

    qtbot.waitUntil(lambda: persona.open_for_login.call_count == 2)
    assert error_label(dialog).isHidden()
    assert error_label(dialog).text() == ""
