"""Tests for the conflict dialog: a save refused because the record changed on disk, shown side by side (#416)."""

from typing import Any, Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QDialog, QLabel, QPushButton, QWidget
from pytest import fixture, mark
from pytestqt.qtbot import QtBot
from rehuco_agent.dialogs.record_conflict_dialog import (
    ABSENT_TEXT,
    NOTHING_TO_SAVE_TIP,
    ConflictResolution,
    ConflictRow,
    ConflictSide,
    RecordConflictDialog,
    field_label,
)
from rehuco_core import ABSENT, FieldPath, MetadataDifference

TITLE_PATH: Final = ("core", "sources", 0, "title")
URL_PATH: Final = ("core", "sources", 0, "url")
PUBLISHER_PATH: Final = ("core", "sources", 0, "publisher")
TAGS_PATH: Final = ("core", "tags")
LANGUAGE_PATH: Final = ("core", "language")

THEIRS_ONLY: Final = MetadataDifference(TITLE_PATH, "Old", "Old", "Theirs")
"""A detail only the file changed."""
MINE_ONLY: Final = MetadataDifference(URL_PATH, "https://old.example", "https://mine.example", "https://old.example")
"""A detail only the edited document changed."""
BOTH: Final = MetadataDifference(PUBLISHER_PATH, "Old Co", "Mine Co", "Their Co")
"""A detail both sides changed."""
REMOVED_ON_DISK: Final = MetadataDifference(TAGS_PATH, ["a"], ["a"], ABSENT)
"""A detail the file dropped, left unchanged here."""
ADDED_ON_BOTH: Final = MetadataDifference(LANGUAGE_PATH, ABSENT, "en", "fr")
"""A detail neither side had when opened, added on both."""

DIFFERENCES: Final = (THEIRS_ONLY, MINE_ONLY, BOTH, REMOVED_ON_DISK)

SAVE_TIP: Final = "Save, keeping the chosen value of each detail."
"""Save's own tooltip, from the ``.ui``, while it has something to save."""


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


