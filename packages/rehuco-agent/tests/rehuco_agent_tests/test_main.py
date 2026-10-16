"""Cross-platform tests for the rehuco-agent CLI entry point.

Windows-specific behavior (register/unregister, AUMID) lives in
``tests/platforms/windows/test_main.py``, guarded by ``pytest.importorskip("winreg")`` -- these
tests exercise the platform-agnostic and non-Windows paths, so they run on every OS.
"""

import sys
from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent import __version__
from rehuco_agent.__main__ import SETTINGS_DIR_ENVIRONMENT_VARIABLE, main, resolve_settings_dir
from rehuco_agent.settings.persistent_settings import (
    APPLICATION_NAME,
    settings_dir,
)

FAKE_ARGV0: Final = "/fake/rehuco-agent-dev"
"""No ``.exe``/drive-letter shape -- argv[0] isn't a Windows executable on this path."""


def test_version_flag_prints_and_returns_without_launching_gui(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--version`` is a plain flag, not argparse's own ``action="version"`` -- it must combine with
    ``--info``/``--register``/``--unregister`` on one command line rather than exiting from inside
    ``parse_args()`` (see ``__main__``'s comment on the parser setup). This is also the smoke check
    the release workflow runs against each packaged artifact
    ([[appendices.continuous-integration#release-agent]]).

    **Test steps:**

    * force a non-registration platform (macOS) so the check is the shared final fallback, not either
      platform-specific branch
    * set ``sys.argv`` to argv[0] plus ``--version``
    * mock ``run`` and verify ``main()`` returns ``0``, prints the version, and never reaches ``run()``
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--version"])
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    assert main() == 0
    assert __version__ in capsys.readouterr().out
    run.assert_not_called()


def test_info_flag_on_macos_reports_no_runtime_state(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--info`` on macOS has nothing to query -- registration there is the app bundle's own
    declaration, with no ``--register`` equivalent (:data:`REGISTRATION_PLATFORMS`).

    **Test steps:**

    * force ``sys.platform`` to ``darwin``, set ``sys.argv`` to argv[0] plus ``--info``
    * mock ``run`` and verify ``main()`` returns ``0`` without launching the GUI
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--info"])
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    assert main() == 0
    assert "no runtime state to query" in capsys.readouterr().out
    run.assert_not_called()


def test_paths_only_skips_windows_block_on_non_windows(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """With no register/unregister flags, a non-Windows platform skips the whole win32 block.

    Distinct from ``test_register_not_offered_on_macos`` (in the Windows-only test file):
    that one exercises argparse's own rejection of ``--register`` before the platform check is
    ever reached. This one has no flags at all, so parsing succeeds and
    ``if sys.platform == "win32":`` is actually evaluated and takes its ``False`` branch
    straight to ``run()``. macOS, not Linux, so it stays about the win32 block alone -- the Linux
    branch has its own file, ``tests/platforms/linux/test_main.py`` (#209).

    **Test steps:**

    * force ``sys.platform`` to a non-Windows value
    * set ``sys.argv`` to argv[0] plus one ``.rehu`` path, no flags
    * mock ``run`` and ``ctypes.windll`` (absent on non-Windows -- patched with ``create=True``)
    * verify ``run`` was called and the AUMID call was not (it's inside the win32 block)
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "a.rehu"])
    # ctypes.windll does not exist off Windows; patch the whole attribute (its parent ctypes does
    # exist, so create=True can add it) rather than the deep shell32.<fn> path, whose intermediate
    # traversal would AttributeError before create=True ever reaches the leaf.
    windll = mocker.patch("ctypes.windll", create=True)
    # patched at its source, not on __main__: `run` is imported inside main() rather than at module
    # scope, so that --register/--unregister never pay for loading PySide6 (see __main__'s comment)
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    assert main() == 0
    run.assert_called_once_with([str(Path(FAKE_ARGV0).resolve()), "a.rehu"])
    windll.shell32.SetCurrentProcessExplicitAppUserModelID.assert_not_called()


def test_scrape_schema_writes_the_schema_and_never_launches_the_gui(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, tmp_path: Path
) -> None:
    """``--scrape-schema PATH`` is checked before any platform branch and returns without ``run()`` (#340).

    **Test steps:**

    * set ``sys.argv`` to argv[0] plus ``--scrape-schema PATH``
    * mock ``run`` and verify ``main()`` returns ``0``, the file is written, and ``run()`` is never called
    """
    path = tmp_path / "schema.json"
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--scrape-schema", str(path)])
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    assert main() == 0
    assert path.exists()
    run.assert_not_called()


def test_output_without_scrape_is_a_usage_error(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--output``/``--scrapers-folder`` qualify ``--scrape``; alone they are refused the way argparse
    refuses any misuse (exit ``2``), rather than silently ignored on the way to a GUI launch (#340).

    **Test steps:**

    * set ``sys.argv`` to argv[0] plus ``--output PATH`` and no ``--scrape``
    * mock ``run`` and verify ``main()`` exits ``2`` and never reaches ``run()``
    """
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--output", "out.json"])
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 2
    run.assert_not_called()


def test_scrape_flag_dispatches_to_the_scraping_cli_and_never_launches_the_gui(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """``--scrape URL`` dispatches to `rehuco_agent.scraping.cli.scrape_url_to_json` and returns without
    ``run()`` (#340).

    **Test steps:**

    * set ``sys.argv`` to argv[0] plus ``--scrape URL``
    * mock ``scrape_url_to_json`` and ``run``
    * verify ``main()`` returns the mocked exit code, the CLI helper is called with the parsed
      arguments, and ``run()`` is never called
    """
    url = "https://example.com/page"
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--scrape", url])
    scrape_url_to_json = mocker.patch("rehuco_agent.scraping.cli.scrape_url_to_json", return_value=0)
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    assert main() == 0
    scrape_url_to_json.assert_called_once_with(url, scrapers_folder=None, output=None)
    run.assert_not_called()


def test_a_gui_launch_exception_is_logged_and_reraised(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """An exception from ``run()`` itself -- rather than from ``app.exec()``, which ``run()`` already
    logs on its own way out -- would otherwise reach here having never been logged at all (#362).

    **Test steps:**

    * set ``sys.argv`` to argv[0] with no flags, a plain GUI launch
    * make ``run`` raise
    * verify the exception was logged through the shared run log, then re-raised
    """
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0])
    error = RuntimeError("boom")
    mocker.patch("rehuco_agent.app.run", side_effect=error)
    run_log = mocker.patch("rehuco_agent.run_log.shared_run_log").return_value

    with pytest.raises(RuntimeError):
        main()

    run_log.log_exception.assert_called_once_with(error, "main()")


def test_the_settings_dir_flag_wins_over_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The flag is the more deliberate of the two, so it decides when both are given (#494).

    **Test steps:**

    * resolve a flag and an environment value that differ
    * verify the flag's folder is the answer
    """
    monkeypatch.chdir(tmp_path)

    assert resolve_settings_dir(tmp_path / "flag", str(tmp_path / "env")) == tmp_path / "flag"


def test_the_settings_dir_falls_back_to_the_environment(tmp_path: Path) -> None:
    """Without the flag, the environment variable's folder is used (#494).

    **Test steps:**

    * resolve no flag and an environment value
    * verify the environment's folder is the answer
    """
    assert resolve_settings_dir(None, str(tmp_path / "env")) == tmp_path / "env"


@pytest.mark.parametrize("environment", [None, ""])
def test_no_settings_dir_is_chosen_without_a_flag_or_a_value(environment: str | None) -> None:
    """An unset or empty variable is no choice: the platform's locations stay (#494).

    **Test steps:**

    * resolve no flag with an absent or empty environment value
    * verify there is no folder
    """
    assert resolve_settings_dir(None, environment) is None


def test_a_relative_settings_dir_is_made_absolute_against_the_launch_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The GUI leaves its launch directory before reading a setting, so the folder is pinned down first (#494).

    **Test steps:**

    * launch from a temporary directory and resolve a relative flag and a relative environment value
    * verify both come back absolute, under that directory
    """
    monkeypatch.chdir(tmp_path)

    assert resolve_settings_dir(Path("rel"), None) == tmp_path / "rel"
    assert resolve_settings_dir(None, "rel") == tmp_path / "rel"


def test_a_gui_launch_with_a_settings_dir_creates_it_and_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """``--settings-dir`` takes effect before the GUI starts (#494).

    **Test steps:**

    * force a non-registration platform, set ``sys.argv`` to argv[0] plus ``--settings-dir`` for a missing folder
    * mock ``run`` and verify ``main()`` returns its code
    * verify the folder exists and is the settings dir while ``run`` is called
    """
    folder = tmp_path / "dev"
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--settings-dir", str(folder)])
    seen: list[Path | None] = []
    mocker.patch("rehuco_agent.app.run", side_effect=lambda _argv: seen.append(settings_dir()) or 0)

    assert main() == 0
    assert folder.is_dir()
    assert seen == [folder]


def test_a_gui_launch_takes_the_settings_dir_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """The environment variable does what the flag does when no flag is given (#494).

    **Test steps:**

    * set the variable and launch without the flag
    * verify the settings dir in effect during ``run`` is the variable's folder
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0])
    monkeypatch.setenv(SETTINGS_DIR_ENVIRONMENT_VARIABLE, str(tmp_path / "env"))
    seen: list[Path | None] = []
    mocker.patch("rehuco_agent.app.run", side_effect=lambda _argv: seen.append(settings_dir()) or 0)

    assert main() == 0
    assert seen == [tmp_path / "env"]


def test_a_launch_without_a_settings_dir_leaves_the_platforms_locations(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """Nothing changes for a run that asks for nothing (#494).

    **Test steps:**

    * launch with no flag and the variable removed
    * verify no settings dir was in effect during ``run``
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0])
    monkeypatch.delenv(SETTINGS_DIR_ENVIRONMENT_VARIABLE, raising=False)
    seen: list[Path | None] = []
    mocker.patch("rehuco_agent.app.run", side_effect=lambda _argv: seen.append(settings_dir()) or 0)

    assert main() == 0
    assert seen == [None]


def test_a_settings_dir_that_is_a_file_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """A file cannot hold settings, so the launch stops with argparse's usage error (#494).

    **Test steps:**

    * point ``--settings-dir`` at an existing file
    * mock ``run`` and verify ``main()`` exits ``2`` without launching and without a settings dir
    """
    not_a_folder = tmp_path / "file"
    not_a_folder.write_text("", encoding="utf-8")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--settings-dir", str(not_a_folder)])
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 2
    run.assert_not_called()
    assert settings_dir() is None


def test_info_reports_where_the_settings_data_and_cache_are(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--info`` says which state a run would use, so a development build is easy to tell from the installed one
    (#494).

    **Test steps:**

    * ask for ``--info`` with ``--settings-dir`` on a non-registration platform
    * verify the output names the ini, the data and the cache in that folder, in the platform's own spelling
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "--info", "--settings-dir", str(tmp_path)])

    assert main() == 0

    lines = capsys.readouterr().out.splitlines()
    assert f"settings: {tmp_path / f'{APPLICATION_NAME}.ini'}" in lines
    assert f"data: {tmp_path}" in lines
    assert f"cache: {tmp_path}" in lines


def test_node_flag_runs_the_node_instead_of_the_agent(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """``rehuco-agent --node ...`` hands the remaining arguments to the node's own main and returns its code (#506),
    so the packaged exe hosts the node as itself.

    **Test steps:**

    * run ``main`` with ``--node --version``
    * verify the node's version line was printed and the GUI never launched
    """
    mocker.patch.object(sys, "argv", ["rehuco-agent", "--node", "--version"])
    run = mocker.patch("rehuco_agent.app.run")

    assert main() == 0

    assert capsys.readouterr().out.strip().startswith("version: ")
    run.assert_not_called()
