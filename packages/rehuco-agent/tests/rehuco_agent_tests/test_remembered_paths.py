"""Tests for RememberedPaths: the three remembered lists kept honest by what is found of the files (#464).

The scan and the per-path judging are replaced: a path counts as remote when a test says so, the scan is a recorder,
and an answer is delivered by emitting what ``StartupPresence`` would. What is asserted is the bookkeeping -- who is
forgotten, who is restored now, who is awaited, who arrives late and with what -- which is the whole of this class.
"""

from pathlib import Path
from typing import Any, Final

from borco_core import Device, Presence, StorageKind, device_of
from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent import startup_presence
from rehuco_agent.remembered_paths import SETTLING_SECONDS, RememberedPaths
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.recent_files_settings import RecentFilesSettings
from rehuco_agent.settings.rehuco_settings import RehucoSettings
from rehuco_agent.settings.session_restore_settings import SessionRestoreSettings

REMOTE: Final = Path("//nas/share/pack/info.rehu")
OTHER_REMOTE: Final = Path("//nas/share/other/info.rehu")
REMOTE_REHUCO: Final = Path("//nas/share/home.rehuco")


class Clock:  # pylint: disable=too-few-public-methods
    """A clock the test moves by hand, standing in for ``time.monotonic``."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@fixture(name="clock", autouse=True)
def fixture_clock(mocker: MockerFixture) -> Clock:
    """Freeze the clock the start-up window is measured on.

    :returns: the clock; advance ``now`` to move time.
    """
    clock = Clock()
    mocker.patch("rehuco_agent.remembered_paths.time.monotonic", clock)
    return clock


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


class Lists:  # pylint: disable=too-few-public-methods,too-many-instance-attributes
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
            self.session.items[path] = DocumentSessionSettings.Item(open=True, state=b"layout")  # pylint: disable=unsupported-assignment-operation
        for path in session_closed:
            self.session.items[path] = DocumentSessionSettings.Item(open=False)  # pylint: disable=unsupported-assignment-operation
        self.session.focused_path = focused
        self.remembered = RememberedPaths(self.recent_files, self.rehuco, self.session)
        self.arrived: list[tuple[Path, DocumentSessionSettings.Item, bool]] = []
        self.rehucos: list[Path] = []
        self.layouts = 0
        self.remembered.document_arrived.connect(lambda *args: self.arrived.append(args))
        self.remembered.rehuco_arrived.connect(self.rehucos.append)
        self.remembered.layout_due.connect(self.__count_layout)

    def __count_layout(self) -> None:
        self.layouts += 1

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


def test_only_local_documents_that_are_there_are_restored_now(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """The set handed to the dock is the open local documents whose file is there (#464).

    **Test steps:**

    * make one existing open document, name one that is gone, one remote and one closed
    * ask what to restore now with both toggles on
    * verify only the existing one is in the set
    """
    del qapp, scan_class
    there, closed = tmp_path / "there.rehu", tmp_path / "closed.rehu"
    there.touch()
    closed.touch()
    lists = Lists(session_open=(there, REMOTE), session_closed=(closed,))

    now = lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    assert now == {there}


def test_nothing_local_is_restored_with_the_local_toggle_off(qapp: Any, tmp_path: Path, scan_class: Any) -> None:
    """The local-storage box off leaves local documents out (#464).

    **Test steps:**

    * make one existing open document and ask with the local toggle off
    * verify the set is empty and nothing is remembered as still open
    """
    del qapp, scan_class
    there = tmp_path / "there.rehu"
    there.touch()
    lists = Lists(session_open=(there,))

    now = lists.remembered.documents_to_restore_now(SessionRestoreSettings(restore_local_documents=False))

    assert now == set()
    assert lists.remembered.still_open == frozenset()


def test_a_remote_document_is_awaited_and_remembered_as_open(qapp: Any, scan_class: Any) -> None:
    """With the remote toggle on, a document on a share is left out of the restore now, awaited, and recorded as still
    open (#464).

    **Test steps:**

    * name one remote open document and ask with both toggles on
    * verify the set is empty and the document is in ``still_open``
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,))

    now = lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    assert now == set()
    assert lists.remembered.still_open == {REMOTE}


def test_a_remote_document_is_not_awaited_with_the_remote_toggle_off(qapp: Any, scan_class: Any) -> None:
    """The remote-storage box off leaves a share's documents out and does not remember them as open (#464).

    **Test steps:**

    * name one remote open document and ask with the remote toggle off
    * verify nothing is awaited, and an answer that it is there brings nothing back
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,))

    lists.remembered.documents_to_restore_now(SessionRestoreSettings(restore_remote_documents=False))
    lists.answer(REMOTE, Presence.PRESENT)

    assert lists.remembered.still_open == frozenset()
    assert not lists.arrived


def test_a_local_document_that_cannot_be_judged_stays_open_in_the_session(
    qapp: Any, tmp_path: Path, mocker: MockerFixture, scan_class: Any
) -> None:
    """A local document the operating system gave no verdict on is not restored, and is not lost either (#464).

    **Test steps:**

    * make a local path's judging answer offline and name it as an open document
    * ask what to restore now
    * verify it is not in the set and is remembered as still open
    """
    del qapp, scan_class
    path = tmp_path / "locked.rehu"
    mocker.patch.object(startup_presence, "presence_of", return_value=Presence.OFFLINE)
    lists = Lists(session_open=(path,))

    now = lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    assert now == set()
    assert lists.remembered.still_open == {path}


def test_a_remote_document_that_is_there_arrives_with_its_entry_and_the_focus(qapp: Any, scan_class: Any) -> None:
    """The answer that a share's document is there hands it over with its session entry, and the focus when it was
    the focused one and the start is still settling (#464).

    **Test steps:**

    * name one remote open document as the focused one, and await it
    * deliver *present*
    * verify it arrived with its entry and the focus, and is no longer remembered as merely open
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,), focused=REMOTE)
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.PRESENT)

    assert lists.arrived == [(REMOTE, lists.session.items[REMOTE], True)]
    assert lists.remembered.still_open == frozenset()


