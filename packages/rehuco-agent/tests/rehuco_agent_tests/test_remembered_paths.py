"""Tests for RememberedPaths: the three remembered lists kept honest by what is found of the files (#464).

The scan and the per-path judging are replaced: a path counts as remote when a test says so, the scan is a recorder,
and an answer is delivered by emitting what ``StartupPresence`` would. What is asserted is the bookkeeping -- who is
forgotten, who is restored, who is held unread, and whose storage's answer goes out -- which is the whole of this class.
"""

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from borco_core import Device, Presence, StorageKind, device_of, path_presence
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import startup_presence
from rehuco_agent.remembered_paths import RememberedPaths
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.recent_files_settings import RecentFilesSettings
from rehuco_agent.settings.rehuco_settings import RehucoSettings
from rehuco_agent.settings.session_restore_settings import SessionRestoreSettings

REMOTE: Final = Path("//nas/share/pack/info.rehu")
OTHER_REMOTE: Final = Path("//nas/share/other/info.rehu")
REMOTE_REHUCO: Final = Path("//nas/share/home.rehuco")


@fixture(name="scan_class")
def fixture_scan_class(mocker: MockerFixture) -> Any:
    """Classify the ``REMOTE*`` paths as network storage and replace the scan with a recorder.

    :returns: the stand-in for the scan class.
    """
    remote = {REMOTE, OTHER_REMOTE, REMOTE_REHUCO}
    real = device_of

    def classify(path: Path, mounts: object = None) -> Device:
        if path in remote:
            return Device(StorageKind.NETWORK, Path("//nas/share"), "nas", 445)
        return real(path, mounts)  # type: ignore[arg-type]

    mocker.patch.object(startup_presence, "device_of", classify)
    return mocker.patch.object(startup_presence, "PresenceScan")


class Lists:  # pylint: disable=too-few-public-methods
    """The three remembered lists and the object judging them, as one window holds them."""

    def __init__(  # pylint: disable=too-many-arguments  # one keyword per list a window remembers
        self,
        *,
        recents: tuple[Path, ...] = (),
        rehuco_recents: tuple[Path, ...] = (),
        current: Path | None = None,
        session_open: tuple[Path, ...] = (),
        session_closed: tuple[Path, ...] = (),
        focused: Path | None = None,
        preview: DocumentSessionSettings.Preview | None = None,
    ) -> None:
        self.recent_files = RecentFilesSettings()
        for path in recents:
            self.recent_files.record(path)
        self.rehuco = RehucoSettings()
        for path in rehuco_recents:
            self.rehuco.record(path)
        self.rehuco.current_path = current
        self.session = DocumentSessionSettings()
        for path in session_open:
            self.session.items[path] = DocumentSessionSettings.Item(open=True, state=b"layout")
        for path in session_closed:
            self.session.items[path] = DocumentSessionSettings.Item(open=False)
        self.session.focused_path = focused
        self.session.preview = preview
        self.remembered = RememberedPaths(self.recent_files, self.rehuco, self.session)
        self.answers: list[tuple[Path, Presence]] = []
        self.rehucos: list[Path] = []
        self.remembered.storage_answered.connect(lambda *args: self.answers.append(args))
        self.remembered.rehuco_arrived.connect(self.rehucos.append)

    def answer(self, path: Path, presence: Presence) -> None:
        """Deliver ``presence`` for ``path`` as the presence tracker does once it is on the GUI thread.

        :param path: a remote path.
        :param presence: the verdict.
        """
        tracker = self.remembered._RememberedPaths__presence  # type: ignore[attr-defined]  # pylint: disable=protected-access
        tracker._StartupPresence__remote[path] = presence  # pylint: disable=protected-access
        tracker.answered.emit(path, presence)


