"""Tests for the VLC descriptor: reading ``vlc --version`` and knowing where each OS keeps it (#318)."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Final

from pytest import MonkeyPatch, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import EXTERNAL_TOOLS, VLC_TOOL, ToolNotRunnableError, ToolStatus, Version

MODULE: Final = "rehuco_core.external_tools.vlc_tool"
RUNNER: Final = "rehuco_core.external_tools.tool_descriptor.subprocess.run"


def run_printing(mocker: MockerFixture, stdout: str, returncode: int = 0) -> None:
    """Make ``vlc`` print something.

    :param mocker: the pytest-mock fixture.
    :param stdout: what it prints.
    :param returncode: how it exits.
    """
    mocker.patch(RUNNER, return_value=SimpleNamespace(stdout=stdout, returncode=returncode))


def test_vlc_is_one_of_the_tools_the_tools_page_lists() -> None:
    """The Tools page builds a frame per registered tool, so registering is how VLC gets one.

    **Test steps:**

    * look VLC up by its id
    * verify the registry holds the very descriptor
    """
    assert EXTERNAL_TOOLS[VLC_TOOL.ID] is VLC_TOOL


@mark.parametrize(
    ("first_line", "version"),
    [
        param("VLC version 3.0.23 Vetinari (3.0.23-2-0-g79128878dd)", (3, 0, 23), id="release"),
        param("VLC version 3.0 Vetinari", (3, 0), id="two-parts"),
        param("VLC version 4.0.0-dev Otto Chriek (4.0.0-dev-1234-gabcdef)", (4, 0, 0), id="vlc-4"),
        param("VLC version nightly-20260101", None, id="nightly"),
        param("something else entirely", None, id="no-version-line"),
    ],
)
def test_the_version_is_read_off_the_first_line(
    mocker: MockerFixture, first_line: str, version: Version | None
) -> None:
    """A release prints its numbers and a nightly prints none a comparison could use.

    **Test steps:**

    * make ``vlc`` print a banner
    * read the version
    * verify the numbers, or none for a build that prints a date
    """
    run_printing(mocker, f"{first_line}\nCompiled by videolan (version 9.9.9)\n")

    assert VLC_TOOL.read_version(Path("/opt/vlc")) == version


def test_the_version_is_asked_of_vlc_with_no_shell(mocker: MockerFixture) -> None:
    """The copy runs with a fixed flag and a time limit, never through a shell.

    **Test steps:**

    * read a version
    * verify what ran
    """
    run = mocker.patch(RUNNER, return_value=SimpleNamespace(stdout="", returncode=0))
    VLC_TOOL.read_version(Path("/opt/vlc"))

    command = run.call_args.args[0]
    assert Path(command[0]).stem == "vlc"
    assert command[1:] == ["--version"]
    assert run.call_args.kwargs["timeout"] > 0
    assert run.call_args.kwargs["check"] is False


@mark.parametrize(
    ("error", "returncode"),
    [
        param(OSError("not executable"), 0, id="would-not-start"),
        param(subprocess.TimeoutExpired("vlc", 30.0), 0, id="never-returned"),
        param(None, 1, id="exited-with-an-error"),
    ],
)
def test_a_copy_that_does_not_run_says_so(mocker: MockerFixture, error: Exception | None, returncode: int) -> None:
    """A copy that cannot answer is *not runnable*, with the reason shown on the page.

    **Test steps:**

    * make the call fail, hang or exit with an error
    * verify the version read raises with a reason
    """
    if error is None:
        run_printing(mocker, "", returncode)
    else:
        mocker.patch(RUNNER, side_effect=error)

    with raises(ToolNotRunnableError) as raised:
        VLC_TOOL.read_version(Path("/opt/vlc"))

    assert raised.value.reason


@mark.parametrize(
    ("version", "status"),
    [
        param((2, 2, 8), ToolStatus.TOO_OLD, id="too-old"),
        param((3, 0, 23), ToolStatus.USABLE, id="tested"),
        param((3, 1), ToolStatus.UNTESTED, id="newer-than-tested"),
        param(None, ToolStatus.UNTESTED, id="unreadable"),
    ],
)
def test_a_version_is_judged_against_the_minimum_and_the_newest_tested(
    version: Version | None, status: ToolStatus
) -> None:
    """VLC 3.0 is the oldest that works, and a later one is allowed but untested.

    **Test steps:**

    * judge a version older than the minimum, a tested one, a newer one and an unreadable one
    * verify each status
    """
    assert VLC_TOOL.judge(version)[0] is status


@mark.parametrize(
    ("platform", "sources"),
    [
        param("win32", {"Program Files", "scoop"}, id="windows"),
        param("darwin", {"Applications", "Homebrew"}, id="macos"),
        param("linux", {"system"}, id="linux"),
    ],
)
def test_each_os_has_its_own_places_to_look(
    mocker: MockerFixture, monkeypatch: MonkeyPatch, platform: str, sources: set[str]
) -> None:
    """Detection searches where each OS installs VLC, by name.

    **Test steps:**

    * ask for the patterns on each OS
    * verify the places it names
    """
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")
    mocker.patch(f"{MODULE}.sys", SimpleNamespace(platform=platform))

    assert {source for source, _ in VLC_TOOL.search_patterns()} == sources


@mark.skipif(sys.platform != "win32", reason="only Windows' os.path expands %VAR%")
def test_the_windows_patterns_expand_the_environment(monkeypatch: MonkeyPatch) -> None:
    """The patterns name folders under the environment's, so the variables are expanded here.

    **Test steps:**

    * set ``ProgramFiles`` and ask for the Windows patterns
    * verify the first pattern is the 64-bit Program Files one, expanded
    """
    monkeypatch.setenv("ProgramFiles", "C:\\Program Files")

    assert VLC_TOOL.search_patterns()[0] == ("Program Files", "C:\\Program Files\\VideoLAN\\VLC")
