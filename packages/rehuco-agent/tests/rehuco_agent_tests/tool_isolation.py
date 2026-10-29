"""Keeps every test off the developer's real external tools: their saved paths, and the search for an install (#521);
with the fixtures that do it, imported by name into the package's ``conftest.py``."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent import playback_libraries
from rehuco_agent.settings import tool_discovery, tools_settings
from rehuco_agent.settings.tool_discovery import shared_tool_discovery
from rehuco_agent.settings.tools_settings import shared_tools_settings
from rehuco_agent.settings.ui import tool_frame
from rehuco_core import ToolLocator, rehu_content_duration


class MemorySettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API, as every settings test's ``FakeSettings``."""

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


@fixture(name="isolate_shared_tools_settings", autouse=True)
def fixture_isolate_shared_tools_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `ToolsSettings` singleton (#521).

    Same rationale as ``isolate_shared_videos_settings``: whichever test first builds a `ToolsPage` or a duration probe
    would otherwise pin the developer's real tool paths for the rest of the session.

    :param mocker: pytest-mock fixture.
    """
    shared_tools_settings.cache_clear()
    mocker.patch.object(tools_settings, "persistent_settings", return_value=MemorySettings())
    yield
    # the discovery holds the settings it was built over, so it goes with them, its thread stopped
    shared_tool_discovery().stop()
    shared_tool_discovery.cache_clear()
    shared_tools_settings.cache_clear()


@fixture(name="fake_tool_locator", autouse=True)
def fixture_fake_tool_locator(mocker: MockerFixture) -> Any:
    """Replace the process-wide `ToolLocator` with one that finds no tool, so no test runs or searches for a real one.

    A test that needs a tool found sets ``detect``, ``inspect`` or ``resolve`` on what this returns.

    :param mocker: pytest-mock fixture.
    :returns: the mock locator every consumer of ``shared_tool_locator`` now gets.
    """
    locator = mocker.Mock(spec=ToolLocator)
    locator.detect.return_value = []
    locator.resolve.return_value = None
    for module in (tool_frame, tool_discovery, tools_settings, rehu_content_duration, playback_libraries):
        mocker.patch.object(module, "shared_tool_locator", return_value=locator)
    return locator
