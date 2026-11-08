"""Tests for the Add Roots dialog (#578): folders and ``.rehuroot`` files staged from the browser, planned off the GUI
thread, edited in place, and what OK adds; *Scan after adding* saved on every exit (#542).

Every test works on a catalog saved in ``tmp_path`` with one root, real folders and real root files beside it, so the
plans are the real ones.
"""

from pathlib import Path

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QDialog
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco import add_roots_dialog
from rehuco_agent.rehuco.add_roots_dialog import CHECKING_ALL, NOTHING_STAGED, PLAN_FAILED, AddRootsDialog
from rehuco_agent.rehuco.new_layout_dialog import NewLayoutDialog
from rehuco_agent.rehuco.new_root_item_editor import CHECKING, NEW_LAYOUT, NewRootItemEditor
from rehuco_agent.rehuco.root_candidates_model import CandidateRole
from rehuco_agent.rehuco.root_overlap_check import RootOverlapCheck
from rehuco_agent.rehuco.root_storage import (
    ROOT_STORAGE_ICONS,
    ROOT_STORAGE_LABELS,
    ROOT_STORAGE_OFFLINE_ROWS,
    ROOT_STORAGE_OFFLINE_TOOLTIPS,
)
from rehuco_agent.settings.root_catalog_settings import DEFAULT_ROOT_LAYOUTS, RootLayout, shared_root_catalog_settings
from rehuco_core import CandidateKind, MappedRoot, RehucoFile, RehurootFile, RootStorage, location_of
from rehuco_core.root_candidates import path_key

from rehuco_agent_tests.conftest import FakeSettings

pytestmark = mark.usefixtures("real_path_stat")

WAIT_MS = 5000
"""How long a plan may take on its thread."""


@fixture(name="stored")
def stored_fixture(mocker: MockerFixture) -> FakeSettings:
    """Stand in for ``persistent_settings()`` so the dialog never touches real storage.

    :param mocker: pytest-mock fixture.
    :returns: the store the dialog writes to.
    """
    fake = FakeSettings()
    mocker.patch.object(add_roots_dialog, "persistent_settings", return_value=fake)
    return fake


@fixture(name="home")
def fixture_home(tmp_path: Path) -> RehucoFile:
    """A catalog saved in ``tmp_path/catalog`` with one root, ``tmp_path/lib``.

    :param tmp_path: pytest's temporary directory.
    :returns: the catalog.
    """
    (tmp_path / "catalog").mkdir()
    (tmp_path / "lib").mkdir()
    file = RehucoFile.new()
    file.save(tmp_path / "catalog" / "home.rehuco")
    file.add_root(location_of(tmp_path / "lib"), "lib")
    file.save()
    return file


@fixture(name="dialog")
def fixture_dialog(qtbot: QtBot, home: RehucoFile, tmp_path: Path, stored: FakeSettings) -> AddRootsDialog:
    """The dialog over ``home``, its root mapped to ``tmp_path/lib``.

    :param qtbot: pytest-qt fixture.
    :param home: the catalog.
    :param tmp_path: pytest's temporary directory.
    :param stored: the settings store, so a save never reaches the real one.
    :returns: the dialog.
    """
    del stored
    root = next(iter(home.roots))
    mapped = (MappedRoot(root.root_id, root.label, root.location, tmp_path / "lib", file=root.file),)
    built = AddRootsDialog(home, mapped, ())
    qtbot.addWidget(built)
    return built


def folders(tmp_path: Path, *names: str) -> list[Path]:
    """Folders made under ``tmp_path``.

    :param tmp_path: pytest's temporary directory.
    :param names: their names.
    :returns: them, in order.
    """
    made = [tmp_path / name for name in names]
    for path in made:
        path.mkdir(parents=True)
    return made


def planned(qtbot: QtBot, dialog: AddRootsDialog) -> None:
    """Wait until the list is planned.

    :param qtbot: pytest-qt fixture.
    :param dialog: the dialog.
    """
    qtbot.waitUntil(lambda: dialog.status != CHECKING_ALL and not dialog.model.checking, timeout=WAIT_MS)


def editor_at(dialog: AddRootsDialog, row: int) -> NewRootItemEditor:
    """The editor a folder's row keeps open.

    :param dialog: the dialog.
    :param row: the row.
    :returns: its editor.
    """
    editor = dialog.staging_view.indexWidget(dialog.model.index(row))
    assert isinstance(editor, NewRootItemEditor)
    return editor


