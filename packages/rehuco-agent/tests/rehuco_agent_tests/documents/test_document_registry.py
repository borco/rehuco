"""Tests for DocumentRegistry: one shared view-model per open key, refcounted (#375), read and saved through
its records (#416)."""

import json
import logging
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QLabel, QLineEdit
from pytest import LogCaptureFixture, mark, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_registry import DocumentRegistry, load_record
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.resource_events import ResourceEvents
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_core import RecordConflict, RehuDocument, Relocation, RenameCoordinator
from rehuco_core.access import ChangeFeed, Records, ResourceKey

from rehuco_agent_tests.qt_waits import wait_destroyed

from .test_rehu_document_model_conflict import edit_on_disk, retitle, write_record

FAKE_PATH: Final = Path.cwd() / "fake" / "tutorials" / "sculpting" / "info.rehu"
"""Built from ``Path.cwd()`` so it is absolute on every platform."""
FAKE_KEY: Final = ResourceKey(FAKE_PATH)
OTHER_PATH: Final = Path.cwd() / "fake" / "tutorials" / "painting" / "info.rehu"
OTHER_KEY: Final = ResourceKey(OTHER_PATH)
TC_KEY: Final = ResourceKey(Path.cwd() / "fake" / "tutorials" / "legacy" / "info.tc")

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


