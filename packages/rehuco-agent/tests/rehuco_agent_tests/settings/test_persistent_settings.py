"""Tests for the app-wide persistent settings storage helper."""

import logging
from pathlib import Path

from PySide6.QtCore import QSettings
from pytest import LogCaptureFixture, fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings.persistent_settings import (
    APPLICATION_NAME,
    CONFIG_CACHE_FOLDER_NAME,
    ORGANIZATION_NAME,
    cache_folder,
    config_folder,
    persistent_settings,
    read_stored_strings,
    set_settings_dir,
    settings_dir,
)


def test_persistent_settings_is_scoped_to_this_app() -> None:
    """The returned ``QSettings`` is an ini-format, per-user store identified as rehuco-agent's.

    **Test steps:**

    * call ``persistent_settings``
    * verify its format, scope, organization, and application name
    """
    settings = persistent_settings()

    assert settings.format() == QSettings.Format.IniFormat
    assert settings.scope() == QSettings.Scope.UserScope
    assert settings.organizationName() == ORGANIZATION_NAME
    assert settings.applicationName() == APPLICATION_NAME


def test_a_stored_list_is_read_back_verbatim() -> None:
    """Entries come back in the order and spelling they were stored in -- nothing is trimmed here.

    **Test steps:**

    * read a stored list holding padding and mixed case
    * verify every entry survives untouched
    """
    assert read_stored_strings(["  Padded  ", "MiXeD", ""]) == ("  Padded  ", "MiXeD", "")


def test_a_bare_string_is_read_as_the_one_element_list_it_was_stored_as() -> None:
    """The ini backend writes a single-element list as a plain string and hands it back that way, so a
    one-entry list must not read as no list at all.

    **Test steps:**

    * read a bare string
    * verify it came back as exactly one entry
    """
    assert read_stored_strings("only") == ("only",)


def test_a_non_string_inside_a_stored_list_is_skipped_not_stringified() -> None:
    """Reading a stray ``7`` as ``"7"`` would invent an entry nobody typed.

    **Test steps:**

    * read a list holding a number between two real entries
    * verify only the two entries survive
    """
    assert read_stored_strings(["a", 7, "b"]) == ("a", "b")


@mark.parametrize("value", [None, 7, {"a": True}])
def test_a_value_of_a_type_no_list_was_stored_as_reads_as_nothing(value: object) -> None:
    """Absent, or of a type nothing ever wrote: either way there are no entries to read, and what
    that means is left to the section reading them.

    **Test steps:**

    * read each of an absent, numeric and mapping value
    * verify each yields no entries
    """
    assert not read_stored_strings(value)


def test_the_cache_folder_is_this_apps_own_under_the_local_cache_location(mocker: MockerFixture) -> None:
    """A rebuildable cache lives in the platform's local cache directory, organization then application --
    never beside the ``.ini``, which a roaming profile carries between machines (#377).

    **Test steps:**

    * point Qt's generic cache location at a fake folder
    * verify the cache folder is that folder's organization/application subfolder
    """
    mocker.patch(
        "rehuco_agent.settings.persistent_settings.QStandardPaths.writableLocation", return_value="/fake/cache"
    )

    assert cache_folder() == Path("/fake/cache") / ORGANIZATION_NAME / APPLICATION_NAME


def test_the_cache_folder_falls_back_under_the_config_folder_when_the_host_knows_no_cache_location(
    mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """Qt may answer nothing; a relative path would then land wherever the app was launched from, so the
    config folder is used instead, and the fallback is logged (#377).

    **Test steps:**

    * make Qt's generic cache location empty and the config folder known
    * verify the cache folder is a ``cache`` folder under the config folder, and a warning was logged
    """
    mocker.patch("rehuco_agent.settings.persistent_settings.QStandardPaths.writableLocation", return_value="")
    mocker.patch("rehuco_agent.settings.persistent_settings.config_folder", return_value=Path("/fake/config"))

    with caplog.at_level(logging.WARNING):
        folder = cache_folder()

    assert folder == Path("/fake/config/cache")
    assert "No cache location" in caplog.text


@fixture(name="real_settings")
def fixture_real_settings(mocker: MockerFixture) -> None:
    """Put the real ``persistent_settings`` back where ``config_folder`` looks it up.

    The suite swaps it for an in-memory stand-in in that module (see ``conftest``), which would hide the very
    thing these tests are about: where the real store goes under a settings dir (#494).
    """
    mocker.patch("rehuco_agent.settings.persistent_settings.persistent_settings", new=persistent_settings)


def test_no_settings_dir_is_in_effect_by_default() -> None:
    """A run without ``--settings-dir`` uses the platform's locations (#494).

    **Test steps:**

    * ask for the settings dir with none set
    * verify there is none
    """
    assert settings_dir() is None


def test_a_settings_dir_holds_the_ini_beside_the_apps_own_folder(tmp_path: Path, real_settings: None) -> None:
    """The layout under the folder is the platform's own: ``rehuco-agent.ini`` beside ``rehuco-agent/`` (#494).

    **Test steps:**

    * put the settings under a temporary folder
    * verify the ini is an ini-format file named after the app in that folder
    * verify the config folder is the app's folder beside it
    """
    del real_settings
    set_settings_dir(tmp_path)

    settings = persistent_settings()

    assert settings_dir() == tmp_path
    assert settings.format() == QSettings.Format.IniFormat
    assert Path(settings.fileName()) == tmp_path / f"{APPLICATION_NAME}.ini"
    assert config_folder() == tmp_path / APPLICATION_NAME


def test_a_value_saved_under_a_settings_dir_lands_in_its_ini(tmp_path: Path) -> None:
    """The override moves the real store, not only the reported name (#494).

    **Test steps:**

    * put the settings under a temporary folder and save a value
    * verify the ini file exists there and reads the value back
    """
    set_settings_dir(tmp_path)
    settings = persistent_settings()
    settings.setValue("section/key", "value")
    settings.sync()

    assert (tmp_path / f"{APPLICATION_NAME}.ini").is_file()
    assert persistent_settings().value("section/key") == "value"


def test_a_settings_dir_keeps_the_cache_inside_the_apps_folder(tmp_path: Path, real_settings: None) -> None:
    """Nothing is left in the platform's cache location, and the cache sits in the app's folder like the rest (#494).

    **Test steps:**

    * put the settings under a temporary folder
    * verify the cache folder is ``cache`` under the config folder
    """
    del real_settings
    set_settings_dir(tmp_path)

    assert cache_folder() == tmp_path / APPLICATION_NAME / CONFIG_CACHE_FOLDER_NAME


def test_clearing_the_settings_dir_returns_to_the_platforms_locations(tmp_path: Path, mocker: MockerFixture) -> None:
    """``None`` undoes the override (#494).

    **Test steps:**

    * set a settings dir, then clear it
    * verify none is in effect and the cache is under the platform's cache location again
    """
    mocker.patch(
        "rehuco_agent.settings.persistent_settings.QStandardPaths.writableLocation", return_value="/fake/cache"
    )
    set_settings_dir(tmp_path)
    set_settings_dir(None)

    assert settings_dir() is None
    assert cache_folder() == Path("/fake/cache") / ORGANIZATION_NAME / APPLICATION_NAME
