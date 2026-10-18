"""Tests for the file notifier's floor: a sweep of known files by stat signature (#511).

Every file is real, under ``tmp_path``; a sweep is called directly, and the timer loop is run on its thread with the
interval patched short.
"""

import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock

from pytest import LogCaptureFixture
from pytest_mock import MockerFixture
from rehuco_core import FileSignature, RenameCoordinator
from rehuco_core.notify import PollingWatch, RawChange, RawChangeKind

from rehuco_core_tests.concurrency import wait_until

MODULE: Final = "rehuco_core.notify.polling_watch"


class Sweeper:
    """A polling watch over a folder, the files it is told of, and what it reported.

    :param folder: the swept folder.
    :param coordinator: the rename coordinator; a fresh one when omitted.
    """

    def __init__(self, folder: Path, coordinator: RenameCoordinator | MagicMock | None = None) -> None:
        self.known: dict[Path, FileSignature | None] = {}
        self.reported: list[RawChange] = []
        self.reachability: list[bool] = []
        self.watch: Final = PollingWatch(
            folder,
            self.reported.append,
            self.answer,
            coordinator if coordinator is not None else RenameCoordinator(),
            on_reachability=self.reachability.append,
        )

    def answer(self) -> Mapping[Path, FileSignature | None]:
        """What the watch is told to sweep.

        :returns: :attr:`known`.
        """
        return self.known

    def kinds(self) -> list[tuple[RawChangeKind, str]]:
        """What was reported, as kinds and file names.

        :returns: the reports.
        """
        return [(change.kind, change.path.name) for change in self.reported]


def signature_of(path: Path) -> FileSignature:
    """A file's stat signature.

    :param path: the file.
    :returns: its modification time and size.
    """
    status = path.stat()
    return status.st_mtime_ns, status.st_size


def test_a_file_written_or_deleted_since_the_last_sweep_is_reported(tmp_path: Path) -> None:
    """The first sweep notes a file nothing was expected of; a later one reports it written, then gone.

    **Test steps:**

    * tell the watch of a file with no expected signature, and sweep: nothing is reported
    * make the file larger and sweep, then delete it and sweep, then sweep again
    * verify one write and one deletion were reported, each sweep reached the folder, and the watch never failed
    """
    path = tmp_path / "info.rehu"
    path.write_text("a", encoding="utf-8")
    sweeper = Sweeper(tmp_path)
    sweeper.known[path] = None

    assert sweeper.watch.sweep()
    assert not sweeper.reported
    path.write_text("ab", encoding="utf-8")
    assert sweeper.watch.sweep()
    path.unlink()
    assert sweeper.watch.sweep()
    assert sweeper.watch.sweep()

    assert sweeper.kinds() == [(RawChangeKind.MODIFIED, "info.rehu"), (RawChangeKind.DELETED, "info.rehu")]
    assert sweeper.reported[0] == RawChange(RawChangeKind.MODIFIED, path)
    assert not sweeper.watch.failed


def test_a_file_first_swept_is_compared_with_what_was_expected_of_it(tmp_path: Path) -> None:
    """The first time a file is swept, what its cache row expects is the comparison: a file that differs is
    reported written, one missing is reported gone, and one that matches is not reported.

    **Test steps:**

    * tell the watch of a file expected at another signature, a missing file expected at one, and a file expected
      at its own
    * sweep once
    * verify the first was reported written and the second gone, and nothing else
    """
    changed, missing, same = tmp_path / "changed.rehu", tmp_path / "missing.rehu", tmp_path / "same.rehu"
    changed.write_text("a", encoding="utf-8")
    same.write_text("b", encoding="utf-8")
    sweeper = Sweeper(tmp_path)
    sweeper.known.update({changed: (1, 1), missing: (1, 1), same: signature_of(same)})

    assert sweeper.watch.sweep()

    assert sweeper.kinds() == [(RawChangeKind.MODIFIED, "changed.rehu"), (RawChangeKind.DELETED, "missing.rehu")]