def test_a_local_file_that_is_gone_is_forgotten_from_every_list_at_once(
    qapp: Any, tmp_path: Path, scan_class: Any
) -> None:
    """A file on a fixed local drive that is not there is dropped from the recents, the catalog recents, the catalog to
    reopen and the session, before anything is shown (#464).

    **Test steps:**

    * name a missing ``.rehu`` and a missing ``.rehuco`` across all three lists
    * construct ``RememberedPaths``
    * verify every list is empty of them
    """
    del qapp, scan_class
    gone, gone_rehuco = tmp_path / "gone.rehu", tmp_path / "gone.rehuco"

    lists = Lists(
        recents=(gone,), rehuco_recents=(gone_rehuco,), current=gone_rehuco, session_open=(gone,), focused=gone
    )

    assert not lists.recent_files.newest_first()
    assert not lists.rehuco.newest_first()
    assert lists.rehuco.current_path is None
    assert not lists.session.items
    assert lists.session.focused_path is None


def test_a_local_file_that_is_there_stays_everywhere(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """A file that is there is left alone (#464).

    **Test steps:**

    * make one ``.rehu`` and one ``.rehuco`` and name them across all three lists
    * construct ``RememberedPaths``
    * verify nothing was dropped
    """
    del qapp, scan_class
    there, there_rehuco = tmp_path / "there.rehu", tmp_path / "there.rehuco"
    there.touch()
    there_rehuco.touch()

    lists = Lists(recents=(there,), rehuco_recents=(there_rehuco,), current=there_rehuco, session_open=(there,))

    assert lists.recent_files.newest_first() == [there]
    assert lists.rehuco.newest_first() == [there_rehuco]
    assert lists.rehuco.current_path == there_rehuco
    assert list(lists.session.items) == [there]


def test_a_local_file_that_cannot_be_judged_is_kept(
    qapp: Any, tmp_path: Path, mocker: MockerFixture, scan_class: Any
) -> None:
    """A permission error is not "gone": the entry stays (#464).

    **Test steps:**

    * make the judging of a local path answer offline, and name it in the recents and the session
    * construct ``RememberedPaths``
    * verify it is still in both
    """
    del qapp, scan_class
    path = tmp_path / "locked.rehu"
    mocker.patch.object(startup_presence, "presence_of", return_value=Presence.OFFLINE)

    lists = Lists(recents=(path,), session_open=(path,))

    assert lists.recent_files.newest_first() == [path]
    assert path in lists.session.items


def test_every_open_document_is_restored_and_those_to_be_asked_are_held(
    qapp: Any, tmp_path: Path, scan_class: Any
) -> None:
    """The set handed to the dock is every open document, and the ones on a share are to be held unread (#698).

    **Test steps:**

    * make one existing open document, name one remote and one closed
    * ask what to restore with both toggles on
    * verify the local and the remote one are restored, and only the remote one is held
    """
    del qapp, scan_class
    there, closed = tmp_path / "there.rehu", tmp_path / "closed.rehu"
    there.touch()
    closed.touch()
    lists = Lists(session_open=(there, REMOTE), session_closed=(closed,))

    now, held = lists.remembered.documents_to_restore(SessionRestoreSettings())

    assert now == {there, REMOTE}
    assert held == {REMOTE}


def test_nothing_local_is_restored_with_the_local_toggle_off(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """The local-storage box off leaves local documents out (#464).

    **Test steps:**

    * make one existing open document, name one remote, and ask with the local toggle off
    * verify only the remote one is restored
    """
    del qapp, scan_class
    there = tmp_path / "there.rehu"
    there.touch()
    lists = Lists(session_open=(there, REMOTE))

    now, held = lists.remembered.documents_to_restore(SessionRestoreSettings(restore_local_documents=False))

    assert now == {REMOTE}
    assert held == {REMOTE}


def test_a_remote_document_is_left_out_with_the_remote_toggle_off(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """The remote-storage box off leaves a share's documents out, and their storage's answer goes nowhere (#464).

    **Test steps:**

    * make one existing open document, name one remote, and ask with the remote toggle off
    * verify only the local one is restored and nothing is held
    * deliver *present* for the remote one, and verify no answer goes out
    """
    del qapp, scan_class
    there = tmp_path / "there.rehu"
    there.touch()
    lists = Lists(session_open=(there, REMOTE))

    now, held = lists.remembered.documents_to_restore(SessionRestoreSettings(restore_remote_documents=False))
    lists.answer(REMOTE, Presence.PRESENT)

    assert now == {there}
    assert held == set()
    assert not lists.answers


def test_a_local_document_that_cannot_be_judged_is_restored_unheld(
    qapp: Any, tmp_path: Path, mocker: MockerFixture, scan_class: Any
) -> None:
    """A local document the operating system gave no verdict on gets its dock, which says what its read ran into
    (#698).

    **Test steps:**

    * make a local path's judging answer offline and name it as an open document
    * ask what to restore
    * verify it is restored and not held
    """
    del qapp, scan_class
    path = tmp_path / "locked.rehu"
    mocker.patch.object(startup_presence, "presence_of", return_value=Presence.OFFLINE)
    lists = Lists(session_open=(path,))

    now, held = lists.remembered.documents_to_restore(SessionRestoreSettings())

    assert now == {path}
    assert held == set()


def test_a_held_documents_storage_that_is_there_is_said_once_and_logged(
    qapp: Any, scan_class: Any, caplog: LogCaptureFixture
) -> None:
    """The answer that a held document's share is there goes out, is logged, and ends the hold (#698).

    **Test steps:**

    * name one remote open document and ask what to restore
    * deliver *present* twice
    * verify one answer went out, and the log names the document and the verdict
    """
    del qapp, scan_class
    caplog.set_level("INFO", logger="rehuco_agent.remembered_paths")
    lists = Lists(session_open=(REMOTE,), focused=REMOTE)
    lists.remembered.documents_to_restore(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.PRESENT)
    lists.answer(REMOTE, Presence.PRESENT)

    assert lists.answers == [(REMOTE, Presence.PRESENT)]
    assert f"Session: the storage of {REMOTE} answered: present" in caplog.messages


def test_a_held_document_whose_storage_does_not_answer_stays_held(qapp: Any, scan_class: Any) -> None:
    """A share that does not answer is said, and the document stays held for the next answer (#698).

    **Test steps:**

    * name one remote open document and ask what to restore
    * deliver *offline*, then *present*
    * verify both answers went out, and the document is still in the session
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,))
    lists.remembered.documents_to_restore(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.OFFLINE)
    lists.answer(REMOTE, Presence.PRESENT)

    assert lists.answers == [(REMOTE, Presence.OFFLINE), (REMOTE, Presence.PRESENT)]
    assert REMOTE in lists.session.items


def test_a_held_document_that_is_gone_keeps_its_session_entry(qapp: Any, scan_class: Any) -> None:
    """A share that answers and does not hold a held document's file is said: the recents forget it, and the session
    does not, since its dock is there for the reader to close (#698).

    **Test steps:**

    * name a remote path in the recents and as an open document, and ask what to restore
    * deliver *gone*
    * verify the answer went out, the recents dropped it and the session kept it
    """
    del qapp, scan_class
    lists = Lists(recents=(REMOTE,), session_open=(REMOTE,), focused=REMOTE)
    lists.remembered.documents_to_restore(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.GONE)

    assert lists.answers == [(REMOTE, Presence.GONE)]
    assert not lists.recent_files.newest_first()
    assert REMOTE in lists.session.items
    assert lists.session.focused_path == REMOTE


def test_asking_again_goes_to_the_presence_tracker(qapp: Any, mocker: MockerFixture, scan_class: Any) -> None:
    """**Test steps:**

    * replace the tracker's ``ask_again`` and ask again about a held document
    * verify the tracker was asked about it, and its answer is handed back
    """
    del qapp, scan_class
    ask_again = mocker.patch.object(startup_presence.StartupPresence, "ask_again", return_value=True)
    lists = Lists(session_open=(REMOTE,))

    assert lists.remembered.ask_again(REMOTE)

    ask_again.assert_called_once_with(REMOTE)


def test_a_remote_file_that_is_gone_is_forgotten_everywhere(qapp: Any, scan_class: Any) -> None:
    """A share that answers and does not hold a file no dock was made for drops it from every list (#464).

    **Test steps:**

    * name a remote path across the recents and the session, without restoring anything
    * deliver *gone*
    * verify it is in no list, and no answer went out
    """
    del qapp, scan_class
    lists = Lists(recents=(REMOTE,), session_open=(REMOTE,), focused=REMOTE)

    lists.answer(REMOTE, Presence.GONE)

    assert not lists.recent_files.newest_first()
    assert not lists.session.items
    assert not lists.answers


def test_an_answer_for_a_file_only_remembered_in_the_recents_brings_nothing_back(qapp: Any, scan_class: Any) -> None:
    """A recents entry that is there needs nothing opened (#464).

    **Test steps:**

    * name a remote path in the recents only
    * deliver *present*
    * verify no answer went out
    """
    del qapp, scan_class
    lists = Lists(recents=(REMOTE,))

    lists.answer(REMOTE, Presence.PRESENT)

    assert not lists.answers
    assert not lists.rehucos


def test_a_remote_catalog_is_deferred_and_arrives_when_its_server_answers(qapp: Any, scan_class: Any) -> None:
    """The catalog to reopen on a share waits for its server, and is announced when it is there (#464).

    **Test steps:**

    * defer a remote catalog and verify it is the deferred one
    * deliver *present*
    * verify it arrived and is no longer deferred
    """
    del qapp, scan_class
    lists = Lists(current=REMOTE_REHUCO)

    assert lists.remembered.defer_rehuco(REMOTE_REHUCO) is True
    assert lists.remembered.deferred_rehuco == REMOTE_REHUCO
    lists.answer(REMOTE_REHUCO, Presence.PRESENT)

    assert lists.rehucos == [REMOTE_REHUCO]
    assert lists.remembered.deferred_rehuco is None


def test_a_local_catalog_is_not_deferred(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """A catalog on a fixed local drive is opened at once by the caller (#464).

    **Test steps:**

    * ask to defer a local catalog
    * verify it was refused and nothing is deferred
    """
    del qapp, scan_class
    lists = Lists()

    assert lists.remembered.defer_rehuco(tmp_path / "home.rehuco") is False
    assert lists.remembered.deferred_rehuco is None


def test_the_wait_for_a_catalog_can_be_ended(qapp: Any, scan_class: Any) -> None:
    """Once the user has opened or closed a catalog themselves, the deferred one is not waited for (#464).

    **Test steps:**

    * defer a remote catalog and clear the deferral
    * deliver *present*
    * verify nothing arrived
    """
    del qapp, scan_class
    lists = Lists(current=REMOTE_REHUCO)
    lists.remembered.defer_rehuco(REMOTE_REHUCO)

    lists.remembered.clear_deferred_rehuco()
    lists.answer(REMOTE_REHUCO, Presence.PRESENT)

    assert not lists.rehucos


def test_a_deferred_catalog_that_is_gone_is_forgotten(qapp: Any, scan_class: Any) -> None:
    """A catalog whose server says it is gone is not the one to reopen, and not in the recents (#464).

    **Test steps:**

    * defer a remote catalog that is also in the catalog recents
    * deliver *gone*
    * verify it is neither deferred, nor the one to reopen, nor a recent
    """
    del qapp, scan_class
    lists = Lists(current=REMOTE_REHUCO, rehuco_recents=(REMOTE_REHUCO,))
    lists.remembered.defer_rehuco(REMOTE_REHUCO)

    lists.answer(REMOTE_REHUCO, Presence.GONE)

    assert lists.remembered.deferred_rehuco is None
    assert lists.rehuco.current_path is None
    assert not lists.rehuco.newest_first()


def test_unavailable_follows_the_presence_tracker(qapp: Any, scan_class: Any) -> None:
    """A recents entry on a share is unavailable until its server answers present (#464).

    **Test steps:**

    * name a remote path in the recents
    * verify it is unavailable, and available once *present* is delivered
    """
    del qapp, scan_class
    lists = Lists(recents=(REMOTE,))

    assert lists.remembered.unavailable(REMOTE)
    lists.answer(REMOTE, Presence.PRESENT)

    assert not lists.remembered.unavailable(REMOTE)


def test_start_and_stop_go_to_the_scan(qapp: Any, scan_class: Any) -> None:
    """Starting begins the scan and stopping stops it (#464).

    **Test steps:**

    * build the lists, then start and stop
    * verify the scan saw one of each
    """
    del qapp
    lists = Lists(recents=(REMOTE,))
    scan = scan_class.return_value

    lists.remembered.start()
    lists.remembered.stop()

    scan.start.assert_called_once_with()
    scan.stop.assert_called_once_with()


@fixture(name="dead_server")
def fixture_dead_server() -> Iterator[tuple[str, int]]:
    """A real listener on the loopback address that never completes a connection: its queue of waiting connections is
    full, so the next one hangs until the caller gives up -- what a switched-off machine looks like to a probe.

    :returns: its ``(host, port)``; closed when the test ends.
    """
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)  # not 0, which macOS reads as its default backlog of 128 (as ``UnansweringServer`` says)
    address: tuple[str, int] = listener.getsockname()
    fillers: list[socket.socket] = []
    while True:  # until a connection hangs: the queue is then full, whatever this system's backlog is
        assert len(fillers) < 64, "the queue never filled"
        try:
            fillers.append(socket.create_connection(address, timeout=0.05))
        except TimeoutError:
            break
    yield address
    for filler in fillers:
        filler.close()
    listener.close()


def test_a_document_on_a_server_that_never_answers_is_kept_through_the_real_scan(
    qtbot: QtBot, mocker: MockerFixture, dead_server: tuple[str, int]
) -> None:
    """A share whose server hangs does not make its file gone: the entry stays, disabled and open for the next run,
    the verdict coming from the real scan and the real probe (#464).

    Only the classification is replaced, in the start and in the scan, to put one path on the listener that never
    answers; neither the scan, the probe nor the verdict is.

    **Test steps:**

    * put one path on that listener and remember it in the recents and as an open, focused document
    * construct ``RememberedPaths``, ask what to restore, start the scan and wait for its answer
    * verify the answer is *offline* and went out, and the path is still in both lists and unavailable
    """
    path = Path("/dead-server/pack/info.rehu")
    host, port = dead_server
    device = Device(StorageKind.NETWORK, Path("/dead-server"), host, port)
    mocker.patch.object(startup_presence, "device_of", return_value=device)  # the start's own classification...
    mocker.patch.object(path_presence, "device_of", return_value=device)  # ...and the scan's
    lists = Lists(recents=(path,), session_open=(path,), focused=path)
    heard: list[tuple[Path, Presence]] = []
    lists.remembered._RememberedPaths__presence.answered.connect(  # type: ignore[attr-defined]  # pylint: disable=protected-access
        lambda answered, verdict: heard.append((answered, verdict))
    )
    lists.remembered.documents_to_restore(SessionRestoreSettings())

    lists.remembered.start()
    qtbot.waitUntil(lambda: bool(heard), timeout=5000)
    lists.remembered.stop()

    assert heard == [(path, Presence.OFFLINE)]
    assert lists.answers == [(path, Presence.OFFLINE)]
    assert lists.recent_files.newest_first() == [path]
    assert lists.remembered.unavailable(path)
    assert path in lists.session.items


# region The preview (#576)


def test_a_local_preview_that_is_there_is_restored_with_the_window(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """The preview's path joins those to restore now, and not the open documents.

    **Test steps:**

    * remember a preview of a local file that is there
    * verify it is among the paths to restore, and stays out of the session's items
    """
    del qapp, scan_class
    record = tmp_path / "a.rehu"
    record.write_text("", encoding="utf-8")
    session = DocumentSessionSettings()
    session.preview = DocumentSessionSettings.Preview(record, "Preview-1", DocumentSessionSettings.Item(open=True))
    remembered = RememberedPaths(RecentFilesSettings(), RehucoSettings(), session)

    assert remembered.documents_to_restore(SessionRestoreSettings()) == ({record}, set())
    assert record not in session.items


def test_a_local_preview_whose_file_is_gone_is_forgotten(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """A preview of a deleted file leaves no dock behind.

    **Test steps:**

    * remember a preview of a file that is not there
    * verify the entry is gone, and nothing is to be restored
    """
    del qapp, scan_class
    session = DocumentSessionSettings()
    session.preview = DocumentSessionSettings.Preview(
        tmp_path / "gone.rehu", "Preview-1", DocumentSessionSettings.Item(open=True)
    )

    remembered = RememberedPaths(RecentFilesSettings(), RehucoSettings(), session)

    assert session.preview is None
    assert remembered.documents_to_restore(SessionRestoreSettings()) == (set(), set())


# endregion


def test_a_remote_preview_is_restored_held_and_its_storages_answer_goes_out(qapp: Any, scan_class: Any) -> None:
    """A preview on a share is handled as a document there is: restored, held, and its storage's answer said (#698).

    **Test steps:**

    * remember a preview of a remote file, and ask what to restore
    * verify it is restored and held
    * deliver *gone*, and verify the answer went out and the entry is kept for its dock to decide
    """
    del qapp, scan_class
    preview = DocumentSessionSettings.Preview(REMOTE, "Preview-1", DocumentSessionSettings.Item(open=True))
    lists = Lists(preview=preview)

    assert lists.remembered.documents_to_restore(SessionRestoreSettings()) == ({REMOTE}, {REMOTE})

    lists.answer(REMOTE, Presence.GONE)

    assert lists.answers == [(REMOTE, Presence.GONE)]
    assert lists.session.preview is preview


def test_a_remote_preview_is_left_out_with_the_remote_toggle_off(qapp: Any, scan_class: Any) -> None:
    """**Test steps:**

    * remember a preview of a remote file, and ask with the remote toggle off
    * verify it is not to be restored
    """
    del qapp, scan_class
    lists = Lists(preview=DocumentSessionSettings.Preview(REMOTE, "Preview-1", DocumentSessionSettings.Item(open=True)))

    restored = lists.remembered.documents_to_restore(SessionRestoreSettings(restore_remote_documents=False))

    assert restored == (set(), set())


def test_a_local_preview_is_left_out_with_the_local_toggle_off(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """**Test steps:**

    * remember a preview of a local file, and ask with the local toggle off
    * verify it is not to be restored
    """
    del qapp, scan_class
    there = tmp_path / "there.rehu"
    there.touch()
    lists = Lists(preview=DocumentSessionSettings.Preview(there, "Preview-1", DocumentSessionSettings.Item(open=True)))

    restored = lists.remembered.documents_to_restore(SessionRestoreSettings(restore_local_documents=False))

    assert restored == (set(), set())


def test_a_local_preview_that_cannot_be_judged_is_restored(
    qapp: Any, tmp_path: Path, mocker: MockerFixture, scan_class: Any
) -> None:
    """**Test steps:**

    * remember a preview of a local file the operating system gives no verdict on
    * verify it is to be restored, unheld
    """
    del qapp, scan_class
    path = tmp_path / "locked.rehu"
    mocker.patch.object(startup_presence, "presence_of", return_value=Presence.OFFLINE)
    lists = Lists(preview=DocumentSessionSettings.Preview(path, "Preview-1", DocumentSessionSettings.Item(open=True)))

    assert lists.remembered.documents_to_restore(SessionRestoreSettings()) == ({path}, set())
