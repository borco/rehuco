"""Tests for HeldFilesWatch: the open documents' files read off the GUI thread, and the folders of those under no root
watched (#511).

The reads are real ``stat`` calls on files under ``tmp_path``, or a gated stand-in where a test must hold the reader
part-way; the watches are :class:`~rehuco_core.notify.FileNotifier` stand-ins, since what is asserted is which folders
get one, not what a notifier does.
"""

import threading
from collections.abc import Callable, Collection, Iterator
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from borco_core import Presence
from PySide6.QtCore import Qt, QThread
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.held_files_watch import HeldFilesWatch
from rehuco_core import DEFAULT_RENAME_COORDINATOR, RehuDocument, RenameCoordinator
from rehuco_core.access import ChangeFeed, Records, ResourceKey
from rehuco_core.notify import WatchedFolder

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

PLACE: Final = Path.cwd() / "fake"
"""Built from ``Path.cwd()`` so it is absolute on every platform."""
ROOT: Final = PLACE / "root"
LOOSE: Final = PLACE / "loose"

READER: Final = "held-files-read"
"""The name the watch gives its reading thread."""

SETTLE_S: Final = 5.0
"""How long a test waits for the reading thread, in seconds."""

TIMEOUT_MS: Final = 5000
"""How long a test waits for a delivery, in milliseconds."""


def key(path: Path) -> ResourceKey:
    """The key of a path.

    :param path: the path.
    :returns: its key.
    """
    return ResourceKey(path)


def written(path: Path) -> tuple[int, int]:
    """Write a record at ``path`` and say what its file looks like.

    :param path: where.
    :returns: its modification time in nanoseconds and its size.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    RehuDocument.new(path).save()
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def join_readers() -> None:
    """Wait for every reading thread still out to end."""
    for thread in threading.enumerate():
        if thread.name == READER:
            thread.join(SETTLE_S)
            assert not thread.is_alive()


def delivered_directly(watch: HeldFilesWatch) -> list[object]:
    """Hear :attr:`~HeldFilesWatch.statted` on the reading thread itself, so what was delivered is known the moment
    the reader is joined.

    :param watch: the watch.
    :returns: the list each delivery is appended to.
    """
    heard: list[object] = []
    watch.statted.connect(heard.append, type=Qt.ConnectionType.DirectConnection)
    return heard


@fixture(name="notifiers")
def fixture_notifiers(mocker: MockerFixture) -> MagicMock:
    """Stand in for the file notifier, each one built a mock of its own that remembers its folder.

    :param mocker: pytest-mock fixture.
    :returns: the stand-in class; each built notifier is in its ``built`` list.
    """
    built: list[MagicMock] = []

    def build(folder: WatchedFolder, *_args: object) -> MagicMock:
        notifier = MagicMock(name=f"FileNotifier({folder})")
        notifier.folder = folder
        built.append(notifier)
        return notifier

    stand_in = mocker.patch("rehuco_agent.documents.held_files_watch.FileNotifier", side_effect=build)
    stand_in.built = built
    return stand_in


def watched(notifiers: MagicMock) -> set[WatchedFolder]:
    """The folders the notifiers still running watch.

    :param notifiers: the stand-in class.
    :returns: the folders of every built notifier not stopped.
    """
    return {notifier.folder for notifier in notifiers.built if not notifier.stop.called}


def loose_watch(roots: Collection[Path] = (ROOT,), coordinator: RenameCoordinator | None = None) -> HeldFilesWatch:
    """A watch with ``roots`` as the open ``.rehuco``'s.

    :param roots: the roots.
    :param coordinator: the rename coordinator to hand it.
    :returns: the watch.
    """
    return HeldFilesWatch(ChangeFeed(), Records(), coordinator, lambda: roots)


@fixture(name="gate")
def fixture_gate() -> Iterator[threading.Event]:
    """An event a held reader waits on; set at teardown so no reader is left waiting.

    :yields: the event.
    """
    release = threading.Event()
    yield release
    release.set()


def held_reads(mocker: MockerFixture, records: Records, release: threading.Event) -> threading.Event:
    """Have every read of ``records`` wait for ``release``, answering a signature once let through.

    :param mocker: pytest-mock fixture.
    :param records: the records the watch reads through.
    :param release: what lets a read through.
    :returns: an event set once a read is waiting.
    """
    entered = threading.Event()

    def signature(_key: ResourceKey) -> tuple[int, int]:
        entered.set()
        assert release.wait(SETTLE_S)
        return 1, 2

    mocker.patch.object(records, "signature", side_effect=signature)
    return entered


# region reading


@mark.usefixtures("real_path_stat")
def test_a_read_delivers_each_files_time_and_size_on_the_gui_thread(
    qtbot: QtBot, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """What the files look like is read off the GUI thread and arrives on it; a file that cannot be read is left out.

    **Test steps:**

    * write two records under ``tmp_path``, and name a third that is not there
    * read the three
    * verify one delivery arrived on the GUI thread, with the two files' times and sizes alone
    """
    first, second, missing = tmp_path / "a" / "info.rehu", tmp_path / "b" / "foo.rehu", tmp_path / "c" / "info.rehu"
    expected = {first: written(first), second: written(second)}
    watch = delete_at_teardown(HeldFilesWatch(ChangeFeed(), Records(), None, None))
    threads: list[QThread] = []
    watch.statted.connect(lambda _signatures: threads.append(QThread.currentThread()))

    with qtbot.waitSignal(watch.statted, timeout=TIMEOUT_MS) as statted:
        watch.read([key(first), key(second), key(missing)])

    assert statted.args == [expected]
    assert threads == [watch.thread()]
    join_readers()


@mark.usefixtures("real_path_stat")
def test_a_read_finding_nothing_delivers_nothing(
    tmp_path: Path, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A read whose files are all gone has no time or size to deliver.

    **Test steps:**

    * read a file that is not there, and wait for the reader to end
    * verify no time or size was delivered
    """
    del qtbot
    watch = delete_at_teardown(HeldFilesWatch(ChangeFeed(), Records(), None, None))
    heard = delivered_directly(watch)

    watch.read([key(tmp_path / "info.rehu")])
    join_readers()

    assert not heard


