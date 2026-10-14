"""Tests for the conflict dialog: a save refused because the record changed on disk, shown side by side (#416)."""

from typing import Any, Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QWidget
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.record_conflict_dialog import (
    ABSENT_TEXT,
    ConflictResolution,
    ConflictRow,
    RecordConflictDialog,
    field_label,
)
from rehuco_core import ABSENT, FieldPath, MetadataDifference

TITLE_PATH: Final = ("core", "sources", 0, "title")
URL_PATH: Final = ("core", "sources", 0, "url")
PUBLISHER_PATH: Final = ("core", "sources", 0, "publisher")
TAGS_PATH: Final = ("core", "tags")

THEIRS_ONLY: Final = MetadataDifference(TITLE_PATH, "Old", "Old", "Theirs")
"""A detail only the file changed."""
MINE_ONLY: Final = MetadataDifference(URL_PATH, "https://old.example", "https://mine.example", "https://old.example")
"""A detail only the edited document changed."""
BOTH: Final = MetadataDifference(PUBLISHER_PATH, "Old Co", "Mine Co", "Their Co")
"""A detail both sides changed."""
REMOVED_ON_DISK: Final = MetadataDifference(TAGS_PATH, ["a"], ["a"], ABSENT)
"""A detail the file dropped, left unchanged here."""

DIFFERENCES: Final = (THEIRS_ONLY, MINE_ONLY, BOTH, REMOVED_ON_DISK)


@fixture
def parent(qtbot: QtBot) -> QWidget:
    """A real widget to parent the dialog and its rows to, registered for teardown.

    :param qtbot: pytest-qt fixture.
    :returns: the widget.
    """
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def dialog_over(qtbot: QtBot, differences: tuple[MetadataDifference, ...] = DIFFERENCES) -> RecordConflictDialog:
    """A conflict dialog for a document named ``Sculpting``, registered for teardown.

    :param qtbot: pytest-qt fixture.
    :param differences: what the two sides disagree on.
    :returns: the dialog, not shown.
    """
    dialog = RecordConflictDialog("Sculpting", differences)
    qtbot.addWidget(dialog)
    return dialog


def button(dialog: RecordConflictDialog, name: str) -> QPushButton:
    """One of the dialog's buttons, by its ``.ui`` name.

    :param dialog: the dialog.
    :param name: the button's object name.
    :returns: the button.
    """
    found = dialog.findChild(QPushButton, name)
    assert isinstance(found, QPushButton)
    return found


def message(dialog: RecordConflictDialog) -> str:
    """What the dialog says above its rows.

    :param dialog: the dialog.
    :returns: the message label's text.
    """
    found = dialog.findChild(QLabel, "message_label")
    assert isinstance(found, QLabel)
    return found.text()


@mark.parametrize(
    ("path", "label"),
    [
        (("core", "title"), "core.title"),
        (TITLE_PATH, "core.sources[0].title"),
        (("tutorial", "chapters", 2, 0), "tutorial.chapters[2][0]"),
    ],
)
def test_a_field_is_named_by_its_keys_and_list_indexes(path: FieldPath, label: str) -> None:
    """A detail's name in the grid reads like the path a developer would write, so two rows of one list are told apart.

    **Test steps:**

    * name a plain path, one through a list item, and one through two list indexes in a row
    * verify keys are joined by dots and indexes are bracketed, with no leading dot
    """
    assert field_label(path) == label


def test_a_detail_only_the_file_changed_starts_on_the_files_side(parent: QWidget) -> None:
    """A one-sided change is already merged when the dialog opens: Save alone keeps both sides' edits.

    **Test steps:**

    * build the row for a detail only the file changed
    * verify the On Disk side is picked, and the field name is not bold
    """
    row = ConflictRow(THEIRS_ONLY, parent)

    assert row.keeps_theirs
    assert row.theirs.isChecked() and not row.mine.isChecked()
    assert not row.field.font().bold()


def test_a_detail_only_this_document_changed_starts_on_its_side(parent: QWidget) -> None:
    """The edit made here is kept by default when the file left the detail alone.

    **Test steps:**

    * build the row for a detail only the edited document changed
    * verify the Mine side is picked, and the field name is not bold
    """
    row = ConflictRow(MINE_ONLY, parent)

    assert not row.keeps_theirs
    assert row.mine.isChecked()
    assert not row.field.font().bold()


def test_a_detail_both_sides_changed_starts_on_mine_in_bold(parent: QWidget) -> None:
    """The one real clash is called out: bold, with a tooltip saying why, and on the side the person typed.

    **Test steps:**

    * build the row for a detail changed both here and on disk
    * verify the Mine side is picked, and the field name is bold with its tooltip
    """
    row = ConflictRow(BOTH, parent)

    assert not row.keeps_theirs
    assert row.field.font().bold()
    assert row.field.toolTip() == "Changed both here and on disk."
    assert row.field.text() == "core.sources[0].publisher"


def test_a_side_without_the_detail_shows_none_in_italics(parent: QWidget) -> None:
    """A missing value must not read as an empty string: it says so, set apart in italics.

    **Test steps:**

    * build the row for a detail the file removed
    * verify the On Disk side reads "(none)" in italics, and the other sides show the list as JSON, upright
    """
    row = ConflictRow(REMOVED_ON_DISK, parent)

    assert (row.theirs.text(), row.theirs.toolTip()) == (ABSENT_TEXT, ABSENT_TEXT)
    assert row.theirs.font().italic()
    assert row.original.text() == '["a"]'
    assert row.mine.text() == '["a"]'
    assert not row.original.font().italic()
    assert not row.mine.font().italic()


