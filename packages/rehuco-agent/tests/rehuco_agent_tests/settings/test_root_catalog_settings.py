"""Tests for RootCatalogSettings: how the Root Catalog dock behaves while it is browsed (#457)."""

import logging

from pytest import LogCaptureFixture, fixture, mark, param
from pytest_mock import MockerFixture
from rehuco_agent.settings import root_catalog_settings
from rehuco_agent.settings.root_catalog_settings import (
    AUTO_PREVIEW_KEY,
    DEFAULT_AUTO_PREVIEW,
    DEFAULT_LAYOUTS_KEY,
    DEFAULT_ROOT_LAYOUTS,
    DEFAULT_SCAN_AFTER_ADDING,
    FALLBACKS_KEY,
    GROUP,
    LABEL_KEY,
    LAYOUTS_KEY,
    SCAN_AFTER_ADDING_KEY,
    RootCatalogSettings,
    RootLayout,
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


def test_adding_a_root_scans_it_until_told_not_to(stored: FakeSettings) -> None:
    """A fresh install scans a root as it is added (#542): an empty new root looks like a failed add.

    **Test steps:**

    * build the settings and load them from an empty store
    * verify the scan after adding is on
    """
    settings = RootCatalogSettings()

    settings.load(stored)  # type: ignore[arg-type]

    assert DEFAULT_SCAN_AFTER_ADDING is True
    assert settings.scan_after_adding is True


def test_the_scan_after_adding_choice_is_saved_and_announced(stored: FakeSettings) -> None:
    """The choice round-trips under the group, and a change is announced.

    **Test steps:**

    * listen to the change signal, set the choice to what it is, then to off, and save
    * load a second object and verify the store, the signal and the second object's value
    """
    settings = RootCatalogSettings()
    heard: list[object] = []
    settings.scan_after_adding_changed.connect(heard.append)

    settings.scan_after_adding = True
    settings.scan_after_adding = False
    settings.save(stored)  # type: ignore[arg-type]
    reloaded = RootCatalogSettings()
    reloaded.load(stored)  # type: ignore[arg-type]

    stored.beginGroup(GROUP)
    assert stored.value(SCAN_AFTER_ADDING_KEY) is False
    stored.endGroup()
    assert heard == [False]
    assert reloaded.scan_after_adding is False


def test_the_default_layouts_start_as_the_current_name_layout(stored: FakeSettings) -> None:
    """A fresh install offers one layout, which keeps any record's name, as every root had before #578.

    **Test steps:**

    * load from an empty store
    * verify the one seeded layout and its maps
    """
    settings = RootCatalogSettings()

    settings.load(stored)  # type: ignore[arg-type]

    assert settings.default_layouts == DEFAULT_ROOT_LAYOUTS == (RootLayout("Keep folder names", {"*": ("*",)}, {}),)


def test_the_default_layouts_round_trip_and_a_shorter_list_leaves_nothing_behind(stored: FakeSettings) -> None:
    """Names and maps are read back as saved, in order; saving fewer layouts later drops the extra ones (#578).

    **Test steps:**

    * save two layouts, one with fallbacks, and load them into a second object
    * save one layout over them and load again
    * verify both reads and that no stale entry is left in the store
    """
    layouts = (
        RootLayout("By author", {"tutorial": ("{authors}/{title}",)}, {"authors": "Unknown"}),
        RootLayout("Flat", {"*": ("*",)}, {}),
    )
    settings = RootCatalogSettings()
    settings.default_layouts = layouts
    settings.save(stored)  # type: ignore[arg-type]
    reloaded = RootCatalogSettings()
    reloaded.load(stored)  # type: ignore[arg-type]
    assert reloaded.default_layouts == layouts

    settings.default_layouts = layouts[1:]
    settings.save(stored)  # type: ignore[arg-type]
    again = RootCatalogSettings()
    again.load(stored)  # type: ignore[arg-type]

    assert again.default_layouts == layouts[1:]
    stored.beginGroup(GROUP)
    assert stored.value(f"{DEFAULT_LAYOUTS_KEY}/2/{LABEL_KEY}") is None
    stored.endGroup()


def test_an_empty_list_of_layouts_reads_back_as_the_seed(stored: FakeSettings) -> None:
    """A root made from a folder always needs a layout, so a list saved empty reads back as the shipped one.

    **Test steps:**

    * save an empty list and load it into a second object
    * verify the seed
    """
    settings = RootCatalogSettings()
    settings.default_layouts = ()
    settings.save(stored)  # type: ignore[arg-type]
    reloaded = RootCatalogSettings()

    reloaded.load(stored)  # type: ignore[arg-type]

    assert reloaded.default_layouts == DEFAULT_ROOT_LAYOUTS


@mark.parametrize("text", [param("not json", id="not-json"), param('{"*": 1}', id="not-strings")])
def test_a_layout_map_that_cannot_be_read_is_dropped_and_logged(
    stored: FakeSettings, caplog: LogCaptureFixture, text: str
) -> None:
    """A map edited by hand into something no root can hold is read as empty, and the log says so; the layout stays.

    **Test steps:**

    * save a layout, then overwrite its layouts with ``text``, and load
    * verify the layout is kept with empty layouts and its fallbacks, and the warning
    """
    settings = RootCatalogSettings()
    settings.default_layouts = (RootLayout("Kept", {"*": ("*",)}, {"title": "Untitled"}),)
    settings.save(stored)  # type: ignore[arg-type]
    stored.beginGroup(GROUP)
    stored.setValue(f"{DEFAULT_LAYOUTS_KEY}/1/{LAYOUTS_KEY}", text)
    stored.endGroup()
    reloaded = RootCatalogSettings()

    with caplog.at_level(logging.WARNING, logger=root_catalog_settings.__name__):
        reloaded.load(stored)  # type: ignore[arg-type]

    assert reloaded.default_layouts == (RootLayout("Kept", {}, {"title": "Untitled"}),)
    assert "are not an object of templates" in caplog.text


def test_a_stored_layout_reads_a_string_as_one_template_and_saves_lists(stored: FakeSettings) -> None:
    """A preset holding a plain string for a type reads as one template, and a save writes every type as a list (#638).

    **Test steps:**

    * store a preset whose layouts hold a string and a list of two, and load
    * save it again and read the stored text
    * verify the templates read, and the stored text holding both as lists
    """
    settings = RootCatalogSettings()
    settings.default_layouts = (RootLayout("Kept"),)
    settings.save(stored)  # type: ignore[arg-type]
    stored.beginGroup(GROUP)
    stored.setValue(f"{DEFAULT_LAYOUTS_KEY}/1/{LAYOUTS_KEY}", '{"tutorial": "{title}", "*": ["*", "{title}"]}')
    stored.endGroup()
    reloaded = RootCatalogSettings()
    reloaded.load(stored)  # type: ignore[arg-type]

    assert reloaded.default_layouts[0].layouts == {"tutorial": ("{title}",), "*": ("*", "{title}")}

    reloaded.save(stored)  # type: ignore[arg-type]
    stored.beginGroup(GROUP)
    assert stored.value(f"{DEFAULT_LAYOUTS_KEY}/1/{LAYOUTS_KEY}") == '{"tutorial": ["{title}"], "*": ["*", "{title}"]}'
    stored.endGroup()


@mark.parametrize("text", [param("not json", id="not-json"), param('{"title": 1}', id="not-strings")])
def test_a_fallback_map_that_cannot_be_read_is_dropped_and_logged(
    stored: FakeSettings, caplog: LogCaptureFixture, text: str
) -> None:
    """Fallbacks edited by hand into something no root can hold are read as empty, and the log says so; the layout
    stays.

    **Test steps:**

    * save a layout, then overwrite its fallbacks with ``text``, and load
    * verify the layout is kept with its layouts and no fallbacks, and the warning
    """
    settings = RootCatalogSettings()
    settings.default_layouts = (RootLayout("Kept", {"*": ("*",)}, {"title": "Untitled"}),)
    settings.save(stored)  # type: ignore[arg-type]
    stored.beginGroup(GROUP)
    stored.setValue(f"{DEFAULT_LAYOUTS_KEY}/1/{FALLBACKS_KEY}", text)
    stored.endGroup()
    reloaded = RootCatalogSettings()

    with caplog.at_level(logging.WARNING, logger=root_catalog_settings.__name__):
        reloaded.load(stored)  # type: ignore[arg-type]

    assert reloaded.default_layouts == (RootLayout("Kept", {"*": ("*",)}, {}),)
    assert "fallbacks are not an object of strings" in caplog.text
