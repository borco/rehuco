"""Tests for the file notifier (#511): which backend a folder's storage gets, falling back to polling, and coming back
from an outage, publishing on a real change feed.

The backends are replaced in the module with fakes the test drives, and the storage kind and the folder's presence are
patched, so no test depends on this machine's drives; the notifier's and the coalescer's waits are shortened.
"""

import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from borco_core import Device, Presence, StorageKind
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from rehuco_core import ChangeEvent, ChangeFeed, RenameCoordinator, RootReachable, RootStale
from rehuco_core.notify import FileNotifier, RawChange, WatchedFolder

from rehuco_core_tests.concurrency import wait_until

MODULE: Final = "rehuco_core.notify.file_notifier"

ROOT_ID: Final = UUID("00000000-0000-0000-0000-0000000000b1")

FOLDER: Final = Path(Path.cwd().anchor) / "fake" / "library"
"""The watched folder; never touched -- every backend is a fake."""


class FakeWatch:
    """A backend the test drives: it starts or refuses to, and fails when told.

    :param args: how it was built.
    :param kwargs: how it was built.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args: Final = args
        self.kwargs: Final = kwargs
        self.refusal: OSError | None = None
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.failed = False

    def start(self) -> None:
        """Start, or raise the refusal it was given.

        :raises OSError: the refusal.
        """
        if self.refusal is not None:
            raise self.refusal
        self.started.set()

    def stop(self) -> None:
        """Note the stop."""
        self.stopped.set()

    @property
    def sink(self) -> Callable[[RawChange], None]:
        """What it reports to: the coalescer's push."""
        return self.args[1]


class Backends:  # pylint: disable=too-few-public-methods  # a bundle of the module's patched names
    """The module's backends and storage probes, replaced; every watch made is kept in order.

    :param mocker: pytest-mock fixture.
    """

    def __init__(self, mocker: MockerFixture) -> None:
        mocker.patch(f"{MODULE}.HEALTH_SECONDS", 0.01)
        mocker.patch(f"{MODULE}.RETRY_SECONDS", 0.01)
        mocker.patch("rehuco_core.notify.change_coalescer.QUIET_SECONDS", 0.01)
        mocker.patch("rehuco_core.notify.change_coalescer.POLL_SECONDS", 0.01)
        self.native: list[FakeWatch] = []
        self.smb: list[FakeWatch] = []
        self.polling: list[FakeWatch] = []
        self.refusals: list[OSError] = []
        self.smb_reachable = True
        self.kind = StorageKind.LOCAL
        self.presence: list[Presence] = []
        mocker.patch(f"{MODULE}.NativeWatch", side_effect=self.__made(self.native))
        mocker.patch(f"{MODULE}.PollingWatch", side_effect=self.__made(self.polling))
        smb = mocker.patch(f"{MODULE}.SmbWatch")
        smb.located.side_effect = self.__located
        mocker.patch(f"{MODULE}.device_of", side_effect=lambda path: Device(self.kind, Path(path.anchor)))
        mocker.patch(f"{MODULE}.presence_of", side_effect=self.__presence)

    def __made(self, made: list[FakeWatch]) -> Callable[..., FakeWatch]:
        """A factory of fakes, each kept in ``made``, refusing to start while refusals are queued.

        :param made: where to keep them.
        :returns: the factory.
        """

        def make(*args: Any, **kwargs: Any) -> FakeWatch:
            """A fake, kept, given the next refusal when it is no poll."""
            watch = FakeWatch(*args, **kwargs)
            if made is not self.polling and self.refusals:
                watch.refusal = self.refusals.pop(0)
            made.append(watch)
            return watch

        return make

    def __located(self, *args: Any) -> FakeWatch | None:
        """An SMB watch, when the share is reachable this way.

        :param args: how it was asked for.
        :returns: the watch, or ``None``.
        """
        return self.__made(self.smb)(*args) if self.smb_reachable else None

    def __presence(self, path: Path, *, device: Device) -> Presence:
        """The folder's presence: the next queued answer, then present.

        :param path: the folder.
        :param device: its storage.
        :returns: the answer.
        """
        del path, device
        return self.presence.pop(0) if self.presence else Presence.PRESENT


