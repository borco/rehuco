"""Tests for the mapping wizard: ``MapRootsDialog`` and its per-root ``MapRootRow`` (#514)."""

from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QLineEdit, QPushButton
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.map_root_row import MapRootRow
from rehuco_agent.rehuco.map_roots_dialog import MapRootsDialog
from rehuco_agent.settings.map_roots_dialog_settings import MapRootsDialogSettings
from rehuco_core import RehucoRoot

TUTORIALS = RehucoRoot(uuid4(), "Tutorials", "//nas/data/Tutorials")
MUSIC = RehucoRoot(uuid4(), "Music", "//nas/data/Music")


@fixture(autouse=True)
def mock_persistent_settings(mocker: MockerFixture) -> Any:
    """Stand in for ``persistent_settings()`` so geometry load/save never touch real ``QSettings`` storage.

    ``value`` returns whatever default it was called with, so no geometry is reported saved.

    :param mocker: pytest-mock fixture.
    :returns: the patched function.
    """
    settings = mocker.MagicMock()
    settings.value.side_effect = lambda key, default=None, type=None: default  # noqa: A002
    return mocker.patch("rehuco_agent.rehuco.map_roots_dialog.persistent_settings", return_value=settings)


def rows_of(dialog: MapRootsDialog) -> list[MapRootRow]:
    """The dialog's rows, in order.

    :param dialog: the dialog.
    :returns: its rows.
    """
    return dialog.findChildren(MapRootRow)


def path_edit_of(row: MapRootRow) -> QLineEdit:
    """The row's folder line.

    :param row: the row.
    :returns: its folder line edit.
    """
    edit = row.findChild(QLineEdit, "path_edit")
    assert isinstance(edit, QLineEdit)
    return edit


def skip_of(row: MapRootRow) -> QCheckBox:
    """The row's *Skip* box.

    :param row: the row.
    :returns: its checkbox.
    """
    box = row.findChild(QCheckBox, "skip_check_box")
    assert isinstance(box, QCheckBox)
    return box


def make_dialog(qtbot: QtBot, *roots: RehucoRoot) -> MapRootsDialog:
    """Build a dialog over ``roots``, owned by the test.

    :param qtbot: pytest-qt's bot.
    :param roots: the roots to ask about.
    :returns: the dialog.
    """
    dialog = MapRootsDialog(roots)
    qtbot.addWidget(dialog)
    return dialog


def accepted(dialog: MapRootsDialog) -> MapRootsDialog:
    """Close the dialog the way OK does.

    :param dialog: the dialog.
    :returns: the same dialog.
    """
    dialog.done(QDialog.DialogCode.Accepted)
    return dialog


def test_a_row_is_built_per_root_with_its_label_and_location(qtbot: QtBot) -> None:
    """Each root gets a row showing its label and its read-only location.

    **Test steps:**

    * build a dialog over two roots
    * verify two rows, in order, each showing the root's label and location, the location read-only
    * verify the folder line starts empty and *Skip* unchecked
    """
    dialog = make_dialog(qtbot, TUTORIALS, MUSIC)

    rows = rows_of(dialog)
    assert [row.root for row in rows] == [TUTORIALS, MUSIC]
    first = rows[0]
    label = first.findChild(QLabel, "label_label")
    location = first.findChild(QLineEdit, "location_edit")
    assert isinstance(label, QLabel) and isinstance(location, QLineEdit)
    assert label.text() == "Tutorials"
    assert location.text() == "//nas/data/Tutorials"
    assert location.isReadOnly()
    assert not path_edit_of(first).text()
    assert not skip_of(first).isChecked()


