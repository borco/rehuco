"""Tests for the rehuco-agent CLI entry point's Linux register/unregister dispatch (#209).

``sys.platform`` is faked rather than skipped around: ``main()`` reads it at call time, and
everything the Linux branch reaches is mocked, so the branch is exercised (and measured) on every
OS -- unlike the Windows sibling file, which cannot even import ``winreg`` elsewhere.
"""

from pathlib import Path
from typing import Final

import pytest
from pytest_mock import MockerFixture
from rehuco_agent.__main__ import main

MODULE: Final = "rehuco_agent.linux_registration"

FAKE_SHIM: Final = "/fake/home/.local/bin/rehuco-agent"
FAKE_APPIMAGE: Final = Path("/fake/downloads/Rehuco-x86_64.AppImage")
BLOCKER: Final = "Cannot register/unregister -- running inside Flatpak."


def test_register_registers_the_launched_executable(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--register`` registers whatever file the user actually launched, not ``sys.argv[0]``.

    Inside an AppImage those differ: ``executable_path`` resolves ``$APPIMAGE``, while
    ``sys.argv[0]`` points into a temporary mount that will not exist by the time anyone
    double-clicks the entry.

    **Test steps:**

    * force ``sys.platform`` to Linux and set ``sys.argv`` to ``--register``
    * mock ``executable_path`` to report an AppImage, and ``registration_blocker`` to allow it
    * verify ``main()`` returns ``0`` and ``register`` was called with the AppImage
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--register"])
    mocker.patch(f"{MODULE}.executable_path", return_value=FAKE_APPIMAGE)
    mocker.patch(f"{MODULE}.registration_blocker", return_value=None)
    register = mocker.patch(f"{MODULE}.register")

    assert main() == 0
    register.assert_called_once_with(FAKE_APPIMAGE)


def test_unregister_calls_linux_registration(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--unregister`` removes the desktop entry, MIME package and icon.

    **Test steps:**

    * force ``sys.platform`` to Linux and set ``sys.argv`` to ``--unregister``
    * mock ``executable_path``/``registration_blocker`` and ``unregister``
    * verify ``main()`` returns ``0`` and ``unregister`` was called
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--unregister"])
    mocker.patch(f"{MODULE}.executable_path", return_value=Path(FAKE_SHIM))
    mocker.patch(f"{MODULE}.registration_blocker", return_value=None)
    unregister = mocker.patch(f"{MODULE}.unregister")

    assert main() == 0
    unregister.assert_called_once_with()


def test_info_reports_the_installed_desktop_entrys_exec_value(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--info`` reads the installed desktop entry, not ``exe_path`` -- the AppImage the user is
    running right now may not be the one that's actually registered, which is the ordinary state
    there rather than an edge case ([[packaging-deployment#linux-format]]).

    **Test steps:**

    * force ``sys.platform`` to Linux and set ``sys.argv`` to ``--info``
    * mock ``registered_command`` to report an installed ``Exec=`` value
    * verify ``main()`` returns ``0`` and printed that value, without consulting ``executable_path``
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--info"])
    executable_path = mocker.patch(f"{MODULE}.executable_path")
    mocker.patch(f"{MODULE}.registered_command", return_value=f'"{FAKE_APPIMAGE}" %F')

    assert main() == 0
    assert str(FAKE_APPIMAGE) in capsys.readouterr().out
    executable_path.assert_not_called()


def test_info_reports_not_registered(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--info`` with nothing installed prints a plain "not registered", the same on every OS.

    **Test steps:**

    * force ``sys.platform`` to Linux and set ``sys.argv`` to ``--info``
    * mock ``registered_command`` to report nothing installed
    * verify ``main()`` returns ``0`` and printed "not registered"
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--info"])
    mocker.patch(f"{MODULE}.registered_command", return_value=None)

    assert main() == 0
    assert "not registered" in capsys.readouterr().out


def test_info_reports_before_register_acts(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--info --register`` on one command line: the printed state is the state *before*
    registering, then registration happens -- matching how the flags read left to right, regardless
    of the order they were typed in.

    **Test steps:**

    * set ``sys.argv`` to ``--info --register``, with nothing registered yet
    * verify ``main()`` returns ``0``, printed "not registered", and then called ``register``
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--info", "--register"])
    mocker.patch(f"{MODULE}.registered_command", return_value=None)
    mocker.patch(f"{MODULE}.executable_path", return_value=Path(FAKE_SHIM))
    mocker.patch(f"{MODULE}.registration_blocker", return_value=None)
    register = mocker.patch(f"{MODULE}.register")

    assert main() == 0
    assert "not registered" in capsys.readouterr().out
    register.assert_called_once_with(Path(FAKE_SHIM))


def test_register_refuses_and_explains_when_blocked(
    monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """A blocked registration (a sandbox, or a source checkout) exits non-zero and says why.

    The message is `linux_registration`'s own, so the CLI and the settings page cannot drift apart
    on what they tell the user.

    **Test steps:**

    * force ``sys.platform`` to Linux and set ``sys.argv`` to ``--register``
    * mock ``registration_blocker`` to report a reason
    * verify ``main()`` returns ``1``, ``register`` was never called, and the reason reached stderr
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--register"])
    mocker.patch(f"{MODULE}.executable_path", return_value=Path(FAKE_SHIM))
    mocker.patch(f"{MODULE}.registration_blocker", return_value=BLOCKER)
    register = mocker.patch(f"{MODULE}.register")

    assert main() == 1
    register.assert_not_called()
    assert BLOCKER in capsys.readouterr().err


def test_unregister_refuses_when_blocked(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--unregister`` is refused by its own blocker (sandboxed), not ``registration_blocker``.

    Unregistering never depends on ``executable_path`` -- ``unregister()`` itself takes no
    argument, since it only removes fixed per-user files -- so only a sandbox can block it.

    **Test steps:**

    * force ``sys.platform`` to Linux and set ``sys.argv`` to ``--unregister``
    * mock ``unregistration_blocker`` to report a reason
    * verify ``main()`` returns ``1``, ``unregister`` was never called, and ``executable_path``
      was never consulted
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--unregister"])
    executable_path = mocker.patch(f"{MODULE}.executable_path")
    mocker.patch(f"{MODULE}.unregistration_blocker", return_value=BLOCKER)
    unregister = mocker.patch(f"{MODULE}.unregister")

    assert main() == 1
    unregister.assert_not_called()
    executable_path.assert_not_called()


def test_register_is_not_offered_on_macos(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """``--register`` isn't defined on the parser at all on macOS.

    There the association is the app bundle's own declaration, with nothing per-user to write --
    so argparse rejects the flag as unrecognized rather than this code making a runtime check.

    **Test steps:**

    * force ``sys.platform`` to macOS and set ``sys.argv`` to ``--register``
    * verify ``main()`` raises ``SystemExit`` without ever registering anything
    """
    monkeypatch.setattr("sys.platform", "darwin")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "--register"])
    register = mocker.patch(f"{MODULE}.register")

    with pytest.raises(SystemExit):
        main()
    register.assert_not_called()


def test_paths_only_skips_the_linux_block(monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture) -> None:
    """With no flags, Linux goes straight to the GUI without touching the registration module.

    **Test steps:**

    * force ``sys.platform`` to Linux and set ``sys.argv`` to argv[0] plus one ``.rehu`` path
    * mock ``run`` and ``executable_path``
    * verify ``run`` received the path and ``executable_path`` was never consulted
    """
    monkeypatch.setattr("sys.platform", "linux")
    monkeypatch.setattr("sys.argv", [FAKE_SHIM, "a.rehu"])
    executable_path = mocker.patch(f"{MODULE}.executable_path")
    # patched at its source, not on __main__: `run` is imported inside main() rather than at module
    # scope, so that --register/--unregister never pay for loading the dock shell
    run = mocker.patch("rehuco_agent.app.run", return_value=0)

    assert main() == 0
    run.assert_called_once_with([str(Path(FAKE_SHIM).resolve()), "a.rehu"])
    executable_path.assert_not_called()