@fixture(name="backends")
def fixture_backends(mocker: MockerFixture) -> Backends:
    """The backends replaced.

    :param mocker: pytest-mock fixture.
    :returns: the fakes.
    """
    return Backends(mocker)


class Notified:  # pylint: disable=too-few-public-methods  # a notifier and its feed, read by the test
    """A notifier over a real feed, and what the feed published.

    :param root_id: the watched folder's root, or ``None``.
    """

    def __init__(self, root_id: UUID | None = ROOT_ID) -> None:
        self.feed: Final = ChangeFeed()
        self.__lock: Final = threading.Lock()
        self.__heard: list[ChangeEvent] = []
        self.feed.add_listener(self.__hear)
        self.coordinator: Final = RenameCoordinator()
        self.known: Final = dict[Path, None]
        self.notifier: Final = FileNotifier(WatchedFolder(FOLDER, root_id), self.feed, self.known, self.coordinator)
        self.__thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the notifier, and note the thread it started -- its own, whatever another test left running under the
        same name."""
        before = set(threading.enumerate())
        self.notifier.start()
        (self.__thread,) = (
            thread for thread in set(threading.enumerate()) - before if thread.name == f"file-notifier {FOLDER}"
        )

    def ended(self) -> bool:
        """:returns: whether the notifier's thread has ended; ``True`` for one never started."""
        return self.__thread is None or not self.__thread.is_alive()

    def __hear(self, event: ChangeEvent) -> None:
        """Note one published event (any thread).

        :param event: the event.
        """
        with self.__lock:
            self.__heard.append(event)

    def heard(self) -> list[ChangeEvent]:
        """:returns: what was published so far."""
        with self.__lock:
            return list(self.__heard)


@fixture(name="notify")
def fixture_notify(backends: Backends) -> Iterator[Callable[..., Notified]]:
    """Make notifiers, and stop each and wait for its thread when the test ends -- a failed test's included, so its
    thread never runs on into the next test's. Torn down before ``backends``, whose fakes the threads still use.

    :param backends: the backends replaced.
    :yields: what makes a :class:`Notified`.
    """
    del backends
    made: list[Notified] = []

    def notify(root_id: UUID | None = ROOT_ID) -> Notified:
        notified = Notified(root_id)
        made.append(notified)
        return notified

    yield notify
    for notified in made:
        notified.notifier.stop()
    for notified in made:
        assert wait_until(notified.ended), "a notifier's thread did not end"


@mark.parametrize("kind", [StorageKind.LOCAL, StorageKind.REMOVABLE])
def test_a_root_on_a_local_disk_is_watched_natively_and_said_reachable_once(
    backends: Backends, notify: Callable[..., Notified], kind: StorageKind
) -> None:
    """A root on this machine's disks gets the operating system's events, with no coordinator -- a root's watch
    never stands in a rename's way -- and is published reachable once; a stop closes the backend.

    **Test steps:**

    * start a notifier of a root on a local or removable disk
    * verify a native watch of the folder was started with the coalescer's push and no coordinator
    * verify the root was published reachable, once; stop it, and verify the backend stopped and the thread ended
    """
    backends.kind = kind
    notified = notify()

    notified.start()

    assert wait_until(lambda: bool(backends.native) and backends.native[0].started.is_set())
    (watch,) = backends.native
    assert watch.args[0] == WatchedFolder(FOLDER, ROOT_ID)
    assert watch.args[2] is None
    assert wait_until(lambda: notified.heard() == [RootReachable(ROOT_ID, True)])
    assert notified.notifier.folder == WatchedFolder(FOLDER, ROOT_ID)
    notified.notifier.stop()
    assert wait_until(watch.stopped.is_set)
    assert wait_until(notified.ended)
    assert notified.heard() == [RootReachable(ROOT_ID, True)]
    assert not backends.polling


