"""Tests for xdg's shared primitives: data_home, write_file, read_file, remove_file and
run_update_command."""

import subprocess
from pathlib import Path
from typing import Final

import pytest
from borco_core.platforms.linux import xdg
from pytest import fixture
from pytest_mock import MockerFixture

HOME: Final = Path("/fake/home")
OVERRIDE: Final = "/fake/override/share"
TARGET: Final = Path("/fake/data-home/applications/example.desktop")
CONTENT: Final = b"[Desktop Entry]\n"
MODULE: Final = "borco_core.platforms.linux.xdg"
"""Module path prefix for the ``shutil``/``subprocess`` patch targets below."""

COMMAND: Final = "update-desktop-database"
RESOLVED_COMMAND: Final = "/usr/bin/update-desktop-database"


@fixture
def fake_home(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ``Path.home()`` at a fixed fake and clear any real ``XDG_DATA_HOME``.

    :param mocker: pytest-mock fixture.
    :param monkeypatch: pytest's environment-patching fixture.
    """
    mocker.patch("pathlib.Path.home", return_value=HOME)
    monkeypatch.delenv(xdg.DATA_HOME_VARIABLE, raising=False)


def test_data_home_defaults_below_the_home_directory(fake_home: None) -> None:
    """With no ``XDG_DATA_HOME``, data files live under ``~/.local/share``.

    **Test steps:**

    * point ``Path.home()`` at a fake and unset the override
    * read ``data_home``
    * verify it is the home directory's ``.local/share``
    """
    del fake_home

    assert xdg.data_home() == HOME / xdg.DEFAULT_DATA_HOME


def test_data_home_honours_the_override(fake_home: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A set ``XDG_DATA_HOME`` replaces the default entirely.

    **Test steps:**

    * set the override
    * read ``data_home``
    * verify it is the override, not a path below the home directory
    """
    del fake_home
    monkeypatch.setenv(xdg.DATA_HOME_VARIABLE, OVERRIDE)

    assert xdg.data_home() == Path(OVERRIDE)


def test_data_home_treats_an_empty_override_as_unset(fake_home: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``XDG_DATA_HOME`` set to the empty string falls back to the default, per the spec.

    **Test steps:**

    * set the override to an empty string
    * read ``data_home``
    * verify it is the home directory's ``.local/share``
    """
    del fake_home
    monkeypatch.setenv(xdg.DATA_HOME_VARIABLE, "")

    assert xdg.data_home() == HOME / xdg.DEFAULT_DATA_HOME


def test_write_file_creates_the_parent_directories(mocker: MockerFixture) -> None:
    """``write_file`` makes the whole parent chain before writing, so a first-ever install works.

    **Test steps:**

    * mock ``Path.mkdir`` and ``Path.write_bytes``
    * write a file three levels down
    * verify the parent was created recursively and the bytes were written to the target
    """
    mkdir = mocker.patch("pathlib.Path.mkdir", autospec=True)
    write_bytes = mocker.patch("pathlib.Path.write_bytes", autospec=True)

    xdg.write_file(TARGET, CONTENT)

    mkdir.assert_called_once_with(TARGET.parent, parents=True, exist_ok=True)
    write_bytes.assert_called_once_with(TARGET, CONTENT)


def test_read_file_returns_the_contents(mocker: MockerFixture) -> None:
    """``read_file`` hands back exactly the bytes on disk.

    **Test steps:**

    * mock ``Path.read_bytes``
    * read the file
    * verify the bytes come back unchanged
    """
    mocker.patch("pathlib.Path.read_bytes", return_value=CONTENT)

    assert xdg.read_file(TARGET) == CONTENT


def test_read_file_returns_none_when_missing(mocker: MockerFixture) -> None:
    """``read_file`` reports ``None`` rather than raising when the file doesn't exist.

    **Test steps:**

    * mock ``Path.read_bytes`` to raise ``FileNotFoundError``
    * read the file
    * verify it returns ``None``
    """
    mocker.patch("pathlib.Path.read_bytes", side_effect=FileNotFoundError)

    assert xdg.read_file(TARGET) is None


def test_remove_file_deletes_the_file(mocker: MockerFixture) -> None:
    """``remove_file`` unlinks exactly the path it was given.

    **Test steps:**

    * mock ``Path.unlink``
    * remove the file
    * verify ``unlink`` was called on it
    """
    unlink = mocker.patch("pathlib.Path.unlink", autospec=True)

    xdg.remove_file(TARGET)

    unlink.assert_called_once_with(TARGET)


def test_remove_file_tolerates_an_already_gone_file(mocker: MockerFixture) -> None:
    """Removing a file that isn't there is a no-op, not an error -- unregister runs on partial state.

    **Test steps:**

    * mock ``Path.unlink`` to raise ``FileNotFoundError``
    * remove the file
    * verify nothing propagates
    """
    mocker.patch("pathlib.Path.unlink", side_effect=FileNotFoundError)

    xdg.remove_file(TARGET)


def test_remove_file_logs_rather_than_raising_on_other_failures(mocker: MockerFixture) -> None:
    """A removal that fails for any other reason is logged, not raised: cleanup must not crash the caller.

    **Test steps:**

    * mock ``Path.unlink`` to raise ``PermissionError``
    * remove the file
    * verify nothing propagates and a warning was logged
    """
    mocker.patch("pathlib.Path.unlink", side_effect=PermissionError)
    warning = mocker.patch.object(xdg.LOG, "warning")

    xdg.remove_file(TARGET)

    warning.assert_called_once()


def test_run_update_command_runs_the_resolved_executable(mocker: MockerFixture) -> None:
    """``run_update_command`` resolves the command on ``PATH`` and runs it with its arguments.

    **Test steps:**

    * mock ``shutil.which`` to resolve the command and mock ``subprocess.run``
    * run it with one argument
    * verify the resolved path (not the bare name) was executed with that argument
    """
    mocker.patch(f"{MODULE}.shutil.which", return_value=RESOLVED_COMMAND)
    run = mocker.patch(f"{MODULE}.subprocess.run")

    xdg.run_update_command(COMMAND, str(TARGET.parent))

    run.assert_called_once_with([RESOLVED_COMMAND, str(TARGET.parent)], check=True, capture_output=True)


def test_run_update_command_tolerates_a_missing_command(mocker: MockerFixture) -> None:
    """A desktop without ``desktop-file-utils``/``shared-mime-info`` installed is not a failure.

    **Test steps:**

    * mock ``shutil.which`` to resolve nothing and mock ``subprocess.run``
    * run the command
    * verify nothing was executed and nothing raised
    """
    mocker.patch(f"{MODULE}.shutil.which", return_value=None)
    run = mocker.patch(f"{MODULE}.subprocess.run")

    xdg.run_update_command(COMMAND, str(TARGET.parent))

    run.assert_not_called()


def test_run_update_command_tolerates_a_failing_command(mocker: MockerFixture) -> None:
    """A cache refresh that runs and fails is logged, not raised -- the files are already written.

    **Test steps:**

    * mock ``shutil.which`` to resolve the command and ``subprocess.run`` to fail
    * run the command
    * verify nothing propagates and a warning was logged
    """
    mocker.patch(f"{MODULE}.shutil.which", return_value=RESOLVED_COMMAND)
    mocker.patch(f"{MODULE}.subprocess.run", side_effect=subprocess.CalledProcessError(1, COMMAND))
    warning = mocker.patch.object(xdg.LOG, "warning")

    xdg.run_update_command(COMMAND, str(TARGET.parent))

    warning.assert_called_once()
