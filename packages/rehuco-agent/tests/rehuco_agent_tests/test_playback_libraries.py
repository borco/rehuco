"""Tests for the external FFmpeg libraries a run loads before Qt Multimedia is imported (#580)."""

import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final
from unittest.mock import Mock

from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from rehuco_agent import playback_libraries
from rehuco_agent.playback_libraries import PlaybackLibraries, shared_playback_libraries
from rehuco_agent.settings.tools_settings import shared_tools_settings
from rehuco_agent.settings.videos_settings import FFMPEG_LIBRARIES_PLAYER, IN_APP_PLAYER, shared_videos_settings
from rehuco_core import FFMPEG_LIBRARIES_TOOL, LibrariesUnusableError, ToolCandidate, ToolStatus

QT_NAMES: Final = ("avcodec-61.dll", "avformat-61.dll", "avutil-59.dll", "swresample-5.dll", "swscale-8.dll")
"""The libraries the PySide6 under test bundles."""

LOAD_ORDER: Final = ("avutil-59.dll", "swresample-5.dll", "swscale-8.dll", "avcodec-61.dll", "avformat-61.dll")
"""``QT_NAMES`` in the order they are loaded."""


def make_files(folder: Path, names: tuple[str, ...]) -> Path:
    """Put empty files in a folder.

    :param folder: the folder, created when absent.
    :param names: the file names.
    :returns: the folder.
    """
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"")
    return folder


@fixture(name="libraries")
def fixture_libraries(mocker: MockerFixture, tmp_path: Path) -> Iterator[PlaybackLibraries]:
    """A fresh record over a PySide6 folder of the 6.11 libraries, with nothing really loaded.

    :param mocker: the pytest-mock fixture.
    :param tmp_path: the test's folder.
    :returns: the record.
    """
    shared_playback_libraries.cache_clear()
    qt_folder = make_files(tmp_path / "PySide6", QT_NAMES)
    mocker.patch.object(playback_libraries, "PySide6", SimpleNamespace(__file__=str(qt_folder / "__init__.py")))
    mocker.patch.object(playback_libraries, "own_program", return_value=["/opt/rehuco-agent"])
    mocker.patch.object(playback_libraries, "EXTERNAL_TOOLS", {FFMPEG_LIBRARIES_TOOL.ID: FFMPEG_LIBRARIES_TOOL})
    yield shared_playback_libraries()
    shared_playback_libraries.cache_clear()


@fixture(name="configure", autouse=True)
def fixture_configure(mocker: MockerFixture) -> Mock:
    """The descriptor's set-up, mocked so the shared descriptor keeps no state between tests.

    :param mocker: the pytest-mock fixture.
    :returns: the mock.
    """
    return mocker.patch.object(FFMPEG_LIBRARIES_TOOL, "configure")


@fixture(name="load")
def fixture_load(mocker: MockerFixture) -> Mock:
    """The loader, mocked so no library is really loaded.

    :param mocker: the pytest-mock fixture.
    :returns: the mock.
    """
    return mocker.patch.object(playback_libraries, "load_libraries")


def choose(player: str, build: Path | None = None) -> None:
    """Set the Videos page's player and the Tools page's FFmpeg libraries path.

    :param player: the player chosen.
    :param build: the folder of the build, or ``None`` for none set up.
    """
    shared_videos_settings().player = player
    shared_tools_settings().set_path(FFMPEG_LIBRARIES_TOOL.ID, "" if build is None else str(build))


def resolved(fake_tool_locator: Any, candidate: ToolCandidate | None) -> None:
    """Make the locator resolve the FFmpeg libraries to ``candidate``.

    :param fake_tool_locator: the mock locator.
    :param candidate: what the Tools page's set-up resolves to; ``None`` for nothing.
    """
    fake_tool_locator.resolve.return_value = candidate


def test_the_tool_is_told_where_qt_is_and_how_to_run_the_child_whatever_is_chosen(
    libraries: PlaybackLibraries, load: Mock, configure: Mock
) -> None:
    """The Tools page judges builds in this process too, so the descriptor is set up even when nothing is chosen.

    **Test steps:**

    * start with the app's player chosen
    * verify the descriptor was configured with Qt's folder and this program, and nothing was loaded or requested
    """
    choose(IN_APP_PLAYER)

    libraries.load_at_start()

    configure.assert_called_once()
    qt_folder, program = configure.call_args.args
    assert (qt_folder.name, program) == ("PySide6", ("/opt/rehuco-agent",))
    load.assert_not_called()
    assert (libraries.requested, libraries.loaded_from, libraries.fallback_reason) == (False, None, None)


