"""Keeps every test off the developer's saved choice of where a record's URL is shown (#620); the fixture that does it
is imported by name into the package's ``conftest.py``, which is past its line budget for one more."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import record_url_settings
from rehuco_agent.settings.record_url_settings import shared_record_url_settings


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


@fixture(name="isolate_shared_record_url_settings", autouse=True)
def fixture_isolate_shared_record_url_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `RecordUrlSettings` singleton (#620).

    Same rationale as ``conftest.py``'s ``isolate_shared_description_editor_settings``: building a document's
    fields reads it, so the first such test would otherwise pin an instance loaded from the developer's real
    settings for the rest of the session.
    """
    shared_record_url_settings.cache_clear()
    mocker.patch.object(record_url_settings, "persistent_settings", return_value=MemorySettings())
    yield
    shared_record_url_settings.cache_clear()
