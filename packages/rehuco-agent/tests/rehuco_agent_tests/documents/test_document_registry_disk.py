"""Tests for DocumentRegistry hearing the disk (#511): a change the feed reports reaches the held model of that file
through a read off the GUI thread, and the folders of the held documents under no root are watched.

The changes are published on the registry's own feed, as a notifier would; the records are real, under ``tmp_path``,
where a model must reload or be flagged.
"""

from pathlib import Path
from typing import Final
from unittest.mock import MagicMock
from uuid import uuid4

from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_registry import DocumentRegistry
from rehuco_agent.documents.held_files_watch import HeldFilesWatch
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core.access import Changed, ChangeEvent, FolderChanged, ResourceKey, RootStale
from rehuco_core.notify import WatchedFolder

from .test_document_registry import FAKE_KEY, FAKE_PATH, OTHER_KEY, OTHER_PATH, load_document
from .test_rehu_document_model_conflict import edit_on_disk, retitle, write_record

TIMEOUT_MS: Final = 5000
"""How long a test waits for a read off the GUI thread, in milliseconds."""


def disk_of(registry: DocumentRegistry) -> HeldFilesWatch:
    """The registry's disk side.

    :param registry: the registry.
    :returns: its watch.
    """
    watch = registry.findChild(HeldFilesWatch)
    assert isinstance(watch, HeldFilesWatch)
    return watch


def opened(qtbot: QtBot, tmp_path: Path) -> tuple[DocumentRegistry, RehuDocumentModel, Path]:
    """A registry holding a real record under ``tmp_path``, titled ``Old``.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: where the record is written.
    :returns: the registry, the held model and the record's path.
    """
    del qtbot
    path = tmp_path / "info.rehu"
    write_record(path, "Old")
    registry = DocumentRegistry()
    return registry, registry.acquire(ResourceKey(path)), path


def published(registry: DocumentRegistry, event: ChangeEvent) -> None:
    """Publish ``event`` on the registry's feed, as a file notifier would.

    :param registry: the registry.
    :param event: what changed.
    """
    registry.resource_events.changes.publish(event)


@fixture(name="notifiers")
def fixture_notifiers(mocker: MockerFixture) -> MagicMock:
    """Stand in for the file notifier the registry's watch builds.

    :param mocker: pytest-mock fixture.
    :returns: the stand-in class.
    """
    return mocker.patch("rehuco_agent.documents.held_files_watch.FileNotifier")


# region a change on disk reaches the held model


@mark.usefixtures("real_path_stat")
def test_a_change_to_a_clean_models_file_reloads_it(qtbot: QtBot, tmp_path: Path) -> None:
    """A clean model follows its file when the feed says it changed: the file is read, and differs from what it holds.

    **Test steps:**

    * hold a real record, and retitle its file outside the app
    * publish the file as changed
    * verify the model reloads with the file's title, and is not flagged
    """
    registry, model, path = opened(qtbot, tmp_path)
    edit_on_disk(path, retitle("Theirs"))

    with qtbot.waitSignal(model.reloaded, timeout=TIMEOUT_MS):
        published(registry, Changed((ResourceKey(path),)))

    assert model.title == "Theirs"
    assert not model.changed_on_disk


@mark.usefixtures("real_path_stat")
def test_a_change_to_a_dirty_models_file_flags_it(qtbot: QtBot, tmp_path: Path) -> None:
    """A model with unsaved edits is not reloaded over them: it is flagged, for the user to choose.

    **Test steps:**

    * hold a real record and edit its title, then retitle its file outside the app
    * publish the file as changed
    * verify the model is flagged as changed on disk and keeps its edit
    """
    registry, model, path = opened(qtbot, tmp_path)
    model.title = "Mine"
    edit_on_disk(path, retitle("Theirs"))

    with qtbot.waitSignal(model.changed_on_disk_changed, timeout=TIMEOUT_MS):  # type: ignore[attr-defined]
        published(registry, Changed((ResourceKey(path),)))

    assert model.changed_on_disk
    assert model.title == "Mine"


