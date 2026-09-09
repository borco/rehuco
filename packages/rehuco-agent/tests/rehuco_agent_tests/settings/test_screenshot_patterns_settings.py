"""Tests for ScreenshotPatternsSettings: the patterns a legacy `.tc`'s screenshots are recognized by,
and the try-it samples kept beside them (#53, #287).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import screenshot_patterns_settings
from rehuco_agent.settings.screenshot_patterns_settings import (
    DEFAULT_SAMPLES,
    ScreenshotPatternsSettings,
    normalize_screenshot_name_patterns,
    normalize_screenshot_samples,
    pattern_is_valid,
    shared_screenshot_patterns_settings,
)
from rehuco_core import SCREENSHOT_NAME_PATTERNS, ScreenshotNamePatterns

DEFAULT_PATTERN_STRINGS = tuple(pattern.pattern for pattern in SCREENSHOT_NAME_PATTERNS)


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API, since :meth:`ScreenshotPatternsSettings.load`/:meth:`~ScreenshotPatternsSettings.save` call
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
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_screenshot_patterns_settings.cache_clear()
    yield
    shared_screenshot_patterns_settings.cache_clear()


# endregion

# region pattern_is_valid


def test_a_blank_pattern_is_not_valid() -> None:
    """A blank pattern is unusable regardless of whether it compiles."""
    assert pattern_is_valid("") is False
    assert pattern_is_valid("   ") is False


def test_a_syntactically_broken_pattern_is_not_valid() -> None:
    """A regex that fails to compile is not valid."""
    assert pattern_is_valid("[") is False


def test_a_pattern_with_two_capture_groups_is_not_valid() -> None:
    """More than one capture group leaves the slot ambiguous, so it is refused."""
    assert pattern_is_valid(r"(\d+)-(\d+)") is False


def test_a_well_formed_pattern_is_valid() -> None:
    """A blank-free, compiling, at-most-one-group pattern is usable."""
    assert pattern_is_valid(r"^sample-(\d+)$") is True
    assert pattern_is_valid(r"^cover$") is True


# endregion

# region normalize_screenshot_name_patterns


def test_patterns_are_trimmed_and_order_is_kept() -> None:
    """Order is what decides which pattern matches first, so normalizing never reorders.

    **Test steps:**

    * normalize two patterns carrying surrounding whitespace
    * verify both are trimmed and the order is unchanged
    """
    patterns = normalize_screenshot_name_patterns([" ^shot-(\\d+)$ ", " ^cover$ "])

    assert patterns == (r"^shot-(\d+)$", "^cover$")


def test_an_uncompilable_pattern_is_dropped() -> None:
    """The page flags a half-typed pattern rather than refusing the keystroke, so saving is where it goes.

    **Test steps:**

    * normalize a list holding a blank pattern, a broken one, a two-group one, and a good one
    * verify only the good one survives
    """
    patterns = normalize_screenshot_name_patterns(["", "[", r"(\d+)-(\d+)", r"^shot-(\d+)$"])

    assert patterns == (r"^shot-(\d+)$",)


def test_a_duplicate_pattern_is_dropped_by_exact_string_match() -> None:
    """Regex casing matters syntactically, so duplicates are dropped by exact string, not
    case-insensitively.

    **Test steps:**

    * normalize a list holding the same pattern twice, and once again differing only in case
    * verify the exact repeat is dropped and the case-differing one survives as its own entry
    """
    patterns = normalize_screenshot_name_patterns(["^cover$", "^cover$", "^COVER$"])

    assert patterns == ("^cover$", "^COVER$")


def test_a_bare_string_reads_as_a_one_element_list() -> None:
    """The ``QSettings`` ini backend hands a single-element list back as a plain string, not as garbage.

    **Test steps:**

    * normalize the bare string ``"^cover$"``
    * verify it became a one-element tuple rather than falling back to the defaults
    """
    assert normalize_screenshot_name_patterns("^cover$") == ("^cover$",)


@mark.parametrize(
    "value",
    [None, [], (), "", "   ", ["", "  "], 42, ["["]],
    ids=["absent", "empty-list", "empty-tuple", "empty-string", "blank-string", "blank-entries", "int", "all-broken"],
)
def test_a_value_naming_no_pattern_falls_back_to_the_defaults(value: object) -> None:
    """Absent, empty and garbage all yield the shipped defaults, never *recognize nothing* (#287).

    Falling back to an empty set would silently convert every legacy resource without carrying a
    single screenshot across.

    **Test steps:**

    * normalize each value that names no usable pattern
    * verify the shipped defaults came back
    """
    assert normalize_screenshot_name_patterns(value) == DEFAULT_PATTERN_STRINGS


def test_non_string_entries_are_dropped_rather_than_rejected() -> None:
    """One unusable entry in an otherwise usable list costs that entry, not the whole list.

    **Test steps:**

    * normalize a list mixing a pattern with a number and ``None``
    * verify only the pattern survived
    """
    assert normalize_screenshot_name_patterns(["^cover$", 7, None]) == ("^cover$",)


# endregion

# region normalize_screenshot_samples


def test_the_seeded_samples_are_shipped_pattern_matches() -> None:
    """The seeded samples are a helpful starting point: real matches, not arbitrary text.

    **Test steps:**

    * ask the shipped patterns to recognize every seeded sample's stem
    """
    patterns = ScreenshotNamePatterns(SCREENSHOT_NAME_PATTERNS)

    assert all(patterns.recognizes(Path(sample).stem) for sample in DEFAULT_SAMPLES)


def test_samples_are_trimmed_deduplicated_and_kept_in_order() -> None:
    """A sample is a name as typed: trimmed, once, in the order given -- nothing about it is validated.

    **Test steps:**

    * normalize a list carrying whitespace, a blank, and an exact repeat
    * verify the survivors, in order
    """
    samples = normalize_screenshot_samples([" shot-3.jpg ", "", "cover.png", "shot-3.jpg", "  "])

    assert samples == ("shot-3.jpg", "cover.png")


@mark.parametrize(
    "value",
    [None, [], "", ["", "  "], 42],
    ids=["absent", "empty-list", "empty-string", "blank-entries", "int"],
)
def test_a_value_naming_no_sample_falls_back_to_the_seeded_ones(value: object) -> None:
    """An empty try-it table shows nothing, so nothing stored means the seeded samples (#287).

    **Test steps:**

    * normalize each value that names no sample
    * verify the seeded samples came back
    """
    assert normalize_screenshot_samples(value) == DEFAULT_SAMPLES


# endregion

# region the effective sets


def test_a_fresh_instance_resolves_to_the_defaults() -> None:
    """Nothing stored means the shipped patterns and the seeded samples are in force.

    **Test steps:**

    * build a settings object without loading anything
    * verify both effective sets are the defaults
    """
    fresh = ScreenshotPatternsSettings()

    assert tuple(pattern.pattern for pattern in fresh.screenshot_name_patterns) == DEFAULT_PATTERN_STRINGS
    assert fresh.screenshot_samples == DEFAULT_SAMPLES


def test_stored_values_replace_the_defaults_entirely() -> None:
    """A custom list is the whole answer, not an addition to the shipped one.

    **Test steps:**

    * build a settings object holding one pattern and one sample
    * verify each effective set is exactly that
    """
    stored = ScreenshotPatternsSettings(patterns=("^cover$",), samples=("shot-3.jpg",))

    assert [pattern.pattern for pattern in stored.screenshot_name_patterns] == ["^cover$"]
    assert stored.screenshot_samples == ("shot-3.jpg",)


# endregion

# region persistence


def test_load_falls_back_to_the_defaults_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields the shipped patterns and the seeded samples.

    **Test steps:**

    * load a settings object from empty storage
    * verify both stored fields are the defaults
    """
    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == DEFAULT_PATTERN_STRINGS
    assert loaded.samples == DEFAULT_SAMPLES


def test_both_fields_round_trip_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back, in order, for the patterns and the samples alike (#287).

    **Test steps:**

    * save a settings object holding two patterns and two samples
    * load a second object from the same storage
    * verify it holds the same, in the same order
    """
    saved = ScreenshotPatternsSettings(patterns=(r"^shot-(\d+)$", "^cover$"), samples=("shot-3.jpg", "cover.png"))
    saved.save(settings)  # type: ignore[arg-type]

    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == (r"^shot-(\d+)$", "^cover$")
    assert loaded.samples == ("shot-3.jpg", "cover.png")


def test_both_fields_are_saved_as_lists(settings: FakeSettings) -> None:
    """Stored as lists, which is what the ``QSettings`` ini backend can round-trip.

    **Test steps:**

    * save a settings object holding two patterns and one sample
    * verify each raw stored value is a ``list``, not a tuple
    """
    stored = ScreenshotPatternsSettings(patterns=("^cover$", "^file$"), samples=("cover.jpg",))
    stored.save(settings)  # type: ignore[arg-type]

    assert settings.value("screenshot_patterns/patterns") == ["^cover$", "^file$"]
    assert settings.value("screenshot_patterns/samples") == ["cover.jpg"]


def test_load_repairs_an_unusable_stored_value(settings: FakeSettings) -> None:
    """A stored value a list was never written as yields the defaults rather than propagating.

    **Test steps:**

    * seed storage with a number under each key
    * load a settings object from it
    * verify the defaults came back
    """
    settings.setValue("screenshot_patterns/patterns", 42)
    settings.setValue("screenshot_patterns/samples", 42)

    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == DEFAULT_PATTERN_STRINGS
    assert loaded.samples == DEFAULT_SAMPLES


# endregion

# region the shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The singleton reads persistent storage on first call and hands the same object back after.

    **Test steps:**

    * seed storage with one pattern and patch ``persistent_settings`` to return it
    * call the shared accessor twice
    * verify both calls returned the same object, holding the seeded pattern
    """
    settings.setValue("screenshot_patterns/patterns", ["^cover$"])
    mocker.patch.object(screenshot_patterns_settings, "persistent_settings", return_value=settings)

    first = shared_screenshot_patterns_settings()
    second = shared_screenshot_patterns_settings()

    assert first is second
    assert first.patterns == ("^cover$",)


# endregion
