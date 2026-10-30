"""Tests for ToolsSettings: where each optional external tool is, and which installs were found (#521)."""

from pathlib import Path
from typing import Any

from pytest import fixture, mark, param
from rehuco_agent.settings.tools_settings import ToolDetection, ToolsSettings, shared_tools_settings
from rehuco_core import FFMPEG_TOOL, VLC_TOOL, ToolCandidate, ToolStatus

INSTALL = ToolCandidate(Path("/opt/ffmpeg/bin"), "winget", ToolStatus.USABLE, (7, 1, 1))
"""An install a search found."""


# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API (see ``test_videos_settings.py``)."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__group + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__group + key, default)


# pylint: enable=duplicate-code


@fixture(name="settings")
def fixture_settings() -> FakeSettings:
    """An empty in-memory storage."""
    return FakeSettings()


def test_a_tool_never_set_is_automatic_and_never_searched() -> None:
    """No entry reads as the empty path, which is the best install found, and a tool not yet searched for.

    **Test steps:**

    * ask a fresh object for FFmpeg's path and detection
    * verify an empty path and a detection that is not searched and holds nothing
    """
    tools = ToolsSettings()

    assert tools.path(FFMPEG_TOOL.ID) == ""
    assert tools.detection(FFMPEG_TOOL.ID) == ToolDetection(False, ())


def test_the_path_and_the_detection_round_trip_through_storage_under_their_keys(settings: FakeSettings) -> None:
    """What was saved is what loads back, in the ``tools`` group by tool id, each under its own key.

    **Test steps:**

    * set a path and a detection for FFmpeg and save
    * verify the raw keys, then load a second object
    * verify it holds both
    """
    saved = ToolsSettings()
    saved.set_path(FFMPEG_TOOL.ID, "/mine")
    saved.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (INSTALL,)))
    saved.save(settings)  # type: ignore[arg-type]

    assert settings.value("tools/ffmpeg_path") == "/mine"
    assert isinstance(settings.value("tools/ffmpeg_detected"), str)
    loaded = ToolsSettings()
    loaded.load(settings)  # type: ignore[arg-type]
    assert loaded.path(FFMPEG_TOOL.ID) == "/mine"
    assert loaded.detection(FFMPEG_TOOL.ID) == ToolDetection(True, (INSTALL,))


def test_the_detection_is_kept_when_a_custom_path_is_set() -> None:
    """Both are stored although only one is used, so giving up a custom path finds what was found before.

    **Test steps:**

    * record a detection, then set a custom path and then clear it
    * verify the detection is untouched throughout
    """
    tools = ToolsSettings()
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (INSTALL,)))

    tools.set_path(FFMPEG_TOOL.ID, "/mine")
    assert tools.detection(FFMPEG_TOOL.ID).installs == (INSTALL,)
    tools.set_path(FFMPEG_TOOL.ID, "")
    assert tools.detection(FFMPEG_TOOL.ID).installs == (INSTALL,)


def test_changing_a_value_only_changes_memory(settings: FakeSettings) -> None:
    """The file is written when the app writes it, not whenever a search finishes.

    **Test steps:**

    * record a detection without saving
    * verify nothing was stored
    """
    ToolsSettings().set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (INSTALL,)))

    assert settings.value("tools/ffmpeg_detected") is None


def test_a_change_is_announced_once_and_only_when_it_is_one() -> None:
    """Pages follow a tool changing; setting what is already there is no change.

    **Test steps:**

    * set a path, then the same path, then a detection, then the same detection
    * verify two announcements, each naming the tool
    """
    tools = ToolsSettings()
    announced: list[str] = []
    tools.tool_changed.connect(announced.append)

    tools.set_path(FFMPEG_TOOL.ID, "/mine")
    tools.set_path(FFMPEG_TOOL.ID, "/mine")
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (INSTALL,)))
    tools.set_detection(FFMPEG_TOOL.ID, ToolDetection(True, (INSTALL,)))

    assert announced == [FFMPEG_TOOL.ID, FFMPEG_TOOL.ID]


@mark.parametrize(
    "stored",
    [
        param(None, id="never-stored"),
        param("", id="empty"),
        param("not json", id="not-json"),
        param("[]", id="not-an-object"),
        param('{"searched": "yes", "installs": 3}', id="wrong-types"),
    ],
)
def test_a_detection_that_cannot_be_read_is_a_tool_never_searched(stored: object) -> None:
    """The file may come from another build or a hand edit: the tool is searched for again.

    **Test steps:**

    * read each unreadable value
    * verify a detection that is not searched and holds nothing
    """
    assert ToolDetection.from_text(stored) == ToolDetection(False, ())