def test_every_storage_has_a_glyph_a_label_and_two_offline_texts() -> None:
    """The four mappings are complete, so nothing can be drawn or worded without an answer.

    **Test steps:**

    * read each mapping
    * verify every storage is a key of each
    """
    for mapping in (ROOT_STORAGE_ICONS, ROOT_STORAGE_LABELS, ROOT_STORAGE_OFFLINE_ROWS, ROOT_STORAGE_OFFLINE_TOOLTIPS):
        assert set(mapping) == set(RootStorage)


def test_the_browser_opens_in_the_catalogs_folder_and_the_list_says_what_to_do(
    dialog: AddRootsDialog, tmp_path: Path
) -> None:
    """Nothing is staged yet: the browser shows the ``.rehuco``'s folder, and OK has nothing to add.

    **Test steps:**

    * read the browser's folder, the status and OK
    """
    assert path_key(dialog.browser.folder) == path_key(tmp_path / "catalog")
    assert dialog.status == NOTHING_STAGED
    assert not dialog.ok_button.isEnabled()
    assert dialog.candidates == ()


def test_folders_staged_become_roots_each_with_its_editors(
    qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path
) -> None:
    """Sibling folders staged at once each get a row with its editors open, are planned, and OK adds them all with the
    first preset's maps, their root files beside the ``.rehuco``.

    **Test steps:**

    * stage two sibling folders and wait for the plan
    * verify each row's editor, the candidates' labels, root files and maps, the status and OK
    """
    blender, krita = folders(tmp_path, "t/Blender", "t/Krita")

    dialog.stage([blender, krita])
    planned(qtbot, dialog)

    assert editor_at(dialog, 0).label_edit.placeholderText() == "Blender"
    assert editor_at(dialog, 1).root_file_edit.placeholderText() == str(tmp_path / "catalog" / "Krita.rehuroot")
    candidates = dialog.candidates
    assert [line.label for line in candidates] == ["Blender", "Krita"]
    assert [path_key(line.root_file) for line in candidates] == [
        path_key(tmp_path / "catalog" / "Blender.rehuroot"),
        path_key(tmp_path / "catalog" / "Krita.rehuroot"),
    ]
    assert all(line.layouts == dict(DEFAULT_ROOT_LAYOUTS[0].layouts) for line in candidates)
    assert dialog.status == "2 to add."
    assert dialog.ok_button.isEnabled()


def test_a_path_staged_twice_is_listed_once_without_a_word(
    qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path
) -> None:
    """Adding what is already in the list, alone or among new paths, is quietly passed over.

    **Test steps:**

    * stage a folder, then it again with a second folder, in another spelling
    * verify two rows, in order
    """
    first, second = folders(tmp_path, "a", "b")
    dialog.stage([first])

    dialog.stage([Path(str(first).upper()) if Path(str(first).upper()).exists() else first, second])
    planned(qtbot, dialog)

    assert [index.data(CandidateRole.PICK).path for index in map(dialog.model.index, range(2))] == [first, second]
    assert dialog.model.rowCount() == 2


def test_a_root_file_stands_for_the_folder_it_resolves_to_in_either_order(
    qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path
) -> None:
    """A staged folder that a staged ``.rehuroot`` is the root of shows only as the file, whichever came first, and
    comes back if the file is taken out.

    **Test steps:**

    * stage a folder, then the root file whose location it is; read the rows
    * take the file out and read the rows again
    """
    (shared,) = folders(tmp_path, "shared")
    root = RehurootFile.new(tmp_path / "shared.rehuroot", location_of(shared), "Shared", layouts={"*": "{title}"})
    root.save()

    dialog.stage([shared])
    dialog.stage([root.path])
    planned(qtbot, dialog)

    assert dialog.model.rowCount() == 1
    assert dialog.model.index(0).data(CandidateRole.KIND) == CandidateKind.FILE
    (line,) = dialog.candidates
    assert (line.label, line.folder, line.layouts) == ("Shared", shared, {"*": "{title}"})

    dialog.model.remove(0)
    planned(qtbot, dialog)
    assert [dialog.model.index(0).data(CandidateRole.PICK).path] == [shared]


def test_what_cannot_be_added_is_listed_with_why_and_left_out(
    qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path
) -> None:
    """The catalog's own root folder, staged, says why it cannot be added; OK adds only the others.

    **Test steps:**

    * stage the root folder alone and verify OK is off and the status counts it left out
    * stage another folder and verify only it is a candidate
    """
    dialog.stage([tmp_path / "lib"])
    planned(qtbot, dialog)

    assert editor_at(dialog, 0).problem == "Already a root of this catalog."
    assert dialog.status == "0 to add, 1 left out."
    assert not dialog.ok_button.isEnabled()

    (other,) = folders(tmp_path, "other")
    dialog.stage([other])
    planned(qtbot, dialog)
    assert [line.folder for line in dialog.candidates] == [other]


