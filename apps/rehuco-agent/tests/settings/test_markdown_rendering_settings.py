"""Tests for MarkdownRenderingSettings: engine, per-engine CSS, and image-width cap.

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import markdown_rendering_settings
from rehuco_agent.settings.markdown_rendering_settings import (
    MarkdownRenderingSettings,
    shared_markdown_rendering_settings,
)


# region fixtures
# Mirrors test_markdown_rendering_page.py's (and conftest.py's) FakeSettings exactly -- kept as a
# separate copy rather than a shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`MarkdownRenderingSettings.load`/:meth:`~MarkdownRenderingSettings.save` call
    them by name.
    """

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


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test.

    Without this, the first test to call :func:`shared_markdown_rendering_settings` would pin its
    instance for the rest of the whole test session, silently leaking state between tests.
    """
    shared_markdown_rendering_settings.cache_clear()
    yield
    shared_markdown_rendering_settings.cache_clear()


# endregion


def test_save_then_load_round_trips_every_field(settings: FakeSettings) -> None:
    """Saving and reloading reproduces every field's value.

    **Test steps:**

    * set non-default values on a fresh instance and save
    * load into a fresh instance from the same settings stand-in
    * verify every field came back unchanged
    """
    original = MarkdownRenderingSettings()
    original.engine = "mistletoe"
    original.markdown_css = "body { color: red; }"
    original.mistletoe_css = "body { color: blue; }"
    original.max_image_width = 500

    original.save(settings)  # type: ignore[arg-type]

    restored = MarkdownRenderingSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.engine == "mistletoe"
    assert restored.markdown_css == "body { color: red; }"
    assert restored.mistletoe_css == "body { color: blue; }"
    assert restored.max_image_width == 500


def test_load_defaults_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had anything saved yields the documented defaults.

    **Test steps:**

    * load into a fresh instance from an empty settings stand-in
    * verify every field holds its default
    """
    loaded = MarkdownRenderingSettings()

    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.engine == "markdown"
    assert loaded.markdown_css == ""
    assert loaded.mistletoe_css == ""
    assert loaded.max_image_width == 350


def test_css_for_current_engine_returns_markdown_css_when_selected() -> None:
    """``css_for_current_engine`` returns ``markdown_css`` while ``engine`` is ``"markdown"``.

    **Test steps:**

    * set distinct CSS for both engines, with ``engine`` left at its default (``"markdown"``)
    * verify ``css_for_current_engine`` returns the markdown one
    """
    rendering_settings = MarkdownRenderingSettings()
    rendering_settings.markdown_css = "markdown-css"
    rendering_settings.mistletoe_css = "mistletoe-css"

    assert rendering_settings.css_for_current_engine() == "markdown-css"


def test_css_for_current_engine_returns_mistletoe_css_when_selected() -> None:
    """``css_for_current_engine`` returns ``mistletoe_css`` once ``engine`` is ``"mistletoe"``.

    **Test steps:**

    * set distinct CSS for both engines and switch ``engine`` to ``"mistletoe"``
    * verify ``css_for_current_engine`` returns the mistletoe one
    """
    rendering_settings = MarkdownRenderingSettings()
    rendering_settings.markdown_css = "markdown-css"
    rendering_settings.mistletoe_css = "mistletoe-css"
    rendering_settings.engine = "mistletoe"

    assert rendering_settings.css_for_current_engine() == "mistletoe-css"


def test_shared_instance_is_the_same_object_across_calls(mocker: MockerFixture) -> None:
    """``shared_markdown_rendering_settings`` returns the identical instance every call.

    **Test steps:**

    * mock ``persistent_settings`` so the first call's ``load`` doesn't touch real storage
    * call the accessor twice
    * verify both calls return the same object
    """
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=FakeSettings())

    first = shared_markdown_rendering_settings()
    second = shared_markdown_rendering_settings()

    assert first is second


def test_shared_instance_loads_from_persistent_settings_on_first_call(mocker: MockerFixture) -> None:
    """``shared_markdown_rendering_settings`` loads its values from ``persistent_settings()`` the
    first time it's constructed.

    **Test steps:**

    * pre-populate a fake settings store and mock ``persistent_settings`` to return it
    * call the accessor
    * verify the returned instance reflects the pre-populated values
    """
    fake = FakeSettings()
    to_save = MarkdownRenderingSettings()
    to_save.engine = "mistletoe"
    to_save.save(fake)  # type: ignore[arg-type]
    mocker.patch.object(markdown_rendering_settings, "persistent_settings", return_value=fake)

    instance = shared_markdown_rendering_settings()

    assert instance.engine == "mistletoe"