def test_a_file_no_longer_known_is_forgotten(tmp_path: Path) -> None:
    """A file dropped from what the watch is told of is forgotten, so when it comes back it is first seen again --
    noted, not compared with what was seen before it went.

    **Test steps:**

    * sweep a known file; drop it from the known files and sweep; change it
    * tell the watch of it again with nothing expected, and sweep
    * verify nothing was reported
    """
    path = tmp_path / "info.rehu"
    path.write_text("a", encoding="utf-8")
    sweeper = Sweeper(tmp_path)
    sweeper.known[path] = None
    sweeper.watch.sweep()
    del sweeper.known[path]
    sweeper.watch.sweep()
    path.write_text("abc", encoding="utf-8")

    sweeper.known[path] = None
    sweeper.watch.sweep()

    assert not sweeper.reported


def test_a_folder_that_cannot_be_reached_is_not_swept(tmp_path: Path) -> None:
    """A sweep of a folder that is not there says nothing about its files.

    **Test steps:**

    * tell a watch of a missing folder about a missing file, and sweep
    * verify the sweep answers unreachable and reported nothing
    """
    folder = tmp_path / "gone"
    sweeper = Sweeper(folder)
    sweeper.known[folder / "info.rehu"] = (1, 1)

    assert not sweeper.watch.sweep()
    assert not sweeper.reported


