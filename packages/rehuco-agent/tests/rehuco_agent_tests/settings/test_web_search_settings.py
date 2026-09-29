"""Tests for WebSearchSettings: the engine list, the active engine and the URL a query becomes (#388)."""

from typing import Any

from pytest import mark
from pytest_mock import MockerFixture
from rehuco_agent.settings import web_search_settings
from rehuco_agent.settings.web_search_settings import (
    DEFAULT_ENGINES,
    EMPTY_NAME_PROBLEM,
    NO_PLACEHOLDER_PROBLEM,
    NOT_HTTP_PROBLEM,
    SearchEngine,
    WebSearchSettings,
    engine_problem,
    search_url,
    shared_web_search_settings,
    usable_engines,
)

GOOD = SearchEngine("Mine", "https://example.com/find?q={query}")


# region Sample settings backend
# Mirrors the array-capable FakeSettings of conftest.py -- kept as a separate copy rather than a shared
# import, matching this codebase's settings-test convention.
# pylint: disable=duplicate-code
class FakeSettings:  # pylint: disable=invalid-name,missing-function-docstring,redefined-builtin
    """An in-memory stand-in for the ``QSettings`` group, value and array API.

    Groups nest on a prefix stack rather than being replaced, which is what ``QSettings`` itself does
    and what the array support below needs: an array opened inside a group writes under both. Every
    section that uses this opens one group at a time, so nothing existing reads differently for it.

    The array half exists for `ConversionBackupsDialogSettings`, the only section here storing a list
    ([[appendices.code-conventions]]), and follows ``QSettings``' own layout -- ``<prefix>/<n>/<key>``
    numbered from one, alongside a ``<prefix>/size`` written when the array closes. Faithful enough
    that the dialog's save-then-load round trip reads back exactly what it wrote, which is what its
    remembered-geometry and recent-roots tests assert on.
    """

    def __init__(self) -> None:
        self.__data: dict[str, Any] = {}
        self.__prefixes: list[str] = []
        self.__arrays: list[list[Any]] = []

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

    def remove(self, key: str) -> None:
        """Drop ``key`` and everything under it from the open group -- ``""`` empties the whole group,
        as ``QSettings`` does."""
        full = self.__prefix + key
        for stored in list(self.__data):
            if stored == full or stored.startswith(full + "/") or (not key and stored.startswith(full)):
                del self.__data[stored]

    def beginWriteArray(self, prefix: str, size: int = -1) -> None:  # noqa: N802
        del size
        self.__arrays.append([prefix, self.__prefix, 0])
        self.__prefixes.append(f"{prefix}/")

    def beginReadArray(self, prefix: str) -> int:  # noqa: N802
        stored = self.__data.get(f"{self.__prefix}{prefix}/size", 0)
        size = int(stored) if stored else 0
        self.__arrays.append([prefix, self.__prefix, size])
        self.__prefixes.append(f"{prefix}/")
        return size

    def setArrayIndex(self, index: int) -> None:  # noqa: N802
        prefix, _, count = self.__arrays[-1]
        self.__prefixes[-1] = f"{prefix}/{index + 1}/"
        self.__arrays[-1][2] = max(count, index + 1)

    def endArray(self) -> None:  # noqa: N802
        prefix, outer, count = self.__arrays.pop()
        self.__prefixes.pop()
        self.__data[f"{outer}{prefix}/size"] = count


# pylint: enable=duplicate-code
# endregion


# region engine_problem
@mark.parametrize(
    ("engine", "problem"),
    [
        (GOOD, ""),
        (SearchEngine("Mine", "HTTP://example.com/?q={query}"), ""),
        (SearchEngine("  ", "https://example.com/?q={query}"), EMPTY_NAME_PROBLEM),
        (SearchEngine("Mine", "ftp://example.com/?q={query}"), NOT_HTTP_PROBLEM),
        (SearchEngine("Mine", "example.com/?q={query}"), NOT_HTTP_PROBLEM),
        (SearchEngine("Mine", "https://example.com/?q="), NO_PLACEHOLDER_PROBLEM),
    ],
)
def test_engine_problem(engine: SearchEngine, problem: str) -> None:
    """A template without ``{query}``, or not http(s), or a nameless row, is refused.

    **Test steps:**

    * check each engine
    * verify the explanation, empty for a fine one
    """
    assert engine_problem(engine) == problem


# endregion


# region search_url
def test_search_url_encodes_the_query_into_the_template() -> None:
    """The query is URL-encoded where the placeholder is.

    **Test steps:**

    * put a query with spaces, a plus and an apostrophe into a template
    * verify the encoded URL
    """
    assert search_url("https://x.example/?q={query}", "Sci-Fi C++ Artist's") == (
        "https://x.example/?q=Sci-Fi+C%2B%2B+Artist%27s"
    )


# endregion


# region WebSearchSettings
def test_fresh_settings_search_with_the_first_shipped_engine() -> None:
    """The shipped list makes its first engine the active one.

    **Test steps:**

    * build unloaded settings
    * verify the shipped list and its first engine as the selection
    """
    settings = WebSearchSettings()
    assert settings.engines == DEFAULT_ENGINES
    assert settings.selected == DEFAULT_ENGINES[0]


def test_selected_is_the_active_usable_engine_and_ignores_a_broken_or_absent_one() -> None:
    """The active row must be usable; anything else falls to the first usable one.

    **Test steps:**

    * make a usable row active and verify it is selected
    * make a broken row the only active one, then clear every flag, and verify the first usable row
    """
    plain = DEFAULT_ENGINES[0]._replace(active=False)
    settings = WebSearchSettings()
    settings.engines = (plain, GOOD._replace(active=True))
    assert settings.selected == GOOD._replace(active=True)
    settings.engines = (SearchEngine("Broken", "https://example.com/", active=True), plain, GOOD)
    assert settings.selected == plain
    settings.engines = (plain, GOOD)
    assert settings.selected == plain


def test_a_list_with_nothing_usable_resolves_to_the_shipped_one() -> None:
    """There is always somewhere to search.

    **Test steps:**

    * hand over only broken rows
    * verify the usable engines are the shipped ones
    """
    assert usable_engines([SearchEngine("", ""), SearchEngine("A", "nope")]) == DEFAULT_ENGINES


def test_save_then_load_round_trips_the_list_and_the_active_flag() -> None:
    """The list comes back as saved, a shrunk list leaves no dead rows, and a broken row is kept.

    **Test steps:**

    * save three rows, then a shorter list with an active row and a broken one
    * load into fresh settings
    * verify the shorter list, flags included
    """
    store = FakeSettings()
    saved = WebSearchSettings()
    saved.engines = (GOOD, DEFAULT_ENGINES[0], DEFAULT_ENGINES[1])
    saved.save(store)  # type: ignore[arg-type]
    saved.engines = (
        SearchEngine("Mine", "https://example.com/find?q={query}", active=True),
        SearchEngine("Broken", "x"),
    )
    saved.save(store)  # type: ignore[arg-type]

    loaded = WebSearchSettings()
    loaded.load(store)  # type: ignore[arg-type]

    assert loaded.engines == saved.engines


def test_a_never_saved_store_loads_the_shipped_list(mocker: MockerFixture) -> None:
    """A fresh install shows the shipped engines, Google active.

    **Test steps:**

    * load from an empty store
    * verify the shipped list and the selected engine
    """
    mocker.patch.object(web_search_settings, "persistent_settings", return_value=FakeSettings())
    settings = shared_web_search_settings()
    assert settings.engines == DEFAULT_ENGINES
    assert settings.selected.name == "Google"


# endregion
