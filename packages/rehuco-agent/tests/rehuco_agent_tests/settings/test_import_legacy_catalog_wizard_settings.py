"""Tests for ImportLegacyCatalogWizardSettings: the wizard's geometry and its recent-roots MRU list
(#192).

Uses a hand-rolled in-memory stand-in for ``QSettings`` rather than a real one or ``tmp_path`` -- the
same array-capable shape `test_recent_files_settings` uses, since this settings object mixes a scalar
(geometry) with an array (recent roots).
"""

from pathlib import Path
from typing import Any, Final

from pytest import fixture
from rehuco_agent.settings.import_legacy_catalog_wizard_settings import (
    MAXIMUM_RECENT_ROOTS,
    ImportLegacyCatalogWizardSettings,
)

FIRST: Final = Path.cwd() / "fake" / "first"
SECOND: Final = Path.cwd() / "fake" / "second"
THIRD: Final = Path.cwd() / "fake" / "third"


# region fixtures
# Mirrors test_recent_files_settings.py's own FakeSettings exactly (same array-capable QSettings
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

    def __full_key(self, key: str) -> str:
        """The storage key for ``key``: array-indexed while inside an array, else group-scoped."""
        if self.__in_array:
            return f"{self.__array_key}/{self.__array_index}/{key}"
        return self.__group + key


# pylint: enable=duplicate-code


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# endregion


# region record_root tests


def test_record_root_appends_a_new_root_as_the_newest() -> None:
    """Recording a never-seen root adds it to the newest end.

    **Test steps:**

    * record two distinct roots
    * verify ``newest_roots_first`` reports the second one first
    """
    wizard_settings = ImportLegacyCatalogWizardSettings()
    wizard_settings.record_root(FIRST)
    wizard_settings.record_root(SECOND)

    assert wizard_settings.newest_roots_first() == [SECOND, FIRST]


def test_record_root_moves_an_already_remembered_root_to_newest() -> None:
    """Re-recording an already-remembered root moves it to the newest end, not a duplicate.

    **Test steps:**

    * record two roots, then re-record the older one
    * verify it's now newest, and the list has no duplicate entry
    """
    wizard_settings = ImportLegacyCatalogWizardSettings()
    wizard_settings.record_root(FIRST)
    wizard_settings.record_root(SECOND)

    wizard_settings.record_root(FIRST)

    assert wizard_settings.newest_roots_first() == [FIRST, SECOND]


def test_record_root_drops_the_oldest_entry_past_the_cap() -> None:
    """Recording past :data:`MAXIMUM_RECENT_ROOTS` drops the oldest entry.

    **Test steps:**

    * record one more root than the cap allows
    * verify the oldest one is gone and the count matches the cap
    """
    wizard_settings = ImportLegacyCatalogWizardSettings()
    roots = [Path.cwd() / "fake" / str(i) for i in range(MAXIMUM_RECENT_ROOTS + 1)]
    for root in roots:
        wizard_settings.record_root(root)

    newest_first = wizard_settings.newest_roots_first()

    assert len(newest_first) == MAXIMUM_RECENT_ROOTS
    assert roots[0] not in newest_first
    assert newest_first[0] == roots[-1]


# endregion


# region load/save tests


def test_save_then_load_round_trips_geometry_and_roots(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the geometry blob and the roots, in MRU order.

    **Test steps:**

    * set a geometry blob, record two roots, and save
    * load into a fresh instance from the same settings stand-in
    * verify both round-tripped
    """
    wizard_settings = ImportLegacyCatalogWizardSettings(geometry=b"blob")
    wizard_settings.record_root(FIRST)
    wizard_settings.record_root(SECOND)

    wizard_settings.save(settings)  # type: ignore[arg-type]

    restored = ImportLegacyCatalogWizardSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.geometry == b"blob"
    assert restored.newest_roots_first() == [SECOND.resolve(), FIRST.resolve()]


def test_load_clears_prior_roots(settings: FakeSettings) -> None:
    """Loading replaces whatever roots were already present, rather than merging with them.

    **Test steps:**

    * save one root, then load into an instance that already holds an unrelated one
    * verify only the loaded root remains
    """
    wizard_settings = ImportLegacyCatalogWizardSettings()
    wizard_settings.record_root(FIRST)
    wizard_settings.save(settings)  # type: ignore[arg-type]

    restored = ImportLegacyCatalogWizardSettings()
    restored.record_root(THIRD)
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.newest_roots_first() == [FIRST.resolve()]


def test_load_defaults_to_empty_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had anything saved yields empty geometry and no roots.

    **Test steps:**

    * load into a fresh instance from settings nothing was ever saved into
    * verify geometry is empty and ``newest_roots_first`` is empty
    """
    restored = ImportLegacyCatalogWizardSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.geometry == b""
    assert not restored.newest_roots_first()


# endregion
