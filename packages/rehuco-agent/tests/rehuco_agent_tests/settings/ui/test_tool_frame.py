"""Tests for ToolFrame: one tool's block on the Tools page (#521)."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pytest import fixture
from pytestqt.qtbot import QtBot
from rehuco_agent.settings.tool_discovery import ToolDiscovery
from rehuco_agent.settings.tools_settings import ToolDetection, ToolsSettings
from rehuco_agent.settings.ui.tool_frame import NOT_FOUND_STATUS, ToolFrame
from rehuco_agent.settings.ui.tool_path_control import LOOKING_TEXT, NOT_FOUND_TEXT, WARNING_PROPERTY
from rehuco_core import EXTERNAL_TOOLS, FFMPEG_TOOL, ToolCandidate, ToolStatus

USABLE = ToolCandidate(Path("/opt/ffmpeg/bin"), "PATH", ToolStatus.USABLE, (7, 1, 1))
TOO_OLD = ToolCandidate(Path("/old"), "Custom", ToolStatus.TOO_OLD, (3, 0), "Version 4.0 or newer is needed.")


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


def frame_ui(frame: ToolFrame) -> Any:
    """The block's generated UI object, for reaching its widgets.

    :param frame: the block to reach into.
    :returns: the ``Ui_ToolFrame`` instance.
    """
    return frame._ToolFrame__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def control_ui(frame: ToolFrame) -> Any:
    """The generated UI object of the block's path control, for reaching its widgets.

    :param frame: the block to reach into.
    :returns: the ``Ui_ToolPathControl`` instance.
    """
    return frame.control._ToolPathControl__ui  # type: ignore[attr-defined]  # pylint: disable=protected-access


def make_frame(qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, locator: Any) -> ToolFrame:
    """Build a block for FFmpeg over the test's settings and discovery, and keep its frame alive for the test.

    :param qtbot: the pytest-qt fixture.
    :param tools: where its detection is read.
    :param discovery: what searches.
    :param locator: what judges a typed path.
    :returns: the block.
    """
    frame = ToolFrame(FFMPEG_TOOL, tools, discovery, locator)
    qtbot.addWidget(frame.frame)
    return frame


def test_the_block_is_named_after_its_tool_and_links_to_its_install_instructions(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """The header label is found by name, so the dialog can build the Apply, Reset and Defaults row around it.

    **Test steps:**

    * build the block for FFmpeg
    * verify the frame and label names, the title, the purpose line, the rest in its tooltip and the link to its docs
      section
    """
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)
    ui = frame_ui(frame)

    assert frame.frame.objectName() == "ffmpeg_frame"
    assert ui.tool_frame_label.objectName() == "ffmpeg_frame_label"
    assert ui.tool_frame_label.text() == "FFmpeg"
    assert ui.description_label.text() == FFMPEG_TOOL.PURPOSE
    assert FFMPEG_TOOL.FEATURES in ui.description_label.toolTip()
    assert FFMPEG_TOOL.NOT_BUNDLED_BECAUSE in ui.description_label.toolTip()
    assert "external-tools/#ffmpeg" in ui.install_label.text()


def test_a_tool_never_searched_for_shows_that_it_is_being_looked_for(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """Until the discovery has answered, nothing is known: the list says so, and the value is still the best one's.

    **Test steps:**

    * build the block over a tool never searched for
    * verify the list and status say it is looking, no row is listed, and the value is empty
    """
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    assert control_ui(frame).looking_label.isHidden() is False
    assert frame_ui(frame).status_label.text() == LOOKING_TEXT
    assert not frame.control.rows
    assert frame.control.settings_value() == ""
    fake_tool_locator.detect.assert_not_called()


def test_a_tool_found_earlier_is_shown_at_once_without_searching(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """What the last run stored is listed at once, so the page never waits for a search.

    **Test steps:**

    * store a search that found two installs, one unusable, and build the block
    * verify both are listed, the usable one chosen, no line repeats its row, and nothing was searched for
    """
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (TOO_OLD, USABLE)))

    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    assert frame.control.candidates == (TOO_OLD, USABLE)
    assert frame.control.chosen_candidate() == USABLE
    assert frame_ui(frame).status_label.isHidden()
    assert frame.control.settings_value() == ""
    fake_tool_locator.detect.assert_not_called()


def test_a_search_that_found_nothing_usable_leaves_only_custom(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """An install that is listed but unusable is never chosen.

    **Test steps:**

    * store a search that found only an install that is too old, and build the block
    * verify its row is greyed, Custom is chosen, and the status says nothing usable was found
    """
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (TOO_OLD,)))

    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    assert frame.control.rows[0].isEnabled() is False
    assert frame.control.chosen_candidate() is None
    assert frame_ui(frame).status_label.text() == NOT_FOUND_STATUS


def test_the_block_follows_the_discovery_when_it_records_the_tool(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """The start-up search finishing is shown without the user doing anything.

    **Test steps:**

    * build the block over a tool never searched for, then run the discovery over a locator finding an install
    * verify the block now lists and chooses it
    """
    fake_tool_locator.detect.return_value = [USABLE]
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    with qtbot.waitSignal(frame.answered, timeout=5000):
        discovery.start()

    assert frame.control.chosen_candidate() == USABLE
    assert frame_ui(frame).status_label.isHidden()


def test_the_detect_button_forces_a_search_and_shows_the_result(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """Detect is how a tool installed while the app runs is found.

    **Test steps:**

    * store a search that found nothing for each tool, make the locator find an install now, and click Detect
    * verify the block says it is looking, then names the install, and the search ran although one was stored
    """
    for tool_id in EXTERNAL_TOOLS:
        tools.set_detection(tool_id, ToolDetection(True, ()))
    fake_tool_locator.verify.return_value = []
    fake_tool_locator.detect.return_value = [USABLE]
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    with qtbot.waitSignal(frame.answered, timeout=5000):
        frame_ui(frame).detect_button.click()
        assert control_ui(frame).looking_label.isHidden() is False

    fake_tool_locator.detect.assert_called_once_with(FFMPEG_TOOL)
    assert frame.control.chosen_candidate() == USABLE


def test_another_tools_result_is_not_this_blocks(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """The discovery reports every tool; a block only follows its own.

    **Test steps:**

    * build the block over a tool never searched for and have the discovery report another tool
    * verify the block is still looking
    """
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    discovery.tool_done.emit("vlc")

    assert control_ui(frame).looking_label.isHidden() is False


def test_a_typed_path_is_inspected_and_its_status_shown(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """The status is about the path as typed, in the words of its judgement.

    **Test steps:**

    * make the locator judge any path too old
    * stage a custom path
    * verify the locator was asked about that path, the Custom row reads its judgement and no line repeats it
    """
    fake_tool_locator.inspect.return_value = TOO_OLD
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    with qtbot.waitSignal(frame.answered, timeout=5000):
        frame.control.set_settings_value("/old")

    fake_tool_locator.inspect.assert_called_with(FFMPEG_TOOL, "/old")
    assert control_ui(frame).custom_status_label.text() == "(3.0, too old: Version 4.0 or newer is needed.)"
    assert frame_ui(frame).status_label.isHidden()


def test_an_inspection_that_fails_is_reported(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """A path that cannot be judged says so.

    **Test steps:**

    * make inspecting raise and stage a path
    * verify the status names the failure
    """
    fake_tool_locator.inspect.side_effect = RuntimeError("boom")
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    with qtbot.waitSignal(frame.answered, timeout=5000):
        frame.control.set_settings_value("/old")

    assert frame_ui(frame).status_label.text() == "Looking for it failed: boom"
    assert frame_ui(frame).status_label.isHidden() is False


def test_a_pinned_install_that_has_gone_shows_under_custom_marked_not_found(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """A folder the user chose that a later search no longer lists is not dropped silently: it is Custom, marked.

    **Test steps:**

    * store a search that found one install, make inspecting any other path answer missing
    * stage a folder that is not listed
    * verify Custom holds it, reads *not found*, is painted as a warning, and no line repeats that
    """
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (USABLE,)))
    gone = ToolCandidate(Path("/gone/bin"), "Custom", ToolStatus.MISSING, reason="No FFmpeg at /gone/bin.")
    fake_tool_locator.inspect.return_value = gone
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    with qtbot.waitSignal(frame.answered, timeout=5000):
        frame.control.set_settings_value("/gone/bin")

    ui = control_ui(frame)
    assert frame.control.chosen_candidate() is None
    assert ui.custom_status_label.text() == f"({NOT_FOUND_TEXT})"
    assert ui.path_edit.property(WARNING_PROPERTY) is True
    assert frame_ui(frame).status_label.isHidden()


def test_choosing_a_listed_install_reads_nothing(
    qtbot: QtBot, tools: ToolsSettings, discovery: ToolDiscovery, fake_tool_locator: Any
) -> None:
    """A listed install was judged when it was found, so choosing it shows that at once, with no version read.

    **Test steps:**

    * store a search that found two installs, build the block and pin the second
    * verify no line repeats its row and nothing was inspected
    """
    other = ToolCandidate(Path("/other/bin"), "scoop", ToolStatus.USABLE, (6, 0))
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (USABLE, other)))
    frame = make_frame(qtbot, tools, discovery, fake_tool_locator)

    frame.control.rows[1].setChecked(True)

    assert frame_ui(frame).status_label.isHidden()
    fake_tool_locator.inspect.assert_not_called()
