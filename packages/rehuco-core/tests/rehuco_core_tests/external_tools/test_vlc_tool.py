"""Tests for the VLC descriptor: reading ``vlc --version`` and knowing where each OS keeps it (#318)."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

from pytest import MonkeyPatch, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    EXTERNAL_TOOLS,
    LIBVLC_PROBE_FLAG,
    VLC_TOOL,
    ToolNotRunnableError,
    ToolStatus,
    Version,
    VlcTool,
)

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


# region The library (#319)

TOOL: Final = VlcTool()
"""A descriptor of this module's own: the shared one is configured by the app's entry point, which other tests run,
and these tests judge installs with and without the child configured."""


def lay_out(folder: Path, *names: str) -> None:
    """Put empty files and folders into an install.

    :param folder: the install.
    :param names: file names; one ending in ``/`` is a folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        if name.endswith("/"):
            (folder / name.rstrip("/")).mkdir()
        else:
            (folder / name).touch()


@mark.parametrize(
    ("platform", "expected"),
    [
        param("win32", ["libvlc.dll", "libvlccore.dll", "plugins"], id="windows"),
        param("darwin", ["lib/libvlc.dylib", "lib/libvlccore.dylib", "plugins"], id="macos"),
    ],
)
def test_the_library_files_are_the_oss_layout(
    mocker: MockerFixture, tmp_path: Path, platform: str, expected: list[str]
) -> None:
    """**Test steps:**

    * ask, as each OS, what loading libvlc from an install needs
    * verify the library, its core and the plugins folder, where that OS keeps them
    """
    mocker.patch.object(sys, "platform", platform)

    assert TOOL.library_files(tmp_path) == [tmp_path / name for name in expected]


