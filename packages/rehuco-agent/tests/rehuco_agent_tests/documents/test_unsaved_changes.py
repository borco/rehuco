"""Tests for ``UnsavedChanges``: unsaved edits kept across a quit, and their documents reopened with them on the next
start -- at once on a local drive, as the device answers otherwise (#497).

The kept edits are a real file under ``tmp_path``; the Documents dock, the records and the startup presence are mocks
-- each has its own tests.
"""

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from borco_core import Presence
from PySide6.QtCore import QObject
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.documents import unsaved_changes as module
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.documents.unsaved_changes import UNSAVED_CHANGES_FILENAME, UNSAVED_CHANGES_VERSION, UnsavedChanges
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_agent.settings.state_file import encode_bytes
from rehuco_core import RecordVersion, RehuDocument, SavePayload
from rehuco_core.access import LoadedRecord, Records, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

USERNAME: Final = "someone"
LAYOUT: Final = b"the document's own layout"
BASE: Final = RecordVersion("meta", "base", ())
BASE_PAYLOAD: Final = {"core": {"title": "Old"}}
EDITS: Final = {"core": {"title": "Mine"}}
ON_DISK: Final = {"core": {"title": "Theirs"}}


def payload_at(path: Path, *, base: RecordVersion | None = BASE, first_save: bool = False) -> SavePayload:
    """A document's kept edits of the record at ``path``.

    :param path: the record.
    :param base: the version it was read at; ``None`` for a record never read from its file.
    :param first_save: whether nothing was ever written there.
    :returns: the payload.
    """
    return SavePayload(
        path, USERNAME, dict(EDITS), None if base is None else dict(BASE_PAYLOAD), base, first_save=first_save
    )


def write_entries(store: Path, documents: Any) -> None:
    """Write the kept edits file as a previous run would have.

    :param store: the file.
    :param documents: what it holds under ``documents``.
    """
    store.write_text(json.dumps({"version": UNSAVED_CHANGES_VERSION, "documents": documents}), encoding="utf-8")


def entry_of(payload: SavePayload) -> dict[str, Any]:
    """One kept document, as the file spells it.

    :param payload: its edits.
    :returns: the entry.
    """
    return {"payload": payload.to_json(), "layout": encode_bytes(LAYOUT)}


def kept_paths(store: Path) -> list[str]:
    """The records the kept edits file holds edits of.

    :param store: the file.
    :returns: their paths, as written.
    """
    values = json.loads(store.read_text(encoding="utf-8"))
    return [document["payload"]["path"] for document in values["documents"]]


