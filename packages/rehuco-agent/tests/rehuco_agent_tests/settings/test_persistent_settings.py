"""Tests for the app-wide persistent settings storage helper."""

from pathlib import Path

from PySide6.QtCore import QSettings
from pytest import mark
from pytest_mock import MockerFixture
from rehuco_agent.settings.persistent_settings import (
    APPLICATION_NAME,
    cache_folder,
    config_folder,
    folders,
    persistent_settings,
    read_stored_strings,
    set_settings_dir,
    settings_dir,
)
from rehuco_core import AppFolders


def test_persistent_settings_is_scoped_to_this_app() -> None:
    """The returned ``QSettings`` is an ini-format store, in rehuco-agent's ``.ini`` in the settings folder (#412).

    **Test steps:**

    * call ``persistent_settings``
    * verify its format and that its file is named after the app, in the settings folder
    """
    settings = persistent_settings()

    assert settings.format() == QSettings.Format.IniFormat
    assert Path(settings.fileName()) == folders().settings / f"{APPLICATION_NAME}.ini"


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


def test_the_folders_are_the_platforms_when_no_settings_dir_is_set(tmp_path: Path, mocker: MockerFixture) -> None:
    """Without a settings dir, ``config_folder`` and ``cache_folder`` answer core's data and cache folders (#412).

    **Test steps:**

    * make core's ``app_folders`` answer three distinct folders
    * verify the data folder is ``config_folder``, the cache folder is ``cache_folder``, and the ``.ini`` is in the
      settings folder
    """
    platform = AppFolders(settings=tmp_path / "config", data=tmp_path / "data", cache=tmp_path / "cache")
    mocker.patch("rehuco_agent.settings.persistent_settings.app_folders", return_value=platform)

    assert config_folder() == tmp_path / "data"
    assert cache_folder() == tmp_path / "cache"
    assert Path(persistent_settings().fileName()) == tmp_path / "config" / f"{APPLICATION_NAME}.ini"


def test_no_settings_dir_is_in_effect_by_default() -> None:
    """A run without ``--settings-dir`` uses the platform's locations (#494).

    **Test steps:**

    * ask for the settings dir with none set
    * verify there is none
    """
    assert settings_dir() is None


def test_a_settings_dir_holds_the_ini_the_state_and_the_cache_alike(tmp_path: Path) -> None:
    """Under a settings dir all three folders are the dir itself, the layout of Windows and macOS (#494, #412).

    **Test steps:**

    * put the settings under a temporary folder
    * verify the ini is an ini-format file named after the app in that folder
    * verify the config folder and the cache folder are that folder
    """
    set_settings_dir(tmp_path)

    settings = persistent_settings()

    assert settings_dir() == tmp_path
    assert settings.format() == QSettings.Format.IniFormat
    assert Path(settings.fileName()) == tmp_path / f"{APPLICATION_NAME}.ini"
    assert config_folder() == tmp_path
    assert cache_folder() == tmp_path


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


def test_clearing_the_settings_dir_returns_to_the_platforms_locations(tmp_path: Path, mocker: MockerFixture) -> None:
    """``None`` undoes the override (#494).

    **Test steps:**

    * set a settings dir, then clear it
    * verify none is in effect and the folders are core's again
    """
    platform = AppFolders(settings=tmp_path / "config", data=tmp_path / "data", cache=tmp_path / "cache")
    mocker.patch("rehuco_agent.settings.persistent_settings.app_folders", return_value=platform)
    set_settings_dir(tmp_path / "elsewhere")
    set_settings_dir(None)

    assert settings_dir() is None
    assert folders() == platform