def test_a_document_arriving_after_the_start_settled_does_not_take_the_focus(
    qapp: Any, clock: Clock, scan_class: Any
) -> None:
    """A share that answers long after the start is a device the user has stopped waiting for (#464).

    **Test steps:**

    * name one remote open document as the focused one and await it
    * move the clock past the settling window and deliver *present*
    * verify it arrived without the focus, and the saved layout is not asked to be re-applied
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,), focused=REMOTE)
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())
    clock.now += SETTLING_SECONDS + 1

    lists.answer(REMOTE, Presence.PRESENT)

    assert lists.arrived == [(REMOTE, lists.session.items[REMOTE], False)]
    assert lists.layouts == 0


def test_an_unfocused_document_arrives_without_the_focus(qapp: Any, scan_class: Any) -> None:
    """Only the session's focused document may take the focus (#464).

    **Test steps:**

    * name two remote open documents, the second focused, await both and deliver *present* for the first
    * verify it arrived without the focus
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE, OTHER_REMOTE), focused=OTHER_REMOTE)
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.PRESENT)

    assert lists.arrived[0][2] is False


def test_the_layout_is_due_once_every_awaited_document_has_answered(qapp: Any, scan_class: Any) -> None:
    """The saved split layout is re-applied once, after the last awaited answer, and only if one arrived (#464).

    **Test steps:**

    * await two remote documents and deliver *present* for the first
    * verify the layout is not yet due
    * deliver *offline* for the second and verify it is due exactly once
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE, OTHER_REMOTE))
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.PRESENT)
    assert lists.layouts == 0
    lists.answer(OTHER_REMOTE, Presence.OFFLINE)

    assert lists.layouts == 1
    assert lists.remembered.still_open == {OTHER_REMOTE}


def test_the_layout_is_not_due_when_nothing_arrived(qapp: Any, scan_class: Any) -> None:
    """With no late document there is nothing to lay out (#464).

    **Test steps:**

    * await one remote document and deliver *offline*
    * verify the layout was not asked for
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,))
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.OFFLINE)

    assert lists.layouts == 0


def test_a_remote_file_that_is_gone_is_forgotten_everywhere(qapp: Any, scan_class: Any) -> None:
    """A share that answers and does not hold the file drops it from every list, and it is no longer awaited
    (#464).

    **Test steps:**

    * name a remote path across the recents, the catalog recents and the session, and await it
    * deliver *gone*
    * verify it is in no list, not remembered as open, and nothing arrived
    """
    del qapp, scan_class
    lists = Lists(recents=(REMOTE,), session_open=(REMOTE,), focused=REMOTE)
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    lists.answer(REMOTE, Presence.GONE)

    assert not lists.recent_files.newest_first()
    assert not lists.session.items
    assert lists.remembered.still_open == frozenset()
    assert not lists.arrived


def test_an_answer_for_a_file_only_remembered_in_the_recents_brings_nothing_back(qapp: Any, scan_class: Any) -> None:
    """A recents entry that is there needs nothing opened (#464).

    **Test steps:**

    * name a remote path in the recents only
    * deliver *present*
    * verify nothing arrived and no layout is due
    """
    del qapp, scan_class
    lists = Lists(recents=(REMOTE,))

    lists.answer(REMOTE, Presence.PRESENT)

    assert not lists.arrived
    assert not lists.rehucos
    assert lists.layouts == 0


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


def test_a_document_the_user_reached_is_no_longer_kept_open_for_its_share(qapp: Any, scan_class: Any) -> None:
    """Once the user opens a document themselves, its dock decides what the session records -- so closing it is
    not undone at the next save (#464).

    **Test steps:**

    * await one remote open document, with its share not yet answered
    * report it reached by the user
    * verify it is no longer remembered as still open, and a later *present* brings nothing back
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,))
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    lists.remembered.reached(REMOTE)
    lists.answer(REMOTE, Presence.PRESENT)

    assert lists.remembered.still_open == frozenset()
    assert not lists.arrived


def test_a_document_with_no_file_reaches_nothing(qapp: Any, scan_class: Any) -> None:
    """A document not yet saved has no path, and changes nothing the session keeps (#464).

    **Test steps:**

    * await one remote open document, and report a pathless document reached
    * verify the remote one is still remembered as open
    """
    del qapp, scan_class
    lists = Lists(session_open=(REMOTE,))
    lists.remembered.documents_to_restore_now(SessionRestoreSettings())

    lists.remembered.reached(None)

    assert lists.remembered.still_open == {REMOTE}