def test_a_root_file_this_machine_cannot_resolve_is_added_unmapped(
    qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path
) -> None:
    """A ``.rehuroot`` whose location resolves nowhere here is still added, with no folder.

    **Test steps:**

    * stage a root file whose location names no machine here and wait for the plan
    * verify its candidate has no folder and OK is on
    """
    root = RehurootFile.new(tmp_path / "far.rehuroot", "//nohost-578/share/far", "Far")
    root.save()

    dialog.stage([root.path])
    planned(qtbot, dialog)

    (line,) = dialog.candidates
    assert (line.kind, line.label, line.folder) == (CandidateKind.FILE, "Far", None)
    assert dialog.ok_button.isEnabled()


def test_a_label_typed_names_the_root_and_its_root_file(qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path) -> None:
    """The label left after typing is planned again: the root takes it, and the root file left empty follows it.

    **Test steps:**

    * stage a folder, type a label in its editor and leave the field
    * verify the candidate's label and root file, and the root file field's placeholder
    """
    (folder,) = folders(tmp_path, "Krita")
    dialog.stage([folder])
    planned(qtbot, dialog)
    editor = editor_at(dialog, 0)

    editor.label_edit.setText("Painting")
    editor.edited.emit()
    planned(qtbot, dialog)

    (line,) = dialog.candidates
    assert line.label == "Painting"
    assert path_key(line.root_file) == path_key(tmp_path / "catalog" / "Painting.rehuroot")
    assert editor_at(dialog, 0).root_file_edit.placeholderText() == str(line.root_file)


def test_a_root_file_typed_is_where_the_root_file_goes(qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path) -> None:
    """A root file put elsewhere -- the NAS both catalogs reach -- is the one the root gets.

    **Test steps:**

    * stage a folder, type a root file in a shared folder and leave the field
    * verify the candidate's root file
    """
    folder, nas = folders(tmp_path, "Krita", "nas")
    dialog.stage([folder])
    planned(qtbot, dialog)
    editor = editor_at(dialog, 0)

    editor.root_file_edit.setText(str(nas / "krita.rehuroot"))
    editor.edited.emit()
    planned(qtbot, dialog)

    assert [line.root_file for line in dialog.candidates] == [nas / "krita.rehuroot"]


def test_the_preset_picked_gives_the_root_its_layouts(qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path) -> None:
    """A folder starts with the maps of the preset its combo shows.

    **Test steps:**

    * have two presets, stage a folder, and pick the second in its combo
    * verify the candidate carries the second preset's maps
    """
    second = RootLayout("By title", {"tutorial": "{title}"}, {"title": "?"})
    shared_root_catalog_settings().default_layouts = (*DEFAULT_ROOT_LAYOUTS, second)
    (folder,) = folders(tmp_path, "Krita")
    dialog.stage([folder])
    planned(qtbot, dialog)

    editor_at(dialog, 0).layout_combo.activated.emit(1)

    (line,) = dialog.candidates
    assert (line.layouts, line.fallbacks) == ({"tutorial": "{title}"}, {"title": "?"})


def test_new_layout_saves_a_preset_and_gives_it_to_the_folder(
    qtbot: QtBot, mocker: MockerFixture, dialog: AddRootsDialog, tmp_path: Path, stored: FakeSettings
) -> None:
    """*New layout…* asks for a preset, saves it with the others at once, and the folder that asked starts with it;
    a cancelled one changes nothing.

    **Test steps:**

    * stage a folder; answer *New layout…* with nothing, then with a preset
    * verify nothing changed the first time; then the settings hold the preset, the store has it, the candidate
      carries its maps, and the combo offers it before *New layout…*
    """
    made = RootLayout("Deep", {"tutorial": "{authors}/{title}"}, {})
    ask = mocker.patch.object(dialog, "ask_new_layout", side_effect=[None, made])
    (folder,) = folders(tmp_path, "Krita")
    dialog.stage([folder])
    planned(qtbot, dialog)
    combo = editor_at(dialog, 0).layout_combo

    combo.activated.emit(combo.count() - 1)
    assert shared_root_catalog_settings().default_layouts == DEFAULT_ROOT_LAYOUTS
    combo.activated.emit(combo.count() - 1)

    assert ask.call_args.args[0] == frozenset({DEFAULT_ROOT_LAYOUTS[0].label})
    assert shared_root_catalog_settings().default_layouts == (*DEFAULT_ROOT_LAYOUTS, made)
    stored.beginGroup("root_catalog")
    assert stored.value("default_layouts/2/label") == "Deep"
    stored.endGroup()
    assert next(iter(dialog.candidates)).layouts == {"tutorial": "{authors}/{title}"}
    combo = editor_at(dialog, 0).layout_combo
    assert [combo.itemText(row) for row in range(combo.count())][-2] == "Deep"
    assert combo.currentText() == "Deep"


