"""Tests for LocationReplacementsSettings: the global text -> replacement rule table applied to a
rendered location name before it is sanitized into a filesystem name (#350).

Uses a hand-rolled in-memory stand-in for ``QSettings`` (see ``test_document_session_settings.py`` for
the same rationale -- an array-capable group/value API) rather than a real one or ``tmp_path``.
"""

from collections.abc import Iterator
from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import location_replacements_settings
from rehuco_agent.settings.location_replacements_settings import (
    DEFAULT_RULES,
    EMPTY_TEXT_PROBLEM,
    INVALID_REGEX_PROBLEM,
    LocationReplacementsSettings,
    ReplacementRule,
    apply_location_replacements,
    rule_problem,
    shared_location_replacements_settings,
)


# region fixtures
# Mirrors test_document_session_settings.py's own FakeSettings exactly (same array-capable QSettings
# stand-in) -- kept as a separate copy rather than a shared import, matching this codebase's
# settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/array/value API."""

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__group = ""
        self.__array_key = ""
        self.__array_index = 0
        self.__in_array = False

    def beginGroup(self, name: str) -> None:  # noqa: N802  (Qt API name)
        self.__group = f"{name}/"

    def endGroup(self) -> None:  # noqa: N802
        self.__group = ""

    def beginWriteArray(self, key: str) -> None:  # noqa: N802
        self.__array_key = self.__group + key
        self.__in_array = True
        self.__data[f"{self.__array_key}/size"] = 0

    def beginReadArray(self, key: str) -> int:  # noqa: N802
        self.__array_key = self.__group + key
        self.__in_array = True
        return self.__data.get(f"{self.__array_key}/size", 0)

    def setArrayIndex(self, index: int) -> None:  # noqa: N802
        self.__array_index = index
        size_key = f"{self.__array_key}/size"
        self.__data[size_key] = max(self.__data.get(size_key, 0), index + 1)

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802
        self.__data[self.__full_key(key)] = value

    def value(self, key: str, default: Any = None, type: Any = None) -> Any:  # noqa: A002, N802
        del type
        return self.__data.get(self.__full_key(key), default)

    def endArray(self) -> None:  # noqa: N802
        self.__in_array = False
        self.__array_key = ""

    def remove(self, key: str) -> None:
        """Drop ``key`` and everything under it from the open group, as ``QSettings`` does."""
        full = self.__group + key
        for stored in list(self.__data):
            if stored == full or stored.startswith(full + "/"):
                del self.__data[stored]

    def keys(self) -> list[str]:
        """Every stored key, for asserting on what a save left behind."""
        return sorted(self.__data)

    def __full_key(self, key: str) -> str:
        if self.__in_array:
            return f"{self.__array_key}/{self.__array_index}/{key}"
        return self.__group + key


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# pylint: enable=duplicate-code


@fixture(autouse=True)
def clear_shared_instance_cache() -> Iterator[None]:
    """Clear the ``lru_cache``-backed singleton before and after every test."""
    shared_location_replacements_settings.cache_clear()
    yield
    shared_location_replacements_settings.cache_clear()


# endregion

# region rule_problem


def test_a_rule_with_text_is_fine() -> None:
    """A rule naming something to look for is usable."""
    assert rule_problem(ReplacementRule(": ", " - ")) == ""


def test_a_rule_with_no_text_is_a_problem() -> None:
    """An empty text cell would match everywhere, so it is flagged rather than acted on."""
    assert rule_problem(ReplacementRule("", " - ")) == EMPTY_TEXT_PROBLEM


def test_an_empty_replacement_is_fine() -> None:
    """Deleting the matched text outright is a legitimate rule, not a mistake."""
    assert rule_problem(ReplacementRule(":", "")) == ""


def test_a_well_formed_regex_is_fine() -> None:
    """A regex rule that compiles is usable."""
    assert rule_problem(ReplacementRule(r" *\| *", " - ", is_regex=True)) == ""


def test_an_unparsable_regex_is_a_problem() -> None:
    """An unbalanced group is refused up front rather than raising at replace time."""
    assert rule_problem(ReplacementRule("(", "-", is_regex=True)) == INVALID_REGEX_PROBLEM


def test_the_same_text_is_fine_as_a_literal_but_not_as_a_regex() -> None:
    """Whether text is a problem depends on the checkbox, not on the text alone."""
    assert rule_problem(ReplacementRule("(", "-", is_regex=False)) == ""


# endregion

# region apply_location_replacements


def test_rules_apply_in_order() -> None:
    """Both shipped rules turn their own separator into the same plain one -- the pipe rule is a regex
    that also consumes the spaces either side of it, so no doubled space is left behind."""
    assert apply_location_replacements("Foo: The Bar | Vol 2", DEFAULT_RULES) == "Foo - The Bar - Vol 2"


def test_a_later_rule_sees_what_an_earlier_one_left_behind() -> None:
    """Rules run left to right across the whole table, not independently against the original text."""
    rules = (ReplacementRule("a", "b"), ReplacementRule("b", "c"))

    assert apply_location_replacements("a", rules) == "c"


def test_an_empty_text_rule_is_skipped_rather_than_inserted_everywhere() -> None:
    """Replacing an empty string would insert the replacement between every character -- skipped instead."""
    assert apply_location_replacements("abc", (ReplacementRule("", "-"),)) == "abc"


def test_no_rules_returns_the_text_unchanged() -> None:
    """An empty rule table is a no-op, not an error."""
    assert apply_location_replacements("Foo: Bar", ()) == "Foo: Bar"


