"""Shared fixtures for the per-user XDG desktop-integration tests (desktop entry, MIME package, icon).

Unlike the Windows sibling tree, nothing here skips off its own platform: these modules are
``pathlib``/``subprocess`` only, so they import and behave identically wherever the tests run --
which is the point, since the developer's machine is not Linux.
"""

from pathlib import Path
from typing import Final

from pytest import fixture
from pytest_mock import MockerFixture

XDG: Final = "borco_core.platforms.linux.xdg"
"""Module path prefix for ``mocker.patch`` targets below -- every filesystem write, read, removal
and cache refresh the three composite modules make funnels through here, regardless of which one
triggered it."""

DATA_HOME: Final = Path("/fake/data-home")
"""The stand-in :func:`~borco_core.platforms.linux.xdg.data_home` reports to the fixture's users."""


class FakeXdg:
    """In-memory stand-in for the user's XDG data home, plus a record of cache-refresh calls."""

    def __init__(self) -> None:
        self.files: dict[Path, bytes] = {}
        self.update_calls: list[tuple[str, tuple[str, ...]]] = []

    def data_home(self) -> Path:
        """Fake for :func:`~borco_core.platforms.linux.xdg.data_home`.

        :returns: the fixed :data:`DATA_HOME`.
        """
        return DATA_HOME

    def write_file(self, path: Path, data: bytes) -> None:
        """Fake for :func:`~borco_core.platforms.linux.xdg.write_file`.

        :param path: the file being written.
        :param data: its full contents.
        """
        self.files[path] = data

    def read_file(self, path: Path) -> bytes | None:
        """Fake for :func:`~borco_core.platforms.linux.xdg.read_file`.

        :param path: the file being read.
        :returns: its contents, or ``None`` when it was never written.
        """
        return self.files.get(path)

    def remove_file(self, path: Path) -> None:
        """Fake for :func:`~borco_core.platforms.linux.xdg.remove_file` -- a no-op when absent.

        :param path: the file being removed.
        """
        self.files.pop(path, None)

    def run_update_command(self, command: str, *arguments: str) -> None:
        """Fake for :func:`~borco_core.platforms.linux.xdg.run_update_command` -- records the call.

        :param command: the cache-refresh command's name.
        :param arguments: the arguments it was given.
        """
        self.update_calls.append((command, arguments))


@fixture
def fake_xdg(mocker: MockerFixture) -> FakeXdg:
    """Replace every filesystem/subprocess call the composite modules make with an in-memory fake.

    :param mocker: pytest-mock fixture.
    :returns: the fake data home, so tests can inspect what got written.
    """
    store = FakeXdg()
    mocker.patch(f"{XDG}.data_home", side_effect=store.data_home)
    mocker.patch(f"{XDG}.write_file", side_effect=store.write_file)
    mocker.patch(f"{XDG}.read_file", side_effect=store.read_file)
    mocker.patch(f"{XDG}.remove_file", side_effect=store.remove_file)
    mocker.patch(f"{XDG}.run_update_command", side_effect=store.run_update_command)
    return store