def test_a_stat_that_fails_mid_sweep_ends_it_unreachable(
    tmp_path: Path, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A stat failing for any reason but the file's absence means the folder went away under the sweep: what is left
    is not swept, and nothing it would say is a verdict.

    **Test steps:**

    * tell the watch of two files expected at other signatures, the first failing to stat with a permission error
    * sweep
    * verify the sweep answers unreachable, nothing was reported, and the failure was logged
    """
    broken, after = tmp_path / "broken.rehu", tmp_path / "after.rehu"
    broken.write_text("a", encoding="utf-8")
    after.write_text("b", encoding="utf-8")
    real_stat = Path.stat

    def stat(path: Path, **kwargs: bool) -> object:
        """The real stat, but a permission error for the broken file."""
        if path == broken:
            raise PermissionError(13, "denied", str(path))
        return real_stat(path, **kwargs)

    mocker.patch.object(Path, "stat", autospec=True, side_effect=stat)
    sweeper = Sweeper(tmp_path)
    sweeper.known.update({broken: (1, 1), after: (1, 1)})

    with caplog.at_level("INFO", logger=MODULE):
        assert not sweeper.watch.sweep()

    assert not sweeper.reported
    assert f"Stopped sweeping {tmp_path} at {broken}" in caplog.text


def test_a_sweep_stopped_part_way_reports_nothing_more(tmp_path: Path) -> None:
    """A stop lands between stats: the stat in flight reports nothing, and no other file is looked at.

    **Test steps:**

    * hand the watch a coordinator whose hold stops the watch, and tell it of two changed files
    * sweep
    * verify the sweep answers reachable, took one stat, and reported nothing
    """
    first, second = tmp_path / "a.rehu", tmp_path / "b.rehu"
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    holds: list[None] = []
    sweeper: Sweeper

    @contextmanager
    def holding() -> Generator[None]:
        """Note the hold, and stop the watch inside it."""
        holds.append(None)
        sweeper.watch.stop()
        yield

    coordinator = MagicMock()
    coordinator.holding.side_effect = holding
    sweeper = Sweeper(tmp_path, coordinator)
    sweeper.known.update({first: (1, 1), second: (1, 1)})

    assert sweeper.watch.sweep()

    assert len(holds) == 1
    assert not sweeper.reported


def sweeping_ended(folder: Path) -> bool:
    """Whether no polling thread for ``folder`` is running.

    :param folder: the swept folder.
    :returns: whether it ended.
    """
    return not any(thread.name == f"polling-watch {folder}" for thread in threading.enumerate())


def test_the_timer_sweeps_and_says_each_time_whether_the_folder_was_reached(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Started, the watch sweeps at once and then every interval, telling its listener after each sweep whether the
    folder could be reached; stopped, it tells nothing more.

    **Test steps:**

    * shorten the interval, and start a watch of a folder
    * wait for a sweep that reached it; delete the folder and wait for one that did not
    * stop it, wait for its thread to end, and verify nothing was told after the stop
    """
    mocker.patch(f"{MODULE}.POLL_INTERVAL", 0.01)
    folder = tmp_path / "root"
    folder.mkdir()
    sweeper = Sweeper(folder)
    sweeper.watch.start()

    assert wait_until(lambda: True in sweeper.reachability)
    folder.rmdir()
    assert wait_until(lambda: False in sweeper.reachability)
    sweeper.watch.stop()
    told = len(sweeper.reachability)

    assert wait_until(lambda: sweeping_ended(folder))
    assert len(sweeper.reachability) == told


def test_a_timer_with_no_listener_and_a_stop_mid_sweep_tells_no_one(tmp_path: Path, mocker: MockerFixture) -> None:
    """A watch with no reachability listener sweeps all the same; one stopped during a sweep tells its listener
    nothing about it.

    **Test steps:**

    * start a watch with no listener, wait for its known files to be asked for twice, and stop it
    * start a watch with a listener, which is stopped while its known files are asked for
    * verify the second's thread ends having told its listener nothing
    """
    mocker.patch(f"{MODULE}.POLL_INTERVAL", 0.01)
    quiet_folder, stopped_folder = tmp_path / "quiet", tmp_path / "stopped"
    quiet_folder.mkdir()
    stopped_folder.mkdir()
    asked: list[None] = []

    def known() -> dict[Path, FileSignature | None]:
        """Nothing to sweep; noted."""
        asked.append(None)
        return {}

    quiet = PollingWatch(quiet_folder, lambda _change: None, known, RenameCoordinator())
    quiet.start()
    assert wait_until(lambda: len(asked) >= 2)
    quiet.stop()

    told: list[bool] = []
    stopping: PollingWatch

    def stop_while_asked() -> dict[Path, FileSignature | None]:
        """Stop the watch, and answer nothing to sweep."""
        stopping.stop()
        return {}

    stopping = PollingWatch(
        stopped_folder, lambda _change: None, stop_while_asked, RenameCoordinator(), on_reachability=told.append
    )
    stopping.start()

    assert wait_until(lambda: sweeping_ended(stopped_folder))
    assert not told


def test_a_stop_waits_for_a_report_being_made_and_none_follows_it(tmp_path: Path, mocker: MockerFixture) -> None:
    """Whoever stops the watch and then says the folder can be reached must not be contradicted by a sweep that
    finished just before: a stop waits for a report already being made, and no report is made after it.

    **Test steps:**

    * start a watch whose listener holds its first report until released
    * stop the watch from another thread while that report is held, and verify the stop waits
    * release the report, and verify the stop returns and nothing more is told
    """
    mocker.patch(f"{MODULE}.POLL_INTERVAL", 0.01)
    entered, release = threading.Event(), threading.Event()
    told: list[bool] = []

    def report(reachable: bool) -> None:
        told.append(reachable)
        entered.set()
        release.wait()

    folder = tmp_path / "root"
    folder.mkdir()
    watch = PollingWatch(folder, lambda change: None, dict, RenameCoordinator(), on_reachability=report)
    watch.start()
    assert entered.wait(5)
    stopping = threading.Thread(target=watch.stop, daemon=True)
    stopping.start()

    stopping.join(0.2)
    assert stopping.is_alive()
    release.set()
    stopping.join(5)

    assert not stopping.is_alive()
    assert wait_until(lambda: sweeping_ended(folder))
    assert told == [True]
