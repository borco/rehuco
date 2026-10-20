"""Tests for the Add Root dialog and the storage combo it shares with the root card (#378)."""

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import add_root_dialog
from rehuco_agent.rehuco.add_root_dialog import AddRootDialog
from rehuco_agent.rehuco.root_storage import (
    ROOT_STORAGE_ICONS,
    ROOT_STORAGE_LABELS,
    ROOT_STORAGE_OFFLINE_ROWS,
    ROOT_STORAGE_OFFLINE_TOOLTIPS,
    fill_root_storage_combo,
    select_root_storage,
    selected_root_storage,
)
from rehuco_agent.settings.root_catalog_settings import shared_root_catalog_settings
from rehuco_core import RootStorage

from rehuco_agent_tests.conftest import FakeSettings


def test_every_storage_has_a_glyph_a_label_and_two_offline_texts() -> None:
    """The four mappings are complete, so nothing can be drawn or worded without an answer.

    **Test steps:**

    * read each mapping
    * verify every storage is a key of each
    """
    for mapping in (ROOT_STORAGE_ICONS, ROOT_STORAGE_LABELS, ROOT_STORAGE_OFFLINE_ROWS, ROOT_STORAGE_OFFLINE_TOOLTIPS):
        assert set(mapping) == set(RootStorage)


def test_the_combo_lists_every_storage_with_its_glyph_and_hands_the_enum_back(qtbot: QtBot) -> None:
    """Filling the combo adds one row per storage, in order, each with an icon, and reading it returns the enum --
    item data comes back from Qt as the plain string.

    **Test steps:**

    * fill a combo twice, so a second fill replaces the first
    * verify the rows, their icons, and what each selection reads back as
    """
    combo = QComboBox()
    qtbot.addWidget(combo)

    fill_root_storage_combo(combo)
    fill_root_storage_combo(combo)

    assert [combo.itemText(row) for row in range(combo.count())] == list(ROOT_STORAGE_LABELS.values())
    assert not any(combo.itemIcon(row).isNull() for row in range(combo.count()))
    for row, storage in enumerate(RootStorage):
        combo.setCurrentIndex(row)
        assert selected_root_storage(combo) is storage


def test_selecting_a_storage_does_not_tell_anyone(qtbot: QtBot) -> None:
    """Showing a storage is not choosing one: the combo's signals are blocked meanwhile, and restored after.

    **Test steps:**

    * select a storage on a combo whose ``activated`` and ``currentIndexChanged`` are watched
    * verify it shows the storage, nothing was emitted, and signals are on again
    """
    combo = QComboBox()
    qtbot.addWidget(combo)
    fill_root_storage_combo(combo)
    emitted: list[int] = []
    combo.currentIndexChanged.connect(emitted.append)

    select_root_storage(combo, RootStorage.COMPACT_DISK)

    assert selected_root_storage(combo) is RootStorage.COMPACT_DISK
    assert not emitted
    assert not combo.signalsBlocked()


def test_an_empty_combo_reads_as_local(qtbot: QtBot) -> None:
    """Nothing chosen is the default storage, never an error.

    **Test steps:**

    * read the storage of a combo that was never filled
    * verify local
    """
    combo = QComboBox()
    qtbot.addWidget(combo)

    assert selected_root_storage(combo) is RootStorage.LOCAL


def test_the_dialog_asks_for_the_storage_first_and_defaults_to_local(qtbot: QtBot) -> None:
    """The storage is the first row of the form, ahead of the folder, because it will decide what the folder is picked
    from.

    **Test steps:**

    * open the dialog
    * verify the storage combo sits above the folder field, offers every storage, and starts on Local folder
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.storage_combo.count() == len(RootStorage)
    assert dialog.storage is RootStorage.LOCAL
    folder_edit = dialog.findChild(QLineEdit, "folder_edit")
    assert folder_edit is not None
    assert dialog.storage_combo.geometry().top() < folder_edit.geometry().top()


def test_ok_needs_an_absolute_folder(qtbot: QtBot) -> None:
    """The dialog cannot be accepted with nothing typed, with only blanks, or with a relative folder -- which would be
    read against the app's working directory, something the folder picker beside the field never hands back.

    **Test steps:**

    * open the dialog, then type an absolute folder, blanks, and a relative folder
    * verify OK is off, on, off and off
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    assert not dialog.ok_button.isEnabled()

    dialog.folder = str(Path.cwd())
    assert dialog.ok_button.isEnabled()

    dialog.folder = "   "
    assert not dialog.ok_button.isEnabled()

    dialog.folder = "tutorials"
    assert not dialog.ok_button.isEnabled()


