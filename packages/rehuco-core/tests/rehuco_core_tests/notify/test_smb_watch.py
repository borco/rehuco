"""Tests for the file notifier's SMB backend (#511): where a folder is on its server, opening the session, and turning
the server's answers into observations.

``smbprotocol`` is never reached: its ``Connection``, ``Session``, ``TreeConnect``, ``Open`` and
``FileSystemWatcher`` are replaced in the module with fakes, so no test touches the network. The folder is real, under
``tmp_path``, because a change's ``is_directory`` is read from the disk.
"""

import os
import sys
import threading
from collections.abc import Iterator
from pathlib import Path, PureWindowsPath
from typing import Any, Final
from unittest.mock import MagicMock

from pytest import LogCaptureFixture, MonkeyPatch, fixture, mark, raises
from pytest_mock import MockerFixture
from rehuco_core.notify import RawChange, RawChangeKind, SmbLocation, SmbWatch
from smbprotocol.change_notify import FileAction

from rehuco_core_tests.concurrency import wait_until

MODULE: Final = "rehuco_core.notify.smb_watch"

LOCATION: Final = SmbLocation("nas", "data", r"library\courses")


# region Where a folder is


def test_a_unc_folder_is_located_on_its_server(monkeypatch: MonkeyPatch) -> None:
    """A UNC path names its server and share; what follows is the folder inside the share, and the share itself is
    the empty path.

    **Test steps:**

    * as Windows, locate a folder deep in a share, and the share itself
    * verify the server, share and relative path of each
    """
    monkeypatch.setattr(sys, "platform", "win32")

    assert SmbLocation.of(Path(PureWindowsPath(r"\\nas\data\library\courses"))) == LOCATION
    assert SmbLocation.of(Path(PureWindowsPath(r"\\nas\data"))) == SmbLocation("nas", "data", "")


@mark.windows
@mark.parametrize(
    ("share", "expected"),
    [(r"\\nas\data", LOCATION), (None, None), (r"\\nas", None)],
    ids=["mapped", "not mapped", "no share"],
)
def test_a_drive_letter_is_located_through_its_mapping(
    mocker: MockerFixture, share: str | None, expected: SmbLocation | None
) -> None:
    """A mapped drive's folder is on the share the connection table maps its letter to; a letter mapped to nothing,
    or to a server with no share, is no share this backend can reach.

    **Test steps:**

    * make the letter ``T:`` map to a share, to nothing, or to a bare server
    * locate a folder on ``T:``
    * verify its location, or none, and that the mapping was asked for the letter
    """
    mapped_share = mocker.patch("borco_core.platforms.windows.drives.mapped_share", return_value=share)

    assert SmbLocation.of(Path(r"T:\library\courses")) == expected
    mapped_share.assert_called_once_with("T:")


def test_no_folder_is_located_off_windows(monkeypatch: MonkeyPatch) -> None:
    """Off Windows there is no logon to authenticate with, so no share is reachable, and no watch is made.

    **Test steps:**

    * as Linux, locate a UNC folder, and ask for a watch of it
    * verify neither is given
    """
    monkeypatch.setattr(sys, "platform", "linux")
    folder = Path(PureWindowsPath(r"\\nas\data\library"))

    assert SmbLocation.of(folder) is None
    assert SmbWatch.located(folder, lambda _change: None) is None


def test_a_watch_is_made_for_a_folder_on_a_share(monkeypatch: MonkeyPatch) -> None:
    """A folder on a share this backend reaches gets a watch, not yet started.

    **Test steps:**

    * as Windows, ask for a watch of a UNC folder
    * verify one is made, and has not failed
    """
    monkeypatch.setattr(sys, "platform", "win32")

    watch = SmbWatch.located(Path(PureWindowsPath(r"\\nas\data\library")), lambda _change: None)

    assert watch is not None
    assert not watch.failed


# endregion

# region The session


class Value:  # pylint: disable=too-few-public-methods  # smbprotocol's field interface
    """One field of a ``FILE_NOTIFY_INFORMATION`` entry.

    :param value: what it holds.
    """

    def __init__(self, value: Any) -> None:
        self.__value: Final = value

    def get_value(self) -> Any:
        """:returns: what it holds."""
        return self.__value


def action(code: int, name: str) -> dict[str, Value]:
    """A ``FILE_NOTIFY_INFORMATION`` entry.

    :param code: the action, a :class:`~smbprotocol.change_notify.FileAction` value.
    :param name: the entry's name inside the watched folder, ``\\``-separated.
    :returns: the entry.
    """
    return {"action": Value(code), "file_name": Value(name)}


