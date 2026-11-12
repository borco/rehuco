"""Keeps every test off the developer's saved library of root path templates (#637); the fixture that does it is
imported by name into the package's ``conftest.py``, which is past its line budget for one more."""

from collections.abc import Iterator

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import root_layout_templates_settings
from rehuco_agent.settings.root_layout_templates_settings import shared_root_layout_templates_settings
from rehuco_agent.settings.ui import root_layout_templates_page

from rehuco_agent_tests.record_url_isolation import MemorySettings


@fixture(name="isolate_shared_root_layout_templates_settings", autouse=True)
def fixture_isolate_shared_root_layout_templates_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `RootLayoutTemplatesSettings` singleton (#637).

    Same rationale as ``conftest.py``'s ``isolate_shared_location_templates_settings``: a root editor reads the library
    for its drop-down, so the first such test would otherwise pin an instance loaded from the developer's real
    settings for the rest of the session. `RootLayoutTemplatesPage` is patched with the same stand-in.

    Tests that specifically exercise the library's storage patch ``persistent_settings`` themselves.
    """
    shared_root_layout_templates_settings.cache_clear()
    fake = MemorySettings()
    mocker.patch.object(root_layout_templates_settings, "persistent_settings", return_value=fake)
    mocker.patch.object(root_layout_templates_page, "persistent_settings", return_value=fake)
    yield
    shared_root_layout_templates_settings.cache_clear()
