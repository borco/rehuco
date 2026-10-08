"""Tests for StartupPresence: which remembered paths are still there, settled without the start waiting (#464).

The judging itself -- what counts as local, what is gone and what is offline -- is ``borco_core.path_presence``'s and
is tested there. These tests are the Qt side of it: a fixed local drive is judged at construction, everything else is
left to a scan that answers from another thread, and each answer reaches the GUI thread as a signal. The scan class is
replaced by a recorder, so no thread is started and no network is asked.
"""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, cast

from borco_core import Device, Presence, StorageKind, device_of
from PySide6.QtCore import QCoreApplication, QThread
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent import startup_presence
from rehuco_agent.startup_presence import StartupPresence

REMOTE: Final = Path("//nas/share/pack/info.rehu")
OTHER_REMOTE: Final = Path("//nas/share/other/info.rehu")


@fixture(name="scan_class")
def fixture_scan_class(mocker: MockerFixture) -> Any:
    """Classify :data:`REMOTE` and :data:`OTHER_REMOTE` as network storage, and replace the scan with a recorder.

    :returns: the stand-in for the scan class; its ``call_args`` holds the paths and the callback it was built with.
    """
    remote = {REMOTE, OTHER_REMOTE}
    real = device_of

    def classify(path: Path, mounts: object = None) -> Device:
        if path in remote:
            return Device(StorageKind.NETWORK, Path("//nas/share"), "nas", 445)
        return real(path, mounts)  # type: ignore[arg-type]

    mocker.patch.object(startup_presence, "device_of", classify)
    return mocker.patch.object(startup_presence, "PresenceScan")


def deliver(scan_class: Any, path: Path, presence: Presence) -> None:
    """Call the callback the scan was built with -- what a scan thread does with each answer.

    :param scan_class: the stand-in returned by the ``scan_class`` fixture.
    :param path: the path answered about.
    :param presence: the verdict.
    """
    callback = cast(Callable[[Path, Presence], None], scan_class.call_args.args[1])
    callback(path, presence)  # pylint: disable=not-callable  # pylint cannot infer a mock's recorded argument


def test_a_path_on_a_fixed_local_drive_is_judged_at_construction(qtbot: QtBot, tmp_path: Path, scan_class: Any) -> None:
    """A local file that is there reads present and one that is not reads gone, at once, with no scan involved (#464).

    **Test steps:**

    * make one file and name one that does not exist, and construct ``StartupPresence`` over both
    * verify the verdicts, that neither is remote or unavailable, and that the scan was handed nothing to ask
    """
    del qtbot
    there = tmp_path / "there.rehu"
    there.touch()
    gone = tmp_path / "gone.rehu"

    presence = StartupPresence([there, gone])

    assert presence.local_paths == {there: Presence.PRESENT, gone: Presence.GONE}
    assert presence.local_presence(there) is Presence.PRESENT
    assert presence.local_presence(gone) is Presence.GONE
    assert not presence.is_remote(there)
    assert not presence.unavailable(there)
    assert not list(scan_class.call_args.args[0])


def test_a_path_judged_twice_is_judged_once(qtbot: QtBot, tmp_path: Path, scan_class: Any) -> None:
    """A path remembered in several lists is one path (#464).

    **Test steps:**

    * construct over the same remote path twice
    * verify the scan was handed it once
    """
    del qtbot, tmp_path

    StartupPresence([REMOTE, REMOTE])

    assert list(scan_class.call_args.args[0]) == [REMOTE]


def test_a_local_path_is_not_known_to_the_remote_side(qtbot: QtBot, scan_class: Any) -> None:
    """Asking about a path that was never judged answers nothing (#464).

    **Test steps:**

    * construct over one remote path
    * verify a local-verdict lookup of it is ``None`` and a path never seen is not remote
    """
    del qtbot, scan_class

    presence = StartupPresence([REMOTE])

    assert presence.local_presence(REMOTE) is None
    assert presence.is_remote(REMOTE)
    assert not presence.is_remote(OTHER_REMOTE)


def test_a_remote_path_is_unavailable_until_its_server_says_it_is_there(qtbot: QtBot, scan_class: Any) -> None:
    """A path on a share is not offered until the scan has heard from it, and stays unavailable if the answer is
    offline (#464).

    **Test steps:**

    * construct over two remote paths and verify both are unavailable
    * deliver *present* for one and *offline* for the other, as a scan thread does
    * verify the first is available and the second is not, and each answer was emitted
    """
    presence = StartupPresence([REMOTE, OTHER_REMOTE])
    assert presence.unavailable(REMOTE)
    assert presence.unavailable(OTHER_REMOTE)
    heard: list[tuple[Path, Presence]] = []
    presence.answered.connect(lambda path, verdict: heard.append((path, verdict)))

    deliver(scan_class, REMOTE, Presence.PRESENT)
    deliver(scan_class, OTHER_REMOTE, Presence.OFFLINE)
    qtbot.waitUntil(lambda: len(heard) == 2)

    assert not presence.unavailable(REMOTE)
    assert presence.unavailable(OTHER_REMOTE)
    assert heard == [(REMOTE, Presence.PRESENT), (OTHER_REMOTE, Presence.OFFLINE)]


