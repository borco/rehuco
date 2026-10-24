"""Tests for the Add Root dialog and the storage words the Roots view shares (#378)."""

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


def test_the_dialog_asks_only_for_the_folder(qtbot: QtBot) -> None:
    """What the folder lives on is detected when it is mapped, so the dialog has a folder field and no storage choice.

    **Test steps:**

    * open the dialog
    * verify it has a folder field and no combo box
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)

    assert dialog.findChild(QLineEdit, "folder_edit") is not None
    assert dialog.findChild(QComboBox) is None


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


def test_the_dialog_reads_back_the_folder_trimmed(qtbot: QtBot) -> None:
    """What the dock is handed: the folder, trimmed.

    **Test steps:**

    * type a folder with blanks around it
    * verify the folder is read back without them
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)

    dialog.folder = "  /fake/refs  "

    assert dialog.folder == "/fake/refs"


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


def browse_to(mocker: MockerFixture, dialog: AddRootDialog, folder: Path) -> None:
    """Press Browse with the system's folder dialog answering ``folder``.

    :param mocker: pytest-mock fixture.
    :param dialog: the dialog.
    :param folder: what the system dialog answers.
    """
    mocker.patch("rehuco_agent.rehuco.add_root_dialog.QFileDialog.getExistingDirectory", return_value=str(folder))
    browse = dialog.findChild(QPushButton, "browse_button")
    assert browse is not None
    browse.click()


def test_choosing_the_first_folder_names_the_root_after_it(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The name field is filled with the folder's name once a folder is browsed to, and the name is also its
    placeholder.

    **Test steps:**

    * open the dialog and verify the field and its placeholder are empty
    * browse to a folder
    * verify the field and the placeholder hold the folder's name
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    assert not dialog.name_edit.text()
    assert not dialog.name_edit.placeholderText()

    browse_to(mocker, dialog, Path.cwd() / "Tutorials")

    assert dialog.name_edit.text() == "Tutorials"
    assert dialog.name_edit.placeholderText() == "Tutorials"


def test_choosing_another_folder_leaves_a_name_that_is_there(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A name already in the field -- typed, or filled by the first folder -- is not replaced by a later folder's, but
    the placeholder follows; an emptied field is filled again.

    **Test steps:**

    * browse to a folder and then to another
    * verify the name is the first folder's and the placeholder the second's
    * clear the name and browse to a third folder
    * verify the name is the third folder's
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    browse_to(mocker, dialog, Path.cwd() / "first")

    browse_to(mocker, dialog, Path.cwd() / "second")

    assert dialog.name_edit.text() == "first"
    assert dialog.name_edit.placeholderText() == "second"
    dialog.name_edit.setText("")
    browse_to(mocker, dialog, Path.cwd() / "third")
    assert dialog.name_edit.text() == "third"


def test_a_typed_folder_names_the_root_once_it_is_left(qtbot: QtBot) -> None:
    """Typing a folder does not fill the name on each keystroke, which would stop at its first letters; leaving the
    folder field does, and the folder setter never does.

    **Test steps:**

    * set a folder through the setter and verify the name is empty
    * type letters one by one and verify the name stays empty, then leave the field
    * verify the name is the folder's
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    dialog.folder = str(Path.cwd() / "set")
    assert not dialog.name_edit.text()

    folder_edit = dialog.findChild(QLineEdit, "folder_edit")
    assert folder_edit is not None
    folder_edit.setText("")
    for text in ("a", "ab", "abc"):
        folder_edit.setText(text)
        assert not dialog.name_edit.text()
    folder_edit.setText(str(Path.cwd() / "typed"))
    folder_edit.editingFinished.emit()

    assert dialog.name_edit.text() == "typed"


def test_the_default_name_button_puts_the_current_folders_name_back(qtbot: QtBot, mocker: MockerFixture) -> None:
    """The button is for the folder now named: it is off while there is no folder or the field already holds its name,
    and sets the field to it otherwise.

    **Test steps:**

    * verify the action is disabled with no folder
    * browse to a folder, then another, and type a name
    * verify the action is enabled, and that triggering it sets the field to the current folder's name and disables it
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    assert not dialog.default_name_action.isEnabled()

    browse_to(mocker, dialog, Path.cwd() / "first")
    assert not dialog.default_name_action.isEnabled()
    browse_to(mocker, dialog, Path.cwd() / "second")
    assert dialog.default_name_action.isEnabled()
    dialog.name_edit.setText("mine")

    dialog.default_name_action.trigger()

    assert dialog.name_edit.text() == "second"
    assert not dialog.default_name_action.isEnabled()


def test_the_name_read_back_is_the_one_typed_or_else_the_default(qtbot: QtBot) -> None:
    """What the dock is handed: the typed name trimmed, or the folder's name when nothing is typed -- empty only while
    there is no folder.

    **Test steps:**

    * read the name with no folder, then with a folder and nothing typed, then with a name typed with blanks
    * verify empty, the folder's name, the trimmed name
    """
    dialog = AddRootDialog()
    qtbot.addWidget(dialog)
    assert dialog.name == ""

    dialog.folder = str(Path.cwd() / "refs")
    assert dialog.name == "refs"

    dialog.name_edit.setText("  mine  ")
    assert dialog.name == "mine"


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