def record_file(folder: Path) -> Path:
    """A record's file, written in ``folder``.

    :param folder: where it is.
    :returns: the file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "res.rehu"
    path.write_text("{}", encoding="utf-8")
    return path


# the owner's collaborators and what each test reaches for
# pylint: disable-next=too-many-instance-attributes
class Rig:
    """An :class:`UnsavedChanges` over a mocked Documents dock, records and startup presence, keeping its edits in a
    file under ``tmp_path``.

    :param mocker: pytest-mock fixture.
    :param tmp_path: the test's folder.
    :param delete_at_teardown: deletes the bare `QObject` s built here when the test ends.
    """

    def __init__(self, mocker: MockerFixture, tmp_path: Path, delete_at_teardown: DeleteAtTeardown) -> None:
        self.__delete: Final = delete_at_teardown
        self.store: Final = tmp_path / "config" / UNSAVED_CHANGES_FILENAME
        self.store.parent.mkdir()
        self.dock: Final = mocker.Mock(spec=DocumentsDock)
        self.model: Final = mocker.Mock(spec=RehuDocumentModel)
        self.model.gone = ""
        self.dock.open_document.return_value.model = self.model
        self.records: Final = mocker.Mock(spec=Records)
        self.presence_class: Final = mocker.patch.object(module, "StartupPresence")
        self.presence: Final = self.presence_class.return_value
        self.presence.local_paths = {}
        self.asked: Final[list[Path]] = []
        """The folders the startup presence was asked about, as it read them at construction."""
        self.presence_class.side_effect = self.__presence_of

    def __presence_of(self, folders: Iterable[Path], parent: QObject) -> Any:
        """Build the startup presence: note the folders it is asked about, reading them as the real one does.

        :param folders: the folders.
        :param parent: its parent.
        :returns: the presence.
        """
        del parent
        self.asked.extend(folders)
        return self.presence

    def build(self) -> UnsavedChanges:
        """A new owner over the file, as a new run builds one.

        :returns: the owner.
        """
        return self.__delete(UnsavedChanges(self.dock, self.records, self.store))

    def answer(self, folder: Path, presence: Presence) -> None:
        """Deliver the scan's verdict on ``folder``, as the startup presence would.

        :param folder: the folder.
        :param presence: the verdict.
        """
        (on_answered,) = self.presence.answered.connect.call_args.args
        on_answered(folder, presence)

    def read_as(self, mocker: MockerFixture, version: RecordVersion | None) -> LoadedRecord:
        """Have the record's file read as holding :data:`ON_DISK` at ``version``.

        :param mocker: pytest-mock fixture.
        :param version: what it was read at, or ``None`` for a file with nothing to compare with.
        :returns: the read.
        """
        document = mocker.Mock(spec=RehuDocument)
        document.payload_to_write.return_value = dict(ON_DISK)
        record = LoadedRecord(document, version, (), None)
        self.records.load.return_value = record
        return record


@fixture(name="rig")
def fixture_rig(
    mocker: MockerFixture, tmp_path: Path, delete_at_teardown: DeleteAtTeardown, real_path_stat: None
) -> Rig:
    """The owner's collaborators, with the real ``Path.stat`` back so its file can be written atomically.

    :param mocker: pytest-mock fixture.
    :param tmp_path: the test's folder.
    :param delete_at_teardown: deletes the bare `QObject` s built here when the test ends.
    :param real_path_stat: the real ``Path.stat``.
    :returns: the rig.
    """
    del real_path_stat
    return Rig(mocker, tmp_path, delete_at_teardown)


@fixture(name="differences")
def fixture_differences(mocker: MockerFixture) -> Any:
    """What the kept edits and the file disagree on: one difference unless a test says otherwise.

    :param mocker: pytest-mock fixture.
    :returns: the patched comparison.
    """
    return mocker.patch.object(module, "record_differences", return_value=[object()])


def edited_widget(mocker: MockerFixture, path: Path | None, *, dirty: bool = True) -> Any:
    """An open document's widget, its model edited.

    :param mocker: pytest-mock fixture.
    :param path: the document's file, or ``None`` for one with none.
    :param dirty: whether it holds unsaved edits.
    :returns: the widget.
    """
    widget = mocker.Mock(spec=DocumentWidget)
    widget.model.dirty = dirty
    widget.model.path = path
    widget.model.snapshot.return_value = None if path is None else payload_at(path)
    widget.save_state.return_value = LAYOUT
    return widget


# region keeping


def test_kept_edits_reopen_on_the_next_start(rig: Rig, tmp_path: Path, mocker: MockerFixture, differences: Any) -> None:
    """The edits a quit keeps come back on the next start, in the document's own layout, against the file as it is.

    **Test steps:**

    * keep the edits of one dirty document whose file is there
    * build a new owner, the record's folder on a local drive, and reopen
    * verify the document was opened in its layout, compared with the file, and adopted the very edits kept
    """
    path = record_file(tmp_path / "res")
    rig.build().keep([edited_widget(mocker, path)])
    rig.presence.local_paths = {path.parent: Presence.PRESENT}
    current = rig.read_as(mocker, BASE)

    rig.build().reopen()

    rig.dock.open_document.assert_called_once_with(ResourceKey(path), state=LAYOUT, new=False, record=current)
    settings = shared_identity_settings()
    rig.records.load.assert_called_once_with(
        ResourceKey(path), username=settings.current_username, unknown_username=settings.unknown_username
    )
    differences.assert_called_once_with(BASE_PAYLOAD, EDITS, ON_DISK, USERNAME)
    rig.model.adopt_unsaved.assert_called_once_with(payload_at(path), current)


def test_only_dirty_documents_with_a_file_are_kept(
    rig: Rig, tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A quit keeps each dirty document once, and skips a clean one, one with no file and one that cannot be saved.

    **Test steps:**

    * keep a dirty document, the same document again, a clean one, one with no file, and one whose snapshot is
      refused
    * verify only the first was written, and the refused one was logged
    """
    path = tmp_path / "res" / "res.rehu"
    refused = edited_widget(mocker, tmp_path / "locked" / "res.rehu")
    refused.model.snapshot.side_effect = ValueError("locked against saving")

    rig.build().keep(
        [
            edited_widget(mocker, path),
            edited_widget(mocker, path),
            edited_widget(mocker, tmp_path / "clean" / "res.rehu", dirty=False),
            edited_widget(mocker, None),
            refused,
        ]
    )

    assert kept_paths(rig.store) == [str(path)]
    assert "locked against saving" in caplog.text


