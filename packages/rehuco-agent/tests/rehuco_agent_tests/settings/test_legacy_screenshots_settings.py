"""Tests for LegacyScreenshotsSettings: the rules a legacy `.tc`'s screenshots are recognized by (#53)."""

from typing import Any

from pytest import fixture
from pytest_mock import MockerFixture
from rehuco_agent.settings import legacy_screenshots_settings
from rehuco_agent.settings.legacy_screenshots_settings import (
    LegacyScreenshotsSettings,
    normalize_legacy_screenshot_rules,
    shared_legacy_screenshots_settings,
)
from rehuco_core import LEGACY_SCREENSHOT_RULES, LegacyScreenshotRule

# region Sample settings backend
# Mirrors test_conversion_backups_dialog_settings.py's array-capable FakeSettings -- kept as a separate
# copy rather than a shared import, matching this codebase's settings-test convention. The size
# argument `beginWriteArray` is given here is accepted and ignored, the way QSettings treats it as a
# hint rather than a bound.
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

    def beginWriteArray(self, key: str, size: int = -1) -> None:  # noqa: N802
        del size
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

    def keys(self) -> list[str]:
        """Every key written so far -- for a test asserting *where* something landed."""
        return list(self.__data)

    def __full_key(self, key: str) -> str:
        """The storage key for ``key``: array-indexed while inside an array, else group-scoped."""
        if self.__in_array:
            return f"{self.__array_key}/{self.__array_index}/{key}"
        return self.__group + key


# pylint: enable=duplicate-code

# endregion


@fixture(name="settings")
def fixture_settings() -> FakeSettings:
    """A fresh in-memory settings backend.

    :returns: the stand-in.
    """
    return FakeSettings()


# region normalize_legacy_screenshot_rules


def test_a_never_saved_list_resolves_to_the_shipped_rules() -> None:
    """Recognizing nothing is not a legitimate answer, so an empty list falls back.

    **Test steps:**

    * normalize an empty list and a value that was never a list
    * verify both resolve to the shipped rules
    """
    assert normalize_legacy_screenshot_rules(()) == LEGACY_SCREENSHOT_RULES
    assert normalize_legacy_screenshot_rules(None) == LEGACY_SCREENSHOT_RULES


def test_both_fields_are_trimmed_and_order_is_kept() -> None:
    """Order is what decides which rule claims a directory, so normalizing never reorders.

    **Test steps:**

    * normalize two rules whose fields carry surrounding whitespace
    * verify both fields are trimmed and the order is unchanged
    """
    rules = normalize_legacy_screenshot_rules(
        [LegacyScreenshotRule(" shot-1 ", " shot-# "), LegacyScreenshotRule("cover", "file-##")]
    )

    assert rules == (LegacyScreenshotRule("shot-1", "shot-#"), LegacyScreenshotRule("cover", "file-##"))


def test_a_rule_a_scan_could_not_compile_is_dropped() -> None:
    """The page flags a half-typed rule rather than refusing the keystroke, so saving is where it goes.

    **Test steps:**

    * normalize a list holding a blank rule, a placeholder-less one, and a good one
    * verify only the good one survives
    """
    rules = normalize_legacy_screenshot_rules(
        [
            LegacyScreenshotRule("", ""),
            LegacyScreenshotRule("cover", "no-number"),
            LegacyScreenshotRule("shot-1", "shot-#"),
        ]
    )

    assert rules == (LegacyScreenshotRule("shot-1", "shot-#"),)


def test_an_entry_that_is_not_a_rule_at_all_is_dropped() -> None:
    """A hand-edited settings file, or an older build's shape, is untrusted input like any other.

    **Test steps:**

    * normalize a list holding a bare string and a rule
    * verify only the rule survives
    """
    rules = normalize_legacy_screenshot_rules(["cover", LegacyScreenshotRule("shot-1", "shot-#")])

    assert rules == (LegacyScreenshotRule("shot-1", "shot-#"),)