def test_a_root_with_an_empty_name_is_shown_and_asked_about_by_its_location(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A root whose name is empty is named by its location, in its row and in its folder question.

    **Test steps:**

    * build a dialog over a root with an empty name, and replace ``QFileDialog.getExistingDirectory``
    * verify the row's name shows the location, and the folder question is titled with it
    """
    root = RehucoRoot(uuid4(), "", "//nas/data/Unnamed")
    dialog = make_dialog(qtbot, root)
    row = rows_of(dialog)[0]
    ask = mocker.patch("rehuco_agent.rehuco.map_root_row.QFileDialog.getExistingDirectory", return_value="")

    row.choose_folder()

    label = row.findChild(QLabel, "label_label")
    assert isinstance(label, QLabel)
    assert label.text() == root.location
    assert ask.call_args.args[1] == f"Folder of {root.location}"


def test_browse_puts_the_chosen_folder_in_the_line(mocker: MockerFixture, qtbot: QtBot, tmp_path: Path) -> None:
    """*Browse...* fills the folder line with what the folder question answers, and leaves it when cancelled.

    **Test steps:**

    * replace the row's folder question to answer a folder, and click *Browse...*
    * verify the line holds that folder
    * replace the question to answer nothing, and click again
    * verify the line is unchanged
    """
    dialog = make_dialog(qtbot, TUTORIALS)
    row = rows_of(dialog)[0]
    button = row.findChild(QPushButton, "browse_button")
    assert isinstance(button, QPushButton)

    mocker.patch.object(row, "choose_folder", return_value=str(tmp_path))
    button.click()
    assert path_edit_of(row).text() == str(tmp_path)

    mocker.patch.object(row, "choose_folder", return_value="")
    button.click()
    assert path_edit_of(row).text() == str(tmp_path)


def test_the_folder_question_starts_from_the_typed_folder(mocker: MockerFixture, qtbot: QtBot, tmp_path: Path) -> None:
    """The real folder question is asked for this root, starting at what is typed.

    **Test steps:**

    * type a folder, replace ``QFileDialog.getExistingDirectory`` to answer another
    * ask the row to choose a folder
    * verify the answer is returned and the question started at the typed folder
    """
    dialog = make_dialog(qtbot, TUTORIALS)
    row = rows_of(dialog)[0]
    path_edit_of(row).setText(str(tmp_path))
    ask = mocker.patch("rehuco_agent.rehuco.map_root_row.QFileDialog.getExistingDirectory", return_value="picked")

    assert row.choose_folder() == "picked"

    ask.assert_called_once_with(row, "Folder of Tutorials", str(tmp_path))


def test_skip_disables_the_folder_and_browse(qtbot: QtBot) -> None:
    """A skipped row cannot be given a folder, and gets it back when un-skipped.

    **Test steps:**

    * check *Skip* on a row
    * verify the folder line and *Browse...* are disabled
    * uncheck it
    * verify both are enabled again
    """
    dialog = make_dialog(qtbot, TUTORIALS)
    row = rows_of(dialog)[0]
    button = row.findChild(QPushButton, "browse_button")
    assert isinstance(button, QPushButton)

    skip_of(row).setChecked(True)
    assert not path_edit_of(row).isEnabled()
    assert not button.isEnabled()

    skip_of(row).setChecked(False)
    assert path_edit_of(row).isEnabled()
    assert button.isEnabled()


def test_accepting_reports_the_filled_and_the_skipped_rows(qtbot: QtBot, tmp_path: Path) -> None:
    """OK gives the folder of each filled row and the ids of the skipped ones; a skipped row's folder is not mapped.

    **Test steps:**

    * build a dialog over three roots; fill the first, fill and skip the second, leave the third empty
    * accept it
    * verify ``mapped`` is only the first and ``skipped`` only the second
    """
    third = RehucoRoot(uuid4(), "Third", "//nas/data/Third")
    dialog = make_dialog(qtbot, TUTORIALS, MUSIC, third)
    first, second, _ = rows_of(dialog)
    path_edit_of(first).setText(f"  {tmp_path}  ")
    path_edit_of(second).setText(str(tmp_path / "music"))
    skip_of(second).setChecked(True)

    accepted(dialog)

    assert dialog.mapped == {TUTORIALS.root_id: tmp_path}
    assert dialog.skipped == [MUSIC.root_id]


def test_a_relative_path_counts_as_not_filled(qtbot: QtBot) -> None:
    """Only an absolute folder is a mapping: a relative one is as good as blank.

    **Test steps:**

    * type a relative path into the only row and accept
    * verify nothing is mapped or skipped
    """
    dialog = make_dialog(qtbot, TUTORIALS)
    path_edit_of(rows_of(dialog)[0]).setText("relative/folder")

    accepted(dialog)

    assert dialog.mapped == {}
    assert dialog.skipped == []


def test_cancelling_reports_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    """Cancel maps and skips nothing, whatever the rows hold.

    **Test steps:**

    * fill one row and skip another
    * reject the dialog
    * verify ``mapped`` and ``skipped`` are empty
    """
    dialog = make_dialog(qtbot, TUTORIALS, MUSIC)
    first, second = rows_of(dialog)
    path_edit_of(first).setText(str(tmp_path))
    skip_of(second).setChecked(True)

    dialog.done(QDialog.DialogCode.Rejected)

    assert dialog.mapped == {}
    assert dialog.skipped == []


def test_geometry_is_restored_when_saved(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Saved geometry is restored on construction.

    **Test steps:**

    * seed ``MapRootsDialogSettings.load`` to report geometry bytes, and spy on ``restoreGeometry``
    * build the dialog
    * verify ``restoreGeometry`` got those bytes
    """

    def fake_load(self: MapRootsDialogSettings, settings: object) -> None:
        del settings
        self.geometry = b"geometry-bytes"

    mocker.patch.object(MapRootsDialogSettings, "load", fake_load)
    restore = mocker.patch.object(MapRootsDialog, "restoreGeometry")

    make_dialog(qtbot, TUTORIALS)

    restore.assert_called_once_with(QByteArray(b"geometry-bytes"))


def test_geometry_is_not_restored_when_nothing_was_saved(mocker: MockerFixture, qtbot: QtBot) -> None:
    """With nothing saved, ``restoreGeometry`` is not called.

    **Test steps:**

    * spy on ``restoreGeometry`` and build the dialog
    * verify no call
    """
    restore = mocker.patch.object(MapRootsDialog, "restoreGeometry")

    make_dialog(qtbot, TUTORIALS)

    restore.assert_not_called()


def test_every_exit_saves_the_geometry(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing through ``done`` saves the geometry, however the dialog closed.

    **Test steps:**

    * build the dialog, make ``saveGeometry`` answer known bytes and spy on the settings' ``save``
    * reject the dialog
    * verify the bytes were recorded and ``save`` was called once
    """
    dialog = make_dialog(qtbot, TUTORIALS)
    mocker.patch.object(dialog, "saveGeometry", return_value=QByteArray(b"new-geometry"))
    save = mocker.patch.object(MapRootsDialogSettings, "save")

    dialog.done(QDialog.DialogCode.Rejected)

    settings = dialog._MapRootsDialog__settings  # type: ignore[attr-defined]  # pylint: disable=protected-access
    assert settings.geometry == b"new-geometry"
    save.assert_called_once()