def test_a_malformed_install_costs_only_itself() -> None:
    """One bad entry in the list does not lose the others.

    **Test steps:**

    * read a detection holding a good install and a malformed one
    * verify only the good one is kept, and the search still counts as done
    """
    good = ToolDetection(True, (INSTALL,)).to_text()
    text = good.replace("]}", ', {"folder": 3}]}')

    assert ToolDetection.from_text(text) == ToolDetection(True, (INSTALL,))


def test_the_shared_instance_is_one_object() -> None:
    """Every reader and the Tools page's Save share the same instance.

    **Test steps:**

    * ask for the shared settings twice
    * verify it is the same object
    """
    assert shared_tools_settings() is shared_tools_settings()


def test_a_tool_is_unusable_for_the_reason_the_locator_gives(fake_tool_locator: Any) -> None:
    """What a feature asks before it uses a tool: nothing, or a sentence it can show (#318, #521).

    **Test steps:**

    * ask with nothing found, then with a usable copy, then with one that is too old
    * verify the answers are a sentence naming the tool, ``None``, and the copy's own reason
    """
    tools = ToolsSettings()
    tools.set_path(VLC_TOOL.ID, "/opt/vlc")

    assert tools.unusable_reason(VLC_TOOL) == "No VLC was found, and none is set up."

    fake_tool_locator.resolve.return_value = ToolCandidate(Path("/opt/vlc"), "Custom", ToolStatus.USABLE, (3, 0, 23))
    assert tools.unusable_reason(VLC_TOOL) is None

    fake_tool_locator.resolve.return_value = ToolCandidate(
        Path("/opt/vlc"), "Custom", ToolStatus.TOO_OLD, (2, 2), "Version 3.0 or newer is needed."
    )
    assert tools.unusable_reason(VLC_TOOL) == "Version 3.0 or newer is needed."
    fake_tool_locator.resolve.assert_called_with(VLC_TOOL, "/opt/vlc", ())


def test_a_tool_is_missing_without_being_run(tmp_path: Path, fake_tool_locator: Any) -> None:
    """What a double-click asks on the GUI thread: a chosen path is only checked to hold the tool, an empty one reads
    the detection, and nothing runs for a version (#318).

    **Test steps:**

    * point VLC at an empty folder, then at one holding its executable
    * verify the first is missing by name and the second is there, with the locator never asked
    * clear the path, with a usable install recorded, and verify the detection answers
    """
    tools = ToolsSettings()
    tools.set_path(VLC_TOOL.ID, str(tmp_path))
    assert tools.missing_reason(VLC_TOOL) == f"No VLC at {tmp_path}."

    VLC_TOOL.executable_files(tmp_path)[0].touch()
    assert tools.missing_reason(VLC_TOOL) is None
    fake_tool_locator.resolve.assert_not_called()

    tools.set_path(VLC_TOOL.ID, "")
    install = ToolCandidate(tmp_path, "PATH", ToolStatus.USABLE, (3, 0, 23))
    tools.set_detection(VLC_TOOL.ID, ToolDetection(True, (install,)))
    fake_tool_locator.resolve.return_value = install
    assert tools.missing_reason(VLC_TOOL) is None
    fake_tool_locator.resolve.assert_called_once_with(VLC_TOOL, "", (install,))


def test_a_tool_folder_is_found_without_running_anything(tmp_path: Path, fake_tool_locator: Any) -> None:
    """What a launch on the GUI thread asks: the folder of the chosen path, or of the best install found (#319).

    **Test steps:**

    * point VLC at an empty folder, then at one holding its executable, and verify the first has none and the second
      is it
    * clear the path, with no usable install, and verify there is none
    * record a usable install and verify its folder, with the locator asked about it
    """
    tools = ToolsSettings()
    tools.set_path(VLC_TOOL.ID, str(tmp_path))
    assert tools.tool_folder(VLC_TOOL) is None
    VLC_TOOL.executable_files(tmp_path)[0].touch()
    assert tools.tool_folder(VLC_TOOL) == tmp_path

    tools.set_path(VLC_TOOL.ID, "")
    fake_tool_locator.resolve.return_value = None
    assert tools.tool_folder(VLC_TOOL) is None
    install = ToolCandidate(tmp_path, "PATH", ToolStatus.USABLE, (3, 0, 23))
    fake_tool_locator.resolve.return_value = install
    assert tools.tool_folder(VLC_TOOL) == tmp_path
    fake_tool_locator.resolve.assert_called_with(VLC_TOOL, "", ())
    unusable = ToolCandidate(tmp_path, "PATH", ToolStatus.TOO_OLD, (2, 0), "old")
    fake_tool_locator.resolve.return_value = unusable
    assert tools.tool_folder(VLC_TOOL) is None
