"""Tests for ToolDiscovery: the one background search for the external tools, and what it records (#521)."""

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import call

from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.tool_discovery import ToolDiscovery, shared_tool_discovery
from rehuco_agent.settings.tools_settings import ToolDetection, ToolsSettings
from rehuco_core import EXTERNAL_TOOLS, FFMPEG_TOOL, VLC_TOOL, ToolCandidate, ToolStatus
from shiboken6 import delete

INSTALL = ToolCandidate(Path("/opt/ffmpeg/bin"), "winget", ToolStatus.USABLE, (7, 1, 1))
OTHER = ToolCandidate(Path("/other/bin"), "PATH", ToolStatus.USABLE, (6, 0))


@fixture(name="tools")
def fixture_tools() -> ToolsSettings:
    """A settings object of its own, so a test records into nothing shared."""
    return ToolsSettings()


@fixture(name="discovery")
def fixture_discovery(tools: ToolsSettings, fake_tool_locator: Any) -> Iterator[ToolDiscovery]:
    """A discovery over the mock locator, stopped when the test is done.

    :param tools: where it records.
    :param fake_tool_locator: the mock locator.
    """
    discovery = ToolDiscovery(tools, fake_tool_locator)
    yield discovery
    discovery.stop()


def run(qtbot: QtBot, discovery: ToolDiscovery, force: tuple[str, ...] = ()) -> None:
    """Start a run and wait until its tool has been recorded.

    :param qtbot: the pytest-qt fixture.
    :param discovery: what to run.
    :param force: the tools to search for whatever is stored.
    """
    with qtbot.waitSignal(discovery.tool_done, timeout=5000) as done:
        discovery.start(force)
    assert done.args == [FFMPEG_TOOL.ID]


def test_a_tool_never_searched_for_is_searched_for_and_recorded(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """The first start finds what is installed and records it, in memory.

    **Test steps:**

    * make the locator find an install and run
    * verify the install was recorded as searched for, every tool was searched for, and nothing was only verified
    """
    fake_tool_locator.detect.return_value = [INSTALL, OTHER]

    run(qtbot, discovery)

    assert tools.detection(FFMPEG_TOOL.ID) == ToolDetection(True, (INSTALL, OTHER))
    assert fake_tool_locator.detect.call_args_list == [call(tool) for tool in EXTERNAL_TOOLS.values()]
    fake_tool_locator.verify.assert_not_called()


def test_a_tool_already_searched_for_is_only_verified(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """A later start checks that what was found is still there and searches for nothing.

    **Test steps:**

    * store two installs for FFmpeg and a search for VLC, make verifying keep one, and run
    * verify what is recorded is the one that is still there, and nothing was searched for
    """
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (INSTALL, OTHER)))
    tools.set_detection(VLC_TOOL.ID, ToolDetection(True, ()))
    fake_tool_locator.verify.return_value = [OTHER]

    run(qtbot, discovery)

    assert tools.detection(FFMPEG_TOOL.ID) == ToolDetection(True, (OTHER,))
    fake_tool_locator.verify.assert_any_call(FFMPEG_TOOL, (INSTALL, OTHER))
    fake_tool_locator.detect.assert_not_called()


def test_a_tool_searched_for_and_not_found_is_not_searched_for_again(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """Finding nothing is an answer: it is only asked again when the user presses Detect.

    **Test steps:**

    * store a search that found nothing for each tool and run
    * verify no search ran
    """
    for tool_id in EXTERNAL_TOOLS:
        tools.set_detection(tool_id, ToolDetection(True, ()))
    fake_tool_locator.verify.return_value = []

    run(qtbot, discovery)

    fake_tool_locator.detect.assert_not_called()


def test_a_forced_tool_is_searched_for_again_whatever_is_stored(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """Detect forces the search, and what it finds replaces what was stored.

    **Test steps:**

    * store an install, make a search find another, and run forced for FFmpeg
    * verify the search ran and replaced the stored list
    """
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (INSTALL,)))
    fake_tool_locator.detect.return_value = [OTHER]

    run(qtbot, discovery, (FFMPEG_TOOL.ID,))

    assert tools.detection(FFMPEG_TOOL.ID) == ToolDetection(True, (OTHER,))


def test_a_search_that_fails_leaves_the_tool_as_it_was_and_is_reported_done(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """A search that raises costs only its tool, which is tried again at the next start.

    **Test steps:**

    * make the search raise and run
    * verify the tool is still not searched for, and the run reported it done
    """
    fake_tool_locator.detect.side_effect = RuntimeError("boom")

    run(qtbot, discovery)

    assert tools.detection(FFMPEG_TOOL.ID) == ToolDetection(False, ())


def test_nothing_is_written_to_disk_by_a_search(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any, mocker: Any
) -> None:
    """The settings are written when the app writes them, not when a tool is found.

    **Test steps:**

    * spy on the settings' ``save`` and run a search that finds an install
    * verify it was never called
    """
    save = mocker.spy(tools, "save")
    fake_tool_locator.detect.return_value = [INSTALL]

    run(qtbot, discovery)

    save.assert_not_called()


def test_what_a_stopped_run_still_reports_is_ignored(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """Closing the app stops the run; a result already on its way must not be recorded after.

    **Test steps:**

    * make the search wait, start a run and stop it, then let the search finish
    * verify the late report arrived and recorded nothing
    """
    release = threading.Event()

    def wait_then_find(_tool: object) -> list[ToolCandidate]:
        assert release.wait(5)
        return [INSTALL]

    fake_tool_locator.detect.side_effect = wait_then_find
    done: list[str] = []
    discovery.tool_done.connect(done.append)

    discovery.start()
    discovery.stop()
    with qtbot.waitSignal(discovery.reported, timeout=5000):
        release.set()

    assert tools.detection(FFMPEG_TOOL.ID) == ToolDetection(False, ())
    assert not done


def test_a_run_already_stopped_visits_no_tool(
    tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """A run outdated before it reaches a tool does not search for it.

    **Test steps:**

    * run the thread's work directly with its stop event already set
    * verify nothing was searched for or verified, and nothing was recorded
    """
    stop = threading.Event()
    stop.set()
    plan = [(FFMPEG_TOOL, ToolDetection(), False)]

    discovery._ToolDiscovery__run(1, stop, plan)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    fake_tool_locator.detect.assert_not_called()
    assert tools.detection(FFMPEG_TOOL.ID) == ToolDetection()


def test_a_report_to_a_discovery_that_was_deleted_is_dropped(tools: ToolsSettings, fake_tool_locator: Any) -> None:
    """The window may be gone while the thread is still searching; its answer has nowhere to go and is not an error.

    **Test steps:**

    * delete the discovery, then run the thread's work directly
    * verify the search ran and reporting it raised nothing
    """
    fake_tool_locator.detect.return_value = [INSTALL]
    deleted = ToolDiscovery(tools, fake_tool_locator)
    plan = [(FFMPEG_TOOL, ToolDetection(), False)]
    delete(deleted)

    deleted._ToolDiscovery__run(1, threading.Event(), plan)  # type: ignore[attr-defined]  # pylint: disable=protected-access

    fake_tool_locator.detect.assert_called_once_with(FFMPEG_TOOL)


def test_the_shared_discovery_is_one_object_over_the_shared_settings() -> None:
    """The start-up search and the Tools page's Detect are the same run.

    **Test steps:**

    * ask for the shared discovery twice
    * verify it is the same object
    """
    assert shared_tool_discovery() is shared_tool_discovery()
