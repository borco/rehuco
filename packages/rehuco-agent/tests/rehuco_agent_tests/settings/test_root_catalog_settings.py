"""Tests for RootCatalogSettings: how the Root Catalog dock behaves while it is browsed (#457)."""

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import root_catalog_settings
from rehuco_agent.settings.root_catalog_settings import (
    AUTO_PREVIEW_KEY,
    DEFAULT_AUTO_PREVIEW,
    GROUP,
    RootCatalogSettings,
    shared_root_catalog_settings,
)

from rehuco_agent_tests.conftest import FakeSettings


@fixture(name="stored")
def stored_fixture() -> FakeSettings:
    """An empty in-memory settings store.

    :returns: the store.
    """
    return FakeSettings()


def test_the_roots_view_previews_the_current_rehu_until_told_not_to(stored: FakeSettings) -> None:
    """A fresh install, with nothing stored, previews: that is what browsing a catalog is for.

    **Test steps:**

    * build the settings and load them from an empty store
    * verify the preview is on
    """
    settings = RootCatalogSettings()

    settings.load(stored)  # type: ignore[arg-type]

    assert DEFAULT_AUTO_PREVIEW is True
    assert settings.auto_preview is True


def test_the_choice_is_saved_under_its_own_group_and_read_back(stored: FakeSettings) -> None:
    """Both values round-trip, and the key lives under the section's group.

    **Test steps:**

    * save a choice of off and load it into a second object
    * verify the store holds it under the group, the second object reads it, and saving on again reads on
    """
    settings = RootCatalogSettings()
    settings.auto_preview = False
    settings.save(stored)  # type: ignore[arg-type]

    reloaded = RootCatalogSettings()
    reloaded.load(stored)  # type: ignore[arg-type]

    stored.beginGroup(GROUP)
    assert stored.value(AUTO_PREVIEW_KEY) is False
    stored.endGroup()
    assert reloaded.auto_preview is False
    reloaded.auto_preview = True
    reloaded.save(stored)  # type: ignore[arg-type]
    again = RootCatalogSettings()
    again.load(stored)  # type: ignore[arg-type]
    assert again.auto_preview is True


def test_a_change_tells_whoever_listens(stored: FakeSettings) -> None:
    """The menu entry and the settings page both follow this one object, so a change must reach them as it is made.

    **Test steps:**

    * listen to the change signal, set the value to what it already is, then to something else
    * verify only the real change was announced
    """
    del stored
    settings = RootCatalogSettings()
    heard: list[object] = []
    settings.auto_preview_changed.connect(heard.append)

    settings.auto_preview = True
    settings.auto_preview = False

    assert heard == [False]


def test_the_shared_settings_are_one_object_loaded_once_from_storage(
    mocker: MockerFixture, stored: FakeSettings
) -> None:
    """Every consumer reads and subscribes to the same instance, loaded from what is stored.

    **Test steps:**

    * store a choice of off, and ask for the shared settings twice
    * verify both answers are one object holding the stored choice
    """
    saved = RootCatalogSettings()
    saved.auto_preview = False
    saved.save(stored)  # type: ignore[arg-type]
    mocker.patch.object(root_catalog_settings, "persistent_settings", return_value=stored)
    shared_root_catalog_settings.cache_clear()

    first, second = shared_root_catalog_settings(), shared_root_catalog_settings()

    assert first is second
    assert first.auto_preview is False
