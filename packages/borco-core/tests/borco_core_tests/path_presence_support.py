"""Shared stand-ins for the path-presence tests (#464): devices, a gated fake server probe, and what a scan delivers.

Kept out of the test files so the verdict tests and the scan tests, split only for length, speak the same fakes.
"""

import socket
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Final

from borco_core.path_presence import Device, Presence, StorageKind
from pytest_mock import MockerFixture

MODULE: Final = "borco_core.path_presence"
"""Module path prefix for the ``mocker.patch`` targets."""

TIMEOUT: Final = 5.0
"""Seconds any wait on a thread may take before the test fails instead of hanging."""


def local(root: str = "/") -> Device:
    """A fixed local drive.

    :param root: where the volume starts.
    :returns: the device.
    """
    return Device(StorageKind.LOCAL, Path(root))


def network(root: str = "/mnt/nas", host: str | None = "nas", port: int | None = 445) -> Device:
    """A network volume.

    :param root: where the volume starts.
    :param host: its server.
    :param port: the port to ask the server.
    :returns: the device.
    """
    return Device(StorageKind.NETWORK, Path(root), host, port)


def join_scan_threads() -> None:
    """Wait for every scan thread to finish: the coordinator first, since it starts the others.

    The scans are bounded, so a thread still alive after :data:`TIMEOUT` means a hang and fails the test.
    """
    for named in (lambda name: name == "presence-scan", lambda name: name.startswith("presence-scan-")):
        for thread in [thread for thread in threading.enumerate() if named(thread.name)]:
            thread.join(TIMEOUT)
            assert not thread.is_alive(), f"{thread.name} is still running"


def scan_threads() -> list[threading.Thread]:
    """The scan threads alive now.

    :returns: coordinator and group threads.
    """
    return [thread for thread in threading.enumerate() if thread.name.startswith("presence-scan")]


class Probe:
    """A fake ``socket.create_connection`` that holds the caller until released, so a test can act while a server
    is being asked."""

    def __init__(self, error: OSError | None = None) -> None:
        self.error = error
        self.calls: list[tuple[tuple[str, int], float]] = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.__reached = threading.Condition()

    def wait_for_calls(self, count: int) -> bool:
        """Wait until ``count`` calls are inside the probe.

        :param count: how many calls to wait for.
        :returns: whether they arrived within :data:`TIMEOUT`.
        """
        with self.__reached:
            return self.__reached.wait_for(lambda: len(self.calls) >= count, TIMEOUT)

    def hold(self) -> None:
        """Make the next calls block until :attr:`release` is set."""
        self.release.clear()

    def __call__(self, address: tuple[str, int], timeout: float) -> nullcontext[None]:
        with self.__reached:
            self.calls.append((address, timeout))
            self.__reached.notify_all()
        self.entered.set()
        if not self.release.wait(TIMEOUT):
            raise TimeoutError("the test never released the probe")
        if self.error is not None:
            raise self.error
        return nullcontext()


class UnansweringServer:
    """A real listener on the loopback address that never completes a connection: its queue of waiting connections is
    full, so the next one is left hanging until the caller's timeout -- what a machine that is switched off looks like
    to :func:`socket.create_connection`, with no network touched."""

    MAX_FILLERS: Final = 64
    """The most connections made to fill the queue, whatever backlog the system really gives a ``listen(0)``."""

    def __init__(self) -> None:
        self.__listener = socket.socket()
        self.__listener.bind(("127.0.0.1", 0))
        self.__listener.listen(0)
        self.address: tuple[str, int] = self.__listener.getsockname()
        self.__fillers: list[socket.socket] = []
        while True:  # connect until one hangs: the queue is then full
            assert len(self.__fillers) < self.MAX_FILLERS, "the queue never filled"
            try:
                self.__fillers.append(socket.create_connection(self.address, timeout=0.05))
            except TimeoutError:
                break

    @property
    def host(self) -> str:
        """The address to connect to."""
        return self.address[0]

    @property
    def port(self) -> int:
        """The port to connect to."""
        return self.address[1]

    def close(self) -> None:
        """Close the listener and the connections that fill it."""
        for filler in self.__fillers:
            filler.close()
        self.__listener.close()


class Answers:  # pylint: disable=too-few-public-methods
    """Collects what a scan delivers, from its threads."""

    def __init__(self) -> None:
        self.received: list[tuple[Path, Presence]] = []

    def __call__(self, path: Path, presence: Presence) -> None:
        self.received.append((path, presence))


def fake_devices(mocker: MockerFixture, devices: dict[Path, Device]) -> None:
    """Make :func:`device_of` and ``read_mounts`` answer from a table, as a scan's thread sees them.

    :param mocker: pytest-mock fixture.
    :param devices: the device of each path.
    """
    mocker.patch(f"{MODULE}.read_mounts", return_value=[])
    mocker.patch(f"{MODULE}.device_of", side_effect=lambda path, mounts=None: devices[path])


def fake_exists(mocker: MockerFixture, found: dict[Path, bool | None]) -> None:
    """Make the stat answer from a table.

    :param mocker: pytest-mock fixture.
    :param found: ``True``, ``False`` or ``None`` (no verdict) per path.
    """
    mocker.patch(f"{MODULE}._exists", side_effect=lambda path: found[path])