def test_a_duplicate_rule_is_dropped_case_insensitively() -> None:
    """Matching ignores case, so two rules differing only in case would claim the same names.

    **Test steps:**

    * normalize a list holding the same rule twice under different casing
    * verify the first spelling survives alone
    """
    rules = normalize_legacy_screenshot_rules(
        [LegacyScreenshotRule("Cover", "File-##"), LegacyScreenshotRule("cover", "file-##")]
    )

    assert rules == (LegacyScreenshotRule("Cover", "File-##"),)


def test_a_list_holding_nothing_usable_falls_back_rather_than_recognizing_nothing() -> None:
    """A set that compiles to nothing would convert every legacy resource without a screenshot.

    **Test steps:**

    * normalize a list of rules none of which compile
    * verify the shipped rules come back
    """
    assert normalize_legacy_screenshot_rules([LegacyScreenshotRule("", "")]) == LEGACY_SCREENSHOT_RULES


# endregion

# region Loading and saving


def test_a_fresh_install_reads_the_shipped_rules(settings: FakeSettings) -> None:
    """Nothing stored is the shipped set, not an empty one.

    **Test steps:**

    * load from an empty backend
    * verify the effective rules are the shipped ones
    """
    stored = LegacyScreenshotsSettings()
    stored.load(settings)  # pyright: ignore[reportArgumentType]  # structural QSettings stand-in

    assert stored.legacy_screenshot_rules == LEGACY_SCREENSHOT_RULES


def test_saved_rules_round_trip_in_order(settings: FakeSettings) -> None:
    """A rule is two fields, so it is stored as an array rather than paired by position in one list.

    **Test steps:**

    * save a reordered rule set
    * load it into a fresh object
    * verify the rules and their order came back
    """
    rules = (LegacyScreenshotRule("shot-1", "shot-#"), LegacyScreenshotRule("cover", "file-##"))
    stored = LegacyScreenshotsSettings(rules=rules)

    stored.save(settings)  # pyright: ignore[reportArgumentType]  # structural QSettings stand-in
    reloaded = LegacyScreenshotsSettings()
    reloaded.load(settings)  # pyright: ignore[reportArgumentType]  # structural QSettings stand-in

    assert reloaded.legacy_screenshot_rules == rules


def test_the_rules_land_under_their_own_group(settings: FakeSettings) -> None:
    """Where a section stores itself is part of its contract with an existing install.

    **Test steps:**

    * save one rule
    * verify the keys sit under the section's group
    """
    stored = LegacyScreenshotsSettings(rules=(LegacyScreenshotRule("cover", "file-##"),))
    stored.save(settings)  # pyright: ignore[reportArgumentType]  # structural QSettings stand-in

    assert any(key.startswith("legacy_screenshots/rules/") for key in settings.keys())


def test_a_stored_entry_missing_a_field_is_dropped_rather_than_half_read(settings: FakeSettings) -> None:
    """A settings file edited by hand is untrusted input like any other.

    **Test steps:**

    * write an array entry carrying only a cover
    * load it
    * verify the shipped rules come back rather than a rule with no template
    """
    settings.beginGroup("legacy_screenshots")
    settings.beginWriteArray("rules")
    settings.setArrayIndex(0)
    settings.setValue("cover", "cover")
    settings.endArray()
    settings.endGroup()

    stored = LegacyScreenshotsSettings()
    stored.load(settings)  # pyright: ignore[reportArgumentType]  # structural QSettings stand-in

    assert stored.legacy_screenshot_rules == LEGACY_SCREENSHOT_RULES


# endregion

# region The shared instance


def test_the_shared_instance_is_loaded_once(mocker: MockerFixture) -> None:
    """Every scan must read the same object the page saved into, not a copy each.

    **Test steps:**

    * ask for the shared settings twice
    * verify the same object comes back and storage was read once
    """
    shared_legacy_screenshots_settings.cache_clear()
    fake = FakeSettings()
    reader = mocker.patch.object(legacy_screenshots_settings, "persistent_settings", return_value=fake)

    first = shared_legacy_screenshots_settings()
    second = shared_legacy_screenshots_settings()

    assert first is second
    assert reader.call_count == 1
    shared_legacy_screenshots_settings.cache_clear()


# endregion
