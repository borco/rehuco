"""Tests for :class:`~borco_core.path_presence.PresenceScan` (#464).

The scan runs its real daemon threads, with every wait gated on a :class:`threading.Event` and every join bounded: a
race is reproduced by holding a fake in the middle of its call, never by sleeping. ``socket.create_connection`` is
always replaced -- no test touches the network.
"""

import threading
from pathlib import Path
from typing import Final

from borco_core.path_presence import Device, Presence, PresenceScan
from borco_core.platforms.linux.mount_table import Mount
from pytest_mock import MockerFixture

from .path_presence_support import (
    MODULE,
    TIMEOUT,
    Answers,
    Probe,
    fake_devices,
    fake_exists,
    join_scan_threads,
    local,
    network,
    scan_threads,
)

FILE: Final = Path("/fake/pack/file.rehu")
"""A stand-in for a remembered path; nothing here is ever really read."""

NAS_MOUNT: Final = Mount("//nas/share", Path("/mnt/nas"), "cifs")


def test_scan_answers_local_paths_each_once(mocker: MockerFixture) -> None:
    """Local paths are answered by the coordinator itself, in order, with no server involved.

    **Test steps:**

    * scan three local paths whose stat finds, misses and gives no verdict
    * wait for the scan to finish
    * verify present, gone and offline, each delivered once, in order
    """
    present, gone, unknown = Path("/a/present"), Path("/a/gone"), Path("/a/unknown")
    fake_devices(mocker, {present: local(), gone: local(), unknown: local()})
    fake_exists(mocker, {present: True, gone: False, unknown: None})
    answers = Answers()

    PresenceScan([present, gone, unknown], answers).start()
    join_scan_threads()

    assert answers.received == [(present, Presence.PRESENT), (gone, Presence.GONE), (unknown, Presence.OFFLINE)]


def test_scan_reads_the_mount_table_off_windows(mocker: MockerFixture) -> None:
    """Off Windows the coordinator reads the table once and hands it to every classification.

    **Test steps:**

    * force Linux and scan a local path
    * verify the table was read once and passed to the classifier
    """
    path = Path("/a/file")
    mounts = [NAS_MOUNT]
    mocker.patch(f"{MODULE}.sys.platform", "linux")
    read = mocker.patch(f"{MODULE}.read_mounts", return_value=mounts)
    classify = mocker.patch(f"{MODULE}.device_of", return_value=local())
    fake_exists(mocker, {path: True})
    answers = Answers()

    PresenceScan([path], answers).start()
    join_scan_threads()

    read.assert_called_once_with()
    classify.assert_called_once_with(path, mounts)
    assert answers.received == [(path, Presence.PRESENT)]


def test_scan_asks_each_server_once_on_one_thread(mocker: MockerFixture, probe: Probe) -> None:
    """Several paths on one share are judged by one thread after one probe of its server.

    **Test steps:**

    * hold the probe, and scan three paths on one share
    * while it is held, verify exactly one group thread exists
    * release it and wait
    * verify all three are present and the server was asked once
    """
    paths = [Path(f"/mnt/nas/{name}") for name in "abc"]
    fake_devices(mocker, {path: network() for path in paths})
    fake_exists(mocker, dict.fromkeys(paths, True))
    probe.hold()
    answers = Answers()

    PresenceScan(paths, answers).start()
    assert probe.entered.wait(TIMEOUT)
    groups = [thread.name for thread in scan_threads() if thread.name.startswith("presence-scan-")]
    probe.release.set()
    join_scan_threads()

    assert groups == ["presence-scan-0"]
    assert answers.received == [(path, Presence.PRESENT) for path in paths]
    assert len(probe.calls) == 1