def test_on_linux_the_libraries_are_the_systems(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * ask, as Linux, with the loader finding the libraries and then not
    * verify their paths, and no library path when the loader finds none
    """
    mocker.patch.object(sys, "platform", "linux")
    find = mocker.patch(f"{MODULE}.ctypes.util.find_library", side_effect=["/lib/libvlc.so.5", "/lib/libvlccore.so.9"])
    assert TOOL.library_files(tmp_path) == [Path("/lib/libvlc.so.5"), Path("/lib/libvlccore.so.9")]
    assert find.call_args_list == [mocker.call("vlc"), mocker.call("vlccore")]

    find.side_effect = [None, None]
    assert TOOL.library_path(tmp_path) is None


def test_a_static_install_has_no_library_and_is_not_usable(mocker: MockerFixture, tmp_path: Path) -> None:
    """A VLC whose executable is there but whose shared library is not cannot be loaded into the player.

    **Test steps:**

    * lay out ``vlc.exe`` alone, as Windows, and judge the install
    * verify *no libraries* with the reason, no version read, no process run, and no library path
    """
    mocker.patch.object(sys, "platform", "win32")
    run = mocker.patch(RUNNER)
    lay_out(tmp_path, "vlc.exe")

    status, version, reason = TOOL.assess(tmp_path)

    assert status is ToolStatus.NO_LIBRARIES
    assert version is None
    assert "static or sandboxed" in reason
    assert TOOL.library_path(tmp_path) is None
    run.assert_not_called()


def test_an_install_missing_part_of_its_library_is_incomplete(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * lay out ``libvlc.dll`` without ``libvlccore.dll`` or ``plugins``
    * verify *incomplete*, naming what is missing
    """
    mocker.patch.object(sys, "platform", "win32")
    lay_out(tmp_path, "vlc.exe", "libvlc.dll")

    status, _, reason = TOOL.assess(tmp_path)

    assert status is ToolStatus.INCOMPLETE
    assert "libvlccore.dll" in reason and "plugins" in reason


def test_a_whole_install_is_judged_by_its_version_when_no_child_is_configured(
    mocker: MockerFixture, tmp_path: Path
) -> None:
    """Unconfigured -- a test, or a process that is not the agent -- the files and the version decide.

    **Test steps:**

    * lay out a whole install and have ``vlc --version`` print 3.0.23
    * verify usable with that version, and the library path
    """
    mocker.patch.object(sys, "platform", "win32")
    lay_out(tmp_path, "vlc.exe", "libvlc.dll", "libvlccore.dll", "plugins/")
    run_printing(mocker, "VLC version 3.0.23 Vetinari\n")

    assert TOOL.assess(tmp_path) == (ToolStatus.USABLE, (3, 0, 23), "")
    assert TOOL.library_path(tmp_path) == tmp_path / "libvlc.dll"


def test_a_too_old_install_is_not_tried_in_the_child(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * configure the child, lay out a whole install printing 2.2.8
    * verify *too old*, with the child never run
    """
    mocker.patch.object(sys, "platform", "win32")
    lay_out(tmp_path, "vlc.exe", "libvlc.dll", "libvlccore.dll", "plugins/")
    run = mocker.patch(RUNNER, return_value=SimpleNamespace(stdout="VLC version 2.2.8 Weatherwax\n", returncode=0))
    TOOL.configure(("rehuco-agent",))
    try:
        status, version, _ = TOOL.assess(tmp_path)
    finally:
        TOOL.configure(())

    assert (status, version) == (ToolStatus.TOO_OLD, (2, 2, 8))
    assert run.call_count == 1


def child_answering(mocker: MockerFixture, answer: dict[str, object] | None) -> Any:
    """Make the child process write an answer, after ``vlc --version`` printed a usable version.

    :param mocker: the pytest-mock fixture.
    :param answer: what the child writes, or ``None`` to write nothing.
    :returns: the patched runner.
    """

    def run(command: list[str], **_: object) -> SimpleNamespace:
        if "--version" in command:
            return SimpleNamespace(stdout="VLC version 3.0.23 Vetinari\n", returncode=0)
        if answer is not None:
            Path(command[command.index("--output") + 1]).write_text(json.dumps(answer), encoding="utf-8")
        return SimpleNamespace(stdout="", returncode=0)

    return mocker.patch(RUNNER, side_effect=run)


def test_a_usable_version_is_then_tried_in_a_child_with_the_library(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * configure the child and lay out a whole install; have the child report usable, bound to the library
    * verify usable with the version ``vlc`` printed, and that the child was run with the flag and the library
    """
    mocker.patch.object(sys, "platform", "win32")
    lay_out(tmp_path, "vlc.exe", "libvlc.dll", "libvlccore.dll", "plugins/")
    library = tmp_path / "libvlc.dll"
    run = child_answering(mocker, {"status": "usable", "version": [3, 0, 23], "reason": "", "library": str(library)})
    TOOL.configure(("rehuco-agent",))
    try:
        assert TOOL.assess(tmp_path) == (ToolStatus.USABLE, (3, 0, 23), "")
    finally:
        TOOL.configure(())

    command = run.call_args_list[1].args[0]
    assert command[:3] == ["rehuco-agent", LIBVLC_PROBE_FLAG, str(library)]
    assert command[3] == "--output"


@mark.parametrize(
    ("answer", "said"),
    [
        param(
            {"status": "not runnable", "version": [], "reason": "it exited with 1", "library": ""},
            "exited",
            id="failed",
        ),
        param(
            {"status": "usable", "version": [3, 0, 23], "reason": "", "library": "/elsewhere/libvlc.dll"},
            "instead of",
            id="other library",
        ),
        param(None, "Loading libvlc failed", id="no answer"),
    ],
)
def test_what_the_child_cannot_load_is_not_runnable(
    mocker: MockerFixture, tmp_path: Path, answer: dict[str, object] | None, said: str
) -> None:
    """**Test steps:**

    * have the child fail, bind another library, or write nothing
    * verify *not runnable* with the reason, the version ``vlc`` printed kept
    """
    mocker.patch.object(sys, "platform", "win32")
    lay_out(tmp_path, "vlc.exe", "libvlc.dll", "libvlccore.dll", "plugins/")
    child_answering(mocker, answer)
    TOOL.configure(("rehuco-agent",))
    try:
        status, version, reason = TOOL.assess(tmp_path)
    finally:
        TOOL.configure(())

    assert (status, version) == (ToolStatus.NOT_RUNNABLE, (3, 0, 23))
    assert said in reason


# endregion


def test_a_whole_install_whose_vlc_does_not_run_is_not_runnable(mocker: MockerFixture, tmp_path: Path) -> None:
    """**Test steps:**

    * lay out a whole install and have ``vlc --version`` fail to start
    * verify *not runnable*, with the reason
    """
    mocker.patch.object(sys, "platform", "win32")
    lay_out(tmp_path, "vlc.exe", "libvlc.dll", "libvlccore.dll", "plugins/")
    mocker.patch(RUNNER, side_effect=OSError("not executable"))

    status, version, reason = TOOL.assess(tmp_path)

    assert (status, version) == (ToolStatus.NOT_RUNNABLE, None)
    assert reason