def test_the_build_the_tools_page_resolves_to_is_loaded_by_full_path_in_order(
    libraries: PlaybackLibraries, load: Mock, tmp_path: Path, fake_tool_locator: Any
) -> None:
    """The agent loads only a build that was seen to load: the locator's verdict -- the discovery's for an install, the
    child's for a typed path -- is asked for, with the path and the detection the Tools page holds.

    **Test steps:**

    * choose the libraries with a path set, and have the locator resolve it to a usable build
    * start
    * verify the locator was asked with that path and the detection, the five files were loaded in order, and the
      record says where from
    """
    build = make_files(tmp_path / "build", QT_NAMES)
    choose(FFMPEG_LIBRARIES_PLAYER, build)
    resolved(fake_tool_locator, ToolCandidate(build, "Custom", ToolStatus.USABLE, (7, 1, 5)))

    libraries.load_at_start()

    fake_tool_locator.resolve.assert_called_once_with(FFMPEG_LIBRARIES_TOOL, str(build), ())
    load.assert_called_once_with([build / name for name in LOAD_ORDER])
    assert (libraries.requested, libraries.loaded_from, libraries.fallback_reason) == (True, build, None)


def test_an_untested_build_is_loaded_too(
    libraries: PlaybackLibraries, load: Mock, tmp_path: Path, fake_tool_locator: Any
) -> None:
    """**Test steps:**

    * resolve to a build the child loaded but could not read a version of
    * start
    * verify it is loaded
    """
    build = make_files(tmp_path / "build", QT_NAMES)
    choose(FFMPEG_LIBRARIES_PLAYER)
    resolved(fake_tool_locator, ToolCandidate(build, "PATH", ToolStatus.UNTESTED, None, "untested"))

    libraries.load_at_start()

    assert libraries.loaded_from == build
    load.assert_called_once()


def test_nothing_set_up_falls_back_and_says_so(
    libraries: PlaybackLibraries, load: Mock, fake_tool_locator: Any
) -> None:
    """**Test steps:**

    * choose the libraries with nothing resolving on the Tools page
    * start
    * verify Qt's own are used, with the reason pointing at the Tools page
    """
    choose(FFMPEG_LIBRARIES_PLAYER)
    resolved(fake_tool_locator, None)

    libraries.load_at_start()

    load.assert_not_called()
    assert libraries.requested is True
    assert libraries.loaded_from is None
    assert "Tools" in (libraries.fallback_reason or "")


def test_a_build_judged_unusable_is_not_loaded_and_its_reason_is_kept(
    libraries: PlaybackLibraries, load: Mock, tmp_path: Path, fake_tool_locator: Any
) -> None:
    """A build the child could not load, or a stored install that is gone, never reaches the agent's own process.

    **Test steps:**

    * resolve to a build judged not runnable, with its reason
    * start
    * verify nothing was loaded and the reason names the folder and what the judgment said
    """
    build = make_files(tmp_path / "build", QT_NAMES)
    choose(FFMPEG_LIBRARIES_PLAYER, build)
    resolved(fake_tool_locator, ToolCandidate(build, "Custom", ToolStatus.NOT_RUNNABLE, None, "avutil-59.dll crashed."))

    libraries.load_at_start()

    load.assert_not_called()
    assert libraries.loaded_from is None
    assert libraries.fallback_reason == f"{build}: avutil-59.dll crashed."


def test_a_build_judged_usable_under_another_qt_falls_back_with_its_reason(
    libraries: PlaybackLibraries, load: Mock, tmp_path: Path, fake_tool_locator: Any
) -> None:
    """**Test steps:**

    * resolve to a usable build whose folder now holds the other major
    * start
    * verify nothing was loaded and the reason names the folder and the files
    """
    build = make_files(tmp_path / "build", ("avcodec-63.dll", "avutil-61.dll"))
    choose(FFMPEG_LIBRARIES_PLAYER, build)
    resolved(fake_tool_locator, ToolCandidate(build, "Custom", ToolStatus.USABLE, (9, 0)))

    libraries.load_at_start()

    load.assert_not_called()
    assert libraries.loaded_from is None
    assert str(build) in (libraries.fallback_reason or "")
    assert "avcodec-63.dll" in (libraries.fallback_reason or "")


