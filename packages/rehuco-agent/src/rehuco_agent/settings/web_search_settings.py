"""The search engines the document toolbar's Search the Web action can use, and which one is active (#388).

No OS API exposes the default browser's own search engine, so the engine is the app's to know: each is a
name and a URL template holding a :data:`QUERY_PLACEHOLDER` the query is URL-encoded into. Every engine
here is the same kind of thing -- a search box's ``?q=`` -- so a new one is a name and a template, with no
code behind it. **Which one is active is a flag on its own row**, so it moves, duplicates and is deleted
with the row rather than naming it from outside.

**A broken row is kept, flagged and never used**, the discipline
`~rehuco_agent.settings.location_replacements_settings` follows for its own rows: :func:`engine_problem`
says why, the page shows it in place, and :attr:`WebSearchSettings.selected` is what a search goes
through. A list with nothing usable resolves to :data:`DEFAULT_ENGINES` rather than leaving the action
with nowhere to search.
"""

from collections.abc import Iterable
from functools import lru_cache
from typing import Final, NamedTuple
from urllib.parse import quote_plus

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal

from .persistent_settings import persistent_settings

GROUP: Final = "web_search"
ENGINES_KEY: Final = "engines"
NAME_KEY: Final = "name"
URL_KEY: Final = "url"
ACTIVE_KEY: Final = "active"

QUERY_PLACEHOLDER: Final = "{query}"
"""Where in a template the URL-encoded query goes."""


class SearchEngine(NamedTuple):
    """One row: a name, the URL template a query is put into, and whether searches go through it."""

    name: str
    """What the row shows; empty is a validation problem (:data:`EMPTY_NAME_PROBLEM`)."""

    url: str
    """The URL template: ``http`` or ``https``, holding :data:`QUERY_PLACEHOLDER`."""

    active: bool = False
    """Whether a search goes through this engine. The list editor keeps at most one row active; an
    unusable active row, or none, resolves to the first usable engine (:attr:`WebSearchSettings.selected`)."""


DEFAULT_ENGINES: Final = (
    SearchEngine("Google", "https://www.google.com/search?q={query}", active=True),
    SearchEngine("DuckDuckGo", "https://duckduckgo.com/?q={query}"),
    SearchEngine("Bing", "https://www.bing.com/search?q={query}"),
)
"""The shipped list; a fresh install searches with Google."""

EMPTY_NAME_PROBLEM: Final = "An engine needs a name."
NOT_HTTP_PROBLEM: Final = "The URL must start with http:// or https://."
NO_PLACEHOLDER_PROBLEM: Final = f"The URL must contain {QUERY_PLACEHOLDER}, where the search text goes."


def engine_problem(engine: SearchEngine) -> str:
    """Why ``engine`` cannot be searched with, if it cannot.

    :param engine: the row to check.
    :returns: the explanation, or an empty string when the row is fine.
    """
    if not engine.name.strip():
        return EMPTY_NAME_PROBLEM
    if not engine.url.lower().startswith(("http://", "https://")):
        return NOT_HTTP_PROBLEM
    if QUERY_PLACEHOLDER not in engine.url:
        return NO_PLACEHOLDER_PROBLEM
    return ""


def usable_engines(engines: Iterable[SearchEngine]) -> tuple[SearchEngine, ...]:
    """The rows of ``engines`` that :func:`engine_problem` accepts, in order.

    :param engines: the rows to filter.
    :returns: the usable ones, or :data:`DEFAULT_ENGINES` when none is -- so there is always somewhere
        to search.
    """
    return tuple(engine for engine in engines if not engine_problem(engine)) or DEFAULT_ENGINES


def search_url(template: str, query: str) -> str:
    """Put ``query`` into ``template`` as a URL query string.

    :param template: a URL holding :data:`QUERY_PLACEHOLDER`.
    :param query: the search text, encoded here.
    :returns: the URL to open.
    """
    return template.replace(QUERY_PLACEHOLDER, quote_plus(query))


class WebSearchSettings(QObject):
    """The engine list, raw as the page left it -- the active flag included.

    A reactive ``QObject`` (`SimpleProperty`) so the toolbar action follows a save the way it follows a
    rename: its tooltip shows what the click will do.

    :param parent: optional Qt parent.
    """

    engines_changed = Signal(object)
    """Fires whenever :attr:`engines` changes -- a tuple value, hence an explicit ``Signal(object)``."""

    engines = SimpleProperty[tuple[SearchEngine, ...]](default_factory=lambda: DEFAULT_ENGINES)
    """Every row, in order, raw as stored -- a broken one included."""

    @property
    def usable_engines(self) -> tuple[SearchEngine, ...]:
        """The rows :func:`engine_problem` accepts, in order; :data:`DEFAULT_ENGINES` when none is."""
        return usable_engines(self.engines)

    @property
    def selected(self) -> SearchEngine:
        """The engine a search goes through: the first usable row that is active, else the first
        usable row."""
        usable = self.usable_engines
        return next((engine for engine in usable if engine.active), usable[0])

    def load(self, settings: QSettings) -> None:
        """Replace :attr:`engines` with what's in persistent storage; a never-saved list is the shipped one.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        try:
            engines: list[SearchEngine] = []
            for index in range(settings.beginReadArray(ENGINES_KEY)):
                settings.setArrayIndex(index)
                engines.append(
                    SearchEngine(
                        str(settings.value(NAME_KEY, "")),
                        str(settings.value(URL_KEY, "")),
                        bool(settings.value(ACTIVE_KEY, False, type=bool)),
                    )
                )
            settings.endArray()
            self.engines = tuple(engines) or DEFAULT_ENGINES
        finally:
            settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save :attr:`engines` to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        try:
            # QSettings' array writer never deletes the indexed keys a longer array left behind, so a
            # list that shrank would keep its dead rows in the file
            settings.remove(ENGINES_KEY)
            settings.beginWriteArray(ENGINES_KEY)
            for index, engine in enumerate(self.engines):
                settings.setArrayIndex(index)
                settings.setValue(NAME_KEY, engine.name)
                settings.setValue(URL_KEY, engine.url)
                settings.setValue(ACTIVE_KEY, engine.active)
            settings.endArray()
        finally:
            settings.endGroup()


@lru_cache(maxsize=1)
def shared_web_search_settings() -> WebSearchSettings:
    """The single, process-wide `WebSearchSettings`, loaded from persistent storage on first call --
    the settings page's Save is what the next click on the toolbar action reads.

    :returns: the shared instance.
    """
    settings = WebSearchSettings()
    settings.load(persistent_settings())
    return settings