def radios(dialog: RecordConflictDialog) -> list[tuple[QAbstractButton, ...]]:
    """Each row's radios, as its button group holds them: Original, Mine, On Disk.

    :param dialog: the dialog.
    :returns: one tuple per row, in the rows' order.
    """
    return [tuple(group.buttons()) for group in dialog.findChildren(QButtonGroup)]


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
    * verify the On Disk side is picked and kept, only its value is bold, and the field name is plain
    """
    row = ConflictRow(THEIRS_ONLY, parent)

    assert row.kept == "Theirs"
    assert row.theirs.isChecked() and not row.mine.isChecked() and not row.original.isChecked()
    assert row.theirs.font().bold()
    assert not row.mine.font().bold()
    assert not row.original.font().bold()
    assert not row.field.font().bold()


def test_a_detail_only_this_document_changed_starts_on_its_side(parent: QWidget) -> None:
    """The edit made here is kept by default when the file left the detail alone.

    **Test steps:**

    * build the row for a detail only the edited document changed
    * verify the Mine side is picked and kept, only its value is bold, and the field name is plain
    """
    row = ConflictRow(MINE_ONLY, parent)

    assert row.kept == "https://mine.example"
    assert row.mine.isChecked()
    assert row.mine.font().bold()
    assert not row.theirs.font().bold()
    assert not row.original.font().bold()
    assert not row.field.font().bold()


def test_a_detail_both_sides_changed_starts_on_mine_with_both_values_bold(parent: QWidget) -> None:
    """The one real clash reads at a glance: both changed values are bold, the original never is, and the row starts
    on the side the person typed. The field name stays plain, with no tooltip -- the values say it all.

    **Test steps:**

    * build the row for a detail changed both here and on disk
    * verify the Mine side is kept, Mine and On Disk are bold, Original is not
    * verify the field name is plain, untipped, and names the detail
    """
    row = ConflictRow(BOTH, parent)

    assert row.kept == "Mine Co"
    assert row.mine.isChecked()
    assert row.mine.font().bold() and row.theirs.font().bold()
    assert not row.original.font().bold()
    assert not row.field.font().bold()
    assert not row.field.toolTip()
    assert row.field.text() == "core.sources[0].publisher"


def test_the_original_value_is_a_choice_of_its_own(parent: QWidget) -> None:
    """Neither edit may be wanted: the value as opened is a third radio of the same group, and picking it keeps it --
    one the record did not have is kept as ``ABSENT``, removing the detail.

    **Test steps:**

    * build a row for a detail both sides changed, and one for a detail both sides added
    * keep the Original side of each
    * verify each Original radio alone is checked, and the rows keep the original value and ``ABSENT``
    * verify the absent original reads "(none)" in italics, and is not bold
    """
    changed = ConflictRow(BOTH, parent)
    added = ConflictRow(ADDED_ON_BOTH, parent)

    changed.keep(ConflictSide.ORIGINAL)
    added.keep(ConflictSide.ORIGINAL)

    assert changed.original.isChecked() and not changed.mine.isChecked() and not changed.theirs.isChecked()
    assert changed.kept == "Old Co"
    assert added.kept is ABSENT
    assert added.original.text() == ABSENT_TEXT
    assert added.original.font().italic()
    assert not added.original.font().bold()


def test_keep_picks_each_side_in_turn(parent: QWidget) -> None:
    """The three radios are one group: picking a side unchecks the others, and ``kept`` follows.

    **Test steps:**

    * build the row for a detail both sides changed
    * keep On Disk, then Original, then Mine
    * verify the kept value and the one checked radio after each
    """
    row = ConflictRow(BOTH, parent)

    row.keep(ConflictSide.THEIRS)
    assert (row.kept, row.theirs.isChecked(), row.mine.isChecked()) == ("Their Co", True, False)
    row.keep(ConflictSide.ORIGINAL)
    assert (row.kept, row.original.isChecked(), row.theirs.isChecked()) == ("Old Co", True, False)
    row.keep(ConflictSide.MINE)
    assert (row.kept, row.mine.isChecked(), row.original.isChecked()) == ("Mine Co", True, False)


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


def test_the_picks_start_merged_and_name_every_rows_value(qtbot: QtBot) -> None:
    """``chosen`` names the value kept for every row, whichever side it comes from -- what ``resolve_conflict`` puts
    back: the file's for a file-only change, this document's for the rest.

    **Test steps:**

    * open the dialog over one detail of each kind
    * verify every row is chosen: the file's value for the two file-only changes -- a removal as ``ABSENT`` -- and
      this document's for the others
    """
    dialog = dialog_over(qtbot)

    expected: dict[FieldPath, Any] = {
        TITLE_PATH: "Theirs",
        URL_PATH: "https://mine.example",
        PUBLISHER_PATH: "Mine Co",
        TAGS_PATH: ABSENT,
    }
    assert dialog.chosen() == expected


def test_all_on_disk_and_all_mine_pick_one_side_for_every_detail(qtbot: QtBot) -> None:
    """The two bulk buttons are the whole-record answers: take the file, or take this document.

    **Test steps:**

    * open the dialog and press All On Disk
    * verify every detail is chosen with the file's value, a removal as ``ABSENT``
    * press All Mine
    * verify every detail is chosen with this document's value
    """
    dialog = dialog_over(qtbot)

    qtbot.mouseClick(button(dialog, "all_on_disk_button"), Qt.MouseButton.LeftButton)

    theirs: dict[FieldPath, Any] = {
        TITLE_PATH: "Theirs",
        URL_PATH: "https://old.example",
        PUBLISHER_PATH: "Their Co",
        TAGS_PATH: ABSENT,
    }
    assert dialog.chosen() == theirs

    qtbot.mouseClick(button(dialog, "all_mine_button"), Qt.MouseButton.LeftButton)

    mine: dict[FieldPath, Any] = {
        TITLE_PATH: "Old",
        URL_PATH: "https://mine.example",
        PUBLISHER_PATH: "Mine Co",
        TAGS_PATH: ["a"],
    }
    assert dialog.chosen() == mine


def test_chosen_names_the_original_values_kept_absent_included(qtbot: QtBot) -> None:
    """A row kept as *Original* hands back the value as opened -- ``ABSENT`` for one the record did not have, so
    ``resolve_conflict`` removes it.

    **Test steps:**

    * open the dialog over a detail both sides changed and one both sides added
    * click each row's Original radio
    * verify ``chosen`` names the original value and ``ABSENT``
    """
    dialog = dialog_over(qtbot, (BOTH, ADDED_ON_BOTH))
    for original, _, _ in radios(dialog):
        original.click()

    assert dialog.chosen() == {PUBLISHER_PATH: "Old Co", LANGUAGE_PATH: ABSENT}


def test_save_is_disabled_while_every_row_keeps_the_files_value(qtbot: QtBot) -> None:
    """Saving the file's values back is what Discard My Edits does: All On Disk disables Save, its tooltip saying why,
    and moving a row back to Mine enables it with its own tooltip again.

    **Test steps:**

    * open the dialog, and verify Save starts enabled with its own tooltip
    * press All On Disk
    * verify Save is disabled, tipped with the nothing-to-save explanation
    * press All Mine
    * verify Save is enabled again, with its own tooltip
    """
    dialog = dialog_over(qtbot)
    save = button(dialog, "save_button")
    assert save.isEnabled()
    assert save.toolTip() == SAVE_TIP

    qtbot.mouseClick(button(dialog, "all_on_disk_button"), Qt.MouseButton.LeftButton)

    assert not save.isEnabled()
    assert save.toolTip() == NOTHING_TO_SAVE_TIP

    qtbot.mouseClick(button(dialog, "all_mine_button"), Qt.MouseButton.LeftButton)

    assert save.isEnabled()
    assert save.toolTip() == SAVE_TIP


def test_save_is_disabled_when_the_original_kept_is_what_the_file_holds(qtbot: QtBot) -> None:
    """Keeping the value as opened where the file still holds it writes nothing new either: Save is disabled until a
    row keeps a value the file does not hold.

    **Test steps:**

    * open the dialog over a detail only this document changed, so the file still holds the original
    * verify Save starts enabled, on Mine
    * click the row's Original radio
    * verify Save is disabled with the nothing-to-save tooltip
    * click the row's Mine radio
    * verify Save is enabled again, with its own tooltip
    """
    dialog = dialog_over(qtbot, (MINE_ONLY,))
    save = button(dialog, "save_button")
    ((original, mine, _),) = radios(dialog)
    assert save.isEnabled()

    original.click()

    assert dialog.chosen() == {URL_PATH: "https://old.example"}
    assert not save.isEnabled()
    assert save.toolTip() == NOTHING_TO_SAVE_TIP

    mine.click()

    assert save.isEnabled()
    assert save.toolTip() == SAVE_TIP


def test_save_starts_disabled_when_only_the_file_changed(qtbot: QtBot) -> None:
    """A conflict whose rows all start on the file's side has nothing of this document's to save until one is moved:
    an Original that differs from the file is something to save.

    **Test steps:**

    * open the dialog over a detail only the file changed
    * verify Save is disabled
    * click the row's Original radio
    * verify Save is enabled, and the original value is chosen
    """
    dialog = dialog_over(qtbot, (THEIRS_ONLY,))
    save = button(dialog, "save_button")
    ((original, _, _),) = radios(dialog)
    assert not save.isEnabled()

    original.click()

    assert save.isEnabled()
    assert dialog.chosen() == {TITLE_PATH: "Old"}


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


def test_a_conflict_with_no_differing_value_says_there_is_nothing_to_save(qtbot: QtBot) -> None:
    """Both sides may have made the same edit: there is nothing to pick and nothing of this document's to save, so the
    message points to Discard My Edits and Save is disabled, its tooltip saying why.

    **Test steps:**

    * open the dialog over no differences
    * verify the message says both hold the same values, nothing is left to save, and names Discard My Edits
    * verify the bulk buttons and Save are disabled, Save tipped with the nothing-to-save explanation
    * verify nothing is chosen, and Discard My Edits is still there to press
    """
    dialog = dialog_over(qtbot, ())

    text = message(dialog)
    assert "both now hold the same values" in text
    assert "nothing of yours to save" in text
    assert "<i>Discard My Edits</i> loads the file as it is" in text
    assert not button(dialog, "all_mine_button").isEnabled()
    assert not button(dialog, "all_on_disk_button").isEnabled()
    assert not button(dialog, "save_button").isEnabled()
    assert button(dialog, "save_button").toolTip() == NOTHING_TO_SAVE_TIP
    assert button(dialog, "discard_button").isEnabled()
    assert not dialog.chosen()
