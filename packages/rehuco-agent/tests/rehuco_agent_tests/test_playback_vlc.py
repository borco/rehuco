"""Tests for this run's libvlc: loaded from the Tools page's VLC when first asked for, kept once it is, and the restart
another VLC then needs (#319)."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import Mock

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent import playback_vlc
from rehuco_agent.playback_vlc import (
    NOT_SET_UP,
    VlcPlayback,
    configure_vlc_probe,
    shared_vlc_library,
    shared_vlc_playback,
    vlc_restart_needed,
)
from rehuco_core import LIBVLC_PROBE_FLAG, VLC_TOOL, VlcLibrary


@fixture(name="tools")
def fixture_tools(mocker: MockerFixture, tmp_path: Path) -> Mock:
    """The Tools settings, resolving a VLC folder with its library.

    :param mocker: pytest-mock fixture.
    :param tmp_path: pytest fixture.
    :returns: the settings mock.
    """
    tools = mocker.patch.object(playback_vlc, "shared_tools_settings").return_value
    tools.tool_folder.return_value = tmp_path
    tools.missing_reason.return_value = None
    mocker.patch.object(VLC_TOOL, "library_path", return_value=tmp_path / "libvlc.dll")
    return tools


@fixture(name="load")
def fixture_load(mocker: MockerFixture, tmp_path: Path) -> Mock:
    """``VlcLibrary.load``, answering an available proxy over the library asked for.

    :param mocker: pytest-mock fixture.
    :param tmp_path: pytest fixture.
    :returns: the patched loader.
    """

    def loaded(library: Path) -> Mock:
        proxy = Mock(spec=VlcLibrary)
        proxy.available = True
        proxy.library = library
        proxy.reason = None
        return proxy

    del tmp_path
    return mocker.patch.object(VlcLibrary, "load", side_effect=loaded)


@fixture(autouse=True)
def fixture_fresh_playback() -> Iterator[None]:
    """A run of its own: nothing loaded before, and nothing left after."""
    shared_vlc_playback.cache_clear()
    yield
    shared_vlc_playback.cache_clear()


def test_the_library_is_loaded_from_the_tools_pages_vlc_once(tools: Mock, load: Mock, tmp_path: Path) -> None:
    """**Test steps:**

    * ask for the library twice
    * verify it was loaded once, from the folder's library, and the same proxy answers both times
    """
    first = shared_vlc_library()
    second = shared_vlc_library()

    load.assert_called_once_with(tmp_path / "libvlc.dll")
    assert first is second
    assert first.available
    tools.tool_folder.assert_called()


def test_no_vlc_is_unavailable_with_the_tools_pages_reason_and_tried_again(tools: Mock, load: Mock) -> None:
    """A load that failed is not kept: a VLC set up afterwards is taken at the next player.

    **Test steps:**

    * have no folder resolve, with a reason, and ask
    * verify unavailable with that reason and nothing loaded
    * have a folder resolve and ask again; verify it is loaded now
    """
    tools.tool_folder.return_value = None
    tools.missing_reason.return_value = "No VLC at /nowhere."

    assert shared_vlc_library().reason == "No VLC at /nowhere."
    load.assert_not_called()

    tools.tool_folder.return_value = Path("/vlc")
    assert shared_vlc_library().available
    load.assert_called_once()


def test_no_reason_from_the_tools_page_falls_back_to_the_generic_one(tools: Mock, load: Mock) -> None:
    """**Test steps:**

    * have no folder resolve and no reason given
    * verify the generic reason
    """
    tools.tool_folder.return_value = None
    tools.missing_reason.return_value = None

    assert shared_vlc_library().reason == NOT_SET_UP
    load.assert_not_called()


def test_a_vlc_without_its_library_is_unavailable_and_says_so(tools: Mock, load: Mock, mocker: MockerFixture) -> None:
    """**Test steps:**

    * have the folder resolve but hold no library
    * verify the static-or-sandboxed reason and nothing loaded
    """
    del tools
    mocker.patch.object(VLC_TOOL, "library_path", return_value=None)

    assert "static or sandboxed" in (shared_vlc_library().reason or "")
    load.assert_not_called()


def test_no_restart_is_needed_before_anything_loaded_or_while_the_vlc_is_the_same(tools: Mock, load: Mock) -> None:
    """**Test steps:**

    * ask before any load, then load, then ask again with the Tools page unchanged
    * verify no restart either time
    """
    del tools, load
    assert vlc_restart_needed() is False

    shared_vlc_library()

    assert vlc_restart_needed() is False


def test_another_vlc_chosen_after_the_load_needs_a_restart(tools: Mock, load: Mock, mocker: MockerFixture) -> None:
    """python-vlc binds its library once per process, so the Tools page's new VLC waits for the next start.

    **Test steps:**

    * load, then have the Tools page resolve another library, then none at all
    * verify a restart is needed both times, and the loaded proxy is still the one answered
    """
    loaded = shared_vlc_library()
    mocker.patch.object(VLC_TOOL, "library_path", return_value=Path("/other/libvlc.dll"))

    assert vlc_restart_needed() is True
    assert shared_vlc_library() is loaded

    tools.tool_folder.return_value = None
    assert vlc_restart_needed() is True
    load.assert_called_once()


def test_a_failed_load_never_asks_for_a_restart(tools: Mock, load: Mock) -> None:
    """**Test steps:**

    * have no folder resolve and ask, then make one resolve
    * verify no restart is needed: nothing is bound
    """
    del load
    tools.tool_folder.return_value = None
    shared_vlc_library()

    tools.tool_folder.return_value = Path("/vlc")

    assert vlc_restart_needed() is False


def test_the_playback_state_is_one_per_process() -> None:
    """**Test steps:**

    * ask for the shared state twice
    * verify one object, of the class
    """
    assert shared_vlc_playback() is shared_vlc_playback()
    assert isinstance(shared_vlc_playback(), VlcPlayback)


def test_configuring_the_probe_gives_the_tool_this_program(mocker: MockerFixture) -> None:
    """**Test steps:**

    * configure, with the program known
    * verify the tool got it, and that the probe flag is what the tool appends
    """
    mocker.patch.object(playback_vlc, "own_program", return_value=["rehuco-agent"])
    configure = mocker.patch.object(VLC_TOOL, "configure")

    configure_vlc_probe()

    configure.assert_called_once_with(("rehuco-agent",))
    assert LIBVLC_PROBE_FLAG == "--probe-libvlc"
