"""Tests for ToolsPage: the Tools settings category page (#521)."""

from pathlib import Path
from typing import Any

from pytestqt.qtbot import QtBot
from rehuco_agent.settings.tools_settings import ToolDetection, shared_tools_settings
from rehuco_agent.settings.ui.settings_frame_filter import SettingsFrameFilter
from rehuco_agent.settings.ui.tools_page import ToolsPage
from rehuco_core import EXTERNAL_TOOLS, FFMPEG_TOOL, ToolCandidate, ToolStatus

USABLE = ToolCandidate(Path("/opt/ffmpeg/bin"), "PATH", ToolStatus.USABLE, (7, 1, 1))


def make_page(qtbot: QtBot) -> ToolsPage:
    """Build the page and keep it alive for the test.

    :param qtbot: the pytest-qt fixture.
    :returns: the page.
    """
    page = ToolsPage()
    qtbot.addWidget(page)
    return page


def test_there_is_one_block_per_tool_in_the_registry(qtbot: QtBot) -> None:
    """The page follows the registry, so a tool added there has its block with no change here.

    **Test steps:**

    * build the page
    * verify one block per registered tool, in order, each a child of the page
    """
    page = make_page(qtbot)

    assert [frame.tool for frame in page.frames] == list(EXTERNAL_TOOLS.values())
    assert all(frame.frame.parent() is page for frame in page.frames)


def test_a_fresh_page_is_clean_and_automatic(qtbot: QtBot) -> None:
    """Nothing saved means every tool is on the best install found.

    **Test steps:**

    * build the page
    * verify it is clean and FFmpeg's choice is empty
    """
    page = make_page(qtbot)

    assert page.is_dirty() is False
    assert page.frames[0].control.settings_value() == ""


def test_finding_nothing_does_not_make_the_page_dirty(qtbot: QtBot) -> None:
    """Switching to Custom because nothing was found is not an edit: no frame tints and Apply stays disabled.

    **Test steps:**

    * store a search that found nothing, build the page and snapshot its frames
    * verify Custom is chosen, and the page and every frame are clean
    """
    shared_tools_settings().set_detection(FFMPEG_TOOL.ID, ToolDetection(True, ()))
    page = make_page(qtbot)
    frame_filter = SettingsFrameFilter(page, "Tools")

    assert page.frames[0].control.settings_value() == ""
    assert frame_filter.dirty_frames() == []
    assert page.is_dirty() is False


def test_a_custom_path_makes_the_page_dirty_until_saved(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """Whatever is staged is what Save would write.

    **Test steps:**

    * build the page and stage a custom path
    * verify the page is dirty and its frame is the dirty one
    * save and verify the shared settings hold the path and the page is clean
    """
    fake_tool_locator.inspect.return_value = USABLE
    page = make_page(qtbot)
    frame_filter = SettingsFrameFilter(page, "Tools")

    page.frames[0].control.set_settings_value("/opt/ffmpeg")

    assert page.is_dirty() is True
    assert frame_filter.dirty_frames() == [page.frames[0].frame]

    page.save_changes()

    assert shared_tools_settings().path(FFMPEG_TOOL.ID) == "/opt/ffmpeg"
    assert page.is_dirty() is False


def test_drop_changes_reverts_to_the_saved_path(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """``drop_changes`` re-seeds the page from the shared settings -- a revert, not a no-op.

    **Test steps:**

    * save a path, build the page and stage the empty value
    * call ``drop_changes``
    * verify the saved path is back and the page is clean
    """
    fake_tool_locator.inspect.return_value = USABLE
    shared_tools_settings().set_path(FFMPEG_TOOL.ID, "/opt/ffmpeg")
    page = make_page(qtbot)
    assert page.frames[0].control.settings_value() == "/opt/ffmpeg"
    page.frames[0].control.set_settings_value("")
    assert page.is_dirty() is True

    page.drop_changes()

    assert page.frames[0].control.settings_value() == "/opt/ffmpeg"
    assert page.is_dirty() is False


def test_seed_defaults_stages_the_best_install_over_a_saved_path(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """``seed_defaults`` shows what a fresh install would, as a staged edit (#342).

    **Test steps:**

    * save a path and build the page
    * call ``seed_defaults``
    * verify the path is empty and the page is dirty
    """
    fake_tool_locator.inspect.return_value = USABLE
    shared_tools_settings().set_path(FFMPEG_TOOL.ID, "/opt/ffmpeg")
    page = make_page(qtbot)

    page.seed_defaults()

    assert page.frames[0].control.settings_value() == ""
    assert page.is_dirty() is True


def test_showing_the_page_searches_for_nothing(qtbot: QtBot, fake_tool_locator: Any) -> None:
    """The page shows what was found; only Detect searches.

    **Test steps:**

    * build the page and show it
    * verify the locator was never asked to search or verify
    """
    page = make_page(qtbot)

    page.show()

    fake_tool_locator.detect.assert_not_called()
    fake_tool_locator.verify.assert_not_called()


def test_saving_writes_the_detections_with_the_paths(qtbot: QtBot) -> None:
    """Apply is a write of the settings file, and the detections are in memory by then.

    **Test steps:**

    * record a detection, stage a path and save
    * verify the settings object was asked to save once
    """
    shared_tools_settings().set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (USABLE,)))
    page = make_page(qtbot)
    page.frames[0].control.set_settings_value("/opt/ffmpeg")

    page.save_changes()

    assert str(shared_tools_settings().path(FFMPEG_TOOL.ID)) == "/opt/ffmpeg"
    assert shared_tools_settings().detection(FFMPEG_TOOL.ID).installs == (USABLE,)