def test_a_loose_folder_lets_go_for_renames_and_publishes_no_reachability(
    backends: Backends, notify: Callable[..., Notified]
) -> None:
    """A folder under no root is an open document's: its watch is given the coordinator, to let go for a rename, and
    nothing is published about its reachability.

    **Test steps:**

    * start a notifier of a folder with no root id
    * verify its native watch was given the coordinator, and nothing was published
    """
    notified = notify(root_id=None)

    notified.start()

    assert wait_until(lambda: bool(backends.native) and backends.native[0].started.is_set())
    assert backends.native[0].args[2] is notified.coordinator
    notified.notifier.stop()
    assert wait_until(notified.ended)
    assert not notified.heard()


def test_a_root_on_a_share_is_watched_over_smb(backends: Backends, notify: Callable[..., Notified]) -> None:
    """A network folder gets the SMB backend, asked for by the folder's path and the coalescer's push.

    **Test steps:**

    * start a notifier of a root on network storage
    * verify an SMB watch was started for the folder, and the root published reachable
    """
    backends.kind = StorageKind.NETWORK
    notified = notify()

    notified.start()

    assert wait_until(lambda: bool(backends.smb) and backends.smb[0].started.is_set())
    assert backends.smb[0].args[0] == FOLDER
    assert wait_until(lambda: notified.heard() == [RootReachable(ROOT_ID, True)])
    notified.notifier.stop()
    assert wait_until(notified.ended)


def test_a_disc_is_only_ever_polled(backends: Backends, notify: Callable[..., Notified]) -> None:
    """Storage no event backend can watch is polled, by the root's known files, under the coordinator, and never
    tried with a backend again; the poll says whether the folder is reached, published once per change.

    **Test steps:**

    * start a notifier of a root on optical storage
    * verify a polling watch of the folder was started with the known files and the coordinator, and no backend made
    * have the poll say reachable twice, then unreachable: verify each change was published once
    * stop it, and verify the poll stopped and nothing more is published
    """
    backends.kind = StorageKind.OPTICAL
    notified = notify()

    notified.start()

    assert wait_until(lambda: bool(backends.polling) and backends.polling[0].started.is_set())
    (polling,) = backends.polling
    assert polling.args[0] == FOLDER
    assert (polling.args[2], polling.args[3]) == (notified.known, notified.coordinator)
    reach = polling.kwargs["on_reachability"]
    reach(True)
    reach(True)
    reach(False)
    assert notified.heard() == [RootReachable(ROOT_ID, True), RootReachable(ROOT_ID, False)]
    notified.notifier.stop()
    assert wait_until(polling.stopped.is_set)
    reach(True)
    assert notified.heard() == [RootReachable(ROOT_ID, True), RootReachable(ROOT_ID, False)]
    assert not backends.native and not backends.smb


def test_a_failed_backend_falls_back_to_polling_and_comes_back_stale(
    backends: Backends, notify: Callable[..., Notified], caplog: LogCaptureFixture
) -> None:
    """A backend that fails is stopped and the folder polled; once the folder is there again the backend is opened
    anew, the poll stopped, and everything that may have happened meanwhile announced: the root is stale.

    **Test steps:**

    * start a notifier of a local root, and make its watch fail, with the folder missing for two retries
    * have the poll say the root unreachable
    * verify the failure was logged, a second native watch started once the folder was back, the poll stopped
    * verify the root was published reachable, unreachable, reachable again, and then stale
    """
    backends.presence.extend([Presence.OFFLINE, Presence.OFFLINE])
    notified = notify()

    with caplog.at_level("INFO", logger=MODULE):
        notified.start()
        assert wait_until(lambda: bool(backends.native) and backends.native[0].started.is_set())
        backends.native[0].failed = True
        assert wait_until(lambda: bool(backends.polling) and backends.polling[0].started.is_set())
        backends.polling[0].kwargs["on_reachability"](False)
        assert wait_until(lambda: len(backends.native) == 2 and backends.native[1].started.is_set())
        assert wait_until(lambda: RootStale(ROOT_ID) in notified.heard())

    assert backends.native[0].stopped.is_set()
    assert backends.polling[0].stopped.is_set()
    assert not backends.presence
    assert notified.heard() == [
        RootReachable(ROOT_ID, True),
        RootReachable(ROOT_ID, False),
        RootReachable(ROOT_ID, True),
        RootStale(ROOT_ID),
    ]
    assert "Lost the watch of" in caplog.text
    assert "Watching" in caplog.text and "again." in caplog.text
    notified.notifier.stop()
    assert wait_until(notified.ended)