def test_a_quit_keeps_the_edits_not_reopened_yet(rig: Rig, tmp_path: Path, mocker: MockerFixture) -> None:
    """Edits whose device did not answer this run are kept by the next quit, and not doubled by an open document.

    **Test steps:**

    * keep the edits of a document on a share; reopen with the share offline
    * quit keeping an open dirty document of the same record and one of another
    * verify the file holds the waiting edits -- not the open document's of the record -- and the other document's,
      once each
    """
    waiting = tmp_path / "share" / "res.rehu"
    other = tmp_path / "other" / "res.rehu"
    write_entries(rig.store, [entry_of(payload_at(waiting))])
    owner = rig.build()
    owner.reopen()
    rig.answer(waiting.parent, Presence.OFFLINE)

    reopened_by_hand = edited_widget(mocker, waiting)
    reopened_by_hand.model.snapshot.return_value = replace(payload_at(waiting), payload={"core": {"title": "Open"}})

    owner.keep([reopened_by_hand, edited_widget(mocker, other)])

    assert kept_paths(rig.store) == [str(waiting), str(other)]
    values = json.loads(rig.store.read_text(encoding="utf-8"))
    assert values["documents"][0]["payload"]["payload"] == EDITS
    rig.dock.open_document.assert_not_called()


def test_forgetting_keeps_nothing(rig: Rig, tmp_path: Path, mocker: MockerFixture) -> None:
    """A quit that asked about the edits instead keeps none of them, so the next start reopens nothing.

    **Test steps:**

    * keep the edits of a dirty document, then forget
    * reopen with a new owner
    * verify the file holds no documents and nothing was looked up or opened
    """
    owner = rig.build()
    owner.keep([edited_widget(mocker, tmp_path / "res" / "res.rehu")])

    owner.forget()
    rig.build().reopen()

    assert not kept_paths(rig.store)
    rig.presence_class.assert_not_called()
    rig.dock.open_document.assert_not_called()


def test_the_kept_edits_live_in_the_config_folder(mocker: MockerFixture, tmp_path: Path, real_path_stat: None) -> None:
    """With no file given, the kept edits are ``unsaved-changes.json`` in the app's config folder.

    **Test steps:**

    * point the config folder at a temporary one
    * forget, with an owner given no file
    * verify the file was written there
    """
    del real_path_stat
    mocker.patch.object(module, "config_folder", return_value=tmp_path)

    UnsavedChanges(mocker.Mock(spec=DocumentsDock), mocker.Mock(spec=Records)).forget()

    assert (tmp_path / UNSAVED_CHANGES_FILENAME).is_file()


# endregion

# region reading


def test_nothing_kept_reopens_nothing(rig: Rig) -> None:
    """A start with no kept edits asks about no folder.

    **Test steps:**

    * reopen with no file
    * verify no presence was asked and nothing opened
    """
    rig.build().reopen()

    rig.presence_class.assert_not_called()
    rig.dock.open_document.assert_not_called()


@mark.parametrize("documents", [{"not": "a list"}, ["not an entry", {"payload": {"path": ""}}]])
def test_an_unreadable_entry_is_dropped(rig: Rig, caplog: LogCaptureFixture, documents: Any, differences: Any) -> None:
    """An entry this build cannot read -- or a file whose documents are no list -- reopens nothing and is logged.

    **Test steps:**

    * write a file whose documents are no list, or whose entries are no entry and a payload naming no record
    * reopen
    * verify nothing was opened, and a damaged entry was logged
    """
    del differences
    write_entries(rig.store, documents)

    rig.build().reopen()

    rig.dock.open_document.assert_not_called()
    assert ("could not be read and were dropped" in caplog.text) is isinstance(documents, list)


def test_a_readable_entry_beside_an_unreadable_one_reopens(
    rig: Rig, tmp_path: Path, mocker: MockerFixture, differences: Any
) -> None:
    """A damaged entry costs only itself: the readable one beside it reopens.

    **Test steps:**

    * write a damaged entry and a readable one whose file is there, on a local drive
    * reopen
    * verify the readable one was opened and adopted its edits
    """
    del differences
    path = record_file(tmp_path / "res")
    write_entries(rig.store, ["damaged", entry_of(payload_at(path))])
    rig.presence.local_paths = {path.parent: Presence.PRESENT}
    read = rig.read_as(mocker, BASE)

    rig.build().reopen()

    rig.dock.open_document.assert_called_once_with(ResourceKey(path), state=LAYOUT, new=False, record=read)
    rig.model.adopt_unsaved.assert_called_once()


