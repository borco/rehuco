"""Tests for LocationTemplatesSettings: the rename-suggestion pattern lists, one per resource type,
keyed by an open-ended type string rather than an enum of today's three (#322).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_default_layout_settings.py`` for the
same rationale -- groups nest on a prefix stack, and this section enumerates its per-type sub-groups the
same way) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import location_templates_settings
from rehuco_agent.settings.location_templates_settings import (
    DEFAULT_SAMPLE,
    NAME_SUGGESTION_PATTERNS,
    SAMPLE_FIELDS,
    LocationTemplatesSettings,
    normalize_location_templates,
    shared_location_templates_settings,
)
from rehuco_core import (
    KNOWN_PLACEHOLDERS,
    render_location_pattern,
)


# region fixtures
# Mirrors every other settings test's FakeSettings exactly -- kept as a separate copy rather than a
# shared import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/value API.

    Groups nest on a prefix stack, since this section opens one group per type inside its own
    (``location_templates/<type>/patterns``), and it enumerates and removes those child groups.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__prefixes: list[str] = []

    @property
    def __prefix(self) -> str:
        return "".join(self.__prefixes)

    def beginGroup(self, name: str) -> None:  # noqa: N802
        self.__prefixes.append(f"{name}/")

    def endGroup(self) -> None:  # noqa: N802
        if self.__prefixes:
            self.__prefixes.pop()

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__prefix + key] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__prefix + key, default)

    def childGroups(self) -> list[str]:  # noqa: N802
        prefix = self.__prefix
        nested = (key[len(prefix) :] for key in self.__data if key.startswith(prefix))
        return sorted({rest.split("/")[0] for rest in nested if "/" in rest})

    def remove(self, key: str) -> None:
        full = self.__prefix + key
        for stored in list(self.__data):
            if stored == full or stored.startswith(full + "/") or (not key and stored.startswith(full)):
                del self.__data[stored]

    def keys(self) -> list[str]:
        """Every stored key, for asserting on what a save left behind."""
        return sorted(self.__data)


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test (see
    ``test_markdown_rendering_settings.py`` for the full rationale)."""
    shared_location_templates_settings.cache_clear()
    yield
    shared_location_templates_settings.cache_clear()


# endregion

# region the shipped defaults


def test_the_shipped_defaults_render_a_title_only_record_to_one_name() -> None:
    """Every field but the title is optional in the shipped set, so a bare record names itself once
    rather than four ways with empty separators.

    **Test steps:**

    * render each shipped default against a record carrying only a title
    * verify they all render to the title
    """
    bare = {"title": "Intro", "publisher": "", "authors": "", "year": ""}

    assert {render_location_pattern(pattern, bare) for pattern in NAME_SUGGESTION_PATTERNS} == {"Intro"}


# endregion

# region normalize_location_templates


def test_patterns_are_trimmed_and_order_is_kept() -> None:
    """Order decides which suggestion is offered first, so normalizing never reorders.

    **Test steps:**

    * normalize two patterns carrying surrounding whitespace
    * verify both are trimmed and the order is unchanged
    """
    patterns = normalize_location_templates([" {title} ", " {publisher} - {title} "], NAME_SUGGESTION_PATTERNS)

    assert patterns == ("{title}", "{publisher} - {title}")


def test_a_pattern_naming_an_unknown_placeholder_is_kept() -> None:
    """Normalizing is the stored shape, and an invalid row is stored: dropping it on Apply would make a
    typo cost the whole row (#322). Only blank rows go.

    **Test steps:**

    * normalize a list holding a blank pattern, one naming an unknown placeholder, and a good one
    * verify the blank one alone is dropped
    """
    patterns = normalize_location_templates(["", "{title} ({series})", "{title}"], NAME_SUGGESTION_PATTERNS)

    assert patterns == ("{title} ({series})", "{title}")


