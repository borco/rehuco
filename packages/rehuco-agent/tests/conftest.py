"""pytest fixtures for rehuco-agent."""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import identity_settings, markdown_rendering_settings
from rehuco_agent.settings.identity_settings import shared_identity_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_agent.settings.ui import settings_dialog


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
    ``test_descriptions_page.py``) patches ``persistent_settings`` itself, which simply
    overrides this default for its own module.
    """
    shared_markdown_rendering_settings.cache_clear()
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_markdown_rendering_settings.cache_clear()


@fixture(autouse=True)
def isolate_shared_identity_settings(mocker: MockerFixture) -> Iterator[None]:
    """Isolate every test from the process-wide `IdentitySettings` singleton (#99).

    Same rationale as :func:`isolate_shared_markdown_rendering_settings`: whichever test first
    calls ``shared_identity_settings()`` (directly, or indirectly via ``DocumentsDock``'s open
    paths or ``MainWindow``'s `IdentityPage`) would otherwise pin an instance loaded from the
    developer's real on-disk settings for the rest of the session. Tests that specifically
    exercise the identity settings patch ``persistent_settings`` themselves.
    """
    shared_identity_settings.cache_clear()
    mocker.patch.object(identity_settings, "persistent_settings", return_value=FakeSettings())
    yield
    shared_identity_settings.cache_clear()


@fixture(autouse=True)
def isolate_settings_dialog_settings(mocker: MockerFixture) -> FakeSettings:
    """Isolate every test building a `SettingsDialog` from real persistent storage (#76).

    The dialog restores its filter toggles on construction and saves them on every change, so
    without this any test constructing one (directly, or via ``MainWindow``) would read -- and
    overwrite -- the developer's own on-disk settings, and leak toggle state into later tests.

    :returns: the in-memory stand-in the dialog loads from and saves to, for a test that wants to
        seed it or assert on what was written.
    """
    fake = FakeSettings()
    mocker.patch.object(settings_dialog, "persistent_settings", return_value=fake)
    return fake