# endregion

# region reopening


def test_a_local_folder_reopens_at_once_and_empties_the_store(
    rig: Rig, tmp_path: Path, mocker: MockerFixture, differences: Any
) -> None:
    """Kept edits on a local drive reopen before :meth:`reopen` returns, and the store empties once they all did.

    **Test steps:**

    * keep the edits of a document on a local drive
    * reopen
    * verify the presence was asked about its folder and started, the document opened, and the file emptied
    """
    del differences
    path = record_file(tmp_path / "res")
    write_entries(rig.store, [entry_of(payload_at(path))])
    rig.presence.local_paths = {path.parent: Presence.PRESENT}
    rig.read_as(mocker, BASE)

    rig.build().reopen()

    assert rig.asked == [path.parent]
    rig.presence.start.assert_called_once_with()
    rig.dock.open_document.assert_called_once()
    assert not kept_paths(rig.store)


def test_a_remote_folder_reopens_once_it_answers(
    rig: Rig, tmp_path: Path, mocker: MockerFixture, differences: Any
) -> None:
    """Kept edits on a share wait for it: nothing opens until it answers, then the document does.

    **Test steps:**

    * keep the edits of a document on a share; reopen with no local verdicts
    * verify nothing opened and the file still holds the entry
    * deliver the share's answer: present
    * verify the document opened and the file emptied
    """
    del differences
    path = record_file(tmp_path / "share")
    write_entries(rig.store, [entry_of(payload_at(path))])
    rig.read_as(mocker, BASE)
    rig.build().reopen()
    rig.dock.open_document.assert_not_called()
    assert kept_paths(rig.store) == [str(path)]

    rig.answer(path.parent, Presence.PRESENT)

    rig.dock.open_document.assert_called_once()
    assert not kept_paths(rig.store)


def test_an_offline_folder_keeps_its_edits_for_the_next_start(rig: Rig, tmp_path: Path) -> None:
    """A share that does not answer keeps its kept edits, so they are never lost because a server was off.

    **Test steps:**

    * keep the edits of a document on a share; reopen
    * deliver the share's answer: offline
    * verify nothing opened and the file still holds the entry
    """
    path = tmp_path / "share" / "res.rehu"
    write_entries(rig.store, [entry_of(payload_at(path))])
    rig.build().reopen()

    rig.answer(path.parent, Presence.OFFLINE)

    rig.dock.open_document.assert_not_called()
    assert kept_paths(rig.store) == [str(path)]


def test_the_store_empties_only_once_every_folder_answered(
    rig: Rig, tmp_path: Path, mocker: MockerFixture, differences: Any
) -> None:
    """With edits in two folders, the store keeps the other's until it answers too.

    **Test steps:**

    * keep the edits of documents in two folders on shares; reopen
    * deliver the first folder's answer, and verify only its document opened and the other's entry is kept
    * deliver the second's, and verify the file emptied
    """
    del differences
    first = record_file(tmp_path / "first")
    second = record_file(tmp_path / "second")
    write_entries(rig.store, [entry_of(payload_at(first)), entry_of(payload_at(second))])
    read = rig.read_as(mocker, BASE)
    rig.build().reopen()

    rig.answer(first.parent, Presence.PRESENT)
    rig.dock.open_document.assert_called_once_with(ResourceKey(first), state=LAYOUT, new=False, record=read)
    assert kept_paths(rig.store) == [str(first), str(second)]

    rig.answer(second.parent, Presence.PRESENT)
    assert not kept_paths(rig.store)


def test_a_gone_folder_reopens_with_its_banner(rig: Rig, tmp_path: Path, differences: Any) -> None:
    """Edits whose folder is gone reopen all the same, against nothing, saying the folder is gone.

    **Test steps:**

    * keep the edits of a read document in a folder; reopen
    * deliver the folder's answer: gone
    * verify the document opened as a read one, the file was not read, it adopted its edits against nothing, and its
      banner names the folder
    """
    path = tmp_path / "gone" / "res.rehu"
    write_entries(rig.store, [entry_of(payload_at(path))])
    rig.build().reopen()

    rig.answer(path.parent, Presence.GONE)

    rig.dock.open_document.assert_called_once_with(ResourceKey(path), state=LAYOUT, new=False, record=None)
    rig.records.load.assert_not_called()
    differences.assert_not_called()
    rig.model.adopt_unsaved.assert_called_once_with(payload_at(path), None)
    assert rig.model.gone == f"The resource's folder is gone: {path.parent}"