def test_two_acquisitions_of_one_key_share_one_model(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Acquiring an already-held key hands back the same model, not a second read of the file.

    **Test steps:**

    * acquire the fake key twice
    * verify both holders got the same model, and it is the one found under the key
    """
    del qtbot  # only needed so a QApplication exists
    load_document(mocker)
    registry = DocumentRegistry()

    first = registry.acquire(FAKE_KEY)
    second = registry.acquire(FAKE_KEY)

    assert first is second
    assert registry.find(FAKE_KEY) is first
    assert registry.models() == [first]


def test_distinct_keys_get_distinct_models(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Two keys are two documents.

    **Test steps:**

    * acquire two distinct keys
    * verify two models are held, each found under its own key
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()

    first = registry.acquire(FAKE_KEY)
    second = registry.acquire(OTHER_KEY)

    assert first is not second
    assert registry.find(FAKE_KEY) is first
    assert registry.find(OTHER_KEY) is second


def test_an_edit_through_one_holders_view_shows_in_the_others(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Two views over the one shared model stay in step before anything is saved ([[plugins#view-model]]).

    **Test steps:**

    * acquire the fake key twice and build a document widget over each hold
    * type a new title into the first widget's editor
    * verify the second widget's viewer shows it, and the shared model is dirty
    """
    load_document(mocker)
    registry = DocumentRegistry()
    first = DocumentWidget(registry.acquire(FAKE_KEY))
    qtbot.addWidget(first)
    second = DocumentWidget(registry.acquire(FAKE_KEY))
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

    * acquire the fake key twice, then release once
    * verify the model is still held and findable, and not destroyed by the event loop running
    * release again, waiting for the model to be destroyed
    * verify the key is no longer held
    """
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_KEY)
    registry.acquire(FAKE_KEY)
    destroyed: list[bool] = []
    model.destroyed.connect(lambda: destroyed.append(True))

    registry.release(model)
    qtbot.wait(1)  # let any (wrongly) deferred delete run

    assert not destroyed
    assert registry.find(FAKE_KEY) is model

    with wait_destroyed(qtbot, model):
        registry.release(model)

    assert registry.find(FAKE_KEY) is None
    assert not registry.models()


def test_only_the_last_release_of_a_dirty_model_discards_edits(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Closing one of several views of a dirty document loses nothing; the last one would.

    **Test steps:**

    * acquire the fake key twice and dirty the model
    * verify releasing would not discard edits while another holder remains
    * release once, then verify the remaining release would
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_KEY)
    registry.acquire(FAKE_KEY)
    model.dirty = True

    assert not registry.release_discards_edits(model)

    registry.release(model)

    assert registry.release_discards_edits(model)


def test_releasing_a_clean_model_never_discards_edits(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A clean last holder has nothing to lose.

    **Test steps:**

    * acquire the fake key once, leaving it clean
    * verify releasing would discard nothing
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_KEY)

    assert not registry.release_discards_edits(model)


def test_a_key_change_moves_the_models_entry(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A renamed or converted document is found under its new key, and no longer under the old one.

    **Test steps:**

    * acquire the fake key, then move the model to the other key
    * verify the old key finds nothing and the new one finds the model
    * verify acquiring the new key hands back the same model
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_KEY)

    model.key = OTHER_KEY

    assert registry.find(FAKE_KEY) is None
    assert registry.find(OTHER_KEY) is model
    assert registry.acquire(OTHER_KEY) is model


def test_a_key_change_onto_another_held_key_keeps_that_ones_entry(
    mocker: MockerFixture, qtbot: QtBot, caplog: LogCaptureFixture
) -> None:
    """A model moving onto a key another held model has leaves that one findable, and says so.

    **Test steps:**

    * acquire both keys, then move the first model onto the second's key
    * verify the second key still finds the second model, the first key finds nothing
    * verify a warning names the clash
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    first = registry.acquire(FAKE_KEY)
    second = registry.acquire(OTHER_KEY)

    with caplog.at_level(logging.WARNING):
        first.key = OTHER_KEY

    assert registry.find(OTHER_KEY) is second
    assert registry.find(FAKE_KEY) is None
    assert any(str(OTHER_KEY) in record.getMessage() for record in caplog.records)


def test_a_lazy_acquisition_is_an_unread_placeholder(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A lazy acquisition reads nothing (#66), and a later real one of the same key reads it.

    **Test steps:**

    * acquire the fake key lazily
    * verify the model is pending and the file was not read
    * acquire it again, not lazily
    * verify the same model is now loaded
    """
    del qtbot
    read_text = mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))
    registry = DocumentRegistry()

    model = registry.acquire(FAKE_KEY, lazy=True)

    assert model.pending
    read_text.assert_not_called()

    assert registry.acquire(FAKE_KEY) is model
    assert not model.pending
    assert model.title == "Foo"


def test_a_second_lazy_acquisition_leaves_the_placeholder_unread(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A lazy holder joining another's placeholder defers too -- only a real acquisition reads it (#66).

    **Test steps:**

    * acquire the fake key lazily, twice
    * verify both holds share the one model, still pending, with the file never read
    """
    del qtbot
    read_text = mocker.patch.object(Path, "read_text", return_value=json.dumps(TUTORIAL))
    registry = DocumentRegistry()

    model = registry.acquire(FAKE_KEY, lazy=True)

    assert registry.acquire(FAKE_KEY, lazy=True) is model
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

    assert not registry.acquire(TC_KEY, lazy=True).pending
    assert not registry.acquire(FAKE_KEY, new=True, lazy=True).pending


def test_a_new_acquisition_starts_dirty(qtbot: QtBot) -> None:
    """A new document is about to be written: empty, editable and dirty.

    **Test steps:**

    * acquire the fake key as a new document
    * verify it is dirty and not locked
    """
    del qtbot
    registry = DocumentRegistry()

    model = registry.acquire(FAKE_KEY, new=True)

    assert model.dirty
    assert not model.locked


def test_releasing_a_model_nobody_holds_raises(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A release without a matching acquire is a bookkeeping bug, not something to swallow.

    **Test steps:**

    * acquire and fully release the fake key
    * verify releasing it once more raises ``KeyError``
    """
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_KEY)
    with wait_destroyed(qtbot, model):
        registry.release(model)

    with raises(KeyError):
        registry.release(model)


# region Following the app's own renames and writes (#376)

LIBRARY: Final = Path.cwd() / "fake" / "library"


def test_a_member_follows_its_collection_folders_rename(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A directory-scoped collection renamed while a member nested in it is open: the member's record moves
    with the folder, and the registry finds it under its new key.

    **Test steps:**

    * hold a member's ``info.rehu`` nested under a collection folder
    * announce the collection folder's rename
    * verify the member's path moved and it is found under the new key only
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    member = LIBRARY / "series" / "part1" / "info.rehu"
    model = registry.acquire(ResourceKey(member))

    registry.resource_events.announce_moved(Relocation(((LIBRARY / "series", LIBRARY / "saga"),)))

    moved = LIBRARY / "saga" / "part1" / "info.rehu"
    assert model.path == moved
    assert registry.find(ResourceKey(moved)) is model
    assert registry.find(ResourceKey(member)) is None


def test_a_file_scoped_record_follows_its_own_rename(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``foo.rehu`` renamed with its sibling set: the open record is re-pointed at ``bar.rehu``.

    **Test steps:**

    * hold ``foo.rehu`` and announce the rename of its set
    * verify it is now ``bar.rehu``
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(ResourceKey(LIBRARY / "foo.rehu"))

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
    assert registry.find(ResourceKey(LIBRARY / "bar.rehu")) is model


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
    info = registry.acquire(ResourceKey(LIBRARY / "pack" / "info.rehu"))
    standalone = registry.acquire(ResourceKey(LIBRARY / "pack" / "bar.rehu"))
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
    """Fail if ``model``'s key changes inside the block.

    :param model: the model that must stay put.
    :yields: nothing; the block runs the announcement.
    """
    moves: list[object] = []
    model.key_changed.connect(moves.append)  # type: ignore[attr-defined]
    try:
        yield
    finally:
        model.key_changed.disconnect(moves.append)  # type: ignore[attr-defined]
    assert not moves


def test_the_renaming_document_adopts_its_rename_exactly_once(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The coordinator's announcement reaches the renaming model through the registry before the rename call
    returns to it; between the two it moves, and each signal fires, exactly once.

    **Test steps:**

    * hold a model in a registry whose events hear a coordinator, with the rename on disk mocked
    * rename it from its location editor
    * verify ``key_changed`` and ``image_scanner_changed`` fired once each, and the registry re-keyed it
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
    model = registry.acquire(FAKE_KEY)
    keys: list[object] = []
    scanners: list[object] = []
    model.key_changed.connect(keys.append)  # type: ignore[attr-defined]
    model.image_scanner_changed.connect(scanners.append)  # type: ignore[attr-defined]

    assert model.rename_location("modelling")

    assert keys == [ResourceKey(renamed)]
    assert len(scanners) == 1
    assert registry.find(ResourceKey(renamed)) is model


# endregion


def test_an_open_is_announced_as_an_access_once_and_a_new_document_never(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Building a model for a file is an access the catalog verifies (#487); a second holder of it, or a document
    that is not on disk yet, is not.

    **Test steps:**

    * acquire one key twice, and start a new document at another
    * verify the one key was announced once, and the new one never
    """
    del qtbot
    load_document(mocker)
    events = ResourceEvents()
    heard: list[object] = []
    events.accessed.connect(heard.append)
    registry = DocumentRegistry(resource_events=events)

    registry.acquire(FAKE_KEY)
    registry.acquire(FAKE_KEY)
    registry.acquire(OTHER_KEY, new=True)

    assert heard == [(FAKE_KEY,)]


def test_a_reload_is_announced_as_an_access(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A revert reads the file again -- the one way an edit made outside the app reaches a document left open (#487).

    **Test steps:**

    * acquire a key, then revert its model
    * verify the key was announced again
    """
    del qtbot
    load_document(mocker)
    events = ResourceEvents()
    heard: list[object] = []
    events.accessed.connect(heard.append)
    registry = DocumentRegistry(resource_events=events)
    model = registry.acquire(FAKE_KEY)

    model.revert()

    assert heard == [(FAKE_KEY,), (FAKE_KEY,)]


def test_a_reload_of_a_document_with_no_key_is_not_announced(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A model whose key is gone has nothing for the catalog to check (#487), and is findable under no key.

    **Test steps:**

    * acquire a key, take the model's key away, and revert it
    * verify the old key finds nothing, and nothing more was announced
    """
    del qtbot
    load_document(mocker)
    events = ResourceEvents()
    heard: list[object] = []
    events.accessed.connect(heard.append)
    registry = DocumentRegistry(resource_events=events)
    model = registry.acquire(FAKE_KEY)
    model.key = None
    heard.clear()

    model.reloaded.emit()

    assert registry.find(FAKE_KEY) is None
    assert not heard


# region the records (#416)
@mark.usefixtures("real_path_stat")
def test_given_records_read_and_save_every_model(mocker: MockerFixture, qtbot: QtBot, tmp_path: Path) -> None:
    """Every model the registry builds -- opened, new, or an unread placeholder -- goes through the records it was
    handed.

    **Test steps:**

    * build a registry over records of the test's own, spying on their saves
    * open a record, start a new document, and take a lazy placeholder and read it; edit and save each
    * verify the records saved each record's key, in turn, and every file holds its new title
    """
    del qtbot
    records = Records()
    saves = mocker.spy(records, "save")
    registry = DocumentRegistry(records=records)
    opened, placeholder = tmp_path / "a" / "info.rehu", tmp_path / "c" / "info.rehu"
    new = tmp_path / "b" / "info.rehu"
    for path in (opened, new, placeholder):
        path.parent.mkdir()
    write_record(opened, "Opened")
    write_record(placeholder, "Placeholder")
    models = [
        registry.acquire(ResourceKey(opened)),
        registry.acquire(ResourceKey(new), new=True),
        registry.acquire(ResourceKey(placeholder), lazy=True),
    ]
    models[2].load_pending()

    for model in models:
        model.title = "Saved"
        model.save()

    assert [call.args[0] for call in saves.call_args_list] == [ResourceKey(path) for path in (opened, new, placeholder)]
    assert all(RehuDocument.load(path).title == "Saved" for path in (opened, new, placeholder))


@mark.usefixtures("real_path_stat")
def test_the_default_records_save_and_announce_nothing(mocker: MockerFixture, qtbot: QtBot, tmp_path: Path) -> None:
    """With no records given, the registry builds its own, which write the file and say nothing: the folder's file
    notifier reports the save to every view (#511).

    **Test steps:**

    * build a registry over the app's events only, and open a real record
    * edit and save it
    * verify the file holds the edit and nothing was published on any change feed
    """
    del qtbot
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    registry = DocumentRegistry(resource_events=ResourceEvents())
    model = registry.acquire(ResourceKey(path))
    model.title = "Mine"
    published = mocker.spy(ChangeFeed, "publish")

    model.save()

    assert RehuDocument.load(path).title == "Mine"
    published.assert_not_called()


@mark.usefixtures("real_path_stat")
def test_a_placeholder_read_later_still_refuses_a_save_over_a_change_on_disk(qtbot: QtBot, tmp_path: Path) -> None:
    """A deferred read takes the version too: what it read is what a save is checked against.

    **Test steps:**

    * take a lazy placeholder of a real record and read it, then edit its title and retitle the file
    * verify a save is refused as a conflict
    """
    del qtbot
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    registry = DocumentRegistry()
    model = registry.acquire(ResourceKey(path), lazy=True)
    model.load_pending()
    model.title = "Mine"
    edit_on_disk(path, retitle("Theirs"))

    with raises(RecordConflict):
        model.save()


@mark.usefixtures("real_path_stat")
def test_a_record_is_read_with_its_version_and_signature_and_logged(
    caplog: LogCaptureFixture, tmp_path: Path, qtbot: QtBot
) -> None:
    """``load_record`` hands a model all it needs to save safely later: the document, what it was read at, and the
    file's signature; the read is logged with the record's type.

    **Test steps:**

    * read a real record through records
    * verify the document, a version, and the file's signature, under the current identity
    * verify the read was logged
    """
    del qtbot
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    stat = path.stat()

    with caplog.at_level(logging.INFO):
        record = load_record(Records(), ResourceKey(path))

    assert record.document.title == "Old"
    assert record.document.username == shared_identity_settings().current_username
    assert record.version is not None
    assert record.signature == (stat.st_mtime_ns, stat.st_size)
    assert f"Read {ResourceKey(path)} as tutorial" in caplog.messages


@mark.usefixtures("real_path_stat")
def test_a_record_that_cannot_be_read_is_a_locked_stub_and_no_read_is_logged(
    caplog: LogCaptureFixture, tmp_path: Path, qtbot: QtBot
) -> None:
    """A missing file opens as a locked stub with nothing to save against, and is not logged as read.

    **Test steps:**

    * read a record whose file does not exist
    * verify a locked stub with no version and no signature
    * verify no read was logged
    """
    del qtbot
    path = tmp_path / "info.rehu"

    with caplog.at_level(logging.INFO):
        record = load_record(Records(), ResourceKey(path))

    assert record.document.load_failed
    assert record.lock_reasons
    assert (record.version, record.signature) == (None, None)
    assert not [message for message in caplog.messages if message.startswith("Read ")]


@mark.usefixtures("real_path_stat")
def test_a_legacy_record_files_its_flags_under_the_unknown_user(tmp_path: Path, qtbot: QtBot) -> None:
    """A ``.tc``'s per-user flags were not set by this install's identity, so they are read as the unknown user's,
    and it is never saved over.

    **Test steps:**

    * write a legacy ``.tc`` carrying a rating, and read it through ``load_record``
    * verify the rating is filed under the unknown user, and there is no version
    """
    del qtbot
    path = tmp_path / "info.tc"
    path.write_text("type: Tutorial\ntitle: Legacy\nrating: 4\n", encoding="utf-8")

    record = load_record(Records(), ResourceKey(path))

    unknown = shared_identity_settings().unknown_username
    assert record.document.title == "Legacy"
    assert record.document.user_field(unknown, "rating") == 4
    assert record.version is None


# endregion
