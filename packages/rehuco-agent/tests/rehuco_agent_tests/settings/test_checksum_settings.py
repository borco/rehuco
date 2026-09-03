"""Tests for ChecksumSettings: what a checksum run is run with (#242).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for the
same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import checksum_settings
from rehuco_agent.settings.checksum_settings import (
    DEFAULT_STALE_DAYS,
    MAX_STALE_DAYS,
    ChecksumSettings,
    read_algorithm,
    read_stale_days,
    shared_checksum_settings,
)
from rehuco_core import DEFAULT_CHECKSUM_ALGORITHM

# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
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


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_checksum_settings.cache_clear()
    yield
    shared_checksum_settings.cache_clear()


# endregion

# region defaults


def test_a_fresh_install_records_under_the_default_algorithm_and_changes_nothing_by_itself() -> None:
    """Both verify toggles are off, so nothing rewrites a record until somebody asks (#242).

    **Test steps:**

    * build a `ChecksumSettings` with no stored values
    * verify the algorithm is the shipped default, both toggles are off and the window is 90 days
    """
    defaults = ChecksumSettings()

    assert defaults.algorithm == DEFAULT_CHECKSUM_ALGORITHM
    assert not defaults.migrate_on_verify
    assert not defaults.create_missing_on_verify
    assert defaults.stale_days == DEFAULT_STALE_DAYS


# endregion

# region reading stored values


def test_an_unknown_stored_algorithm_falls_back_to_the_default() -> None:
    """An ``.ini`` written by a newer build must not stop this one from checksumming anything.

    **Test steps:**

    * read an algorithm name this build does not ship
    * verify the shipped default came back
    """
    assert read_algorithm("blake3") == DEFAULT_CHECKSUM_ALGORITHM


def test_a_known_stored_algorithm_is_kept() -> None:
    """The fallback must not swallow a legitimate choice.

    **Test steps:**

    * read the name of an algorithm this build ships
    * verify it came back unchanged
    """
    assert read_algorithm("crc32") == "crc32"


@mark.parametrize(
    ("stored", "expected"),
    [(0, 0), (90, 90), (1000, 1000), (-5, 0), (5000, MAX_STALE_DAYS), ("30", 30)],
    ids=["zero", "default", "maximum", "negative", "over-maximum", "stored-as-text"],
)
def test_a_stored_window_is_clamped_to_the_range_the_page_offers(stored: object, expected: int) -> None:
    """The ini backend hands numbers back as text, and a hand-edited file can name anything.

    **Test steps:**

    * read each stored value
    * verify it came back inside 0--1000
    """
    assert read_stale_days(stored) == expected


@mark.parametrize("stored", [None, "ninety", [], {}], ids=["absent", "words", "list", "dict"])
def test_a_window_that_is_not_a_number_reads_as_the_default(stored: object) -> None:
    """Garbage selects the shipped window rather than *nothing is ever fresh*, which would re-read a
    catalog on every sweep.

    **Test steps:**

    * read each unusable stored value
    * verify the default window came back
    """
    assert read_stale_days(stored) == DEFAULT_STALE_DAYS


# endregion

# region what a run is handed


def test_the_window_is_whole_days_and_zero_days_is_a_real_window() -> None:
    """``timedelta(0)`` is what makes *nothing is ever fresh* need no special case in core (#242).

    **Test steps:**

    * ask a 90-day and a 0-day setting for the window a run is handed
    * verify both are the plain ``timedelta`` for those days
    """
    assert ChecksumSettings(stale_days=90).stale_after == timedelta(days=90)
    assert ChecksumSettings(stale_days=0).stale_after == timedelta(0)


def test_nothing_is_migrated_while_the_toggle_is_off() -> None:
    """``None`` is how :func:`~rehuco_core.verify_checksums` spells *migrate nothing* (#203).

    **Test steps:**

    * ask a settings object with the toggle off for its migration target
    * verify it is ``None``
    """
    assert ChecksumSettings(algorithm="crc32").migrate_target is None


def test_the_migration_target_is_the_selected_algorithm_when_the_toggle_is_on() -> None:
    """The one place the label's promise -- *update checksums to X* -- becomes the value passed.

    **Test steps:**

    * ask a settings object with the toggle on for its migration target
    * verify it is the selected algorithm
    """
    assert ChecksumSettings(algorithm="crc32", migrate_on_verify=True).migrate_target == "crc32"


# endregion

# region storage


def test_every_value_round_trips_through_storage(settings: FakeSettings) -> None:
    """Including ``last_sweep_root``, which no page edits but which shares this section (#242).

    **Test steps:**

    * save a fully populated settings object
    * load a fresh one from the same storage
    * verify every member came back
    """
    saved = ChecksumSettings(
        algorithm="crc32",
        migrate_on_verify=True,
        create_missing_on_verify=True,
        stale_days=7,
        last_sweep_root="/fake/library",
    )
    saved.save(settings)  # pyright: ignore[reportArgumentType]

    loaded = ChecksumSettings()
    loaded.load(settings)  # pyright: ignore[reportArgumentType]

    assert loaded == saved


def test_loading_from_empty_storage_yields_the_defaults(settings: FakeSettings) -> None:
    """A first run has no stored group at all, and must not read as *migrate everything*.

    **Test steps:**

    * load from storage nothing was ever saved to
    * verify the result equals a default-constructed settings object
    """
    loaded = ChecksumSettings()
    loaded.load(settings)  # pyright: ignore[reportArgumentType]

    assert loaded == ChecksumSettings()


def test_the_shared_instance_is_the_same_object_every_time(mocker: MockerFixture) -> None:
    """The page's Save must be what the next enqueued run reads, not a disconnected copy (#242).

    **Test steps:**

    * mock persistent storage and ask for the shared instance twice
    * verify both calls answered the same object, loaded once
    """
    stored = FakeSettings()
    mocker.patch.object(checksum_settings, "persistent_settings", return_value=stored)

    assert shared_checksum_settings() is shared_checksum_settings()


# endregion