def test_a_long_value_is_elided_on_one_line_with_all_of_it_in_the_tooltip(parent: QWidget) -> None:
    """A description pasted into a cell would blow the grid apart: it is flattened and cut, the tooltip keeps it.

    **Test steps:**

    * build a row whose file value is a long, multi-line string
    * verify the shown text is shorter, holds no line break, and the tooltip is the value itself
    """
    long_text = "First line\n" + "word " * 200
    row = ConflictRow(MetadataDifference(("core", "description"), "", "", long_text), parent)

    assert "\n" not in row.theirs.text()
    assert len(row.theirs.text()) < len(long_text)
    assert row.theirs.toolTip() == long_text


def test_the_picks_start_merged_and_name_the_files_values(qtbot: QtBot) -> None:
    """``chosen`` names only the details kept as the file has them -- what ``resolve_conflict`` puts back.

    **Test steps:**

    * open the dialog over one detail of each kind
    * verify only the two file-only changes are chosen, with the file's value -- a removal as ``ABSENT``
    """
    dialog = dialog_over(qtbot)

    assert dialog.chosen() == {TITLE_PATH: "Theirs", TAGS_PATH: ABSENT}


def test_all_on_disk_and_all_mine_pick_one_side_for_every_detail(qtbot: QtBot) -> None:
    """The two bulk buttons are the whole-record answers: take the file, or take this document.

    **Test steps:**

    * open the dialog and press All On Disk
    * verify every detail is chosen with the file's value, a removal as ``ABSENT``
    * press All Mine
    * verify nothing is chosen
    """
    dialog = dialog_over(qtbot)

    qtbot.mouseClick(button(dialog, "all_on_disk_button"), Qt.MouseButton.LeftButton)

    expected: dict[FieldPath, Any] = {
        TITLE_PATH: "Theirs",
        URL_PATH: "https://old.example",
        PUBLISHER_PATH: "Their Co",
        TAGS_PATH: ABSENT,
    }
    assert dialog.chosen() == expected

    qtbot.mouseClick(button(dialog, "all_mine_button"), Qt.MouseButton.LeftButton)

    assert not dialog.chosen()


@mark.parametrize(
    ("name", "resolution"),
    [("save_button", ConflictResolution.SAVE), ("discard_button", ConflictResolution.DISCARD)],
)
def test_save_and_discard_close_the_dialog_with_their_choice(
    qtbot: QtBot, name: str, resolution: ConflictResolution
) -> None:
    """Both close the dialog as accepted; the caller tells them apart by ``resolution``.

    **Test steps:**

    * open the dialog and press Save, or Discard My Edits
    * verify it closed accepted, with that resolution
    """
    dialog = dialog_over(qtbot)
    assert dialog.resolution is ConflictResolution.CANCEL

    qtbot.mouseClick(button(dialog, name), Qt.MouseButton.LeftButton)

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.resolution is resolution


def test_cancel_closes_the_dialog_as_cancelled(qtbot: QtBot) -> None:
    """Cancel leaves the edits unsaved: the dialog is rejected and says so.

    **Test steps:**

    * show the dialog and press Cancel
    * verify it closed rejected, with the cancel resolution
    """
    dialog = dialog_over(qtbot)
    dialog.show()
    qtbot.waitExposed(dialog)

    qtbot.mouseClick(button(dialog, "cancel_button"), Qt.MouseButton.LeftButton)

    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.resolution is ConflictResolution.CANCEL


def test_escape_closes_the_dialog_as_cancelled(qtbot: QtBot) -> None:
    """Esc is the keyboard's Cancel, never a silent Save.

    **Test steps:**

    * show the dialog and press Esc
    * verify it closed rejected, with the cancel resolution
    """
    dialog = dialog_over(qtbot)
    dialog.show()
    qtbot.waitExposed(dialog)

    qtbot.keyClick(dialog, Qt.Key.Key_Escape)

    assert not dialog.isVisible()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.resolution is ConflictResolution.CANCEL


def test_the_message_names_the_document(qtbot: QtBot) -> None:
    """The person is told which record changed, and what the grid is for.

    **Test steps:**

    * open the dialog over some differences
    * verify the message names the document and asks for a pick, and both bulk buttons are enabled
    """
    dialog = dialog_over(qtbot)

    assert message(dialog).startswith('"Sculpting" was changed on disk since you opened it. Pick the value')
    assert button(dialog, "all_mine_button").isEnabled()
    assert button(dialog, "all_on_disk_button").isEnabled()


def test_a_conflict_with_no_differing_detail_says_save_keeps_them(qtbot: QtBot) -> None:
    """Both sides may have made the same edit: there is nothing to pick, and the message says Save is safe.

    **Test steps:**

    * open the dialog over no differences
    * verify the message says both carry the same details, the bulk buttons are disabled, and nothing is chosen
    """
    dialog = dialog_over(qtbot, ())

    assert "both now carry the same details" in message(dialog)
    assert not button(dialog, "all_mine_button").isEnabled()
    assert not button(dialog, "all_on_disk_button").isEnabled()
    assert not dialog.chosen()