def test_scan_gives_each_server_a_thread_and_a_probe(mocker: MockerFixture, probe: Probe) -> None:
    """Two shares are two groups: neither waits for the other.

    **Test steps:**

    * hold the probe, and scan one path on each of two shares
    * wait until both threads are blocked in the probe
    * verify two group threads existed
    * release them and verify each share was asked once
    """
    first, second = Path("/mnt/one/a"), Path("/mnt/two/a")
    fake_devices(mocker, {first: network("/mnt/one", "one"), second: network("/mnt/two", "two")})
    fake_exists(mocker, {first: True, second: True})
    probe.hold()
    answers = Answers()

    PresenceScan([first, second], answers).start()
    assert probe.wait_for_calls(2)
    groups = sorted(thread.name for thread in scan_threads() if thread.name.startswith("presence-scan-"))
    probe.release.set()
    join_scan_threads()

    assert groups == ["presence-scan-0", "presence-scan-1"]
    assert sorted(address for address, _ in probe.calls) == [("one", 445), ("two", 445)]
    assert sorted(answers.received) == sorted([(first, Presence.PRESENT), (second, Presence.PRESENT)])


def test_scan_an_unreachable_server_leaves_its_paths_offline(mocker: MockerFixture, probe: Probe) -> None:
    """One failed probe is the answer for every path on that server.

    **Test steps:**

    * make the server refuse, and scan two paths on it
    * verify both are offline after a single probe
    """
    paths = [Path("/mnt/nas/a"), Path("/mnt/nas/b")]
    fake_devices(mocker, {path: network() for path in paths})
    fake_exists(mocker, dict.fromkeys(paths, True))
    probe.error = ConnectionRefusedError()
    answers = Answers()

    PresenceScan(paths, answers).start()
    join_scan_threads()

    assert answers.received == [(path, Presence.OFFLINE) for path in paths]
    assert len(probe.calls) == 1


def test_scan_threads_are_daemons(mocker: MockerFixture, probe: Probe) -> None:
    """Neither the coordinator nor a group thread may keep the process alive.

    **Test steps:**

    * hold the classifier of the first path, so the coordinator is alive, and verify its thread is a daemon
    * release it, hold the probe, and verify the group thread is a daemon
    * release everything
    """
    path = Path("/mnt/nas/a")
    classified = threading.Event()
    go = threading.Event()

    def classify(_path: Path, _mounts: object = None) -> Device:
        classified.set()
        assert go.wait(TIMEOUT)
        return network()

    mocker.patch(f"{MODULE}.read_mounts", return_value=[])
    mocker.patch(f"{MODULE}.device_of", side_effect=classify)
    fake_exists(mocker, {path: True})
    probe.hold()

    PresenceScan([path], Answers()).start()
    assert classified.wait(TIMEOUT)
    coordinator = [thread for thread in scan_threads() if thread.name == "presence-scan"]
    go.set()
    assert probe.entered.wait(TIMEOUT)
    group = [thread for thread in scan_threads() if thread.name == "presence-scan-0"]
    probe.release.set()
    join_scan_threads()

    assert len(coordinator) == 1
    assert coordinator[0].daemon
    assert len(group) == 1
    assert group[0].daemon


def test_scan_start_twice_starts_once(mocker: MockerFixture) -> None:
    """A second start does not start a second coordinator, nor answer twice.

    **Test steps:**

    * hold the classifier, and start a scan twice
    * verify exactly one coordinator thread exists
    * release it and verify the path was answered once
    """
    path = Path("/a/file")
    go = threading.Event()
    classified = threading.Event()

    def classify(_path: Path, _mounts: object = None) -> Device:
        classified.set()
        assert go.wait(TIMEOUT)
        return local()

    mocker.patch(f"{MODULE}.read_mounts", return_value=[])
    mocker.patch(f"{MODULE}.device_of", side_effect=classify)
    fake_exists(mocker, {path: True})
    answers = Answers()
    scan = PresenceScan([path], answers)

    scan.start()
    assert classified.wait(TIMEOUT)
    scan.start()
    coordinators = [thread for thread in scan_threads() if thread.name == "presence-scan"]
    go.set()
    join_scan_threads()

    assert len(coordinators) == 1
    assert answers.received == [(path, Presence.PRESENT)]


def test_scan_of_no_paths_starts_nothing() -> None:
    """With nothing to ask there is no thread and no answer.

    **Test steps:**

    * start a scan of no paths
    * verify no scan thread exists and the callback was not called
    """
    answers = Answers()

    PresenceScan([], answers).start()

    assert not scan_threads()
    assert not answers.received