@mark.usefixtures("real_path_stat")
def test_the_echo_of_its_own_save_changes_nothing(qtbot: QtBot, tmp_path: Path) -> None:
    """A model's own save comes back from the folder's notifier like any change; the file then looks as the save left
    it, so the model neither reloads nor is flagged.

    **Test steps:**

    * hold a real record, edit and save it
    * publish the file as changed, and wait for the read
    * verify the model did not reload, is clean and not flagged
    """
    registry, model, path = opened(qtbot, tmp_path)
    model.title = "Mine"
    model.save()
    reloads: list[object] = []
    model.reloaded.connect(lambda: reloads.append(1))

    with qtbot.waitSignal(disk_of(registry).statted, timeout=TIMEOUT_MS) as statted:
        published(registry, Changed((ResourceKey(path),)))

    assert statted.args is not None
    assert list(statted.args[0]) == [path]
    assert not reloads
    assert not model.dirty
    assert not model.changed_on_disk
    assert model.title == "Mine"


@mark.parametrize(
    ("changed", "read"),
    [
        ((FAKE_KEY,), [FAKE_KEY]),
        ((FAKE_KEY.parent.parent,), [FAKE_KEY, OTHER_KEY]),
        ((OTHER_KEY.parent,), [OTHER_KEY]),
        ((ResourceKey(Path.cwd() / "elsewhere"),), []),
    ],
    ids=["the-file", "a-folder-above-both", "the-other-ones-folder", "elsewhere"],
)
def test_a_change_reads_the_held_files_at_or_beneath_it(
    mocker: MockerFixture, qtbot: QtBot, changed: tuple[ResourceKey, ...], read: list[ResourceKey]
) -> None:
    """A changed file is read again if it is held; a changed folder -- a deletion, a rename seen as one -- reads every
    held file beneath it; a change elsewhere reads none.

    **Test steps:**

    * hold two records, and stand in for the watch's read
    * publish the change
    * verify the files read were exactly the held ones at or beneath it
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    registry.acquire(FAKE_KEY)
    registry.acquire(OTHER_KEY)
    reads = mocker.patch.object(disk_of(registry), "read")

    published(registry, Changed(changed))

    reads.assert_called_once()
    assert list(reads.call_args.args[0]) == read


def test_a_folder_whose_listing_changed_reads_the_held_files_in_it(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A folder whose listing changed may hold a document's file that changed with it -- and it is all a folder watch
    that lost events can say of its whole folder -- so the held files in it are read again (#511).

    **Test steps:**

    * hold two records in different folders, and stand in for the watch's read
    * publish one record's folder as changed
    * verify only that record's file was read
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    registry.acquire(FAKE_KEY)
    registry.acquire(OTHER_KEY)
    reads = mocker.patch.object(disk_of(registry), "read")

    published(registry, FolderChanged(OTHER_KEY.parent))

    reads.assert_called_once()
    assert list(reads.call_args.args[0]) == [OTHER_KEY]


def test_a_stale_root_reads_every_held_file(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A root nothing can be trusted about may hold any open document, so all of them are read again.

    **Test steps:**

    * hold two records, and stand in for the watch's read
    * publish a stale root
    * verify both files were read
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    registry.acquire(FAKE_KEY)
    registry.acquire(OTHER_KEY)
    reads = mocker.patch.object(disk_of(registry), "read")

    published(registry, RootStale(uuid4()))

    reads.assert_called_once_with((FAKE_KEY, OTHER_KEY))


def test_what_the_disk_shows_reaches_the_model_of_that_path_only(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A file's time and size go to the model held under that path's key; a path nobody holds -- released while the
    read was out -- is passed over (#487).

    **Test steps:**

    * hold one key, and have the watch deliver its path and a path nobody holds
    * verify the held model alone heard, with what was delivered
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_KEY)
    noted = mocker.patch.object(model, "note_file_signature")

    disk_of(registry).statted.emit({FAKE_PATH: (7, 3), OTHER_PATH: (8, 4)})

    noted.assert_called_once_with(7, 3)


def test_a_file_found_missing_reaches_the_model_of_that_path_only(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A file the watch found missing is told to the model held under that path's key, with whether its folder went;
    a path nobody holds is passed over (#497).

    **Test steps:**

    * hold one key, and have the watch report its path and a path nobody holds as missing
    * verify the held model alone heard its file gone, with its folder gone too
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    model = registry.acquire(FAKE_KEY)
    gone = mocker.patch.object(model, "note_file_gone")

    disk_of(registry).missing.emit({FAKE_PATH: True, OTHER_PATH: False})

    gone.assert_called_once_with(folder_gone=True)


# endregion

# region the loose folders


def test_the_loose_folders_are_followed_whenever_the_held_documents_change(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Which folders to watch is asked again on every first acquisition, last release and key change -- not on a
    second holder or an earlier release.

    **Test steps:**

    * stand in for the watch's follow, and acquire a key twice
    * verify it was followed once, with the key
    * re-key the model, then release it twice
    * verify it was followed with the new key, then with nothing, once each
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    follows = mocker.patch.object(disk_of(registry), "follow")

    model = registry.acquire(FAKE_KEY)
    registry.acquire(FAKE_KEY)

    assert follows.call_args_list == [mocker.call((FAKE_KEY,))]

    model.key = OTHER_KEY
    registry.release(model)
    registry.release(model)

    assert follows.call_args_list == [mocker.call((FAKE_KEY,)), mocker.call((OTHER_KEY,)), mocker.call(())]


@mark.parametrize("onto_other", [False, True], ids=["no key", "another held key"])
def test_a_key_change_that_tracks_nothing_still_lets_the_old_folder_go(
    onto_other: bool, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """A model whose key becomes none, or one another held model already has, is tracked under nothing -- and the
    folder its old key was in is followed again all the same, so its watch is let go (#511).

    **Test steps:**

    * stand in for the watch's follow; acquire one key, and another for the second case
    * move the first model's key to none, or onto the other model's key
    * verify the last follow names only what is still tracked
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry()
    follows = mocker.patch.object(disk_of(registry), "follow")
    model = registry.acquire(FAKE_KEY)
    if onto_other:
        registry.acquire(OTHER_KEY)

    model.key = OTHER_KEY if onto_other else None

    assert follows.call_args == mocker.call((OTHER_KEY,) if onto_other else ())


def test_a_document_under_no_root_has_its_folder_watched(
    notifiers: MagicMock, mocker: MockerFixture, qtbot: QtBot
) -> None:
    """The registry hands its watch the roots it was given: a document under one is left to the root's notifier, one
    under none gets a notifier of its own folder.

    **Test steps:**

    * build a registry whose roots hold the fake key's folder, and acquire it and the other key
    * verify one notifier was built and started, for the other key's folder
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry(roots=lambda: (FAKE_PATH.parent,))

    registry.acquire(FAKE_KEY)
    registry.acquire(OTHER_KEY)

    notifiers.assert_called_once()
    assert notifiers.call_args.args[0] == WatchedFolder(OTHER_PATH.parent, None, True)
    notifiers.return_value.start.assert_called_once_with()


def test_stop_watching_lets_the_loose_folders_go(notifiers: MagicMock, mocker: MockerFixture, qtbot: QtBot) -> None:
    """Before the window goes the registry stops its watches, and a later change of the held documents starts none.

    **Test steps:**

    * hold a document under no root, then stop watching
    * verify its notifier was stopped
    * acquire another, and verify no notifier was built for it
    """
    del qtbot
    load_document(mocker)
    registry = DocumentRegistry(roots=tuple)
    registry.acquire(FAKE_KEY)

    registry.stop_watching()

    notifiers.return_value.stop.assert_called_once_with()
    registry.acquire(OTHER_KEY)
    notifiers.assert_called_once()


# endregion
