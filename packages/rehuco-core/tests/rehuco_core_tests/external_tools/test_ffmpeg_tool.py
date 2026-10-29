"""Tests for the FFmpeg descriptor: reading ``ffprobe -version`` and knowing where each OS keeps it (#521)."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Final

from pytest import MonkeyPatch, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import FFMPEG_TOOL, ToolNotRunnableError, Version

MODULE: Final = "rehuco_core.external_tools.ffmpeg_tool"
RUNNER: Final = "rehuco_core.external_tools.tool_descriptor.subprocess.run"


def run_printing(mocker: MockerFixture, stdout: str, returncode: int = 0) -> None:
    """Make ``ffprobe`` print something.

    :param mocker: the pytest-mock fixture.
    :param stdout: what it prints.
    :param returncode: how it exits.
    """
    mocker.patch(RUNNER, return_value=SimpleNamespace(stdout=stdout, returncode=returncode))


@mark.parametrize(
    ("first_line", "version"),
    [
        param("ffprobe version 7.1.1-essentials_build-www.gyan.dev Copyright (c) 2007-2025", (7, 1, 1), id="release"),
        param("ffprobe version n7.1.5-12-g1fdbca85aa-20260731 Copyright", (7, 1, 5), id="release-tagged-n"),
        param("ffprobe version 6.0 Copyright", (6, 0), id="two-parts"),
        param("ffprobe version N-118000-g1a2b3c Copyright", None, id="git-build-by-commit-count"),
        param("ffprobe version 2024-05-01-git-abcdef-full_build Copyright", None, id="git-build-by-date"),
        param("something else entirely", None, id="no-version-line"),
    ],
)
def test_the_version_is_read_off_the_first_line(
    mocker: MockerFixture, first_line: str, version: Version | None
) -> None:
    """A release prints its numbers and a git build prints none a comparison could use.

    **Test steps:**

    * make ``ffprobe`` print a banner
    * read the version
    * verify the numbers, or none for a build that prints a date or a commit count
    """
    run_printing(mocker, f"{first_line}\nbuilt with gcc 13 (version 9.9.9)\n")

    assert FFMPEG_TOOL.read_version(Path("/opt/ffmpeg/bin")) == version


def test_the_version_is_asked_of_ffprobe_with_no_shell(mocker: MockerFixture) -> None:
    """The copy runs with a fixed flag and a time limit, never through a shell.

    **Test steps:**

    * read a version
    * verify what ran
    """
    run = mocker.patch(RUNNER, return_value=SimpleNamespace(stdout="", returncode=0))
    FFMPEG_TOOL.read_version(Path("/opt/ffmpeg/bin"))

    command = run.call_args.args[0]
    assert Path(command[0]).stem == "ffprobe"
    assert command[1:] == ["-version"]
    assert run.call_args.kwargs["timeout"] > 0
    assert run.call_args.kwargs["check"] is False


@mark.parametrize(
    ("error", "returncode"),
    [
        param(OSError("not executable"), 0, id="would-not-start"),
        param(subprocess.TimeoutExpired("ffprobe", 15.0), 0, id="never-returned"),
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
        FFMPEG_TOOL.read_version(Path("/opt/ffmpeg/bin"))

    assert raised.value.reason


@mark.parametrize(
    ("platform", "sources"),
    [
        param("win32", {"winget", "scoop", "chocolatey", "Program Files"}, id="windows"),
        param("darwin", {"Homebrew", "MacPorts"}, id="macos"),
        param("linux", {"system"}, id="linux"),
    ],
)
def test_each_os_has_its_own_places_to_look(
    mocker: MockerFixture, monkeypatch: MonkeyPatch, platform: str, sources: set[str]
) -> None:
    """Detection searches where the OS's package managers install, by name.

    **Test steps:**

    * ask for the patterns on each OS
    * verify the package managers it names
    """
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\x\\AppData\\Local")
    mocker.patch(f"{MODULE}.sys", SimpleNamespace(platform=platform))

    assert {source for source, _ in FFMPEG_TOOL.search_patterns()} == sources


@mark.skipif(sys.platform != "win32", reason="only Windows' os.path expands %VAR%")
def test_the_windows_patterns_expand_the_environment(monkeypatch: MonkeyPatch) -> None:
    """The patterns name folders under the user's profile, so the variables are expanded here.

    **Test steps:**

    * set ``LOCALAPPDATA`` and ask for the Windows patterns
    * verify the winget pattern starts with it
    """
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\x\\AppData\\Local")

    patterns = dict(FFMPEG_TOOL.search_patterns())

    assert patterns["winget"].startswith("C:\\Users\\x\\AppData\\Local\\Microsoft\\WinGet")
