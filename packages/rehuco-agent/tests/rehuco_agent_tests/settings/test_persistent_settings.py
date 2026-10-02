"""Tests for the app-wide persistent settings storage helper."""

import logging
from pathlib import Path

from PySide6.QtCore import QSettings
from pytest import LogCaptureFixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings.persistent_settings import (
    APPLICATION_NAME,
    ORGANIZATION_NAME,
    cache_folder,
    persistent_settings,
    read_stored_strings,
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
