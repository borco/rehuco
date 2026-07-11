"""pytest fixtures for rehuco-agent."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import markdown_rendering_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings


# Mirrors every dedicated settings test's own FakeSettings exactly (see e.g.
# test_markdown_rendering_settings.py) -- kept as a separate copy rather than a shared import,
# matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API."""

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


@fixture(autouse=True)
def isolate_shared_markdown_rendering_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `MarkdownRenderingSettings` singleton.

    Without this, whichever test first calls ``shared_markdown_rendering_settings()`` (directly,
    or indirectly via ``DescriptionField.make_viewer``, which every test building a document's
    fields touches) would pin its instance -- and whatever it loaded from real persistent storage
    -- for the rest of the whole test session: leaking state between tests, and reading the
    developer's actual on-disk settings file rather than a hermetic fake. A test that specifically
    exercises this settings object (e.g. ``test_markdown_rendering_settings.py``,
    ``test_markdown_rendering_page.py``) patches ``persistent_settings`` itself, which simply
    overrides this default for its own module.
    """
    shared_markdown_rendering_settings.cache_clear()
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_markdown_rendering_settings.cache_clear()
