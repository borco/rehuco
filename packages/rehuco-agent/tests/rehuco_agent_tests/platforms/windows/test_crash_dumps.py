"""Tests for crash_dumps: HKLM ``LocalDumps`` enable/disable/check, and the dumps folder (#363)."""

import base64
import os
from pathlib import Path
from typing import Final

import pytest
from pytest import mark

winreg = pytest.importorskip("winreg")  # module doesn't exist off Windows -- skip the whole file there

from pytest_mock import MockerFixture  # noqa: E402  # pylint: disable=wrong-import-position
from rehuco_agent import crash_dumps  # noqa: E402  # pylint: disable=wrong-import-position

EXE_NAME: Final = "Rehuco.exe"
FAKE_DUMPS_FOLDER: Final = Path("/fake/borco/rehuco-agent/crashdumps")


def _decode_script(outer_argv: list[str]) -> str:
    """Decode the ``-EncodedCommand`` payload out of the outer ``Start-Process`` invocation
    :func:`crash_dumps.run_elevated` builds.

    :param outer_argv: the full ``subprocess.run`` argv, as captured from the mock.
    :returns: the inner PowerShell script, decoded from base64 UTF-16LE.
    """
    outer_script = outer_argv[-1]
    encoded = outer_script.split("-EncodedCommand','")[1].rstrip("'")
    return base64.b64decode(encoded).decode("utf-16-le")


@mark.windows
def test_dumps_folder_is_the_crashdumps_subfolder_of_config_folder(mocker: MockerFixture) -> None:
    """``dumps_folder`` is ``crashdumps`` under this app's own config folder, next to the run log.

    **Test steps:**

    * mock ``config_folder``
    * verify the returned folder
    """
    mocker.patch(f"{crash_dumps.__name__}.config_folder", return_value=Path("/fake/borco/rehuco-agent"))

    assert crash_dumps.dumps_folder() == Path("/fake/borco/rehuco-agent/crashdumps")


@mark.windows
def test_dump_files_is_empty_when_the_folder_does_not_exist() -> None:
    """``dump_files`` reports no dumps rather than raising while the folder doesn't exist yet.

    **Test steps:**

    * list a folder that never exists on this machine
    * verify an empty list
    """
    assert crash_dumps.dump_files(FAKE_DUMPS_FOLDER) == []


@mark.windows
def test_dump_files_lists_only_dmp_files_sorted(mocker: MockerFixture) -> None:
    """``dump_files`` lists only what its own ``*.dmp`` glob returns, sorted.

    **Test steps:**

    * mock a folder that exists and glob two dumps out of order
    * verify they come back sorted
    """
    folder = mocker.Mock()
    folder.is_dir.return_value = True
    folder.glob.return_value = [Path("b.dmp"), Path("a.dmp")]

    assert crash_dumps.dump_files(folder) == [Path("a.dmp"), Path("b.dmp")]
    folder.glob.assert_called_once_with("*.dmp")


@mark.windows
def test_clear_dumps_deletes_every_listed_file() -> None:
    """``clear_dumps`` deletes every ``*.dmp`` file :func:`dump_files` reports, and nothing else.

    **Test steps:**

    * mock two dump files
    * clear the folder
    * verify both were unlinked
    """
    first = MockerFile()
    second = MockerFile()

    crash_dumps.clear_dumps(FakeFolder([first, second]))  # type: ignore[arg-type]

    assert first.unlinked
    assert second.unlinked


class MockerFile:
    """A minimal ``Path``-like stand-in for one dump file, tracking whether ``unlink`` ran."""

    _next_id = 0

    def __init__(self, *, fails: bool = False) -> None:
        self.__fails = fails
        self.unlinked = False
        MockerFile._next_id += 1
        self._id = MockerFile._next_id

    def __lt__(self, other: MockerFile) -> bool:
        return self._id < other._id

    def unlink(self) -> None:
        """Mark this file as unlinked, or raise if it's set up to fail."""
        if self.__fails:
            raise OSError("access denied")
        self.unlinked = True


class FakeFolder:
    """A minimal ``Path``-like stand-in whose ``glob`` hands back a fixed list of files."""

    def __init__(self, files: list[MockerFile]) -> None:
        self.__files = files

    def is_dir(self) -> bool:
        """Always exists -- the fixed file list is what matters for these tests."""
        return True

    def glob(self, pattern: str) -> list[MockerFile]:
        """Return the fixed files, ignoring ``pattern`` -- the module always passes ``"*.dmp"``."""
        del pattern
        return self.__files


@mark.windows
def test_clear_dumps_skips_and_logs_a_file_that_cannot_be_deleted(caplog: pytest.LogCaptureFixture) -> None:
    """``clear_dumps`` logs a file it can't delete and moves on, rather than raising.

    **Test steps:**

    * mock one deletable and one undeletable file
    * clear the folder
    * verify the deletable one was unlinked, a warning was logged, and nothing raised
    """
    ok = MockerFile()
    stuck = MockerFile(fails=True)

    crash_dumps.clear_dumps(FakeFolder([ok, stuck]))  # type: ignore[arg-type]  # must not raise

    assert ok.unlinked
    assert "Could not delete crash dump" in caplog.text


