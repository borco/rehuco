"""Tests for ExcludedFilesSettings: the one pattern list the size scan and the checksums share (#226).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import excluded_files_settings
from rehuco_agent.settings.excluded_files_settings import (
    ExcludedFilesSettings,
    normalize_patterns,
    shared_excluded_files_settings,
)
from rehuco_core import EXCLUDED_FILE_PATTERNS, INFO_REHU_FILENAME, enumerate_content_files

DIRECTORY: Final = Path("/fake/resource")
DIRECTORY_SCOPED_PATH: Final = DIRECTORY / INFO_REHU_FILENAME


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`ExcludedFilesSettings.load`/:meth:`~ExcludedFilesSettings.save` call them by name.
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
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_excluded_files_settings.cache_clear()
    yield
    shared_excluded_files_settings.cache_clear()


def mock_tree(mocker: MockerFixture, filenames: list[str]) -> None:
    """Mock :data:`DIRECTORY` as a flat directory of ``filenames``, read the way the scanner reads one.

    Mirrors ``test_rehu_content_files.py``'s helper in miniature -- this module only needs a flat
    directory, since what it exercises is the *setting* reaching the scan, not the walk.

    :param mocker: pytest-mock fixture.
    :param filenames: the fake filenames the directory should list.
    """

    class FakeDirEntry:
        """A stand-in for :class:`os.DirEntry`, which cannot be constructed outside a directory read."""

        def __init__(self, name: str) -> None:
            self.name = name

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            """Nothing in this fixture's directory is a subdirectory."""
            del follow_symlinks
            return False

        def is_file(self, *, follow_symlinks: bool = True) -> bool:
            """Everything in this fixture's directory is a regular file."""
            del follow_symlinks
            return True

    class FakeScandir:
        """What :func:`os.scandir` returns: an iterator that is also a context manager."""

        def __enter__(self) -> Iterator[FakeDirEntry]:
            return iter([FakeDirEntry(name) for name in filenames])

        def __exit__(self, *_exception: object) -> None:
            return None

    mocker.patch("rehuco_core.rehu_content_files.os.scandir", return_value=FakeScandir())


# endregion

# region normalize_patterns


def test_normalizes_trimming_blanks_and_duplicates() -> None:
    """Whitespace is trimmed, blanks and repeats are dropped, and the order first seen is kept.

    **Test steps:**

    * normalize a list holding padding, a blank entry and a repeat
    * verify the result is the distinct trimmed patterns in their original order
    """
    assert normalize_patterns(["  *.tmp ", "", "Thumbs.db", "*.tmp"]) == ("*.tmp", "Thumbs.db")


def test_patterns_are_kept_case_sensitively() -> None:
    """Storage keeps what was typed: matching lower-cases both sides, so the stored casing is the user's.

    **Test steps:**

    * normalize ``["Thumbs.db"]``
    * verify the casing survived
    """
    assert normalize_patterns(["Thumbs.db"]) == ("Thumbs.db",)


def test_a_bare_string_reads_as_a_one_element_list() -> None:
    """The ``QSettings`` ini backend hands a single-element list back as a plain string, not as garbage.

    **Test steps:**

    * normalize the bare string ``"*.tmp"``
    * verify it became a one-element tuple rather than falling back to the defaults
    """
    assert normalize_patterns("*.tmp") == ("*.tmp",)


@mark.parametrize(
    "value",
    [None, [], (), "", "   ", ["", "  "], 42, {"patterns": ["*.tmp"]}],
    ids=["absent", "empty-list", "empty-tuple", "empty-string", "blank-string", "blank-entries", "int", "dict"],
)
def test_a_value_naming_no_pattern_falls_back_to_the_defaults(value: object) -> None:
    """Absent, empty and garbage all yield the shipped defaults, never *no exclusions* (#226).

    Falling back to an empty set would silently start counting every share's ``Thumbs.db``, churning
    sizes and checksums on resources nobody touched.

    **Test steps:**

    * normalize each value that names no usable pattern
    * verify the shipped defaults came back
    """
    assert normalize_patterns(value) == EXCLUDED_FILE_PATTERNS


def test_non_string_entries_are_dropped_rather_than_rejected() -> None:
    """One unusable entry in an otherwise usable list costs that entry, not the whole list.

    **Test steps:**

    * normalize a list mixing a pattern with a number and ``None``
    * verify only the pattern survived
    """
    assert normalize_patterns(["*.tmp", 7, None]) == ("*.tmp",)


# endregion

# region the effective set