def test_a_duplicate_pattern_is_dropped_by_exact_string_match() -> None:
    """Duplicates are dropped by exact string match after trimming.

    **Test steps:**

    * normalize a list holding the same pattern twice
    * verify only one copy survives
    """
    patterns = normalize_location_templates(["{title}", "{title}", " {title} "], NAME_SUGGESTION_PATTERNS)

    assert patterns == ("{title}",)


def test_a_bare_string_reads_as_a_one_element_list() -> None:
    """The ``QSettings`` ini backend hands a single-element list back as a plain string, not as garbage.

    **Test steps:**

    * normalize the bare string ``"{title}"``
    * verify it became a one-element tuple rather than falling back to the defaults
    """
    assert normalize_location_templates("{title}", NAME_SUGGESTION_PATTERNS) == ("{title}",)


@mark.parametrize(
    "value",
    [None, [], (), "", "   ", ["", "  "], 42],
    ids=["absent", "empty-list", "empty-tuple", "empty-string", "blank-string", "blank-entries", "int"],
)
def test_a_value_naming_no_pattern_falls_back_to_the_defaults(value: object) -> None:
    """Absent, empty and garbage all yield the passed-in defaults, never *offer nothing*.

    **Test steps:**

    * normalize each value that names no pattern at all
    * verify the passed-in defaults came back
    """
    assert normalize_location_templates(value, NAME_SUGGESTION_PATTERNS) == NAME_SUGGESTION_PATTERNS


# endregion

# region stored_for and patterns_for


def test_an_invalid_row_is_stored_but_not_effective() -> None:
    """The two views of one list (#322): the page stages against the stored one, which keeps a broken
    row to fix; a document reads the effective one, which skips it.

    **Test steps:**

    * store a list holding a good pattern and one naming an unknown placeholder
    * verify ``stored_for`` holds both and ``patterns_for`` only the good one
    """
    settings = LocationTemplatesSettings()
    settings.patterns = {"tutorial": ("{title} ({series})", "{title}")}

    assert settings.stored_for("tutorial") == ("{title} ({series})", "{title}")
    assert settings.patterns_for("tutorial") == ("{title}",)


def test_a_list_with_no_valid_row_is_effectively_the_defaults() -> None:
    """A stored list that renders nothing offers the shipped set rather than nothing -- while still
    showing the broken rows on the page.

    **Test steps:**

    * store a list of nothing but invalid patterns
    * verify ``stored_for`` keeps them and ``patterns_for`` falls back to the defaults
    """
    settings = LocationTemplatesSettings()
    settings.patterns = {"tutorial": ("{title} ({series})", "{title")}

    assert settings.stored_for("tutorial") == ("{title} ({series})", "{title")
    assert settings.patterns_for("tutorial") == NAME_SUGGESTION_PATTERNS


def test_patterns_for_a_never_seen_type_resolves_to_the_shipped_defaults() -> None:
    """A type this settings class has never seen -- including a made-up one from a plugin this build
    knows nothing about -- reads as "nothing stored yet", not an error (#322).

    **Test steps:**

    * build a fresh settings object with nothing stored
    * ask for a type key nobody declared
    * verify the shipped defaults came back
    """
    settings = LocationTemplatesSettings()

    assert settings.patterns_for("some_future_plugin") == NAME_SUGGESTION_PATTERNS


def test_patterns_for_accepts_count_only_when_passed_a_wider_known_set() -> None:
    """`LocationTemplatesSettings` itself knows nothing of plugins (#349) -- the caller decides which
    placeholders a type accepts by what it passes as ``known_placeholders``.

    **Test steps:**

    * store a reference-images row naming ``{count}``
    * verify it is dropped against the default (base-four) known set
    * verify it survives against a set that includes ``count``
    """
    settings = LocationTemplatesSettings()
    settings.patterns = {"reference_images": ("{title} ({count})",)}

    assert settings.patterns_for("reference_images") == NAME_SUGGESTION_PATTERNS
    assert settings.patterns_for("reference_images", KNOWN_PLACEHOLDERS | {"count"}) == ("{title} ({count})",)


