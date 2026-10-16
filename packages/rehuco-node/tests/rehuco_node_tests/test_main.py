"""Tests for the node's CLI entry point (#506)."""

import sys
from pathlib import Path

from pytest import CaptureFixture
from pytest_mock import MockerFixture
from rehuco_core import AppFolders, app_folders
from rehuco_node import __main__ as entry
from rehuco_node import __version__
from rehuco_node.local_node import LocalNode


def test_version_prints_and_exits(capsys: CaptureFixture[str]) -> None:
    """``--version`` prints the version and returns 0 without running a node.

    **Test steps:**

    * call ``main`` with ``--version``
    * verify the exit code and the printed line
    """
    assert entry.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"version: {__version__}"


def test_folders_follow_the_settings_dir_rule(tmp_path: Path) -> None:
    """No settings dir means the platform's folders; one means that single folder, resolved.

    **Test steps:**

    * ask for the folders with and without a settings dir
    * verify the platform folders and the single folder
    """
    assert entry.folders_for(None) == app_folders()
    assert entry.folders_for(tmp_path) == AppFolders.single(tmp_path.resolve())


def test_main_runs_the_node_with_stdin_watched_when_piped(mocker: MockerFixture, tmp_path: Path) -> None:
    """With stdin not a terminal, main sets up logging, the signal handlers and the stdin watcher, runs the node
    in the settings dir, and closes the log handler after.

    **Test steps:**

    * patch the node loop, the logging setup, the handlers and the watcher; make stdin report not-a-tty
    * call ``main`` with ``--settings-dir``
    * verify every piece was called once and the node ran on the given folder
    """
    handler = mocker.Mock()
    setup = mocker.patch.object(entry, "setup_logging", return_value=handler)
    handlers = mocker.patch.object(entry, "install_signal_handlers")
    watcher = mocker.patch.object(entry, "watch_stdin")
    run = mocker.patch.object(LocalNode, "run")
    mocker.patch.object(sys.stdin, "isatty", return_value=False)

    assert entry.main(["--settings-dir", str(tmp_path)]) == 0

    setup.assert_called_once_with(tmp_path.resolve() / "node")
    handlers.assert_called_once()
    watcher.assert_called_once()
    run.assert_called_once()
    handler.close.assert_called_once()


def test_main_does_not_watch_a_terminal_stdin(mocker: MockerFixture, tmp_path: Path) -> None:
    """Run from a terminal, the node does not read stdin, or it would steal the shell's input.

    **Test steps:**

    * same patches, with stdin reporting a tty
    * verify the watcher was not started
    """
    mocker.patch.object(entry, "setup_logging", return_value=mocker.Mock())
    mocker.patch.object(entry, "install_signal_handlers")
    watcher = mocker.patch.object(entry, "watch_stdin")
    mocker.patch.object(LocalNode, "run")
    mocker.patch.object(sys.stdin, "isatty", return_value=True)

    assert entry.main(["--settings-dir", str(tmp_path)]) == 0

    watcher.assert_not_called()