def test_a_regex_rule_collapses_the_spaces_it_matches() -> None:
    """The whole point of the shipped pipe rule: a regex can consume its own surrounding whitespace, so
    ``" | "`` becomes one `` - ``, not two doubled spaces either side of a literal replacement."""
    rule = ReplacementRule(r" *\| *", " - ", is_regex=True)

    assert apply_location_replacements("Foo | Bar", (rule,)) == "Foo - Bar"
    assert apply_location_replacements("Foo|Bar", (rule,)) == "Foo - Bar"


def test_a_regex_rules_replacement_may_use_backreferences() -> None:
    """Under ``is_regex``, ``replacement`` is `re.sub`'s own replacement string, backreferences included."""
    rule = ReplacementRule(r"(\w+)_(\w+)", r"\2 \1", is_regex=True)

    assert apply_location_replacements("Vol_2", (rule,)) == "2 Vol"


def test_an_unparsable_regex_rule_is_skipped() -> None:
    """A row `rule_problem` flags never reaches ``re.sub``, so it cannot raise."""
    rule = ReplacementRule("(", "-", is_regex=True)

    assert apply_location_replacements("(abc", (rule,)) == "(abc"


# endregion

# region reactivity


def test_rules_changed_fires_on_assignment(mocker: MockerFixture) -> None:
    """A reactive ``QObject``: assigning :attr:`LocationReplacementsSettings.rules` fires
    ``rules_changed``, the seam `NameSuggestionModel` follows to re-pull an open document's suggestions
    without a reopen (#350).
    """
    settings = LocationReplacementsSettings()
    spy = mocker.Mock()
    settings.rules_changed.connect(spy)  # type: ignore[attr-defined]

    settings.rules = (ReplacementRule(":", "-"),)

    spy.assert_called_once_with((ReplacementRule(":", "-"),))


# endregion

# region persistence


def test_load_from_never_saved_storage_yields_the_shipped_seed(settings: FakeSettings) -> None:
    """A table that was never saved reads back as the shipped seed, not empty.

    **Test steps:**

    * load a settings object from a fresh, never-saved store
    * verify it holds the shipped rules
    """
    loaded = LocationReplacementsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.rules == DEFAULT_RULES


def test_the_rules_round_trip_through_storage(settings: FakeSettings) -> None:
    """What was saved is what loads back, in order, the regexp checkbox included.

    **Test steps:**

    * save a settings object holding a literal rule and a regex rule
    * load a fresh object from the same storage and verify it came back unchanged
    """
    saved = LocationReplacementsSettings()
    saved.rules = (ReplacementRule(":", "-"), ReplacementRule(r" *\| *", " - ", is_regex=True))
    saved.save(settings)  # type: ignore[arg-type]

    loaded = LocationReplacementsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert loaded.rules == saved.rules
    assert loaded.rules[1].is_regex is True


def test_saving_an_emptied_table_is_respected_on_the_next_load(settings: FakeSettings) -> None:
    """Unlike a location pattern list, an empty rule table is a real, permanent choice: deleting both
    shipped rules and saving must not come back as the seed on the next load.

    **Test steps:**

    * save an empty rule table
    * load a fresh object from the same storage
    * verify it comes back empty, not the shipped seed
    """
    saved = LocationReplacementsSettings()
    saved.rules = ()
    saved.save(settings)  # type: ignore[arg-type]

    loaded = LocationReplacementsSettings()
    loaded.load(settings)  # type: ignore[arg-type]

    assert not loaded.rules


def test_a_shrunken_table_leaves_no_dead_rows_in_storage(settings: FakeSettings) -> None:
    """``QSettings`` rewrites an array's size and entries but never deletes the indexed keys a longer
    array wrote, so a save clears the array first -- otherwise a table cut from three rules to one would
    keep two dead rows in the file under a size that no longer counts them.

    **Test steps:**

    * save a three-rule table, then a one-rule one
    * verify storage holds exactly the one rule's keys, the size, and the configured marker
    """
    saved = LocationReplacementsSettings()
    saved.rules = (ReplacementRule("a", "1"), ReplacementRule("b", "2"), ReplacementRule("c", "3"))
    saved.save(settings)  # type: ignore[arg-type]

    saved.rules = (ReplacementRule("z", "9"),)
    saved.save(settings)  # type: ignore[arg-type]

    assert settings.keys() == [
        "location_replacements/configured",
        "location_replacements/rules/0/is_regex",
        "location_replacements/rules/0/replacement",
        "location_replacements/rules/0/text",
        "location_replacements/rules/size",
    ]


def test_saving_marks_the_table_as_configured(settings: FakeSettings) -> None:
    """The configured marker is what tells a never-saved table apart from a saved-empty one.

    **Test steps:**

    * save a settings object holding one rule
    * verify the configured marker is stored true
    """
    saved = LocationReplacementsSettings()
    saved.rules = (ReplacementRule(":", "-"),)
    saved.save(settings)  # type: ignore[arg-type]

    assert settings.value("location_replacements/configured") is True


# endregion

# region the shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture, settings: FakeSettings) -> None:
    """The singleton reads persistent storage on first call and hands the same object back after.

    **Test steps:**

    * seed storage with a custom rule and patch ``persistent_settings`` to return it
    * call the shared accessor twice
    * verify both calls returned the same object, holding the seeded rule
    """
    saved = LocationReplacementsSettings()
    saved.rules = (ReplacementRule(":", "-"),)
    saved.save(settings)  # type: ignore[arg-type]
    mocker.patch.object(location_replacements_settings, "persistent_settings", return_value=settings)

    first = shared_location_replacements_settings()
    second = shared_location_replacements_settings()

    assert first is second
    assert first.rules == (ReplacementRule(":", "-"),)


# endregion