def test_patterns_for_a_customized_type_returns_its_own_list_only() -> None:
    """One type's customized list never leaks into another's (#322).

    **Test steps:**

    * customize one type's list on a settings object
    * verify a different type still resolves to the shipped defaults
    """
    settings = LocationTemplatesSettings()
    settings.patterns = {"reference_images": ("{publisher} - {title}",)}

    assert settings.patterns_for("reference_images") == ("{publisher} - {title}",)
    assert settings.patterns_for("tutorial") == NAME_SUGGESTION_PATTERNS


# endregion

# region reactivity


def test_patterns_changed_fires_on_assignment(mocker: MockerFixture) -> None:
    """A reactive ``QObject``: assigning :attr:`LocationTemplatesSettings.patterns` fires
    ``patterns_changed``, the seam `NameSuggestionModel` follows to re-pull an open document's
    suggestions without a reopen (#322).

    **Test steps:**

    * connect a spy to ``patterns_changed`` on a fresh instance
    * assign a new value to ``patterns``
    * verify the spy fired with the new value
    """
    settings = LocationTemplatesSettings()
    spy = mocker.Mock()
    settings.patterns_changed.connect(spy)  # type: ignore[attr-defined]

    settings.patterns = {"tutorial": ("{title}",)}

    spy.assert_called_once_with({"tutorial": ("{title}",)})


# endregion

# region persistence


def test_load_from_empty_storage_yields_no_types() -> None:
    """A first run has no stored group at all.

    **Test steps:**

    * load a settings object from empty storage
    * verify no type has a stored list
    """
    loaded = LocationTemplatesSettings()
    loaded.load(FakeSettings())  # type: ignore[arg-type]

    assert not loaded.patterns


