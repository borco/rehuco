"""Tests for the Add Roots dialog's parts on their own (#578): the browser and its ``+``, the staging list's model and
delegate, a folder's editors, and *New layout…*.
"""

import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QItemSelectionModel, QModelIndex, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QLineEdit, QStyle, QStyleOptionViewItem, QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.new_layout_dialog import NewLayoutDialog
from rehuco_agent.rehuco.new_root_item_editor import CHECKING, NEW_LAYOUT, NewRootItemEditor
from rehuco_agent.rehuco.root_candidate_delegate import UNMAPPED, RootCandidateDelegate
from rehuco_agent.rehuco.root_candidates_model import CandidateRole, RootCandidatesModel
from rehuco_agent.rehuco.roots_browser import AddButtonDelegate, RootsBrowser
from rehuco_agent.settings.root_catalog_settings import DEFAULT_ROOT_LAYOUTS, RootLayout
from rehuco_core import CandidateKind, RootCandidate, RootPick

pytestmark = mark.usefixtures("real_path_stat")

PRESETS = (*DEFAULT_ROOT_LAYOUTS, RootLayout("By title", {"tutorial": ("{title}",)}, {}))


def mouse_release(point: QPoint) -> QMouseEvent:
    """A left button's release at a point.

    :param point: where.
    :returns: the event.
    """
    return QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(point),
        QPointF(point),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def option_for(rect: QRect, state: QStyle.StateFlag = QStyle.StateFlag.State_None) -> QStyleOptionViewItem:
    """A view item's option over a rect.

    :param rect: the item's rect.
    :param state: its state.
    :returns: the option.
    """
    option = QStyleOptionViewItem()
    option.rect = rect  # type: ignore[attr-defined]
    option.state = state  # type: ignore[attr-defined]
    return option


def file_line(path: Path, **changes: object) -> RootCandidate:
    """A ``.rehuroot``'s line.

    :param path: the root file.
    :param changes: fields to change from a mapped, addable root with one layout.
    :returns: the line.
    """
    fields: dict[str, object] = {
        "pick": RootPick(path),
        "kind": CandidateKind.FILE,
        "label": "Music",
        "location": "//nas/data/Music",
        "root_file": path,
        "folder": Path("T:/Music"),
        "layouts": {"*": ("*",)},
        "fallbacks": {},
        "problem": "",
    }
    fields.update(changes)
    return RootCandidate(**fields)  # type: ignore[arg-type]


# region the browser


@fixture(name="browser")
def fixture_browser(qtbot: QtBot, tmp_path: Path) -> RootsBrowser:
    """A browser showing ``tmp_path``, which holds two folders and a root file, its rows listed.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :returns: the browser.
    """
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    (tmp_path / "x.rehuroot").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("", encoding="utf-8")
    built = RootsBrowser()
    qtbot.addWidget(built)
    built.resize(400, 300)
    built.show_folder(tmp_path)
    model = built.tree_view.model()
    qtbot.waitUntil(lambda: model.rowCount(built.tree_view.rootIndex()) == 3, timeout=5000)
    return built


def test_the_browser_lists_folders_and_root_files_only_and_goes_up(browser: RootsBrowser, tmp_path: Path) -> None:
    """Other files are left out; the up button shows the folder above, and a path that is no folder changes nothing.

    **Test steps:**

    * read the rows; show a file's path; go up
    * verify the names, the folder kept, the parent shown
    """
    tree = browser.tree_view
    model = tree.model()
    names = sorted(model.index(row, 0, tree.rootIndex()).data() for row in range(model.rowCount(tree.rootIndex())))
    assert names == ["a", "b", "x.rehuroot"]

    browser.show_folder(tmp_path / "notes.txt")
    assert browser.folder == tmp_path

    browser.findChild(QWidget, "up_button").click()  # type: ignore[union-attr]
    assert browser.folder == tmp_path.parent


