"""Tests for DocumentSessionSettings: LRU-capped per-file open/state bookkeeping ([[implementation-plan]] #21).

Uses a hand-rolled in-memory stand-in for ``QSettings`` rather than a real one (backed by the
registry/an ini file) or ``tmp_path`` -- it implements just the narrow group/array/value subset
``DocumentSessionSettings.load``/``save`` actually calls, so persistence is exercised end-to-end
without ever touching real storage.
"""

from pathlib import Path
from typing import Any, Final

from pytest import fixture
from rehuco_agent.document_session_settings import MAXIMUM_REMEMBERED_FILES, DocumentSessionSettings

FIRST: Final = Path.cwd() / "fake" / "first.rehu"
SECOND: Final = Path.cwd() / "fake" / "second.rehu"
THIRD: Final = Path.cwd() / "fake" / "third.rehu"


# region fixtures
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """A minimal in-memory stand-in for the ``QSettings`` group/array/value API.

    Method names and the ``type=`` parameter deliberately mirror ``QSettings``'s own C++-derived
    API (``beginGroup``/``setValue``/etc, and ``value(key, default, type=...)``), since
    :meth:`DocumentSessionSettings.load`/:meth:`~DocumentSessionSettings.save` call them by name --
    hence the blanket naming/docstring/builtin-shadowing suppression above, scoped to this class.
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


@fixture
def settings() -> FakeSettings:
    """A fresh in-memory settings stand-in."""
    return FakeSettings()


# endregion


# region items_to_save tests
def test_items_to_save_keeps_every_open_item_even_past_the_cap() -> None:
    """Every open item survives pruning, even when there are more of them than the LRU cap.

    **Test steps:**

    * add more open items than :data:`MAXIMUM_REMEMBERED_FILES`
    * verify ``items_to_save`` returns all of them
    """
    session = DocumentSessionSettings()
    paths = [Path.cwd() / "fake" / f"{i}.rehu" for i in range(MAXIMUM_REMEMBERED_FILES + 3)]
    for path in paths:
        session.items[path] = DocumentSessionSettings.Item(open=True)

    assert list(session.items_to_save()) == paths


def test_items_to_save_prunes_closed_items_beyond_the_cap() -> None:
    """Closed items beyond the LRU cap are dropped, keeping the newest ones.

    **Test steps:**

    * add one open item, then more closed items than the remaining cap budget allows
    * verify only the newest closed items (up to the budget) survive, plus the open one
    """
    session = DocumentSessionSettings()
    session.items[FIRST] = DocumentSessionSettings.Item(open=True)
    closed_paths = [Path.cwd() / "fake" / f"closed_{i}.rehu" for i in range(MAXIMUM_REMEMBERED_FILES + 2)]
    for path in closed_paths:
        session.items[path] = DocumentSessionSettings.Item(open=False)

    kept = session.items_to_save()

    assert FIRST in kept
    assert len(kept) == MAXIMUM_REMEMBERED_FILES
    assert list(kept)[1:] == closed_paths[-(MAXIMUM_REMEMBERED_FILES - 1) :]


# endregion


# region load/save tests
def test_save_then_load_round_trips_items(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the same open flags and state bytes, keyed by path.

    **Test steps:**

    * populate two items (one open, one closed, distinct state bytes) and save them
    * load into a fresh instance from the same settings stand-in
    * verify both items came back with matching open flags and state
    """
    session = DocumentSessionSettings()
    session.items[FIRST] = DocumentSessionSettings.Item(open=True, state=b"first-state")
    session.items[SECOND] = DocumentSessionSettings.Item(open=False, state=b"second-state")

    session.save(settings)  # type: ignore[arg-type]

    restored = DocumentSessionSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.items[FIRST.resolve()] == DocumentSessionSettings.Item(open=True, state=b"first-state")
    assert restored.items[SECOND.resolve()] == DocumentSessionSettings.Item(open=False, state=b"second-state")


def test_save_prunes_before_writing(settings: FakeSettings) -> None:
    """Saving only persists the LRU-pruned items, not the full in-memory set.

    **Test steps:**

    * add more closed items than the cap allows, save
    * load back and verify the closed count matches the cap, not the original count
    """
    session = DocumentSessionSettings()
    for i in range(MAXIMUM_REMEMBERED_FILES + 5):
        session.items[Path.cwd() / "fake" / f"{i}.rehu"] = DocumentSessionSettings.Item(open=False)

    session.save(settings)  # type: ignore[arg-type]

    restored = DocumentSessionSettings()
    restored.load(settings)  # type: ignore[arg-type]
    assert len(restored.items) == MAXIMUM_REMEMBERED_FILES


def test_save_then_load_round_trips_the_focused_document(settings: FakeSettings) -> None:
    """Saving and reloading reproduces the focused document's path, alongside the items array.

    **Test steps:**

    * set a focused document and one item, save
    * load into a fresh instance from the same settings stand-in
    * verify the focused document came back, resolved, and the item still round-tripped too
    """
    session = DocumentSessionSettings()
    session.items[FIRST] = DocumentSessionSettings.Item(open=True)
    session.focused_path = FIRST

    session.save(settings)  # type: ignore[arg-type]

    restored = DocumentSessionSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.focused_path == FIRST.resolve()
    assert FIRST.resolve() in restored.items


def test_load_defaults_to_no_focused_document_when_nothing_was_saved(settings: FakeSettings) -> None:
    """Loading from settings that never had a focused document saved yields ``None``.

    **Test steps:**

    * save a session with no focused document set
    * load into a fresh instance
    * verify the focused document is ``None``
    """
    session = DocumentSessionSettings()
    session.save(settings)  # type: ignore[arg-type]

    restored = DocumentSessionSettings()
    restored.load(settings)  # type: ignore[arg-type]

    assert restored.focused_path is None


def test_load_clears_prior_items(settings: FakeSettings) -> None:
    """Loading replaces whatever items were already present, rather than merging with them.

    **Test steps:**

    * save one item, then load into an instance that already holds an unrelated item
    * verify only the loaded item remains
    """
    session = DocumentSessionSettings()
    session.items[FIRST] = DocumentSessionSettings.Item(open=True)
    session.save(settings)  # type: ignore[arg-type]

    restored = DocumentSessionSettings()
    restored.items[THIRD] = DocumentSessionSettings.Item(open=True)
    restored.load(settings)  # type: ignore[arg-type]

    assert THIRD not in restored.items
    assert FIRST.resolve() in restored.items


# endregion