def test_a_fresh_instance_resolves_to_the_defaults() -> None:
    """Nothing stored means the shipped patterns are in force, not an empty exclusion set.

    **Test steps:**

    * build a settings object without loading anything
    * verify its effective set is the shipped defaults
    """
    assert ExcludedFilesSettings().excluded_file_patterns == EXCLUDED_FILE_PATTERNS


def test_stored_patterns_replace_the_defaults_entirely() -> None:
    """A custom list is the whole answer, not an addition to the shipped one.

    **Test steps:**

    * build a settings object holding one pattern
    * verify its effective set is exactly that pattern
    """
    assert ExcludedFilesSettings(patterns=("*.tmp",)).excluded_file_patterns == ("*.tmp",)


def test_an_emptied_list_resolves_back_to_the_defaults() -> None:
    """A user who empties the list gets the shipped patterns, not silent checksum churn (#226).

    **Test steps:**

    * build a settings object with an empty pattern tuple
    * verify its effective set is the shipped defaults
    """
    assert ExcludedFilesSettings(patterns=()).excluded_file_patterns == EXCLUDED_FILE_PATTERNS


# endregion

# region persistence


def test_load_falls_back_to_the_defaults_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields the shipped patterns.

    **Test steps:**

    * load a settings object from empty storage
    * verify both the stored and the effective patterns are the shipped defaults
    """
    loaded = ExcludedFilesSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == EXCLUDED_FILE_PATTERNS
    assert loaded.excluded_file_patterns == EXCLUDED_FILE_PATTERNS


def test_patterns_round_trip_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back, in order (#226).

    **Test steps:**

    * save a settings object holding three patterns
    * load a second object from the same storage
    * verify it holds the same three, in the same order
    """
    saved = ExcludedFilesSettings(patterns=("*.tmp", "Thumbs.db", "._*"))
    saved.save(settings)  # type: ignore[arg-type]

    loaded = ExcludedFilesSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == ("*.tmp", "Thumbs.db", "._*")


def test_patterns_are_saved_as_a_list(settings: FakeSettings) -> None:
    """Stored as a list, which is what the ``QSettings`` ini backend can round-trip.

    **Test steps:**

    * save a settings object holding two patterns
    * verify the raw stored value is a ``list``, not a tuple
    """
    ExcludedFilesSettings(patterns=("*.tmp", "Thumbs.db")).save(settings)  # type: ignore[arg-type]

    assert settings.value("excluded_files/patterns") == ["*.tmp", "Thumbs.db"]


def test_load_repairs_an_unusable_stored_value(settings: FakeSettings) -> None:
    """A stored value a list was never written as yields the defaults rather than propagating.

    **Test steps:**

    * seed storage with a number under the patterns key
    * load a settings object from it
    * verify the shipped defaults came back
    """
    settings.setValue("excluded_files/patterns", 42)

    loaded = ExcludedFilesSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == EXCLUDED_FILE_PATTERNS


# endregion

# region the shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The singleton reads persistent storage on first call and hands the same object back after.

    **Test steps:**

    * seed storage with one pattern and patch ``persistent_settings`` to return it
    * call the shared accessor twice
    * verify both calls returned the same object, holding the seeded pattern
    """
    settings.setValue("excluded_files/patterns", ["*.tmp"])
    mocker.patch.object(excluded_files_settings, "persistent_settings", return_value=settings)

    first = shared_excluded_files_settings()
    second = shared_excluded_files_settings()

    assert first is second
    assert first.patterns == ("*.tmp",)


def test_the_shared_set_is_what_a_content_scan_leaves_out(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The set really is injected: changing it changes what a scan counts, proving nothing hardcodes it.

    This is the invariant the whole page exists for -- the size scan and the checksums are handed *this*
    tuple, so neither can count a file the other skips.

    **Test steps:**

    * mock a directory-scoped tree holding ``notes.txt`` and ``video.mp4``
    * scan it under the shared settings' effective set, then add ``*.txt`` and scan again
    * verify the first scan counted both files and the second dropped ``notes.txt``
    """
    mocker.patch.object(excluded_files_settings, "persistent_settings", return_value=settings)
    mock_tree(mocker, ["notes.txt", "video.mp4"])
    shared = shared_excluded_files_settings()

    before = enumerate_content_files(DIRECTORY_SCOPED_PATH, shared.excluded_file_patterns)
    shared.patterns = (*EXCLUDED_FILE_PATTERNS, "*.txt")
    after = enumerate_content_files(DIRECTORY_SCOPED_PATH, shared.excluded_file_patterns)

    assert [path.name for path in before.files] == ["notes.txt", "video.mp4"]
    assert [path.name for path in after.files] == ["video.mp4"]


# endregion