@mark.skipif(os.name == "nt", reason="Windows has the drives above a drive's top")
def test_up_stops_at_the_filesystem_root(browser: RootsBrowser, tmp_path: Path) -> None:
    """Where ``/`` is the top, Up there changes nothing.

    **Test steps:**

    * show the top and click Up
    * verify the top is still shown
    """
    top = Path(tmp_path.anchor)
    browser.show_folder(top)
    browser.findChild(QWidget, "up_button").click()  # type: ignore[union-attr]
    assert browser.folder == top


@mark.skipif(os.name != "nt", reason="only Windows has drives above the top of a folder tree")
def test_up_from_a_drive_shows_the_drives_and_stops_there(browser: RootsBrowser, qtbot: QtBot, tmp_path: Path) -> None:
    """One Up above a drive's top lists the machine's drives with the path field empty; Up is then disabled, and a
    path typed or shown brings it back.

    **Test steps:**

    * show a drive's top and click Up; stage the drive's row; click Up again
    * verify the drives listed, the field empty, Up disabled, the drive staged and the view unchanged
    * show a folder
    * verify Up enabled and the folder's path in the field
    """
    up_button = browser.findChild(QWidget, "up_button")
    path_edit = browser.findChild(QLineEdit, "path_edit")
    tree = browser.tree_view
    staged: list[list[Path]] = []
    browser.add_requested.connect(staged.append)
    drive = Path(tmp_path.anchor)
    browser.show_folder(drive)

    up_button.click()  # type: ignore[union-attr]
    qtbot.waitUntil(lambda: tree.model().rowCount(tree.rootIndex()) > 0, timeout=5000)
    assert not tree.rootIndex().isValid()
    assert path_edit.text() == ""  # type: ignore[union-attr]
    assert not up_button.isEnabled()  # type: ignore[union-attr]
    drive_row = browser.index_of(drive)
    assert drive_row.isValid() and drive_row.parent() == tree.rootIndex()

    browser.stage(drive_row)
    assert len(staged) == 1
    assert staged[0] == [drive]

    up_button.click()  # type: ignore[union-attr]
    assert not tree.rootIndex().isValid()

    browser.show_folder(tmp_path)
    assert up_button.isEnabled()  # type: ignore[union-attr]
    assert path_edit.text() == str(tmp_path)  # type: ignore[union-attr]


def test_the_plus_stages_its_row_or_every_selected_row_in_order(browser: RootsBrowser, tmp_path: Path) -> None:
    """A row's ``+`` stages that row; on a selected row, every selected row in the tree's order; the selection stays.

    **Test steps:**

    * stage an unselected row; select the root file and the first folder, and stage the root file
    * verify one path, then both in the tree's order, and the selection unchanged
    """
    staged: list[list[Path]] = []
    browser.add_requested.connect(staged.append)
    a, x = browser.index_of(tmp_path / "a"), browser.index_of(tmp_path / "x.rehuroot")

    browser.stage(QModelIndex(browser.index_of(tmp_path / "b")))
    selection = browser.tree_view.selectionModel()
    for index in (x, a):
        selection.select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    browser.stage(QModelIndex(x))

    assert staged == [[tmp_path / "b"], [tmp_path / "a", tmp_path / "x.rehuroot"]]
    assert len(selection.selectedRows()) == 2


