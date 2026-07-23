"""Tests for RecentFilesSettings: the ``File > Open recents`` menu's MRU path list (#64).

Uses a hand-rolled in-memory stand-in for ``QSettings`` rather than a real one (backed by the
registry/an ini file) or ``tmp_path`` -- it implements just the narrow group/array/value subset
``RecentFilesSettings.load``/``save`` actually calls, so persistence is exercised end-to-end
without ever touching real storage.
"""

from pathlib import Path
from typing import Any, Final

from pytest import fixture
from rehuco_agent.settings.recent_files_settings import MAXIMUM_RECENT_FILES, RecentFilesSettings

FIRST: Final = Path.cwd() / "fake" / "first.rehu"
SECOND: Final = Path.cwd() / "fake" / "second.rehu"
THIRD: Final = Path.cwd() / "fake" / "third.rehu"


# region fixtures
# Mirrors test_document_session_settings.py's own FakeSettings exactly (same array-capable
# QSettings stand-in, RecentFilesSettings uses the same beginReadArray/beginWriteArray shape as
# DocumentSessionSettings) -- kept as a separate copy rather than a shared import, matching this
# codebase's settings-test convention (see conftest.py's own FakeSettings for the simpler variant).
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/array/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API (``beginGroup``/``setValue``/etc, and ``value(key, default, type=...)``), since
    :meth:`RecentFilesSettings.load`/:meth:`~RecentFilesSettings.save` call them by name -- hence
    the blanket naming/docstring/builtin-shadowing suppression above, scoped to this class.
    """

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


# region record tests
def test_record_appends_a_new_path_as_the_newest() -> None:
    """Recording a never-seen path adds it to the newest end.

    **Test steps:**

    * record two distinct paths
    * verify ``newest_first`` reports the second one first
    """
    recent = RecentFilesSettings()
    recent.record(FIRST)
    recent.record(SECOND)

    assert recent.newest_first() == [SECOND, FIRST]


def test_record_moves_an_already_remembered_path_to_newest() -> None:
    """Re-recording an already-remembered path moves it to the newest end, not a duplicate.

    **Test steps:**

    * record two paths, then re-record the older one
    * verify it's now newest, and the list has no duplicate entry
    """
    recent = RecentFilesSettings()
    recent.record(FIRST)
    recent.record(SECOND)

    recent.record(FIRST)

    assert recent.newest_first() == [FIRST, SECOND]


def test_record_drops_the_oldest_entry_past_the_cap() -> None:
    """Recording past :data:`MAXIMUM_RECENT_FILES` drops the oldest entry.

    **Test steps:**

    * record one more path than the cap allows
    * verify the oldest one is gone and the count matches the cap
    """
    recent = RecentFilesSettings()
    paths = [Path.cwd() / "fake" / f"{i}.rehu" for i in range(MAXIMUM_RECENT_FILES + 1)]
    for path in paths:
        recent.record(path)

    newest_first = recent.newest_first()

    assert len(newest_first) == MAXIMUM_RECENT_FILES
    assert paths[0] not in newest_first
    assert newest_first[0] == paths[-1]


# endregion


# region load/save tests
def test_save_then_load_round_trips_paths_in_order(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same paths, in the same MRU order.

    **Test steps:**

    * record two paths and save
    * load into a fresh instance from the same settings stand-in
    * verify ``newest_first`` matches, resolved
    """
    recent = RecentFilesSettings()
    recent.record(FIRST)
    recent.record(SECOND)

    recent.save(settings)  # type: ignore[arg-type]

    restored = RecentFilesSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.newest_first() == [SECOND.resolve(), FIRST.resolve()]


def test_load_clears_prior_paths(settings: FakeSettings) -> None:
    """Loading replaces whatever paths were already present, rather than merging with them.

    **Test steps:**

    * save one path, then load into an instance that already holds an unrelated one
    * verify only the loaded path remains
    """
    recent = RecentFilesSettings()
    recent.record(FIRST)
    recent.save(settings)  # type: ignore[arg-type]

    restored = RecentFilesSettings()
    restored.record(THIRD)
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.newest_first() == [FIRST.resolve()]


def test_load_defaults_to_empty_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had anything saved yields an empty list.

    **Test steps:**

    * load into a fresh instance from settings nothing was ever saved into
    * verify ``newest_first`` is empty
    """
    restored = RecentFilesSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert not restored.newest_first()


# endregion
