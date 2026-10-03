"""Tests for DocumentRegistry: one shared view-model per open path, refcounted (#375)."""

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QLabel, QLineEdit
from pytest import LogCaptureFixture, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_registry import DocumentRegistry
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import Relocation, RenameCoordinator

from rehuco_agent_tests.qt_waits import wait_destroyed

FAKE_PATH: Final = Path.cwd() / "fake" / "tutorials" / "sculpting" / "info.rehu"
"""Built from ``Path.cwd()`` so it is absolute on every platform."""
OTHER_PATH: Final = Path.cwd() / "fake" / "tutorials" / "painting" / "info.rehu"
TC_PATH: Final = Path.cwd() / "fake" / "tutorials" / "legacy" / "info.tc"

TUTORIAL: Final = {
    "format_version": 1,
    "type": "Tutorial",
    "sources": [{"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True}],
}


def load_document(mocker: MockerFixture) -> None:
    """Mock the filesystem so ``RehuDocument.load`` serves :data:`TUTORIAL`.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))


def test_two_acquisitions_of_one_path_share_one_model(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Acquiring an already-held path hands back the same model, not a second read of the file.

    **Test steps:**

    * acquire the fake path twice
    * verify both holders got the same model, and it is the one found under the path
    """
    del qtbot  # only needed so a QApplication exists
    load_document(mocker)
    registry = DocumentRegistry()

    first = registry.acquire(FAKE_PATH)
    second = registry.acquire(FAKE_PATH)

    assert first is second
    assert registry.find(FAKE_PATH) is first
    assert registry.models() == [first]


def test_distinct_paths_get_distinct_models(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Two paths are two documents.

    **Test steps:**

    * acquire two distinct paths
    * verify two models are held, each found under its own path
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()

    first = registry.acquire(FAKE_PATH)
    second = registry.acquire(OTHER_PATH)

    assert first is not second
    assert registry.find(FAKE_PATH) is first
    assert registry.find(OTHER_PATH) is second


def test_an_edit_through_one_holders_view_shows_in_the_others(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Two views over the one shared model stay in step before anything is saved ([[plugins#view-model]]).

    **Test steps:**

    * acquire the fake path twice and build a document widget over each hold
    * type a new title into the first widget's editor
    * verify the second widget's viewer shows it, and the shared model is dirty
    """
    load_document(mocker)
    registry = DocumentRegistry()
    first = DocumentWidget(registry.acquire(FAKE_PATH))
    qtbot.addWidget(first)
    second = DocumentWidget(registry.acquire(FAKE_PATH))
    qtbot.addWidget(second)
    editors = first.sub_docks._DocumentSubDocks__editor_docks  # type: ignore[attr-defined]  # pylint: disable=protected-access
    title_edit = next(
        edit for dock in editors.values() for edit in dock.widget().findChildren(QLineEdit) if edit.text() == "Foo"
    )

    title_edit.setText("Renamed")

    viewers = second.sub_docks._DocumentSubDocks__viewer_docks  # type: ignore[attr-defined]  # pylint: disable=protected-access
    viewer_texts = {label.text() for dock in viewers.values() for label in dock.widget().findChildren(QLabel)}
    assert "Renamed" in viewer_texts
    assert second.model.dirty


def test_the_model_outlives_every_release_but_the_last(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A release that leaves another holder keeps the model, still findable; the last one frees it.

    **Test steps:**

    * acquire the fake path twice, then release once
    * verify the model is still held and findable, and not destroyed by the event loop running
    * release again, waiting for the model to be destroyed
    * verify the path is no longer held
    """
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_PATH)
    registry.acquire(FAKE_PATH)
    destroyed: list[bool] = []
    model.destroyed.connect(lambda: destroyed.append(True))

    registry.release(model)
    qtbot.wait(1)  # let any (wrongly) deferred delete run

    assert not destroyed
    assert registry.find(FAKE_PATH) is model

    with wait_destroyed(qtbot, model):
        registry.release(model)

    assert registry.find(FAKE_PATH) is None
    assert not registry.models()


def test_only_the_last_release_of_a_dirty_model_discards_edits(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing one of several views of a dirty document loses nothing; the last one would.

    **Test steps:**

    * acquire the fake path twice and dirty the model
    * verify releasing would not discard edits while another holder remains
    * release once, then verify the remaining release would
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_PATH)
    registry.acquire(FAKE_PATH)
    model.dirty = True

    assert not registry.release_discards_edits(model)

    registry.release(model)

    assert registry.release_discards_edits(model)


def test_releasing_a_clean_model_never_discards_edits(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A clean last holder has nothing to lose.

    **Test steps:**

    * acquire the fake path once, leaving it clean
    * verify releasing would discard nothing
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_PATH)

    assert not registry.release_discards_edits(model)


def test_a_path_change_moves_the_models_key(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A renamed or converted document is found under its new path, and no longer under the old one.

    **Test steps:**

    * acquire the fake path, then move the model to the other path
    * verify the old path finds nothing and the new one finds the model
    * verify acquiring the new path hands back the same model
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_PATH)

    model.path = OTHER_PATH

    assert registry.find(FAKE_PATH) is None
    assert registry.find(OTHER_PATH) is model
    assert registry.acquire(OTHER_PATH) is model


def test_a_path_change_onto_another_held_path_keeps_that_ones_key(
    mocker: MockerFixture, qtbot: QtBot, caplog: LogCaptureFixture
) -> None:
    """A model moving onto a path another held model has leaves that one findable, and says so.

    **Test steps:**

    * acquire both paths, then move the first model onto the second's path
    * verify the second path still finds the second model, the first path finds nothing
    * verify a warning names the clash
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    first = registry.acquire(FAKE_PATH)
    second = registry.acquire(OTHER_PATH)

    with caplog.at_level(logging.WARNING):
        first.path = OTHER_PATH

    assert registry.find(OTHER_PATH) is second
    assert registry.find(FAKE_PATH) is None
    assert any(str(OTHER_PATH) in record.getMessage() for record in caplog.records)


def test_a_lazy_acquisition_is_an_unread_placeholder(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A lazy acquisition reads nothing (#66), and a later real one of the same path reads it.

    **Test steps:**

    * acquire the fake path lazily
    * verify the model is pending and the file was not read
    * acquire it again, not lazily
    * verify the same model is now loaded
    """
    del qtbot
    read_text = mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))
    registry = DocumentRegistry()

    model = registry.acquire(FAKE_PATH, lazy=True)

    assert model.pending
    read_text.assert_not_called()

    assert registry.acquire(FAKE_PATH) is model
    assert not model.pending
    assert model.title == "Foo"


def test_a_second_lazy_acquisition_leaves_the_placeholder_unread(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A lazy holder joining another's placeholder defers too -- only a real acquisition reads it (#66).

    **Test steps:**

    * acquire the fake path lazily, twice
    * verify both holds share the one model, still pending, with the file never read
    """
    del qtbot
    read_text = mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))
    registry = DocumentRegistry()

    model = registry.acquire(FAKE_PATH, lazy=True)

    assert registry.acquire(FAKE_PATH, lazy=True) is model
    assert model.pending
    read_text.assert_not_called()


def test_a_lazy_acquisition_of_a_tc_or_a_new_document_is_not_deferred(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Neither a ``.tc`` (whose deferred read would go through a ``.rehu``-only reload) nor a new document
    (with nothing to read) is ever a placeholder.

    **Test steps:**

    * acquire a ``.tc`` lazily, and a new document lazily
    * verify neither model is pending
    """
    del qtbot
    mocker.patch.object(Path, "read_text", return_value="type: Tutorial\ntitle: Legacy\n")
    registry = DocumentRegistry()

    assert not registry.acquire(TC_PATH, lazy=True).pending
    assert not registry.acquire(FAKE_PATH, new=True, lazy=True).pending


def test_a_new_acquisition_starts_dirty(qtbot: QtBot) -> None:
    """A new document is about to be written: empty, editable and dirty.

    **Test steps:**

    * acquire the fake path as a new document
    * verify it is dirty and not locked
    """
    del qtbot
    registry = DocumentRegistry()

    model = registry.acquire(FAKE_PATH, new=True)

    assert model.dirty
    assert not model.locked


def test_releasing_a_model_nobody_holds_raises(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A release without a matching acquire is a bookkeeping bug, not something to swallow.

    **Test steps:**

    * acquire and fully release the fake path
    * verify releasing it once more raises ``KeyError``
    """
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_PATH)
    with wait_destroyed(qtbot, model):
        registry.release(model)

    with raises(KeyError):
        registry.release(model)


# region Following the app's own renames and writes (#376)

LIBRARY: Final = Path.cwd() / "fake" / "library"


def test_a_member_follows_its_collection_folders_rename(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A directory-scoped collection renamed while a member nested in it is open: the member's record moves
    with the folder, and the registry finds it under its new path.

    **Test steps:**

    * hold a member's ``info.rehu`` nested under a collection folder
    * announce the collection folder's rename
    * verify the member's path moved and it is found under the new one only
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    member = LIBRARY / "series" / "part1" / "info.rehu"
    model = registry.acquire(member)

    registry.resource_events.announce_moved(Relocation(((LIBRARY / "series", LIBRARY / "saga"),)))

    moved = LIBRARY / "saga" / "part1" / "info.rehu"
    assert model.path == moved
    assert registry.find(moved) is model
    assert registry.find(member) is None


def test_a_file_scoped_record_follows_its_own_rename(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``foo.rehu`` renamed with its sibling set: the open record is re-pointed at ``bar.rehu``.

    **Test steps:**

    * hold ``foo.rehu`` and announce the rename of its set
    * verify it is now ``bar.rehu``
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(LIBRARY / "foo.rehu")

    registry.resource_events.announce_moved(
        Relocation(
            (
                (LIBRARY / "foo.rehu", LIBRARY / "bar.rehu"),
                (LIBRARY / "foo.zip", LIBRARY / "bar.zip"),
                (LIBRARY / "foo.checksum", LIBRARY / "bar.checksum"),
                (LIBRARY / "foo00.jpg", LIBRARY / "bar00.jpg"),
            )
        )
    )

    assert model.path == LIBRARY / "bar.rehu"
    assert registry.find(LIBRARY / "bar.rehu") is model


def test_a_folder_rename_carries_its_file_scoped_record_and_a_sibling_rename_does_not_touch_the_folders(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A folder holding ``info.rehu`` and a file-scoped ``bar.rehu``: renaming the folder moves both open
    records; renaming ``bar`` afterwards moves only ``bar``.

    **Test steps:**

    * hold the folder's ``info.rehu`` and its ``bar.rehu``
    * announce the folder's rename, and verify both moved
    * announce ``bar``'s rename within the renamed folder, and verify ``info.rehu`` stayed
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    info = registry.acquire(LIBRARY / "pack" / "info.rehu")
    standalone = registry.acquire(LIBRARY / "pack" / "bar.rehu")
    kit = LIBRARY / "kit"

    registry.resource_events.announce_moved(Relocation(((LIBRARY / "pack", kit),)))

    assert info.path == kit / "info.rehu"
    assert standalone.path == kit / "bar.rehu"

    with stays_put(info):
        registry.resource_events.announce_moved(Relocation(((kit / "bar.rehu", kit / "baz.rehu"),)))

    assert standalone.path == kit / "baz.rehu"
    assert info.path == kit / "info.rehu"


@contextmanager
def stays_put(model: RehuDocumentModel) -> Generator[None]:
    """Fail if ``model``'s path changes inside the block.

    :param model: the model that must stay put.
    :yields: nothing; the block runs the announcement.
    """
    moves: list[object] = []
    model.path_changed.connect(moves.append)  # type: ignore[attr-defined]
    try:
        yield
    finally:
        model.path_changed.disconnect(moves.append)  # type: ignore[attr-defined]
    assert not moves


def test_a_held_models_writes_are_announced_until_its_last_release(mocker: MockerFixture, qtbot: QtBot) -> None:
    """What a held model says it wrote reaches the app-wide events; a released one is no longer relayed.

    **Test steps:**

    * hold a model and have it announce a write and a folder change
    * verify both were announced app-wide
    * release it, and verify a later announcement is not relayed
    """
    load_document(mocker)
    events = ResourceEvents()
    registry = DocumentRegistry(resource_events=events)
    model = registry.acquire(FAKE_PATH)

    with qtbot.waitSignal(events.changed) as changed:
        model.announce_files_changed((FAKE_PATH,))
    with qtbot.waitSignal(events.folder_changed) as folder:
        model.announce_folder_changed(FAKE_PATH.parent)

    assert changed.args == [(FAKE_PATH,)]
    assert folder.args == [FAKE_PATH.parent]

    registry.release(model)
    with qtbot.assertNotEmitted(events.changed):
        model.announce_files_changed((FAKE_PATH,))


def test_the_renaming_document_adopts_its_rename_exactly_once(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The coordinator's announcement reaches the renaming model through the registry before the rename call
    returns to it; between the two it moves, and each signal fires, exactly once.

    **Test steps:**

    * hold a model in a registry whose events hear a coordinator, with the rename on disk mocked
    * rename it from its location editor
    * verify ``path_changed`` and ``image_scanner_changed`` fired once each, and the registry re-keyed it
    """
    del qtbot
    load_document(mocker)
    renamed = FAKE_PATH.parent.with_name("modelling") / "info.rehu"
    renamer = mocker.patch("rehuco_core.rename_coordination.RehuRenamer", autospec=True).return_value
    renamer.rename.return_value = renamed
    renamer.relocation = Relocation(((FAKE_PATH.parent, renamed.parent),))
    mocker.patch.object(RenameCoordinator, "_RenameCoordinator__step_out_of")
    coordinator = RenameCoordinator()
    events = ResourceEvents()
    coordinator.add_rename_listener(events.announce_moved)
    registry = DocumentRegistry(rename_coordinator=coordinator, resource_events=events)
    model = registry.acquire(FAKE_PATH)
    paths: list[object] = []
    scanners: list[object] = []
    model.path_changed.connect(paths.append)  # type: ignore[attr-defined]
    model.image_scanner_changed.connect(scanners.append)  # type: ignore[attr-defined]

    assert model.rename_location("modelling")

    assert paths == [renamed]
    assert len(scanners) == 1
    assert registry.find(renamed) is model


# endregion