def test_a_build_that_fails_to_load_falls_back_with_its_reason(
    libraries: PlaybackLibraries, load: Mock, tmp_path: Path, fake_tool_locator: Any
) -> None:
    """**Test steps:**

    * resolve to a usable build whose loading fails now
    * start
    * verify Qt's own are used, with the failure as the reason
    """
    build = make_files(tmp_path / "build", QT_NAMES)
    choose(FFMPEG_LIBRARIES_PLAYER, build)
    resolved(fake_tool_locator, ToolCandidate(build, "Custom", ToolStatus.USABLE, (7, 1, 5)))
    load.side_effect = LibrariesUnusableError(ToolStatus.WRONG_ARCHITECTURE, "built for another processor")

    libraries.load_at_start()

    assert libraries.loaded_from is None
    assert "built for another processor" in (libraries.fallback_reason or "")


def test_an_unexpected_error_at_start_falls_back_rather_than_crashing(
    libraries: PlaybackLibraries, load: Mock, fake_tool_locator: Any
) -> None:
    """Start-up runs before the log and before ``main``'s own handler, so a crash here would leave no trace.

    **Test steps:**

    * make resolving raise
    * start
    * verify nothing escaped, nothing was loaded and the reason carries the error
    """
    choose(FFMPEG_LIBRARIES_PLAYER)
    fake_tool_locator.resolve.side_effect = RuntimeError("boom")

    libraries.load_at_start()

    load.assert_not_called()
    assert libraries.loaded_from is None
    assert "boom" in (libraries.fallback_reason or "")


def test_a_build_without_the_tool_does_nothing(mocker: MockerFixture, load: Mock, configure: Mock) -> None:
    """Off Windows the tool is not in the registry, and the start-up has nothing to do.

    **Test steps:**

    * make the registry lack the tool, and choose the libraries anyway
    * start
    * verify nothing was configured or loaded
    """
    shared_playback_libraries.cache_clear()
    mocker.patch.object(playback_libraries, "EXTERNAL_TOOLS", {})
    choose(FFMPEG_LIBRARIES_PLAYER)
    libraries = shared_playback_libraries()

    libraries.load_at_start()

    configure.assert_not_called()
    load.assert_not_called()
    assert libraries.requested is False
    shared_playback_libraries.cache_clear()


def test_the_record_is_one_per_process(libraries: PlaybackLibraries) -> None:
    """**Test steps:**

    * ask for the shared record twice
    * verify it is the same object
    """
    assert shared_playback_libraries() is libraries


def test_the_outcome_is_logged_once_the_log_is_running(
    libraries: PlaybackLibraries, load: Mock, tmp_path: Path, caplog: LogCaptureFixture, fake_tool_locator: Any
) -> None:
    """Start-up runs before the log does, so the outcome is written afterwards.

    **Test steps:**

    * log a start that loaded a build, one that fell back, and one that did not ask
    * verify an info line, a warning with the reason, and nothing
    """
    del load
    caplog.set_level(logging.INFO)
    build = make_files(tmp_path / "build", QT_NAMES)
    choose(FFMPEG_LIBRARIES_PLAYER, build)
    resolved(fake_tool_locator, ToolCandidate(build, "Custom", ToolStatus.USABLE, (7, 1, 5)))
    libraries.load_at_start()
    libraries.log_outcome()
    assert [(record.levelno, str(build) in record.getMessage()) for record in caplog.records] == [(logging.INFO, True)]

    caplog.clear()
    fallen = PlaybackLibraries()
    choose(FFMPEG_LIBRARIES_PLAYER)
    resolved(fake_tool_locator, None)
    fallen.load_at_start()
    fallen.log_outcome()
    assert [record.levelno for record in caplog.records] == [logging.WARNING]
    assert "Tools" in caplog.records[0].getMessage()

    caplog.clear()
    PlaybackLibraries().log_outcome()
    assert caplog.records == []