def test_the_type_lists_round_trip_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back, in order, for every type, including one this build's shipped
    plugins don't declare -- proving the type set is open-ended (#322).

    **Test steps:**

    * save a settings object holding two shipped types and one made-up one
    * verify each landed under its own ``location_templates/<type>/patterns`` group
    * load a fresh object from the same storage and verify it came back unchanged
    """
    saved = LocationTemplatesSettings()
    saved.patterns = {
        "tutorial": ("{authors} - {title}",),
        "reference_images": ("{publisher} - {title}",),
        "some_future_plugin": ("{title}",),
    }
    saved.save(settings)  # type: ignore[arg-type]

    assert settings.keys() == [
        "location_templates/reference_images/patterns",
        "location_templates/some_future_plugin/patterns",
        "location_templates/tutorial/patterns",
    ]

    loaded = LocationTemplatesSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns == saved.patterns


def test_patterns_are_saved_as_a_list(settings: FakeSettings) -> None:
    """Stored as a list, which is what the ``QSettings`` ini backend can round-trip.

    **Test steps:**

    * save a settings object holding one type's two-pattern list
    * verify the raw stored value is a ``list``, not a tuple
    """
    stored = LocationTemplatesSettings()
    stored.patterns = {"tutorial": ("{title}", "{authors} - {title}")}
    stored.save(settings)  # type: ignore[arg-type]

    assert settings.value("location_templates/tutorial/patterns") == ["{title}", "{authors} - {title}"]


def test_load_repairs_an_unusable_stored_value(settings: FakeSettings) -> None:
    """A stored value a list was never written as yields the shipped defaults for that type rather than
    propagating.

    **Test steps:**

    * seed storage with a number under one type's key
    * load a settings object from it
    * verify that type resolves to the shipped defaults
    """
    settings.beginGroup("location_templates")
    settings.beginGroup("tutorial")
    settings.setValue("patterns", 42)
    settings.endGroup()
    settings.endGroup()

    loaded = LocationTemplatesSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.patterns_for("tutorial") == NAME_SUGGESTION_PATTERNS


def test_saving_drops_a_type_no_longer_present(settings: FakeSettings) -> None:
    """A type popped from :attr:`~LocationTemplatesSettings.patterns` leaves storage on the next save --
    the type set is always decided by the in-memory dict, never by what a previous save left behind
    (#322, the same discipline `DefaultLayoutSettings.save` follows for its own per-type groups).

    **Test steps:**

    * save a settings object holding two types
    * reassign ``patterns`` to drop one, and save again
    * verify only the remaining type's group is left in storage
    """
    both = LocationTemplatesSettings()
    both.patterns = {"tutorial": ("{title}",), "reference_images": ("{publisher} - {title}",)}
    both.save(settings)  # type: ignore[arg-type]

    both.patterns = {"reference_images": ("{publisher} - {title}",)}
    both.save(settings)  # type: ignore[arg-type]

    assert settings.keys() == ["location_templates/reference_images/patterns"]


def test_samples_round_trip_through_their_own_group(settings: FakeSettings) -> None:
    """Each type's Try-it record is stored field by field under ``location_try_it/<type>``, apart from
    the patterns -- whose load reads every sub-group of theirs as a customized type.

    **Test steps:**

    * save one type's sample record (and no patterns), a comma-holding authors field included
    * verify it landed in its own group and nothing appeared under the patterns group
    * load a fresh object and verify the record came back, and no type reads as customized
    """
    saved = LocationTemplatesSettings()
    sample = ("Title", "Publisher", "Jane Doe, John Roe", "2024", "12")
    samples: dict[str, tuple[str, ...]] = {"reference_images": sample}
    saved.samples = samples
    saved.save(settings)  # type: ignore[arg-type]

    assert settings.keys() == [f"location_try_it/reference_images/{field}" for field in sorted(SAMPLE_FIELDS)]

    loaded = LocationTemplatesSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.sample_for("reference_images") == sample
    assert not loaded.patterns


def test_a_type_with_no_stored_sample_shows_the_shipped_one() -> None:
    """A type never applied reads as :data:`DEFAULT_SAMPLE`."""
    assert LocationTemplatesSettings().sample_for("tutorial") == DEFAULT_SAMPLE


def test_saving_writes_patterns_and_samples_together(settings: FakeSettings) -> None:
    """One ``save``, one Apply: the patterns and the sample record go to storage together.

    **Test steps:**

    * save an object holding a pattern list and a sample record for one type
    * verify both groups were written
    """
    saved = LocationTemplatesSettings()
    saved.patterns = {"tutorial": ("{title}",)}
    saved.samples = {"tutorial": DEFAULT_SAMPLE}
    saved.save(settings)  # type: ignore[arg-type]

    assert settings.keys() == [
        "location_templates/tutorial/patterns",
        *(f"location_try_it/tutorial/{field}" for field in sorted(SAMPLE_FIELDS)),
    ]


def test_saving_drops_a_sample_no_longer_present(settings: FakeSettings) -> None:
    """A type popped from :attr:`~LocationTemplatesSettings.samples` leaves storage on the next save,
    the same pruning the patterns get.

    **Test steps:**

    * save samples for two types, then drop one and save again
    * verify only the remaining type's sample group is left
    """
    both = LocationTemplatesSettings()
    both.samples = {"tutorial": DEFAULT_SAMPLE, "reference_images": DEFAULT_SAMPLE}
    both.save(settings)  # type: ignore[arg-type]

    both.samples = {"reference_images": DEFAULT_SAMPLE}
    both.save(settings)  # type: ignore[arg-type]

    assert settings.keys() == [f"location_try_it/reference_images/{field}" for field in sorted(SAMPLE_FIELDS)]


# endregion

# region the shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The singleton reads persistent storage on first call and hands the same object back after.

    **Test steps:**

    * seed storage with one type's list and patch ``persistent_settings`` to return it
    * call the shared accessor twice
    * verify both calls returned the same object, holding the seeded list
    """
    settings.beginGroup("location_templates")
    settings.beginGroup("tutorial")
    settings.setValue("patterns", ["{title}"])
    settings.endGroup()
    settings.endGroup()
    mocker.patch.object(location_templates_settings, "persistent_settings", return_value=settings)

    first = shared_location_templates_settings()
    second = shared_location_templates_settings()

    assert first is second
    assert first.patterns_for("tutorial") == ("{title}",)


# endregion