def test_scan_asks_about_a_repeated_path_once(mocker: MockerFixture) -> None:
    """A path given twice is one question.

    **Test steps:**

    * scan a list naming one path twice and another once
    * verify each is answered exactly once, in first-seen order
    """
    first, second = Path("/a/first"), Path("/a/second")
    fake_devices(mocker, {first: local(), second: local()})
    fake_exists(mocker, {first: True, second: True})
    answers = Answers()

    PresenceScan([first, second, first], answers).start()
    join_scan_threads()

    assert answers.received == [(first, Presence.PRESENT), (second, Presence.PRESENT)]


def test_scan_stopped_before_start_delivers_nothing(mocker: MockerFixture) -> None:
    """A scan stopped before it begins ends at its first path.

    **Test steps:**

    * stop a scan, then start it
    * verify it reports stopped and, once its thread ended, delivered nothing
    """
    path = Path("/a/file")
    fake_devices(mocker, {path: local()})
    fake_exists(mocker, {path: True})
    answers = Answers()
    scan = PresenceScan([path], answers)

    scan.stop()
    scan.start()
    join_scan_threads()

    assert scan.stopped
    assert not answers.received


def test_scan_stopped_mid_classification_delivers_nothing_more(mocker: MockerFixture) -> None:
    """A stop that arrives while a local path is being judged drops that answer and ends the scan.

    **Test steps:**

    * make the stat of the first of two local paths stop the scan
    * verify neither path was answered and the second was never even stat-ed
    """
    first, second = Path("/a/first"), Path("/a/second")
    fake_devices(mocker, {first: local(), second: local()})
    answers = Answers()
    scan = PresenceScan([first, second], answers)
    stat_calls: list[Path] = []

    def stat(path: Path) -> bool:
        stat_calls.append(path)
        scan.stop()
        return True

    mocker.patch(f"{MODULE}._exists", side_effect=stat)

    scan.start()
    join_scan_threads()

    assert not answers.received
    assert stat_calls == [first]


def test_scan_stopped_mid_group_delivers_nothing_more(mocker: MockerFixture, probe: Probe) -> None:
    """A stop that arrives while a share's paths are being judged drops that answer and the rest.

    **Test steps:**

    * make the stat of the first of two paths on a share stop the scan
    * verify neither path was answered and the second was never stat-ed
    """
    first, second = Path("/mnt/nas/a"), Path("/mnt/nas/b")
    fake_devices(mocker, {first: network(), second: network()})
    answers = Answers()
    scan = PresenceScan([first, second], answers)
    stat_calls: list[Path] = []

    def stat(path: Path) -> bool:
        stat_calls.append(path)
        scan.stop()
        return True

    mocker.patch(f"{MODULE}._exists", side_effect=stat)

    scan.start()
    join_scan_threads()

    assert not answers.received
    assert stat_calls == [first]
    assert len(probe.calls) == 1


def test_scan_drops_an_answer_when_stopped_during_a_probe(mocker: MockerFixture, probe: Probe) -> None:
    """The case the daemon thread exists for: a probe still blocked when the program tears down.

    **Test steps:**

    * hold the probe and scan one path on a share
    * once the thread is blocked in the probe, stop the scan and release the probe
    * wait for the thread to end
    * verify nothing was delivered
    """
    path = Path("/mnt/nas/a")
    fake_devices(mocker, {path: network()})
    fake_exists(mocker, {path: True})
    probe.hold()
    answers = Answers()
    scan = PresenceScan([path], answers)

    scan.start()
    assert probe.entered.wait(TIMEOUT)
    scan.stop()
    probe.release.set()
    join_scan_threads()

    assert scan.stopped
    assert not answers.received


def test_scan_is_not_stopped_until_told() -> None:
    """A new scan is live.

    **Test steps:**

    * make a scan
    * verify it is not stopped
    """
    assert not PresenceScan([FILE], Answers()).stopped