class Server:  # pylint: disable=too-few-public-methods  # the one factory smbprotocol is patched with
    """Stands in for the server's answers: each ``FileSystemWatcher`` the watch makes takes the next scripted answer,
    and once they run out it waits for one that never comes.

    An answer is a list of entries, ``None`` for a request cancelled under the watch, or an exception its start raises.
    """

    def __init__(self) -> None:
        self.answers: list[list[dict[str, Value]] | None | Exception] = []
        self.requests = 0
        self.before_answer: Any = None

    def watcher(self, directory: object) -> MagicMock:
        """A fake ``FileSystemWatcher`` taking the next answer.

        :param directory: the open folder.
        :returns: the watcher.
        """
        del directory
        self.requests += 1
        watcher = MagicMock()
        if not self.answers:
            watcher.response_event.wait.return_value = False
            return watcher
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            watcher.start.side_effect = answer
            return watcher

        def answered(_timeout: float) -> bool:
            """Run the hook, if any, and say the answer arrived."""
            if self.before_answer is not None:
                self.before_answer()
            return True

        watcher.response_event.wait.side_effect = answered
        watcher.result = answer
        return watcher


class Smb:  # pylint: disable=too-few-public-methods  # a bundle of the module's patched names
    """The module's ``smbprotocol`` names, replaced.

    :param mocker: pytest-mock fixture.
    """

    def __init__(self, mocker: MockerFixture) -> None:
        mocker.patch(f"{MODULE}.WAIT_SECONDS", 0.01)
        self.server: Final = Server()
        self.connection: Final[MagicMock] = mocker.patch(f"{MODULE}.Connection")
        self.session: Final[MagicMock] = mocker.patch(f"{MODULE}.Session")
        self.tree: Final[MagicMock] = mocker.patch(f"{MODULE}.TreeConnect")
        self.open: Final[MagicMock] = mocker.patch(f"{MODULE}.Open")
        self.watcher: Final[MagicMock] = mocker.patch(f"{MODULE}.FileSystemWatcher", side_effect=self.server.watcher)


@fixture(name="smb")
def fixture_smb(mocker: MockerFixture) -> Smb:
    """``smbprotocol`` replaced in the module.

    :param mocker: pytest-mock fixture.
    :returns: the fakes.
    """
    return Smb(mocker)


class Watching:
    """A watch of a real folder over the fakes, and what it reported.

    :param folder: the folder.
    """

    def __init__(self, folder: Path) -> None:
        self.folder: Final = folder
        self.reported: list[RawChange] = []
        self.lock: Final = threading.Lock()
        self.watch: Final = SmbWatch(folder, LOCATION, self.report)

    def report(self, change: RawChange) -> None:
        """Note one observation (the watch's thread).

        :param change: what was seen.
        """
        with self.lock:
            self.reported.append(change)

    def changes(self) -> list[RawChange]:
        """:returns: what was reported so far."""
        with self.lock:
            return list(self.reported)


@fixture(name="watching")
def fixture_watching(tmp_path: Path) -> Iterator[Watching]:
    """A watch of ``tmp_path``, stopped when the test ends.

    :param tmp_path: pytest's temporary folder.
    :yields: the watch.
    """
    watching = Watching(tmp_path)
    yield watching
    watching.watch.stop()


def test_starting_opens_the_session_share_and_folder(smb: Smb, watching: Watching) -> None:
    """A start connects to the server, opens a signed session, the share by its UNC name and the folder inside it,
    and then asks for changes beneath it.

    **Test steps:**

    * start a watch over the fakes
    * verify the connection, session, share and folder were opened in turn, and a change request made
    """
    watching.watch.start()

    assert wait_until(lambda: smb.server.requests >= 1)
    assert smb.connection.call_args.args[1:] == ("nas", 445)
    smb.connection.return_value.connect.assert_called_once()
    smb.session.assert_called_once_with(smb.connection.return_value, require_encryption=False)
    smb.tree.assert_called_once_with(smb.session.return_value, r"\\nas\data")
    smb.open.assert_called_once_with(smb.tree.return_value, r"library\courses")
    smb.open.return_value.create.assert_called_once()
    assert not watching.watch.failed


