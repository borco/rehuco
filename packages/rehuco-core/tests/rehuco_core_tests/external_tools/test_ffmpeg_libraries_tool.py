"""Tests for the FFmpeg libraries descriptor: what makes a folder a build, and how one is judged (#580)."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

from pytest import fixture, mark, param, raises
from pytest_mock import MockerFixture
from rehuco_core import (
    EXTERNAL_TOOLS,
    PROBE_FLAG,
    FfmpegLibrariesTool,
    ToolCandidate,
    ToolLocator,
    ToolNotRunnableError,
    ToolStatus,
)

from .test_ffmpeg_libraries import QT_611, QT_612, make_files

MODULE: Final = "rehuco_core.external_tools.ffmpeg_libraries_tool"
RUNNER: Final = f"{MODULE}.subprocess.run"

PROGRAM: Final = ("/opt/rehuco/rehuco-agent",)
"""What runs the app, as the agent would say."""


@fixture(name="tool")
def fixture_tool(tmp_path: Path) -> FfmpegLibrariesTool:
    """A descriptor configured over a PySide6 folder holding the 6.11 libraries.

    :param tmp_path: the test's folder.
    :returns: the descriptor.
    """
    tool = FfmpegLibrariesTool()
    tool.configure(make_files(tmp_path / "qt", QT_611), PROGRAM)
    return tool


def child_answering(mocker: MockerFixture, status: str, version: list[int] | None = None, reason: str = "") -> Any:
    """Make the child process write an answer.

    :param mocker: the pytest-mock fixture.
    :param status: the status it reports.
    :param version: the version it reports.
    :param reason: the reason it reports.
    :returns: the mocked ``subprocess.run``.
    """

    def run(command: list[str], **_: object) -> None:
        Path(command[-1]).write_text(
            json.dumps({"status": status, "version": version or [], "reason": reason}), encoding="utf-8"
        )

    return mocker.patch(RUNNER, side_effect=run)


def test_the_tool_is_registered_only_where_it_was_measured() -> None:
    """**Test steps:**

    * look the tool up in the registry
    * verify it is there exactly on Windows
    """
    assert (FfmpegLibrariesTool.ID in EXTERNAL_TOOLS) == (sys.platform == "win32")


def test_the_places_it_is_searched_for_are_windows_only(mocker: MockerFixture) -> None:
    """**Test steps:**

    * ask for the search places on each kind of platform
    * verify none off Windows, and the shared FFmpeg packages' places on it
    """
    tool = FfmpegLibrariesTool()
    mocker.patch(f"{MODULE}.sys", SimpleNamespace(platform="linux"))
    assert not tool.search_patterns()

    mocker.patch(f"{MODULE}.sys", SimpleNamespace(platform="win32"))
    sources = {source for source, _ in tool.search_patterns()}
    assert {"winget", "scoop", "chocolatey", "Program Files"} <= sources


def test_a_folder_holding_any_part_of_a_build_is_one(tmp_path: Path, tool: FfmpegLibrariesTool) -> None:
    """A static build and another major are listed rather than missed, so the Tools page can say why they are unusable.

    **Test steps:**

    * resolve an unpacked archive's root, its ``bin``, a file in it and an empty folder
    * verify the folder holding the files, and none for the empty one
    """
    root = tmp_path / "ffmpeg-n7.1"
    bin_folder = make_files(root / "bin", (*QT_612, "ffmpeg.exe"))

    assert tool.resolve_folder(root) == bin_folder
    assert tool.resolve_folder(bin_folder) == bin_folder
    assert tool.resolve_folder(bin_folder / "avcodec-63.dll") == bin_folder
    assert tool.resolve_folder(make_files(tmp_path / "empty", ("readme.txt",))) is None


def test_the_files_of_a_build_are_what_is_there(tmp_path: Path, tool: FfmpegLibrariesTool) -> None:
    """The locator keys its cache on these files' modification times, so an update is seen.

    **Test steps:**

    * list the files of a folder with libraries and a program
    * verify they are listed, and only those that exist
    """
    build = make_files(tmp_path / "build", ("avcodec-61.dll", "ffmpeg.exe", "notes.txt"))

    assert tool.executable_files(build) == [build / "avcodec-61.dll", build / "ffmpeg.exe"]


@mark.parametrize(
    ("present", "status"),
    [
        param(("ffmpeg.exe",), ToolStatus.NO_LIBRARIES, id="static"),
        param(QT_612, ToolStatus.WRONG_MAJOR, id="another-major"),
        param(QT_611[:2], ToolStatus.INCOMPLETE, id="incomplete"),
    ],
)
def test_a_build_that_cannot_stand_in_is_judged_without_loading_anything(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool, present: tuple[str, ...], status: ToolStatus
) -> None:
    """The file names decide before any process is started.

    **Test steps:**

    * assess a static build, one of another major and one missing libraries
    * verify each status with a reason, the version unread and no child started
    """
    run = mocker.patch(RUNNER)

    judged, version, reason = tool.assess(make_files(tmp_path / "build", present))

    assert (judged, version) == (status, None)
    assert reason
    run.assert_not_called()


def test_a_build_of_the_right_major_is_tried_in_a_child(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool
) -> None:
    """The agent loads nothing of a build it has not chosen: its own program loads it, and says what happened.

    **Test steps:**

    * assess a build of the right major with a child that reports it usable
    * verify the status, the version, and the command: this program, the flag, the folder and an output file
    """
    run = child_answering(mocker, "usable", [7, 1, 5])
    build = make_files(tmp_path / "build", QT_611)

    assert tool.assess(build) == (ToolStatus.USABLE, (7, 1, 5), "")

    (command,), options = run.call_args
    assert command[: len(PROGRAM) + 2] == [*PROGRAM, PROBE_FLAG, str(build)]
    assert command[-2] == "--output"
    assert options["timeout"] > 0


def test_what_the_child_reports_is_what_the_build_is(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool
) -> None:
    """**Test steps:**

    * assess a build whose child reports the wrong architecture
    * verify the status and the reason come through
    """
    child_answering(mocker, "wrong architecture", reason="avutil-59.dll is built for another processor.")

    status, version, reason = tool.assess(make_files(tmp_path / "build", QT_611))

    assert (status, version) == (ToolStatus.WRONG_ARCHITECTURE, None)
    assert reason == "avutil-59.dll is built for another processor."


@mark.parametrize(
    "failure",
    [
        param(lambda command, **_: None, id="writes-nothing"),
        param(subprocess.TimeoutExpired("agent", 30), id="times-out"),
        param(OSError("cannot start"), id="cannot-start"),
    ],
)
def test_a_child_that_gives_no_answer_makes_the_build_not_runnable(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool, failure: Callable[..., None] | BaseException
) -> None:
    """A build that crashes the process it loads into is a build that cannot be used, and only the child is lost.

    **Test steps:**

    * assess a build whose child writes nothing, hangs, or does not start
    * verify it is not runnable, with the reason saying loading failed
    """
    mocker.patch(RUNNER, side_effect=failure)

    status, version, reason = tool.assess(make_files(tmp_path / "build", QT_611))

    assert (status, version) == (ToolStatus.NOT_RUNNABLE, None)
    assert reason.startswith("Loading its libraries failed")


def test_a_tool_not_configured_in_this_process_is_not_runnable(tmp_path: Path) -> None:
    """The host process says where Qt's libraries are and how to run the child; a node, say, cannot.

    **Test steps:**

    * assess a build with a descriptor never configured
    * verify it is not runnable
    """
    status, _, reason = FfmpegLibrariesTool().assess(make_files(tmp_path / "build", QT_611))

    assert status is ToolStatus.NOT_RUNNABLE
    assert reason == "Not available in this process."


def test_the_version_is_read_through_the_same_judgement(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool
) -> None:
    """**Test steps:**

    * read the version of a usable build and of a static one
    * verify the numbers, and a refusal carrying the reason for the static build
    """
    child_answering(mocker, "usable", [7, 1, 5])
    assert tool.read_version(make_files(tmp_path / "build", QT_611)) == (7, 1, 5)

    with raises(ToolNotRunnableError) as caught:
        tool.read_version(make_files(tmp_path / "static", ("ffmpeg.exe",)))
    assert "static" in caught.value.reason


def test_the_locator_lists_a_static_build_as_unusable(tmp_path: Path, tool: FfmpegLibrariesTool) -> None:
    """The descriptor plugs into the locator like any tool: found, listed, and judged with its reason.

    **Test steps:**

    * inspect a static build through the locator
    * verify it is found, not usable, and says why
    """
    candidate = ToolLocator().inspect(tool, make_files(tmp_path / "build", ("ffmpeg.exe",)))

    assert candidate.status is ToolStatus.NO_LIBRARIES
    assert not candidate.is_usable
    assert "static" in candidate.reason


def test_a_path_holding_no_build_is_missing(tmp_path: Path, tool: FfmpegLibrariesTool) -> None:
    """**Test steps:**

    * inspect an empty folder through the locator
    * verify it is missing
    """
    assert ToolLocator().inspect(tool, make_files(tmp_path / "empty", ("x.txt",))).status is ToolStatus.MISSING


def test_qts_own_folder_is_never_listed_as_a_build(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool
) -> None:
    """PySide6's folder is on ``PATH`` in a development environment, and its libraries are what a build replaces.

    **Test steps:**

    * put Qt's folder and another on ``PATH``
    * verify only the other is searched
    """
    qt_folder, other = tmp_path / "qt", tmp_path / "other"
    mocker.patch.dict("os.environ", {"PATH": f"{qt_folder}{os.pathsep}{other}"})
    mocker.patch.object(tool, "search_patterns", return_value=())

    assert tool.search_folders() == [("PATH", other)]


# region a later start (#580)


def test_a_stored_usable_build_is_re_judged_against_this_qt_at_a_later_start(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool
) -> None:
    """It is the app's Qt that changes major, not the build: a build found usable under one PySide6 is of the wrong
    major under the next, and a later start must say so without a search.

    **Test steps:**

    * verify a build stored as usable whose folder now holds the other major than Qt's
    * verify it comes back as the wrong major with the reason, no child started
    * verify a build stored as usable whose names still match comes back as it was, no child started
    """
    run = mocker.patch(RUNNER)
    other = ToolCandidate(make_files(tmp_path / "other", QT_612), "PATH", ToolStatus.USABLE, (9, 0))
    same = ToolCandidate(make_files(tmp_path / "same", QT_611), "PATH", ToolStatus.USABLE, (7, 1, 5))

    kept = ToolLocator().verify(tool, [other, same])

    assert [(candidate.folder, candidate.status, candidate.version) for candidate in kept] == [
        (other.folder, ToolStatus.WRONG_MAJOR, None),
        (same.folder, ToolStatus.USABLE, (7, 1, 5)),
    ]
    assert "avcodec-61.dll" in kept[0].reason
    run.assert_not_called()


def test_a_stored_wrong_major_build_whose_names_match_now_is_tried_again(
    mocker: MockerFixture, tmp_path: Path, tool: FfmpegLibrariesTool
) -> None:
    """**Test steps:**

    * verify a build stored as the wrong major whose names match this Qt
    * verify the child was asked and its verdict is what comes back
    """
    child_answering(mocker, "usable", [7, 1, 5])
    stored = ToolCandidate(make_files(tmp_path / "build", QT_611), "PATH", ToolStatus.WRONG_MAJOR, None, "was wrong")

    (kept,) = ToolLocator().verify(tool, [stored])

    assert (kept.status, kept.version, kept.reason) == (ToolStatus.USABLE, (7, 1, 5), "")


def test_a_stored_build_whose_folder_is_gone_is_dropped(tmp_path: Path, tool: FfmpegLibrariesTool) -> None:
    """**Test steps:**

    * verify a build whose folder holds nothing of a build any more, and one still the wrong major as stored
    * verify the first is dropped and the second kept as it was
    """
    gone = ToolCandidate(make_files(tmp_path / "gone", ("x.txt",)), "PATH", ToolStatus.USABLE, (7, 1, 5))
    still = ToolCandidate(make_files(tmp_path / "still", QT_612), "PATH", ToolStatus.WRONG_MAJOR, None, "wrong")

    assert ToolLocator().verify(tool, [gone, still]) == [still]


def test_an_unconfigured_tool_verifies_by_the_folder_alone(tmp_path: Path) -> None:
    """**Test steps:**

    * verify a stored build with a descriptor never configured
    * verify it is kept as it was
    """
    stored = ToolCandidate(make_files(tmp_path / "build", QT_612), "PATH", ToolStatus.USABLE, (9, 0))

    assert ToolLocator().verify(FfmpegLibrariesTool(), [stored]) == [stored]


# endregion
