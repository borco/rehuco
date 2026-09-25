"""Tests for ScreenshotPatternsSettings: the patterns a legacy `.tc`'s screenshots are recognized by
(#53, #287).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_main_window_settings.py`` for
the same rationale) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
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
from rehuco_core import SCREENSHOT_NAME_PATTERNS

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


def test_an_uncompilable_pattern_is_kept() -> None:
    """Normalizing is the stored shape, and a broken row is stored: dropping it on Apply would make a
    typo cost the whole row (#322). Only blank rows go; the effective set is what skips it.

    **Test steps:**

    * normalize a list holding a blank pattern, a broken one, a two-group one, and a good one
    * verify the blank one alone is dropped
    """
    patterns = normalize_screenshot_name_patterns(["", "[", r"(\d+)-(\d+)", r"^shot-(\d+)$"])

    assert patterns == ("[", r"(\d+)-(\d+)", r"^shot-(\d+)$")


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
    [None, [], (), "", "   ", ["", "  "], 42],
    ids=["absent", "empty-list", "empty-tuple", "empty-string", "blank-string", "blank-entries", "int"],
)
def test_a_value_naming_no_pattern_falls_back_to_the_defaults(value: object) -> None:
    """Absent, empty and garbage all yield the shipped defaults, never *recognize nothing* (#287).

    Falling back to an empty set would silently convert every legacy resource without carrying a
    single screenshot across.

    **Test steps:**

    * normalize each value that names no pattern at all
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

# region the effective set


def test_a_fresh_instance_resolves_to_the_defaults() -> None:
    """Nothing stored means the shipped patterns are in force.

    **Test steps:**

    * build a settings object without loading anything
    * verify the effective set is the defaults
    """
    fresh = ScreenshotPatternsSettings()

    assert tuple(pattern.pattern for pattern in fresh.screenshot_name_patterns) == DEFAULT_PATTERN_STRINGS


def test_stored_values_replace_the_defaults_entirely() -> None:
    """A custom list is the whole answer, not an addition to the shipped one.

    **Test steps:**

    * build a settings object holding one pattern
    * verify the effective set is exactly that
    """
    stored = ScreenshotPatternsSettings()
    stored.patterns = ("^cover$",)

    assert [pattern.pattern for pattern in stored.screenshot_name_patterns] == ["^cover$"]


def test_an_uncompilable_row_is_stored_but_not_effective() -> None:
    """The two views of one list (#322): the page stages against the stored one, which keeps a broken
    row to fix; a scan reads the effective one, which skips it.

    **Test steps:**

    * store a list holding a good pattern and one that does not compile
    * verify ``stored_patterns`` holds both and ``screenshot_name_patterns`` only the good one
    """
    stored = ScreenshotPatternsSettings()
    stored.patterns = ("[", "^cover$")

    assert stored.stored_patterns == ("[", "^cover$")
    assert [pattern.pattern for pattern in stored.screenshot_name_patterns] == ["^cover$"]


def test_a_list_with_no_compilable_row_is_effectively_the_defaults() -> None:
    """A stored list that compiles nothing recognizes the shipped set rather than nothing -- while still
    showing the broken rows on the page.

    **Test steps:**

    * store a list of nothing but broken patterns
    * verify ``stored_patterns`` keeps them and the effective set is the shipped one
    """
    stored = ScreenshotPatternsSettings()
    stored.patterns = ("[", r"(\d+)-(\d+)")

    assert stored.stored_patterns == ("[", r"(\d+)-(\d+)")
    assert stored.screenshot_name_patterns == SCREENSHOT_NAME_PATTERNS


# endregion

# region reactivity


def test_patterns_changed_fires_on_assignment(mocker: MockerFixture) -> None:
    """A reactive ``QObject``, not the plain dataclass this used to be (#281): assigning
    :attr:`ScreenshotPatternsSettings.patterns` fires ``patterns_changed``, the seam
    `RehuDocumentModel` follows to reinstall an open document's image scanner.

    **Test steps:**

    * connect a spy to ``patterns_changed`` on a fresh instance
    * assign a new value to ``patterns``
    * verify the spy fired with the new value
    """
    settings = ScreenshotPatternsSettings()
    spy = mocker.Mock()
    settings.patterns_changed.connect(spy)  # type: ignore[attr-defined]

    settings.patterns = ("^cover$",)

    spy.assert_called_once_with(("^cover$",))


# endregion

# region persistence


def test_load_falls_back_to_the_defaults_on_a_fresh_install(settings: FakeSettings) -> None:
    """With nothing persisted, loading yields the shipped patterns.

    **Test steps:**

    * load a settings object from empty storage
    * verify the stored field is the defaults
    """
    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == DEFAULT_PATTERN_STRINGS


def test_the_patterns_round_trip_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back, in order.

    **Test steps:**

    * save a settings object holding two patterns
    * load a second object from the same storage
    * verify it holds the same, in the same order
    """
    saved = ScreenshotPatternsSettings()
    saved.patterns = (r"^shot-(\d+)$", "^cover$")
    saved.save(settings)  # type: ignore[arg-type]

    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == (r"^shot-(\d+)$", "^cover$")


def test_the_patterns_are_saved_as_a_list(settings: FakeSettings) -> None:
    """Stored as a list, which is what the ``QSettings`` ini backend can round-trip.

    **Test steps:**

    * save a settings object holding two patterns
    * verify the raw stored value is a ``list``, not a tuple
    """
    stored = ScreenshotPatternsSettings()
    stored.patterns = ("^cover$", "^file$")
    stored.save(settings)  # type: ignore[arg-type]

    assert settings.value("screenshot_patterns/patterns") == ["^cover$", "^file$"]


def test_a_samples_key_an_earlier_build_wrote_is_read_back(settings: FakeSettings) -> None:
    """The try-it samples live under the key #287 first wrote them to, so a list typed back then comes
    back rather than being orphaned.

    **Test steps:**

    * seed storage with a pattern list and the samples key
    * load a settings object from it
    * verify both came back
    """
    settings.setValue("screenshot_patterns/patterns", ["^cover$"])
    settings.setValue("screenshot_patterns/samples", ["shot-3.jpg", "foo.jpg"])

    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == ("^cover$",)
    assert loaded.samples == ("shot-3.jpg", "foo.jpg")


def test_the_samples_round_trip_through_save_with_the_patterns(settings: FakeSettings) -> None:
    """One ``save``, one Apply: the patterns and the try-it samples go to storage together.

    **Test steps:**

    * save an object holding patterns and samples
    * verify both keys were written, and a fresh load reads them back
    """
    saved = ScreenshotPatternsSettings()
    saved.patterns = ("^cover$",)
    saved.samples = ("a.jpg", "b.jpg")
    saved.save(settings)  # type: ignore[arg-type]

    assert settings.value("screenshot_patterns/patterns") == ["^cover$"]
    assert settings.value("screenshot_patterns/samples") == ["a.jpg", "b.jpg"]

    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]
    assert loaded.samples == ("a.jpg", "b.jpg")


@mark.parametrize("stored", [None, []], ids=["absent", "emptied"])
def test_no_stored_samples_read_as_the_shipped_ones(settings: FakeSettings, stored: object) -> None:
    """Nothing to show reads as the shipped samples, the way an emptied pattern list reads as the
    shipped patterns.

    **Test steps:**

    * seed storage with no usable samples
    * verify loading yields :data:`DEFAULT_SAMPLES`
    """
    if stored is not None:
        settings.setValue("screenshot_patterns/samples", stored)

    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.samples == DEFAULT_SAMPLES


@mark.parametrize(
    ("samples", "expected"),
    [
        (["a.jpg", "", "  ", "b.jpg"], ("a.jpg", "b.jpg")),
        (["", " "], DEFAULT_SAMPLES),
        ("a.jpg", ("a.jpg",)),
        (["a.jpg", "a.jpg"], ("a.jpg", "a.jpg")),
    ],
    ids=["blanks-dropped", "all-blank", "bare-string", "duplicates-kept"],
)
def test_normalize_screenshot_samples(samples: object, expected: tuple[str, ...]) -> None:
    """Blank entries go and order is kept -- a blank row is an insert still open for typing, not a
    sample -- and a list left with nothing is the shipped one. Duplicates are left alone: two rows
    naming one file are harmless in a preview.

    **Test steps:**

    * normalize each input
    * verify the stored shape
    """
    assert normalize_screenshot_samples(samples) == expected


def test_load_repairs_an_unusable_stored_value(settings: FakeSettings) -> None:
    """A stored value a list was never written as yields the defaults rather than propagating.

    **Test steps:**

    * seed storage with a number under the patterns key
    * load a settings object from it
    * verify the defaults came back
    """
    settings.setValue("screenshot_patterns/patterns", 42)

    loaded = ScreenshotPatternsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == DEFAULT_PATTERN_STRINGS


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