@mark.parametrize("failing", ["connect", "session"])
def test_a_start_that_fails_is_an_os_error_and_closes_what_it_opened(
    smb: Smb, watching: Watching, failing: str
) -> None:
    """Whatever ``smbprotocol`` raises while opening becomes an ``OSError`` for the caller to fall back on; a
    connection already made is closed again, one never made is not.

    **Test steps:**

    * make the connection, or the session after it, fail to open
    * start the watch
    * verify an ``OSError`` naming the folder, and the connection closed only when it had been made
    """
    if failing == "connect":
        smb.connection.return_value.connect.side_effect = ConnectionRefusedError("refused")
    else:
        smb.session.return_value.connect.side_effect = ValueError("bad credentials")

    with raises(OSError, match="Could not watch .* over SMB"):
        watching.watch.start()

    assert smb.connection.return_value.disconnect.called is (failing == "session")


def test_each_answer_is_reported_with_a_renames_halves_as_one_move(smb: Smb, watching: Watching) -> None:
    """The server's actions are reported in order: an added folder as a folder and what it holds, a write, a removal,
    a rename's two
    halves as one move, a new name whose old half went missing as a creation, nested names beneath the folder; an
    action this backend does not follow is passed over.

    **Test steps:**

    * make the server answer one batch of every kind of action, with a real folder and a real file on disk
    * start the watch
    * verify the observations, folder-ness read from the disk
    """
    folder = watching.folder
    (folder / "sub").mkdir()
    (folder / "sub" / "info.rehu").write_text("x", encoding="utf-8")
    (folder / "renamed").mkdir()
    smb.server.answers.append(
        [
            action(FileAction.FILE_ACTION_ADDED, "sub"),
            action(FileAction.FILE_ACTION_MODIFIED, r"sub\info.rehu"),
            action(FileAction.FILE_ACTION_MODIFIED, "sub"),
            action(FileAction.FILE_ACTION_REMOVED, "gone.rehu"),
            action(FileAction.FILE_ACTION_RENAMED_OLD_NAME, "before"),
            action(FileAction.FILE_ACTION_RENAMED_NEW_NAME, "renamed"),
            action(FileAction.FILE_ACTION_RENAMED_NEW_NAME, "lone.rehu"),
            action(FileAction.FILE_ACTION_ADDED_STREAM, "sub:stream"),
        ]
    )

    watching.watch.start()

    assert wait_until(lambda: len(watching.changes()) == 7)
    assert watching.changes() == [
        RawChange(RawChangeKind.CREATED, folder / "sub", None, True),
        RawChange(RawChangeKind.CREATED, folder / "sub" / "info.rehu", None, False),
        RawChange(RawChangeKind.MODIFIED, folder / "sub" / "info.rehu", None, False),
        RawChange(RawChangeKind.MODIFIED, folder / "sub", None, True),
        RawChange(RawChangeKind.DELETED, folder / "gone.rehu", None, False),
        RawChange(RawChangeKind.MOVED, folder / "before", folder / "renamed", True),
        RawChange(RawChangeKind.CREATED, folder / "lone.rehu", None, False),
    ]


def test_an_empty_answer_is_an_overflow_and_the_watch_asks_again(smb: Smb, watching: Watching) -> None:
    """An empty answer means the server's buffer overflowed: everything beneath the folder may have changed. The
    watch asks again.

    **Test steps:**

    * make the server answer nothing, then a write
    * start the watch
    * verify an overflow of the folder, then the write
    """
    smb.server.answers.extend([[], [action(FileAction.FILE_ACTION_MODIFIED, "info.rehu")]])

    watching.watch.start()

    assert wait_until(lambda: len(watching.changes()) == 2)
    assert watching.changes() == [
        RawChange(RawChangeKind.OVERFLOW, watching.folder),
        RawChange(RawChangeKind.MODIFIED, watching.folder / "info.rehu"),
    ]


@mark.parametrize("answer", [ConnectionResetError("reset"), None], ids=["raised", "cancelled"])
def test_a_session_that_ends_fails_the_watch(
    smb: Smb, watching: Watching, caplog: LogCaptureFixture, answer: Exception | None
) -> None:
    """A request that raises, or is cancelled under the watch, ends it: it has failed, and a stop then says it did
    not.

    **Test steps:**

    * make the server's first answer an error, or a cancellation
    * start the watch and wait for it to fail
    * verify only the error is logged; stop it and verify it no longer reports failing
    """
    smb.server.answers.append(answer)

    with caplog.at_level("WARNING", logger=MODULE):
        watching.watch.start()
        assert wait_until(lambda: watching.watch.failed)

    assert ("The SMB watch of" in caplog.text) is (answer is not None)
    assert smb.server.requests == 1
    watching.watch.stop()
    assert not watching.watch.failed