def test_the_remove_buttons_take_a_row_out(qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path) -> None:
    """A folder's editor and a painted row each take their row out.

    **Test steps:**

    * stage a root file and a folder; remove the folder by its editor's button, then the file by the delegate
    * verify the rows left each time
    """
    root = RehurootFile.new(tmp_path / "far.rehuroot", "//nohost-578/share/far", "Far")
    root.save()
    (folder,) = folders(tmp_path, "Krita")
    dialog.stage([root.path, folder])
    planned(qtbot, dialog)

    editor_at(dialog, 1).remove_requested.emit()
    planned(qtbot, dialog)
    assert dialog.model.rowCount() == 1

    delegate = dialog.staging_view.itemDelegate()
    delegate.remove_requested.emit(QPersistentModelIndex(dialog.model.index(0)))  # type: ignore[attr-defined]
    delegate.remove_requested.emit(QPersistentModelIndex())  # type: ignore[attr-defined]
    planned(qtbot, dialog)
    assert dialog.model.rowCount() == 0
    assert dialog.status == NOTHING_STAGED


def test_ok_waits_for_the_plan_and_a_late_plan_is_dropped(qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path) -> None:
    """While a plan is out the rows say so and OK waits; an answer for a plan since superseded is not taken.

    **Test steps:**

    * stage a folder and read the status and OK before the plan lands, and the editor's line
    * once planned, deliver a made-up answer under an old serial
    * verify the list is as the real plan left it
    """
    (folder,) = folders(tmp_path, "Krita")
    dialog.stage([folder])

    assert dialog.status == CHECKING_ALL
    assert editor_at(dialog, 0).problem == CHECKING
    assert not dialog.ok_button.isEnabled()
    planned(qtbot, dialog)
    check = dialog.findChild(RootOverlapCheck)
    assert check is not None
    check.planned.emit(0, ())

    assert dialog.model.rowCount() == 1
    assert dialog.ok_button.isEnabled()


def test_a_plan_that_fails_says_so_and_offers_no_ok(
    qtbot: QtBot, mocker: MockerFixture, dialog: AddRootsDialog, tmp_path: Path, caplog: LogCaptureFixture
) -> None:
    """A plan that raises is logged; the list says it could not be checked, and OK stays off.

    **Test steps:**

    * make the planner raise, stage a folder, and wait for the answer
    * verify the status, OK, and the log
    """
    mocker.patch("rehuco_agent.rehuco.root_overlap_check.RootPlanner.plan", side_effect=RuntimeError("boom"))
    (folder,) = folders(tmp_path, "Krita")

    dialog.stage([folder])
    qtbot.waitUntil(lambda: dialog.status == PLAN_FAILED, timeout=WAIT_MS)

    assert not dialog.ok_button.isEnabled()
    assert "Planning the roots to add failed." in caplog.text


def test_the_browsers_plus_stages_into_the_list(qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path) -> None:
    """The browser's ``+`` is what stages.

    **Test steps:**

    * show a folder in the browser and stage a row of it by its ``+``
    * verify the row is in the list
    """
    (folder,) = folders(tmp_path, "t/Krita")
    dialog.browser.show_folder(tmp_path / "t")
    index = QModelIndex(dialog.browser.index_of(folder))

    dialog.browser.stage(index)
    planned(qtbot, dialog)

    assert dialog.model.index(0).data(CandidateRole.PICK).path == folder


def test_the_dialog_shows_the_scan_after_adding_setting(qtbot: QtBot, home: RehucoFile) -> None:
    """The checkbox starts on the setting's value, which is on by default (#542).

    **Test steps:**

    * open the dialog over the default setting, then over a setting of off
    * verify the box is checked, then unchecked
    """
    first = AddRootsDialog(home, (), ())
    qtbot.addWidget(first)
    assert first.scan_after_adding
    assert first.scan_after_adding_check_box.isChecked()

    shared_root_catalog_settings().scan_after_adding = False
    second = AddRootsDialog(home, (), ())
    qtbot.addWidget(second)

    assert not second.scan_after_adding