def test_a_path_never_seen_is_available(qtbot: QtBot, scan_class: Any) -> None:
    """A path opened during the run was just reached, so it is not unavailable (#464).

    **Test steps:**

    * construct over one remote path
    * verify another path is not unavailable
    """
    del qtbot, scan_class

    presence = StartupPresence([REMOTE])

    assert not presence.unavailable(OTHER_REMOTE)


def test_the_answer_reaches_the_gui_thread_from_a_scan_thread(qtbot: QtBot, scan_class: Any) -> None:
    """The scan calls back on its own thread; the slot runs on the GUI thread (#464).

    **Test steps:**

    * construct over one remote path and note which thread the ``answered`` slot runs on
    * call the scan's callback from a plain Python thread
    * verify the slot ran on the GUI thread, not the caller's
    """
    presence = StartupPresence([REMOTE])
    slot_threads: list[QThread] = []
    presence.answered.connect(lambda *_: slot_threads.append(QThread.currentThread()))

    caller = threading.Thread(target=deliver, args=(scan_class, REMOTE, Presence.PRESENT))
    caller.start()
    caller.join(timeout=5)
    qtbot.waitUntil(lambda: bool(slot_threads))

    assert slot_threads == [QCoreApplication.instance().thread()]  # type: ignore[union-attr]


def test_an_answer_about_a_forgotten_path_is_dropped(qtbot: QtBot, scan_class: Any) -> None:
    """A path forgotten before its answer arrives is no longer tracked, and its late answer is moot (#464).

    **Test steps:**

    * construct over one remote path, forget it, and deliver an answer for it
    * verify nothing was emitted and the path is no longer remote
    """
    presence = StartupPresence([REMOTE])
    heard: list[Any] = []
    presence.answered.connect(lambda *args: heard.append(args))

    presence.forget(REMOTE)
    deliver(scan_class, REMOTE, Presence.PRESENT)
    qtbot.wait(50)

    assert not heard
    assert not presence.is_remote(REMOTE)


def test_forgetting_a_local_path_drops_its_verdict(qtbot: QtBot, tmp_path: Path, scan_class: Any) -> None:
    """A forgotten local path no longer has a verdict (#464).

    **Test steps:**

    * construct over a local path that is not there, and forget it
    * verify it has no verdict any more
    """
    del qtbot, scan_class

    presence = StartupPresence([tmp_path / "gone.rehu"])
    presence.forget(tmp_path / "gone.rehu")

    assert not presence.local_paths


def test_start_and_stop_go_to_the_scan(qtbot: QtBot, scan_class: Any) -> None:
    """Starting asks the scan to begin and stopping stops it (#464).

    **Test steps:**

    * construct over one remote path, then start and stop
    * verify the scan saw one ``start`` and one ``stop``
    """
    del qtbot
    presence = StartupPresence([REMOTE])
    scan = scan_class.return_value

    presence.start()
    presence.stop()

    scan.start.assert_called_once_with()
    scan.stop.assert_called_once_with()


def test_the_scan_is_stopped_when_the_object_is_destroyed(qtbot: QtBot, scan_class: Any) -> None:
    """A window torn down without a close must not be emitted into from a scan thread afterwards (#464).

    **Test steps:**

    * construct over one remote path and delete the object
    * verify the scan was stopped
    """
    presence = StartupPresence([REMOTE])
    scan = scan_class.return_value

    presence.deleteLater()
    qtbot.waitUntil(lambda: scan.stop.called)

    scan.stop.assert_called_once_with()


def test_off_windows_the_mount_table_is_read_once_for_the_whole_batch(
    qtbot: QtBot, mocker: MockerFixture, scan_class: Any
) -> None:
    """Where there is a mount table it is read once and handed to every classification, not once per path (#464).

    **Test steps:**

    * force the platform to Linux and fake the mount table read
    * construct over two paths
    * verify the table was read exactly once
    """
    del qtbot, scan_class
    mocker.patch("rehuco_agent.startup_presence.sys.platform", "linux")
    read = mocker.patch.object(startup_presence, "read_mounts", return_value=[])

    StartupPresence([REMOTE, OTHER_REMOTE])

    read.assert_called_once_with()