def test_a_stopped_watch_reports_nothing_more_and_fails_nothing(smb: Smb, watching: Watching) -> None:
    """A stop that lands while an answer arrives drops it; one that lands while the watch waits for an answer ends
    the wait.

    **Test steps:**

    * make the server's first answer arrive just as the watch is stopped
    * start it, and verify the answer was not reported, no further request was made, and the watch did not fail
    * start a second watch, which waits for an answer that never comes, and stop it
    * verify its session was closed, nothing reported, and it did not fail
    """
    smb.server.answers.append([action(FileAction.FILE_ACTION_MODIFIED, "info.rehu")])
    smb.server.before_answer = watching.watch.stop

    watching.watch.start()

    assert wait_until(lambda: smb.connection.return_value.disconnect.called)
    assert not watching.changes()
    assert smb.server.requests == 1
    assert not watching.watch.failed

    smb.server.before_answer = None
    waiting = Watching(watching.folder)
    waiting.watch.start()
    assert wait_until(lambda: smb.server.requests == 2)
    waiting.watch.stop()
    assert wait_until(lambda: smb.connection.return_value.disconnect.call_count == 2)
    assert not waiting.changes()
    assert not waiting.watch.failed


def test_a_stop_while_an_answer_is_reported_asks_for_nothing_more(smb: Smb, tmp_path: Path) -> None:
    """A sink that stops the watch on what it is told ends the watch once that answer is reported.

    **Test steps:**

    * make the server answer two writes, then another
    * start a watch whose sink stops it on the first observation
    * verify both writes of the first answer were reported, the second answer never asked for, and no failure
    """
    smb.server.answers.extend(
        [
            [action(FileAction.FILE_ACTION_MODIFIED, "a.rehu"), action(FileAction.FILE_ACTION_MODIFIED, "b.rehu")],
            [action(FileAction.FILE_ACTION_MODIFIED, "c.rehu")],
        ]
    )
    reported: list[RawChange] = []
    watch: SmbWatch

    def stopping(change: RawChange) -> None:
        """Note the observation, and stop the watch."""
        reported.append(change)
        watch.stop()

    watch = SmbWatch(tmp_path, LOCATION, stopping)
    watch.start()

    # the stop closes the session on a thread of its own at once; the watch's own thread is what reports the rest of
    # the answer, so it is the one waited for
    assert wait_until(lambda: not any(thread.name == f"smb-watch {tmp_path}" for thread in threading.enumerate()))
    assert wait_until(lambda: smb.connection.return_value.disconnect.called)
    assert [change.path.name for change in reported] == ["a.rehu", "b.rehu"]
    assert smb.server.requests == 1
    assert not watch.failed


def test_a_request_that_raises_after_a_stop_is_no_failure(smb: Smb, watching: Watching) -> None:
    """Closing the session under a request makes it raise; that is the stop, not a failure, and is not logged.

    **Test steps:**

    * make the server's first request raise once the watch has been stopped
    * start the watch
    * verify it never reports failing
    """
    smb.server.answers.append(RuntimeError("closed"))
    smb.watcher.side_effect = lambda directory: (watching.watch.stop(), smb.server.watcher(directory))[1]

    watching.watch.start()

    assert wait_until(lambda: smb.server.requests == 1)
    assert wait_until(lambda: smb.connection.return_value.disconnect.called)
    assert not watching.watch.failed


def test_closing_a_session_that_errs_is_logged_and_ignored(
    smb: Smb, watching: Watching, caplog: LogCaptureFixture
) -> None:
    """The server may already be gone when the session is closed: whatever closing raises is logged, never raised.

    **Test steps:**

    * make closing the connection raise, start the watch, and stop it
    * verify the error was logged at debug
    """
    smb.connection.return_value.disconnect.side_effect = ConnectionResetError("gone")

    with caplog.at_level("DEBUG", logger=MODULE):
        watching.watch.start()
        watching.watch.stop()
        assert wait_until(lambda: "Closing the SMB session to nas: gone" in caplog.text)


# endregion