@mark.usefixtures("real_path_stat")
def test_a_read_reports_each_missing_file_and_whether_its_folder_went(
    qtbot: QtBot, tmp_path: Path, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A file that is not there, its device having answered, is reported on the GUI thread with whether its folder is
    gone too (#497); a file that is there is not.

    **Test steps:**

    * write a record under ``tmp_path``, and name one missing from a folder that is there and one whose folder is not
    * read the three
    * verify one missing delivery arrived on the GUI thread, naming the two missing files and which folder went
    """
    present, missing, folder_gone = (
        tmp_path / "a" / "info.rehu",
        tmp_path / "b" / "info.rehu",
        tmp_path / "c" / "info.rehu",
    )
    written(present)
    missing.parent.mkdir()
    watch = delete_at_teardown(HeldFilesWatch(ChangeFeed(), Records(), None, None))
    threads: list[QThread] = []
    watch.missing.connect(lambda _missing: threads.append(QThread.currentThread()))

    with qtbot.waitSignal(watch.missing, timeout=TIMEOUT_MS) as delivered:
        watch.read([key(present), key(missing), key(folder_gone)])

    assert delivered.args == [{missing: False, folder_gone: True}]
    assert threads == [watch.thread()]
    join_readers()


@mark.usefixtures("real_path_stat")
def test_a_missing_file_on_a_share_that_does_not_answer_is_in_neither_delivery(
    mocker: MockerFixture, tmp_path: Path, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Nothing is known of a file whose share does not answer: it is neither there nor gone (#497).

    **Test steps:**

    * have every folder's device not answer, and read a file that is not there
    * wait for the reader to end
    * verify nothing was delivered, of either kind
    """
    del qtbot
    mocker.patch("rehuco_agent.documents.held_files_watch.presence_of", return_value=Presence.OFFLINE)
    watch = delete_at_teardown(HeldFilesWatch(ChangeFeed(), Records(), None, None))
    heard = delivered_directly(watch)
    watch.missing.connect(heard.append, type=Qt.ConnectionType.DirectConnection)

    watch.read([key(tmp_path / "info.rehu")])
    join_readers()

    assert not heard


def test_a_read_of_no_files_starts_no_thread(
    mocker: MockerFixture, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Nothing to read is no reason for a thread.

    **Test steps:**

    * read an empty selection
    * verify no thread was started
    """
    del qtbot
    started = mocker.spy(threading.Thread, "start")

    delete_at_teardown(HeldFilesWatch(ChangeFeed(), Records(), None, None)).read(())

    started.assert_not_called()


def test_nothing_is_delivered_after_stop(
    mocker: MockerFixture, qtbot: QtBot, gate: threading.Event, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A read still out when the watch stops delivers nothing, and no read starts after.

    **Test steps:**

    * hold a read part-way, stop the watch, then let the read finish
    * verify nothing was delivered
    * read again, and verify no thread was started
    """
    del qtbot
    records = Records()
    entered = held_reads(mocker, records, gate)
    watch = delete_at_teardown(HeldFilesWatch(ChangeFeed(), records, None, None))
    heard = delivered_directly(watch)
    watch.read([key(LOOSE / "info.rehu")])
    assert entered.wait(SETTLE_S)

    watch.stop()
    gate.set()
    join_readers()

    assert not heard
    started = mocker.spy(threading.Thread, "start")
    watch.read([key(LOOSE / "info.rehu")])
    started.assert_not_called()


def test_a_watch_destroyed_while_a_read_is_out_drops_the_delivery(
    mocker: MockerFixture, qtbot: QtBot, gate: threading.Event, delete_at_teardown: DeleteAtTeardown
) -> None:
    """The reader outlives a watch destroyed with its window; its delivery then fails quietly, on the reader's thread.

    **Test steps:**

    * hold a read part-way, and make the watch's delivery fail as on a destroyed object
    * let the read finish
    * verify the delivery was tried and no exception escaped the reading thread
    """
    del qtbot
    records = Records()
    entered = held_reads(mocker, records, gate)
    watch = delete_at_teardown(HeldFilesWatch(ChangeFeed(), records, None, None))
    statted = mocker.patch.object(watch, "statted")
    statted.emit.side_effect = RuntimeError("Internal C++ object (HeldFilesWatch) already deleted.")
    escaped = mocker.patch("threading.excepthook")
    watch.read([key(LOOSE / "info.rehu")])
    assert entered.wait(SETTLE_S)

    gate.set()
    join_readers()

    statted.emit.assert_called_once_with({LOOSE / "info.rehu": (1, 2)})
    escaped.assert_not_called()


# endregion

# region watching the folders under no root


def test_only_the_folders_of_documents_under_no_root_are_watched(notifiers: MagicMock, qtbot: QtBot) -> None:
    """A document under a root is the root's notifier's; one under none has its folder watched -- everything beneath a
    directory-scoped record's folder, a file-scoped one's folder alone.

    **Test steps:**

    * follow a document under the root, a directory-scoped one and a file-scoped one under none
    * verify the two loose folders got a started notifier each, recursive for the directory-scoped one only
    """
    del qtbot
    watch = loose_watch()

    watch.follow([key(ROOT / "a" / "info.rehu"), key(LOOSE / "x" / "info.rehu"), key(LOOSE / "y" / "foo.rehu")])

    assert watched(notifiers) == {
        WatchedFolder(LOOSE / "x", None, True),
        WatchedFolder(LOOSE / "y", None, False),
    }
    for notifier in notifiers.built:
        notifier.start.assert_called_once_with()


@mark.parametrize(
    ("held", "expected"),
    [
        (
            [LOOSE / "x" / "info.rehu", LOOSE / "x" / "sub" / "foo.rehu", LOOSE / "x" / "sub" / "info.rehu"],
            {WatchedFolder(LOOSE / "x", None, True)},
        ),
        (
            [LOOSE / "y" / "foo.rehu", LOOSE / "y" / "sub" / "bar.rehu"],
            {WatchedFolder(LOOSE / "y", None, False), WatchedFolder(LOOSE / "y" / "sub", None, False)},
        ),
        (
            [LOOSE / "z" / "foo.rehu", LOOSE / "z" / "info.rehu"],
            {WatchedFolder(LOOSE / "z", None, True)},
        ),
    ],
    ids=["beneath-a-recursive-one", "beneath-a-flat-one", "one-folder-both-scopes"],
)
def test_a_folder_is_watched_once(
    notifiers: MagicMock, qtbot: QtBot, held: list[Path], expected: set[WatchedFolder]
) -> None:
    """A folder beneath a recursively watched one is not watched again -- no watch sits where a rename of the outer
    folder could move it -- but one beneath a folder watched alone is; a folder holding both scopes is watched whole.

    **Test steps:**

    * follow the held documents
    * verify exactly the expected folders are watched
    """
    del qtbot
    loose_watch().follow([key(path) for path in held])

    assert watched(notifiers) == expected
    assert len(notifiers.built) == len(expected)


def test_a_folder_no_longer_wanted_is_let_go_and_one_still_wanted_is_kept(
    notifiers: MagicMock, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Following again stops what is no longer wanted -- a document released, or a root now covering it -- and keeps
    the notifier of a folder still wanted rather than starting it again.

    **Test steps:**

    * follow two loose documents, then the first alone
    * verify the second's notifier was stopped and the first's kept, with no new one built
    * add a root covering the first, and follow it again
    * verify its notifier was stopped too
    """
    del qtbot
    roots = [ROOT]
    watch = delete_at_teardown(HeldFilesWatch(ChangeFeed(), Records(), None, lambda: roots))
    first, second = key(LOOSE / "x" / "info.rehu"), key(LOOSE / "y" / "info.rehu")
    watch.follow([first, second])

    watch.follow([first])

    assert watched(notifiers) == {WatchedFolder(LOOSE / "x", None, True)}
    assert len(notifiers.built) == 2

    roots.append(LOOSE)
    watch.follow([first])

    assert not watched(notifiers)


@mark.parametrize("coordinator", [None, RenameCoordinator()], ids=["default", "given"])
def test_a_notifier_publishes_on_the_feed_and_answers_to_the_coordinator(
    notifiers: MagicMock, qtbot: QtBot, coordinator: RenameCoordinator | None, delete_at_teardown: DeleteAtTeardown
) -> None:
    """Each notifier publishes on the app's feed, compares a sweep with the held documents, and answers to the rename
    coordinator given -- the app's default one when none is.

    **Test steps:**

    * follow a loose document through a watch given a coordinator, or none
    * verify the notifier was built with the watch's feed, a reader of the held document, and that coordinator
    """
    del qtbot
    feed = ChangeFeed()
    held = key(LOOSE / "x" / "info.rehu")
    watch = delete_at_teardown(HeldFilesWatch(feed, Records(), coordinator, lambda: ()))

    watch.follow([held])

    folder, given_feed, known, given_coordinator = notifiers.call_args.args
    assert folder == WatchedFolder(LOOSE / "x", None, True)
    assert given_feed is feed
    assert known() == {held.path: None}
    assert given_coordinator is (coordinator if coordinator is not None else DEFAULT_RENAME_COORDINATOR)


def test_with_no_roots_nothing_is_watched(
    notifiers: MagicMock, qtbot: QtBot, delete_at_teardown: DeleteAtTeardown
) -> None:
    """A watch with no window around it watches nothing.

    **Test steps:**

    * follow a loose document through a watch given no roots
    * verify no notifier was built
    """
    del qtbot
    delete_at_teardown(HeldFilesWatch(ChangeFeed(), Records(), None, None)).follow([key(LOOSE / "x" / "info.rehu")])

    notifiers.assert_not_called()


def test_stop_lets_every_watch_go_and_watches_nothing_after(notifiers: MagicMock, qtbot: QtBot) -> None:
    """Stopping the watch stops each notifier, and following afterwards starts none.

    **Test steps:**

    * follow two loose documents, then stop
    * verify both notifiers were stopped
    * follow again, and verify no notifier was built
    """
    del qtbot
    watch = loose_watch()
    watch.follow([key(LOOSE / "x" / "info.rehu"), key(LOOSE / "y" / "info.rehu")])

    watch.stop()

    assert not watched(notifiers)
    assert all(notifier.stop.call_count == 1 for notifier in notifiers.built)
    watch.follow([key(LOOSE / "x" / "info.rehu")])
    assert len(notifiers.built) == 2


# endregion

# region what a sweep expects


@mark.parametrize(
    ("recursive", "expected"),
    [
        (True, {LOOSE / "x" / "info.rehu", LOOSE / "x" / "sub" / "foo.rehu"}),
        (False, {LOOSE / "x" / "info.rehu"}),
    ],
    ids=["recursive", "flat"],
)
def test_a_sweep_expects_the_held_documents_in_the_folder(recursive: bool, expected: set[Path]) -> None:
    """A polled folder's sweep compares the held documents in it with the disk, expecting nothing of their signatures:
    everything beneath a recursive folder, a flat one's own entries only, never a document elsewhere.

    **Test steps:**

    * ask what a sweep of the folder expects, of documents in it, beneath it and elsewhere
    * verify the documents it watches, each with no signature
    """
    held = [key(LOOSE / "x" / "info.rehu"), key(LOOSE / "x" / "sub" / "foo.rehu"), key(LOOSE / "y" / "info.rehu")]
    known: Callable[[], dict[Path, tuple[int, int] | None]] = HeldFilesWatch.known(
        WatchedFolder(LOOSE / "x", None, recursive), held
    )

    assert known() == dict.fromkeys(expected)


# endregion
