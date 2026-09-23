"""Cross-platform tests for the rehuco-agent CLI entry point.

Windows-specific behavior (register/unregister, AUMID) lives in
``tests/platforms/windows/test_main.py``, guarded by ``pytest.importorskip("winreg")`` -- these
tests exercise the platform-agnostic and non-Windows paths, so they run on every OS.
"""

from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent import __version__
from rehuco_agent.__main__ import main

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