def test_accepting_the_dialog_remembers_the_scan_after_adding_choice(
    dialog: AddRootsDialog, stored: FakeSettings
) -> None:
    """Unticking the box and accepting changes the setting and persists it.

    **Test steps:**

    * untick the box and accept
    * verify the setting is off and the store holds it
    """
    dialog.scan_after_adding_check_box.setChecked(False)

    dialog.accept()

    assert shared_root_catalog_settings().scan_after_adding is False
    stored.beginGroup("root_catalog")
    assert stored.value("scan_after_adding") is False
    stored.endGroup()


def test_accepting_an_unchanged_choice_writes_nothing(dialog: AddRootsDialog, stored: FakeSettings) -> None:
    """Only a changed choice is saved, so most accepts never touch the settings file.

    **Test steps:**

    * accept the dialog without touching the box
    * verify the store is still empty
    """
    dialog.accept()

    stored.beginGroup("root_catalog")
    assert stored.value("scan_after_adding") is None


def test_cancelling_the_dialog_still_remembers_the_scan_after_adding_choice(
    dialog: AddRootsDialog, stored: FakeSettings
) -> None:
    """The choice is saved on every exit path, like a dialog's geometry (#542).

    **Test steps:**

    * untick the box and reject
    * verify the setting is off and the store holds it
    """
    dialog.scan_after_adding_check_box.setChecked(False)

    dialog.reject()

    assert shared_root_catalog_settings().scan_after_adding is False
    stored.beginGroup("root_catalog")
    assert stored.value("scan_after_adding") is False


def test_the_new_layout_question_answers_the_preset_or_nothing(mocker: MockerFixture, dialog: AddRootsDialog) -> None:
    """The real question opens the *New layout* dialog and answers its preset, or nothing when it is cancelled.

    **Test steps:**

    * ask with the dialog accepted holding a name, then cancelled
    * verify the preset, then nothing
    """

    def accept(self: NewLayoutDialog) -> QDialog.DialogCode:
        self.set_name("Deep")
        return QDialog.DialogCode.Accepted

    mocker.patch.object(NewLayoutDialog, "exec", new=accept)
    assert dialog.ask_new_layout(frozenset()) == RootLayout("Deep", {"*": "*"}, {})

    mocker.patch.object(NewLayoutDialog, "exec", return_value=QDialog.DialogCode.Rejected)
    assert dialog.ask_new_layout(frozenset()) is None


def test_a_new_layout_asked_for_a_row_since_taken_out_is_still_saved(
    mocker: MockerFixture, dialog: AddRootsDialog, stored: FakeSettings
) -> None:
    """The preset made is kept with the others even when the folder that asked for it is gone by then.

    **Test steps:**

    * answer *New layout…* with a preset, for a row no longer there
    * verify the settings hold it
    """
    del stored
    made = RootLayout("Deep")
    mocker.patch.object(dialog, "ask_new_layout", return_value=made)

    dialog.staging_view.itemDelegate().new_layout_requested.emit(QPersistentModelIndex())  # type: ignore[attr-defined]

    assert shared_root_catalog_settings().default_layouts == (*DEFAULT_ROOT_LAYOUTS, made)


def test_presets_changed_elsewhere_reach_the_folders_combos(
    qtbot: QtBot, dialog: AddRootsDialog, tmp_path: Path
) -> None:
    """A preset added in the settings while the dialog is open is offered at once -- with nothing staged too.

    **Test steps:**

    * add a preset with nothing staged; stage a folder; add another preset
    * verify the folder's combo offers both, then *New layout…*
    """
    settings = shared_root_catalog_settings()
    settings.default_layouts = (*DEFAULT_ROOT_LAYOUTS, RootLayout("One"))
    (folder,) = folders(tmp_path, "Krita")
    dialog.stage([folder])
    planned(qtbot, dialog)

    settings.default_layouts = (*settings.default_layouts, RootLayout("Two"))

    combo = editor_at(dialog, 0).layout_combo
    assert [combo.itemText(row) for row in range(combo.count())] == [
        DEFAULT_ROOT_LAYOUTS[0].label,
        "One",
        "Two",
        NEW_LAYOUT,
    ]


def test_a_catalog_never_saved_leaves_the_browser_where_it_is(qtbot: QtBot, stored: FakeSettings) -> None:
    """With no folder to start in, the browser shows the file system's top.

    **Test steps:**

    * open the dialog over a catalog never saved
    * verify it lists nothing staged and is not tied to a folder
    """
    del stored
    dialog = AddRootsDialog(RehucoFile.new(), (), ())
    qtbot.addWidget(dialog)

    assert dialog.status == NOTHING_STAGED
    assert str(dialog.browser.folder) in ("", ".")