def test_the_dialog_reads_back_the_folder_and_the_storage_chosen(qtbot: QtBot) -> None:
    """What the dock is handed: the folder trimmed, and the storage the combo shows.

    **Test steps:**

    * type a folder with blanks around it and choose Network share
    * verify the folder and the storage
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)

    dialog.folder = "  /fake/refs  "
    dialog.storage_combo.setCurrentIndex(dialog.storage_combo.findData(RootStorage.NETWORK))

    assert dialog.folder == "/fake/refs"
    assert dialog.storage is RootStorage.NETWORK


@mark.parametrize("picked", ["/picked/folder", ""])
def test_browse_fills_the_folder_unless_cancelled(qtbot: QtBot, mocker: MockerFixture, picked: str) -> None:
    """The system's folder dialog fills the field; cancelling leaves what was there.

    **Test steps:**

    * type a folder, press Browse with the system dialog answering a folder, then nothing
    * verify the field holds the chosen folder, or the typed one after a cancel
    """
    chooser = mocker.patch("rehuco_agent.rehuco.add_root_dialog.QFileDialog.getExistingDirectory", return_value=picked)
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    dialog.folder = "/typed/folder"

    browse = dialog.findChild(QPushButton, "browse_button")
    assert browse is not None
    browse.click()

    chooser.assert_called_once()
    assert dialog.folder == (picked or "/typed/folder")


@fixture(name="stored")
def stored_fixture(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so an accepted dialog never touches real storage.

    :param mocker: pytest-mock fixture.
    :returns: the store the dialog writes to.
    """
    fake = FakeSettings()
    mocker.patch.object(add_root_dialog, "persistent_settings", return_value=fake)
    return fake


def test_the_dialog_shows_the_scan_after_adding_setting(qtbot: QtBot) -> None:
    """The checkbox starts on the setting's value, which is on by default (#542).

    **Test steps:**

    * open the dialog over the default setting, then over a setting of off
    * verify the box is checked, then unchecked
    """
    first = AddRootDialog()
    qtbot.addWidget(first)
    assert first.scan_after_adding
    assert first.scan_after_adding_check_box.isChecked()

    shared_root_catalog_settings().scan_after_adding = False
    second = AddRootDialog()
    qtbot.addWidget(second)

    assert not second.scan_after_adding


def test_accepting_the_dialog_remembers_the_scan_after_adding_choice(qtbot: QtBot, stored: FakeSettings) -> None:
    """Unticking the box and accepting changes the setting and persists it; the next dialog shows it.

    **Test steps:**

    * untick the box and accept
    * verify the setting is off, the store holds it, and a new dialog shows an unticked box
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    dialog.scan_after_adding_check_box.setChecked(False)

    dialog.accept()

    assert shared_root_catalog_settings().scan_after_adding is False
    stored.beginGroup("root_catalog")
    assert stored.value("scan_after_adding") is False
    stored.endGroup()
    again = AddRootDialog()
    qtbot.addWidget(again)
    assert not again.scan_after_adding


def test_accepting_an_unchanged_choice_writes_nothing(qtbot: QtBot, stored: FakeSettings) -> None:
    """Only a changed choice is saved, so most accepts never touch the settings file.

    **Test steps:**

    * accept the dialog without touching the box
    * verify the store is still empty
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)

    dialog.accept()

    stored.beginGroup("root_catalog")
    assert stored.value("scan_after_adding") is None


def test_cancelling_the_dialog_still_remembers_the_scan_after_adding_choice(qtbot: QtBot, stored: FakeSettings) -> None:
    """The choice is saved on every exit path, like a dialog's geometry (#542).

    **Test steps:**

    * untick the box and reject
    * verify the setting is off and the store holds it
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    dialog.scan_after_adding_check_box.setChecked(False)

    dialog.reject()

    assert shared_root_catalog_settings().scan_after_adding is False
    stored.beginGroup("root_catalog")
    assert stored.value("scan_after_adding") is False
