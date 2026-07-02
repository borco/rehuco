"""Cross-platform tests for the rehuco-agent CLI entry point.

Windows-specific behavior (register/unregister, AUMID) lives in
``tests/platforms/windows/test_main.py``, guarded by ``pytest.importorskip("winreg")`` -- these
tests exercise the platform-agnostic and non-Windows paths, so they run on every OS.
"""

from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent.__main__ import main

FAKE_ARGV0: Final = "/fake/rehuco-agent-dev"
"""No ``.exe``/drive-letter shape -- argv[0] isn't a Windows executable on this path."""


def test_paths_only_skips_windows_block_on_non_windows(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """With no register/unregister flags, a non-Windows platform skips the whole win32 block.

    Distinct from ``test_register_not_offered_on_non_windows`` (in the Windows-only test file):
    that one exercises argparse's own rejection of ``--register`` before the platform check is
    ever reached. This one has no flags at all, so parsing succeeds and
    ``if sys.platform == "win32":`` is actually evaluated and takes its ``False`` branch
    straight to ``run()``.

    **Test steps:**

    * force ``sys.platform`` to a non-Windows value
    * set ``sys.argv`` to argv[0] plus one ``.rehu`` path, no flags
    * mock ``run`` and ``SetCurrentProcessExplicitAppUserModelID``
    * verify ``run`` was called and the AUMID call was not (it's inside the win32 block)
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_ARGV0, "a.rehu"])
    set_aumid = mocker.patch("ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID", create=True)
    run = mocker.patch("rehuco_agent.__main__.run", return_value=0)

    assert main() == 0
    run.assert_called_once_with([str(Path(FAKE_ARGV0).resolve()), "a.rehu"])
    set_aumid.assert_not_called()