@mark.windows
def test_enable_writes_the_expected_local_dumps_key_through_an_elevated_powershell(mocker: MockerFixture) -> None:
    """``enable`` runs one elevated, hidden PowerShell whose decoded script writes ``DumpFolder``,
    ``DumpCount`` and ``DumpType`` for the running exe's own ``LocalDumps`` sub-key.

    **Test steps:**

    * mock ``dumps_folder`` and ``subprocess.run``
    * enable crash dumps for a fake exe name
    * verify the outer invocation (``-Verb RunAs``, hidden, no console window) and the decoded inner
      script's registry writes
    """
    mocker.patch(f"{crash_dumps.__name__}.dumps_folder", return_value=FAKE_DUMPS_FOLDER)
    run = mocker.patch(f"{crash_dumps.__name__}.subprocess.run")

    crash_dumps.enable(EXE_NAME)

    run.assert_called_once()
    argv, kwargs = run.call_args
    outer_argv = argv[0]
    assert outer_argv[0] == "powershell"
    outer_script = outer_argv[-1]
    assert "-Verb RunAs" in outer_script
    assert "-WindowStyle Hidden" in outer_script
    assert kwargs["creationflags"] == crash_dumps.CREATE_NO_WINDOW

    script = _decode_script(outer_argv)
    key_path = rf"HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\{EXE_NAME}"
    assert key_path in script
    assert "New-Item" in script
    assert f'-Name DumpFolder -Value "{FAKE_DUMPS_FOLDER}"' in script
    assert "-Name DumpCount -Value 10" in script
    assert "-Name DumpType -Value 1" in script


@mark.windows
def test_disable_removes_the_local_dumps_key_through_an_elevated_powershell(mocker: MockerFixture) -> None:
    """``disable`` runs one elevated PowerShell whose decoded script removes the exe's own
    ``LocalDumps`` sub-key.

    **Test steps:**

    * mock ``subprocess.run``
    * disable crash dumps for a fake exe name
    * verify the outer invocation and the decoded inner script's ``Remove-Item``
    """
    run = mocker.patch(f"{crash_dumps.__name__}.subprocess.run")

    crash_dumps.disable(EXE_NAME)

    run.assert_called_once()
    argv, _kwargs = run.call_args
    outer_argv = argv[0]
    assert "-Verb RunAs" in outer_argv[-1]

    script = _decode_script(outer_argv)
    key_path = rf"HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\{EXE_NAME}"
    assert f'Remove-Item -Path "{key_path}"' in script


@mark.windows
def test_run_elevated_logs_but_does_not_raise_when_powershell_cannot_be_launched(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """``run_elevated`` logs a warning rather than propagating when the outer, unelevated
    ``subprocess.run`` itself fails to launch (e.g. PowerShell missing from ``PATH``).

    **Test steps:**

    * mock ``subprocess.run`` to raise ``OSError``
    * enable crash dumps
    * verify no exception propagates and a warning was logged
    """
    mocker.patch(f"{crash_dumps.__name__}.subprocess.run", side_effect=OSError("not found"))

    crash_dumps.enable(EXE_NAME)  # must not raise

    assert "Could not run elevated PowerShell" in caplog.text


@mark.windows
def test_is_enabled_reports_the_key_and_its_dump_folder_when_present(mocker: MockerFixture) -> None:
    """``is_enabled`` reads the key back through ``winreg`` and reports the folder it names.

    **Test steps:**

    * mock ``winreg.OpenKey``/``QueryValueEx`` to report a value
    * check the status
    * verify ``(True, folder)``
    """
    key = mocker.MagicMock()
    open_key = mocker.patch(f"{crash_dumps.__name__}.winreg.OpenKey")
    open_key.return_value.__enter__.return_value = key
    mocker.patch(f"{crash_dumps.__name__}.winreg.QueryValueEx", return_value=(str(FAKE_DUMPS_FOLDER), 2))

    enabled, folder = crash_dumps.is_enabled(EXE_NAME)

    assert enabled is True
    assert folder == FAKE_DUMPS_FOLDER
    open_key.assert_called_once()
    args, _kwargs = open_key.call_args
    assert args[0] == winreg.HKEY_LOCAL_MACHINE
    assert args[1] == rf"SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\{EXE_NAME}"


@mark.windows
def test_is_enabled_expands_a_dump_folder_set_with_environment_variables(mocker: MockerFixture) -> None:
    """A ``DumpFolder`` set by hand as ``%SystemDrive%\\...`` comes back expanded -- the folder Windows
    itself writes into -- rather than as a literal that exists nowhere. ``SystemDrive`` because it is
    set on every Windows session, so nothing about this machine's environment has to be arranged.

    **Test steps:**

    * mock ``winreg.OpenKey``/``QueryValueEx`` to report an unexpanded ``REG_EXPAND_SZ``
    * check the status
    * verify the folder has the variable expanded
    """
    open_key = mocker.patch(f"{crash_dumps.__name__}.winreg.OpenKey")
    open_key.return_value.__enter__.return_value = mocker.MagicMock()
    mocker.patch(f"{crash_dumps.__name__}.winreg.QueryValueEx", return_value=(r"%SystemDrive%\fake\dumps", 2))

    enabled, folder = crash_dumps.is_enabled(EXE_NAME)

    assert enabled is True
    assert folder == Path(os.environ["SystemDrive"] + r"\fake\dumps")


@mark.windows
def test_is_enabled_reports_not_enabled_when_the_key_is_missing(mocker: MockerFixture) -> None:
    """``is_enabled`` reports not-enabled rather than raising when the key doesn't exist.

    **Test steps:**

    * mock ``winreg.OpenKey`` to raise ``FileNotFoundError``
    * check the status
    * verify ``(False, None)``
    """
    mocker.patch(f"{crash_dumps.__name__}.winreg.OpenKey", side_effect=FileNotFoundError())

    enabled, folder = crash_dumps.is_enabled(EXE_NAME)

    assert enabled is False
    assert folder is None