def test_the_plus_is_drawn_on_a_hovered_or_current_row_and_a_click_on_it_stages(
    browser: RootsBrowser, tmp_path: Path
) -> None:
    """The ``+`` shows where the pointer is and on the current row, and only a click on it stages.

    **Test steps:**

    * paint a plain row, a hovered one and the current one; count the drawn pixels at the ``+``
    * release the button on a row's ``+``, then elsewhere on it
    * verify only the hovered and current rows drew it, and only the first click staged
    """
    tree = browser.tree_view
    delegate = tree.itemDelegate()
    assert isinstance(delegate, AddButtonDelegate)
    a, b = browser.index_of(tmp_path / "a"), browser.index_of(tmp_path / "b")
    tree.setCurrentIndex(b)
    rect = QRect(0, 0, 200, 20)

    def drawn(index: QModelIndex, state: QStyle.StateFlag) -> int:
        image = QImage(200, 20, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        delegate.paint(painter, option_for(rect, state), index)
        painter.end()
        button = delegate.button_rect(rect)
        return sum(image.pixelColor(x, y).alpha() > 0 for x in range(button.left(), button.right()) for y in range(20))

    assert drawn(a, QStyle.StateFlag.State_None) == 0
    assert drawn(a, QStyle.StateFlag.State_MouseOver) > 0
    assert drawn(b, QStyle.StateFlag.State_None) > 0

    clicked: list[object] = []
    delegate.clicked.connect(clicked.append)
    model = tree.model()
    assert delegate.editorEvent(mouse_release(delegate.button_rect(rect).center()), model, option_for(rect), a)
    delegate.editorEvent(mouse_release(QPoint(5, 5)), model, option_for(rect), a)
    assert len(clicked) == 1


# endregion


# region the staging list's model


def test_the_model_answers_each_role_and_edits_only_a_folder(tmp_path: Path) -> None:
    """A row answers its pick, line, kind, label, root file and preset; only a folder's can be edited, and an edit that
    changes nothing is none.

    **Test steps:**

    * stage a root file and a folder, read every role, then edit both rows every way
    * verify the answers and which edits took
    """
    model = RootCandidatesModel(PRESETS[0])
    assert model.stage([tmp_path / "m.rehuroot", tmp_path / "f"]) == 2
    assert model.stage([tmp_path / "f"]) == 0
    file_index, folder_index = model.index(0), model.index(1)

    assert file_index.data() == str(tmp_path / "m.rehuroot")
    assert file_index.data(Qt.ItemDataRole.ToolTipRole) == str(tmp_path / "m.rehuroot")
    assert file_index.data(CandidateRole.KIND) == CandidateKind.FILE
    assert file_index.data(CandidateRole.LINE) is None
    assert folder_index.data(CandidateRole.LABEL) == ""
    assert folder_index.data(CandidateRole.ROOT_FILE) == ""
    assert folder_index.data(CandidateRole.LAYOUT) == PRESETS[0]
    assert folder_index.data(Qt.ItemDataRole.DecorationRole) is None
    assert model.data(QModelIndex()) is None
    assert model.flags(QModelIndex()) == Qt.ItemFlag.NoItemFlags
    assert not model.flags(file_index) & Qt.ItemFlag.ItemIsEditable
    assert model.flags(folder_index) & Qt.ItemFlag.ItemIsEditable
    assert model.rowCount(file_index) == 0

    assert not model.setData(file_index, "x", CandidateRole.LABEL)
    assert not model.setData(folder_index, "x", Qt.ItemDataRole.EditRole)
    assert not model.setData(folder_index, PRESETS[0], CandidateRole.LAYOUT)
    assert model.setData(folder_index, PRESETS[1], CandidateRole.LAYOUT)
    assert model.setData(folder_index, " Mine ", CandidateRole.LABEL)
    assert not model.setData(folder_index, "Mine", CandidateRole.LABEL)
    assert model.setData(folder_index, str(tmp_path / "f.rehuroot"), CandidateRole.ROOT_FILE)
    assert model.setData(folder_index, " ", CandidateRole.ROOT_FILE)
    assert model.picks[1] == RootPick(tmp_path / "f", "Mine", None)
    assert model.layout_of(model.picks[1]) == PRESETS[1]


def test_a_rows_label_and_root_file_written_together_plan_the_list_once(qtbot: QtBot, tmp_path: Path) -> None:
    """A folder's editor writes both its fields at once, so one edit of the row plans the list once, not twice.

    **Test steps:**

    * write a label and a root file together, then the same pair again, then a pair that is no pair
    * verify one plan asked for, then none, and the pick holding both
    """
    model = RootCandidatesModel(PRESETS[0])
    model.stage([tmp_path / "f"])
    asked: list[object] = []
    model.picks_changed.connect(lambda: asked.append(True))

    assert model.setData(model.index(0), ("Mine", str(tmp_path / "m.rehuroot")), CandidateRole.TYPED)
    assert not model.setData(model.index(0), ("Mine", str(tmp_path / "m.rehuroot")), CandidateRole.TYPED)
    assert not model.setData(model.index(0), "Mine", CandidateRole.TYPED)

    assert len(asked) == 1
    assert next(iter(model.picks)) == RootPick(tmp_path / "f", "Mine", tmp_path / "m.rehuroot")
    del qtbot


def test_selected_rows_are_staged_in_the_trees_order_wherever_they_are(browser: RootsBrowser, tmp_path: Path) -> None:
    """Rows are ordered by their place in the tree, not by where they are drawn -- a row scrolled away or under a
    collapsed parent has no place on screen.

    **Test steps:**

    * read the order keys of the three rows and of a row under a folder
    * verify they sort as the tree lists them, and a child sorts after its parent and before the next sibling
    """
    a, b, x = (browser.index_of(tmp_path / name) for name in ("a", "b", "x.rehuroot"))
    keys = [RootsBrowser.tree_order(QModelIndex(index)) for index in (a, b, x)]

    assert keys == sorted(keys)
    assert len({len(key) for key in keys}) == 1
    (tmp_path / "a" / "inner").mkdir()
    inner = browser.index_of(tmp_path / "a" / "inner")
    assert RootsBrowser.tree_order(QModelIndex(a)) < RootsBrowser.tree_order(QModelIndex(inner))
    assert RootsBrowser.tree_order(QModelIndex(inner)) < RootsBrowser.tree_order(QModelIndex(b))


def test_only_planned_addable_lines_are_added(tmp_path: Path) -> None:
    """OK adds the shown lines that can be added, a folder's with its preset's maps; not one still being checked, nor
    one that cannot be added.

    **Test steps:**

    * stage three folders; plan the first two, the second refused, and leave the third unchecked
    * verify only the first is added, with its preset's maps, and that the list is still checking
    """
    model = RootCandidatesModel(PRESETS[1])
    paths = [tmp_path / name for name in ("a", "b", "c")]
    model.stage(paths)
    picks = model.picks[:2]
    lines = [
        RootCandidate(pick, CandidateKind.FOLDER, pick.path.name, "//x", tmp_path / "r.rehuroot", pick.path)
        for pick in picks
    ]
    lines[1] = replace(lines[1], problem="no")

    model.set_plan(picks, lines)

    assert len(model.addable) == 1
    added = next(iter(model.addable))
    assert (added.label, added.layouts) == ("a", {"tutorial": ("{title}",)})
    assert model.checking


# endregion


# region the delegate


def test_a_root_files_row_says_what_it_holds_and_where_it_is(tmp_path: Path) -> None:
    """A painted row: its file; its label and location; its layouts; where this machine finds it, or that it joins
    unmapped, or why it cannot be added; a row still checked says so.

    **Test steps:**

    * read the lines of a mapped root file, an unmapped one, one that cannot be added, one unreadable, and none yet
    """
    path = tmp_path / "m.rehuroot"
    pick = RootPick(path)
    lines_of = RootCandidateDelegate.lines_of

    assert lines_of(file_line(path), pick) == [
        (str(path), False),
        ("Music \N{MIDDLE DOT} //nas/data/Music", False),
        ("Layouts: * \N{RIGHTWARDS ARROW} *", False),
        (f"On this machine: {Path('T:/Music')}", False),
    ]
    several = file_line(path, layouts={"tutorial": ("{title}", "{authors}/{title}"), "*": ("*",)})
    assert lines_of(several, pick)[2] == (
        "Layouts: tutorial \N{RIGHTWARDS ARROW} {title}; tutorial \N{RIGHTWARDS ARROW} {authors}/{title}; "
        "* \N{RIGHTWARDS ARROW} *",
        False,
    )
    assert lines_of(file_line(path, folder=None), pick)[-1] == (UNMAPPED, False)
    assert lines_of(file_line(path, problem="Nope."), pick)[-1] == ("Nope.", True)
    assert lines_of(file_line(path, location="", layouts={}, problem="Unreadable."), pick) == [
        (str(path), False),
        ("Unreadable.", True),
    ]
    assert lines_of(None, pick) == [(str(path), False), (CHECKING, False)]


def test_a_painted_row_is_drawn_measured_and_removed_by_its_button(qtbot: QtBot, tmp_path: Path) -> None:
    """A root file's row is painted line by line with its remove button, is as tall as its lines, and a click on the
    button asks for it to go; a folder's row paints nothing, its editor covering it, and is as tall as the editor.

    **Test steps:**

    * plan a root file and a folder in a model; paint and measure both; click the file's button, then elsewhere
    * verify pixels were drawn for the file only, the heights, and one removal asked for
    """
    host = QWidget()
    qtbot.addWidget(host)
    model = RootCandidatesModel(PRESETS[0])
    model.stage([tmp_path / "m.rehuroot", tmp_path / "f"])
    folder_line = RootCandidate(
        model.picks[1], CandidateKind.FOLDER, "f", "//x", tmp_path / "f.rehuroot", tmp_path / "f", problem="Nope."
    )
    model.set_plan(model.picks, [file_line(tmp_path / "m.rehuroot", problem="Taken."), folder_line])
    delegate = RootCandidateDelegate(lambda: PRESETS, host)
    rect = QRect(0, 0, 400, 120)

    def drawn(row: int) -> int:
        image = QImage(400, 120, QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        delegate.paint(painter, option_for(rect), model.index(row))
        painter.end()
        return sum(image.pixelColor(x, y).alpha() > 0 for x in range(0, 400, 2) for y in range(0, 120, 2))

    assert drawn(0) > 0
    assert drawn(1) == 0
    painted = delegate.sizeHint(option_for(rect), model.index(0)).height()
    assert painted == 4 * QFontMetrics(QFont()).lineSpacing() + 13
    assert delegate.sizeHint(option_for(rect), model.index(1)).height() > painted

    asked: list[object] = []
    delegate.remove_requested.connect(asked.append)
    button = delegate.remove_rect(rect)
    assert delegate.editorEvent(mouse_release(button.center()), model, option_for(rect), model.index(0))
    delegate.editorEvent(mouse_release(QPoint(5, 60)), model, option_for(rect), model.index(0))
    assert len(asked) == 1


def test_a_folders_editor_writes_what_was_typed_and_asks_for_the_rest(qtbot: QtBot, tmp_path: Path) -> None:
    """The delegate's editor fills from the row, writes its label and root file back when one is left, sets the preset
    picked, and passes on a removal and a *New layout…*.

    **Test steps:**

    * open the editor of a folder's row, type a label and leave it, pick the second preset, ask for a removal and a new
      layout
    * verify the pick, the preset, and the two requests
    """
    host = QWidget()
    qtbot.addWidget(host)
    model = RootCandidatesModel(PRESETS[0])
    model.stage([tmp_path / "f"])
    delegate = RootCandidateDelegate(lambda: PRESETS, host)
    index = model.index(0)
    editor = delegate.createEditor(host, option_for(QRect(0, 0, 400, 150)), index)
    assert isinstance(editor, NewRootItemEditor)
    delegate.setEditorData(editor, index)
    delegate.updateEditorGeometry(editor, option_for(QRect(0, 0, 400, 150)), index)
    delegate.commitData.connect(lambda widget: delegate.setModelData(widget, model, index))
    removed: list[object] = []
    wanted: list[object] = []
    delegate.remove_requested.connect(removed.append)
    delegate.new_layout_requested.connect(wanted.append)

    editor.label_edit.setText("Mine")
    editor.edited.emit()
    editor.layout_combo.activated.emit(1)
    editor.remove_requested.emit()
    editor.layout_combo.activated.emit(editor.layout_combo.count() - 1)
    delegate.setEditorData(QWidget(), index)
    delegate.setModelData(QWidget(), model, index)

    assert next(iter(model.picks)).label == "Mine"
    assert model.layout_of(model.picks[0]) == PRESETS[1]
    assert (len(removed), len(wanted)) == (1, 1)
    assert editor.geometry() == QRect(0, 0, 400, 149)


# endregion


# region a folder's editors


def test_the_editors_keep_what_is_being_typed_and_offer_a_new_layout(
    qtbot: QtBot, mocker: MockerFixture, tmp_path: Path
) -> None:
    """Showing the row again leaves a field with the keyboard alone; a preset no longer offered shows the first;
    *New layout…* puts the combo back; Browse puts the file picked in the root file field and says so.

    **Test steps:**

    * show a row; give the label field the keyboard and show the row with another label
    * show it with a preset not offered; pick *New layout…*; browse to a file, then cancel a browse
    * verify each
    """
    editor = NewRootItemEditor()
    qtbot.addWidget(editor)
    pick = RootPick(tmp_path / "f", "typed")
    editor.show_row(pick, None, PRESETS[1], PRESETS)
    assert editor.problem == CHECKING
    assert editor.layout_combo.currentText() == "By title"
    assert editor.layout_combo.itemText(editor.layout_combo.count() - 1) == NEW_LAYOUT

    mocker.patch.object(editor.label_edit, "hasFocus", return_value=True)
    mocker.patch.object(editor.root_file_edit, "hasFocus", return_value=True)
    editor.show_row(RootPick(tmp_path / "f", "other", tmp_path / "x.rehuroot"), None, RootLayout("gone"), PRESETS)
    assert editor.label_edit.text() == "typed"
    assert editor.root_file_edit.text() == ""
    assert editor.layout_combo.currentIndex() == 0

    asked: list[object] = []
    editor.new_layout_requested.connect(lambda: asked.append(True))
    editor.layout_combo.setCurrentIndex(editor.layout_combo.count() - 1)
    editor.layout_combo.activated.emit(editor.layout_combo.count() - 1)
    assert asked == [True]
    assert editor.layout_combo.currentIndex() == 0

    edited: list[object] = []
    editor.edited.connect(lambda: edited.append(True))
    picker = mocker.patch(
        "rehuco_agent.rehuco.new_root_item_editor.QFileDialog.getSaveFileName",
        side_effect=[(str(tmp_path / "nas.rehuroot"), ""), ("", "")],
    )
    editor.findChild(QWidget, "browse_button").click()  # type: ignore[union-attr]
    editor.findChild(QWidget, "browse_button").click()  # type: ignore[union-attr]
    assert editor.root_file_edit.text() == str(tmp_path / "nas.rehuroot")
    assert edited == [True]
    assert picker.call_count == 2


def test_new_layout_needs_a_name_no_preset_has(qtbot: QtBot) -> None:
    """The new preset starts as a folder's default and needs a name of its own.

    **Test steps:**

    * open the dialog with a name taken; type nothing, the taken name in another case, then a new one
    * verify OK each time, and the preset read back
    """
    dialog = NewLayoutDialog(frozenset({"Keep folder names"}))
    qtbot.addWidget(dialog)
    assert not dialog.ok_button.isEnabled()
    assert dialog.layouts_editor.layouts == {"*": ("*",)}

    dialog.set_name("keep FOLDER names")
    assert not dialog.ok_button.isEnabled()
    dialog.set_name(" Deep ")
    assert dialog.ok_button.isEnabled()
    assert dialog.preset == RootLayout("Deep", {"*": ("*",)}, {})


# endregion