def test_a_folder_moved_in_is_reported_with_everything_in_it(smb: Smb, watching: Watching) -> None:
    """The server reports a folder moved in from elsewhere as that one folder; the records in it are news too, so the
    folder is walked through the mount -- by its plain name, or by a rename whose old half was never seen.

    **Test steps:**

    * lay out two folders with a subfolder and files on disk
    * make the server answer one as added, the other as a lone new name
    * verify each is reported created, then every folder and file in it
    """
    folder = watching.folder
    for name in ("added", "renamed in"):
        (folder / name / "lessons").mkdir(parents=True)
        (folder / name / "info.rehu").write_text("x", encoding="utf-8")
        (folder / name / "lessons" / "one.mp4").write_bytes(b"x")
    smb.server.answers.append(
        [action(FileAction.FILE_ACTION_ADDED, "added"), action(FileAction.FILE_ACTION_RENAMED_NEW_NAME, "renamed in")]
    )

    watching.watch.start()

    assert wait_until(lambda: len(watching.changes()) == 8)
    for name in ("added", "renamed in"):
        top = folder / name
        assert {
            RawChange(RawChangeKind.CREATED, top, None, True),
            RawChange(RawChangeKind.CREATED, top / "lessons", None, True),
            RawChange(RawChangeKind.CREATED, top / "info.rehu", None, False),
            RawChange(RawChangeKind.CREATED, top / "lessons" / "one.mp4", None, False),
        } <= set(watching.changes())


def test_a_rename_split_across_two_answers_is_still_one_move(smb: Smb, watching: Watching) -> None:
    """The server may end an answer between a rename's two halves: the old half waits for the next answer.

    **Test steps:**

    * make the server answer a rename's old half, then its new half
    * verify one move from the old name to the new
    """
    smb.server.answers.extend(
        [
            [action(FileAction.FILE_ACTION_RENAMED_OLD_NAME, "before.rehu")],
            [action(FileAction.FILE_ACTION_RENAMED_NEW_NAME, "after.rehu")],
        ]
    )

    watching.watch.start()

    assert wait_until(lambda: len(watching.changes()) == 1)
    folder = watching.folder
    assert watching.changes() == [RawChange(RawChangeKind.MOVED, folder / "before.rehu", folder / "after.rehu", False)]


def test_a_rename_with_no_new_half_is_the_old_name_gone(smb: Smb, watching: Watching) -> None:
    """A rename's old half followed by anything but its new half went out of the watched folder: the old name is
    gone -- reported before what came next, and twice over for two such halves in a row.

    **Test steps:**

    * make the server answer two old halves in a row, then a write
    * verify both old names are reported deleted, then the write
    """
    smb.server.answers.append(
        [
            action(FileAction.FILE_ACTION_RENAMED_OLD_NAME, "first.rehu"),
            action(FileAction.FILE_ACTION_RENAMED_OLD_NAME, "second.rehu"),
            action(FileAction.FILE_ACTION_MODIFIED, "info.rehu"),
        ]
    )

    watching.watch.start()

    assert wait_until(lambda: len(watching.changes()) == 3)
    folder = watching.folder
    assert watching.changes() == [
        RawChange(RawChangeKind.DELETED, folder / "first.rehu"),
        RawChange(RawChangeKind.DELETED, folder / "second.rehu"),
        RawChange(RawChangeKind.MODIFIED, folder / "info.rehu", None, False),
    ]


def test_a_walk_of_a_folder_that_appeared_stops_with_the_watch(
    smb: Smb, watching: Watching, mocker: MockerFixture
) -> None:
    """A folder walked through the mount may be big; a stop ends the walk at the next folder.

    **Test steps:**

    * make the walk stop the watch as it reaches its first folder, and the server answer a folder added
    * verify the folder itself is reported, and nothing of what is beneath it
    """
    folder = watching.folder
    (folder / "big" / "deep").mkdir(parents=True)
    (folder / "big" / "deep" / "info.rehu").write_text("x", encoding="utf-8")
    walk = os.walk

    def stopping_walk(top: Path) -> Iterator[tuple[str, list[str], list[str]]]:
        for entry in walk(top):
            watching.watch.stop()
            yield entry

    mocker.patch(f"{MODULE}.os.walk", side_effect=stopping_walk)
    smb.server.answers.append([action(FileAction.FILE_ACTION_ADDED, "big")])

    watching.watch.start()

    assert wait_until(lambda: bool(watching.changes()))
    assert watching.changes() == [RawChange(RawChangeKind.CREATED, folder / "big", None, True)]