def test_a_backend_that_will_not_start_is_complained_about_once_per_outage(
    backends: Backends, notify: Callable[..., Notified], caplog: LogCaptureFixture
) -> None:
    """A folder whose backend refuses to start is polled, and the backend tried again every retry; the first refusal
    is a warning, the rest of the outage only debug.

    **Test steps:**

    * make the native watch refuse to start three times
    * start a notifier of a local root, and wait for the fourth watch to start
    * verify one warning and two debug lines, one poll started and then stopped
    """
    backends.refusals.extend(OSError("denied") for _ in range(3))
    notified = notify()

    with caplog.at_level("DEBUG", logger=MODULE):
        notified.start()
        assert wait_until(lambda: len(backends.native) == 4 and backends.native[3].started.is_set())

    complaints = [record for record in caplog.records if "Could not watch" in record.getMessage()]
    assert [record.levelname for record in complaints] == ["WARNING", "DEBUG", "DEBUG"]
    (polling,) = backends.polling
    assert wait_until(polling.stopped.is_set)
    notified.notifier.stop()
    assert wait_until(notified.ended)


def test_a_share_this_backend_cannot_reach_is_polled_and_tried_again(
    backends: Backends, notify: Callable[..., Notified]
) -> None:
    """A network folder the SMB backend cannot reach -- no share, or not Windows -- has no backend: it is polled,
    and asked again every retry while it is there; a stop ends the retries and the poll.

    **Test steps:**

    * start a notifier of a root on network storage the SMB backend does not reach
    * verify a poll started, then stop it, and verify the poll stopped and the thread ended
    """
    backends.kind = StorageKind.NETWORK
    backends.smb_reachable = False
    notified = notify()

    notified.start()

    assert wait_until(lambda: bool(backends.polling) and backends.polling[0].started.is_set())
    notified.notifier.stop()
    assert wait_until(backends.polling[0].stopped.is_set)
    assert wait_until(notified.ended)
    assert not backends.smb


def test_a_watched_folder_that_is_not_there_any_more_is_polled(
    backends: Backends, notify: Callable[..., Notified], mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """A backend does not always notice its folder going -- a share whose server vanished without a word, a folder
    renamed away -- so the folder is looked at while it is watched: once it is not there, the backend is stopped and
    the folder polled, and watched again once it is back.

    **Test steps:**

    * look at the watched folder at every health check: there once, then gone
    * start a notifier of a local root whose watch never fails
    * verify the watch went on after the first look, was stopped after the second, the folder polled, and a second
      watch started once it is there again
    * verify the loss was logged
    """
    mocker.patch(f"{MODULE}.PRESENCE_SECONDS", 0.0)
    backends.presence.extend([Presence.PRESENT, Presence.OFFLINE])
    notified = notify()

    with caplog.at_level("WARNING", logger=MODULE):
        notified.start()
        assert wait_until(lambda: len(backends.native) == 2 and backends.native[1].started.is_set())

    assert not backends.presence
    assert backends.native[0].stopped.is_set()
    assert wait_until(lambda: bool(backends.polling) and backends.polling[0].stopped.is_set())
    assert "is not there any more" in caplog.text
    notified.notifier.stop()
    assert wait_until(notified.ended)