def test_a_gone_file_reopens_with_its_banner(rig: Rig, tmp_path: Path, differences: Any) -> None:
    """Edits of a read record whose file is gone, its folder there, reopen saying the file is gone.

    **Test steps:**

    * keep the edits of a read document whose folder is there but its file not, on a local drive; reopen
    * verify the document opened as a read one, the file was not read, it adopted its edits against nothing, and its
      banner names the file
    """
    del differences
    folder = tmp_path / "res"
    folder.mkdir()
    path = folder / "res.rehu"
    write_entries(rig.store, [entry_of(payload_at(path))])
    rig.presence.local_paths = {folder: Presence.PRESENT}

    rig.build().reopen()

    rig.dock.open_document.assert_called_once_with(ResourceKey(path), state=LAYOUT, new=False, record=None)
    rig.records.load.assert_not_called()
    rig.model.adopt_unsaved.assert_called_once_with(payload_at(path), None)
    assert rig.model.gone == f"The file is gone: {path}"


def test_a_never_saved_document_reopens_new(rig: Rig, tmp_path: Path, differences: Any) -> None:
    """Edits of a record never written reopen as a new document, with no banner.

    **Test steps:**

    * keep the edits of a never-saved document, its file not there; reopen on a local drive
    * verify it opened as a new document, adopted its edits against nothing, and its banner stayed empty
    """
    del differences
    folder = tmp_path / "res"
    folder.mkdir()
    path = folder / "res.rehu"
    write_entries(rig.store, [entry_of(payload_at(path, base=None, first_save=True))])
    rig.presence.local_paths = {folder: Presence.PRESENT}

    rig.build().reopen()

    rig.dock.open_document.assert_called_once_with(ResourceKey(path), state=LAYOUT, new=True, record=None)
    rig.model.adopt_unsaved.assert_called_once_with(payload_at(path, base=None, first_save=True), None)
    assert rig.model.gone == ""


def test_edits_the_file_already_holds_are_not_adopted(
    rig: Rig, tmp_path: Path, mocker: MockerFixture, differences: Any
) -> None:
    """Edits a pending save landed before the reopen are in the file already: the document opens as the file is.

    **Test steps:**

    * keep the edits of a document whose file is there; have the file and the edits differ in nothing
    * reopen on a local drive
    * verify the document opened and adopted nothing
    """
    differences.return_value = []
    path = record_file(tmp_path / "res")
    write_entries(rig.store, [entry_of(payload_at(path))])
    rig.presence.local_paths = {path.parent: Presence.PRESENT}
    rig.read_as(mocker, BASE)

    rig.build().reopen()

    rig.dock.open_document.assert_called_once()
    rig.model.adopt_unsaved.assert_not_called()


def test_a_file_with_nothing_to_compare_with_takes_the_edits_against_nothing(
    rig: Rig, tmp_path: Path, mocker: MockerFixture, differences: Any
) -> None:
    """A file read as one that cannot be saved over -- no version -- is no base: the edits are adopted against nothing.

    **Test steps:**

    * keep the edits of a document whose file is there but reads with no version; reopen on a local drive
    * verify nothing was compared and the edits were adopted against nothing
    """
    path = record_file(tmp_path / "res")
    write_entries(rig.store, [entry_of(payload_at(path))])
    rig.presence.local_paths = {path.parent: Presence.PRESENT}
    rig.read_as(mocker, None)

    rig.build().reopen()

    differences.assert_not_called()
    rig.model.adopt_unsaved.assert_called_once_with(payload_at(path), None)


def test_stopping_stops_the_presence_once_there_is_one(rig: Rig, tmp_path: Path) -> None:
    """Stopping before the window goes delivers no more answers; with nothing reopened there is nothing to stop.

    **Test steps:**

    * stop an owner that reopened nothing, and verify no presence was stopped
    * reopen kept edits on a share, stop, and verify the presence was stopped
    """
    owner = rig.build()
    owner.stop()
    rig.presence.stop.assert_not_called()
    write_entries(rig.store, [entry_of(payload_at(tmp_path / "share" / "res.rehu"))])
    owner.reopen()

    owner.stop()

    rig.presence.stop.assert_called_once_with()


# endregion
