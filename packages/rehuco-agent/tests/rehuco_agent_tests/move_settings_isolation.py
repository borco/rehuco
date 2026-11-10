"""Keeps every test off the developer's saved choice of how a record is moved within its root (#579); the fixture that
does it is imported by name into the package's ``conftest.py``, which is past its line budget for one more."""

from collections.abc import Iterator

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import move_settings
from rehuco_agent.settings.move_settings import shared_move_settings

from rehuco_agent_tests.record_url_isolation import MemorySettings


@fixture(name="isolate_shared_move_settings", autouse=True)
def fixture_isolate_shared_move_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `MoveSettings` singleton (#579).

    A landed move reads it, so the first such test would otherwise pin an instance loaded from the developer's real
    settings for the rest of the session.
    """
    shared_move_settings.cache_clear()
    mocker.patch.object(move_settings, "persistent_settings", return_value=MemorySettings())
    yield
    shared_move_settings.cache_clear()
