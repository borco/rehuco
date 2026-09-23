"""The scraper registry: the user's own scripts first, then the built-ins
([[acquisition-tooling#scraper-registry]]).
"""

import importlib.util
import inspect
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Final, cast

from .protocols import SiteScraper
from .sites.artstation import ArtStation
from .sites.udemy import Udemy

LOG: Final = logging.getLogger(__name__)

USER_SCRAPER_MODULE_PREFIX: Final = "rehuco_user_scrapers"
"""Prefixes every module name handed to `importlib`, so a script called ``requests.py`` can neither
shadow the real package nor be shadowed by it -- the loaded module is never inserted into `sys.modules`
either, so this prefix is the only thing standing between two files with the same stem."""

BUILTIN_SCRAPERS: Final[tuple[type[SiteScraper], ...]] = (ArtStation, Udemy)
"""The scrapers this build ships."""


@dataclass(frozen=True)
class LoadedScraperModule:
    """One user script file, as the loader saw it -- one row of the Scrapers settings page's table.

    :param path: the file this row describes.
    :param scrapers: the scrapers it defines, as instances kept only for their `label`/`publisher` and
        for having proven the file loads; a scrape never runs on one of these -- see
        `ScraperRegistry.find`.
    :param error: why the file could not be loaded or executed, or `None` when it loaded cleanly. A
        file that loads but defines no scraper at all is not an error -- it simply contributes nothing.
    """

    path: Path
    scrapers: tuple[SiteScraper, ...]
    error: str | None


BUILTIN_SOURCE_LABEL: Final = "Built-in"
"""What the Scrapers table's Source column shows for a scraper this build ships, rather than a file
name."""


@dataclass(frozen=True)
# a data-carrying row, not behaviour -- splitting it would only scatter one table row's fields
# pylint: disable-next=too-many-instance-attributes
class ScraperRow:
    """One row of the Scrapers settings page's table: one scraper, or one script file that loaded but
    defines no scraper, or failed to load at all ([[acquisition-tooling#browser-persona]]).

    A scraper needs its own row, built-ins included, so the **Use browser** column
    (`~rehuco_agent.settings.scrapers_settings.ScrapersSettings.browser_scrapers`) can be ticked for it
    -- `LoadedScraperModule`'s one-row-per-file shape has no row for a built-in scraper to hang a
    checkbox off.

    :param key: `~rehuco_agent.settings.scrapers_settings.scraper_key` of the scraper this row is for,
        or `None` for a file contributing no scraper (no checkbox, no key to stage).
    :param label: the scraper's own `label`, or `~.scrapers_table_model.NO_SCRAPERS_TEXT` for a file row.
    :param publisher: the scraper's `publisher`, shown alongside :attr:`label` only when it differs --
        ArtStation's scraper names both the same, and showing ``"ArtStation (ArtStation)"`` would say
        nothing a plain ``"ArtStation"`` doesn't. Empty for a file row.
    :param site_name: the scraper's `~.protocols.SiteScraper.site_name`, what the table's Scraper column
        shows as a link. Empty for a file row.
    :param site_url: the scraper's `~.protocols.SiteScraper.site_url`, what that link opens. Empty for a
        file row.
    :param source: the file's name, or :data:`BUILTIN_SOURCE_LABEL`.
    :param needs_browser: whether this scraper always uses the persona browser, forcing its checkbox on
        and disabled. `False`, meaningless, for a file row.
    :param error: why the file could not be loaded, or `None`.
    """

    key: str | None
    label: str
    publisher: str
    site_name: str
    site_url: str
    source: str
    needs_browser: bool
    error: str | None


class ScraperRegistry:
    """Loads scrapers from a scripts folder, ahead of this build's own ([[acquisition-tooling#scraper-registry]]).

    A user's own script needs no import from this package: `SiteScraper` is a plain, structural
    `Protocol`, so a class satisfies it by shape alone, and :meth:`reload` finds every class in every
    ``*.py`` file in the folder that does, without being told which ones to look for.

    **Holds classes, builds instances on demand.** The instance made while scanning a file is used only
    for the structural check and for the table's `label`/`publisher` columns; :meth:`find` always builds
    a fresh one, so two concurrent scrapes for the same host never share one user-written object's state.

    :param folder: the scripts folder to scan, or `None` to read
        `rehuco_agent.settings.scrapers_settings.shared_scrapers_settings`'s
        ``effective_scripts_folder`` on every :meth:`reload` -- the shape every caller but a test wants.
    :param builtins: the built-in scraper classes, in the order they should be tried after the folder's.
    """

    @dataclass(frozen=True)
    class State:
        """The whole of what a scan produces, swapped in as one unit so a concurrent `find` never sees
        a folder's classes and its module rows out of step with each other.

        Nested rather than a module-level helper: it is meaningless outside `ScraperRegistry`, which is
        the only class that ever builds or reads one.
        """

        modules: tuple[LoadedScraperModule, ...]
        folder_classes: tuple[type[SiteScraper], ...]

    def __init__(self, folder: Path | None = None, builtins: Iterable[type[SiteScraper]] = BUILTIN_SCRAPERS) -> None:
        self.__folder: Final = folder
        self.__builtins: Final = tuple(builtins)
        self.__state: ScraperRegistry.State = ScraperRegistry.State(modules=(), folder_classes=())
        self.reload()

    @property
    def modules(self) -> tuple[LoadedScraperModule, ...]:
        """Every scripts-folder file the last :meth:`reload` scanned, in scan order."""
        return self.__state.modules

    @property
    def rows(self) -> tuple[ScraperRow, ...]:
        """The Scrapers table's rows: one per scraper (folder first, then built-in, each a fresh
        instance for its `label`/`publisher`), interleaved with one per file that loaded no scraper or
        failed to -- the same scan order `find` tries, so the table reads top to bottom as the dispatch
        order it describes."""
        from ..settings.scrapers_settings import scraper_key  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

        rows: list[ScraperRow] = []
        for module in self.__state.modules:
            if module.scrapers:
                for scraper in module.scrapers:
                    rows.append(
                        ScraperRow(
                            key=scraper_key(scraper),
                            label=scraper.label,
                            publisher=scraper.publisher,
                            site_name=scraper.site_name,
                            site_url=scraper.site_url,
                            source=module.path.name,
                            needs_browser=scraper.needs_browser,
                            error=None,
                        )
                    )
            else:
                rows.append(
                    ScraperRow(
                        key=None,
                        label="",
                        publisher="",
                        site_name="",
                        site_url="",
                        source=module.path.name,
                        needs_browser=False,
                        error=module.error,
                    )
                )
        for scraper_class in self.__builtins:
            instance = self.__instantiate(scraper_class)
            if instance is None:
                continue
            rows.append(
                ScraperRow(
                    key=scraper_key(instance),
                    label=instance.label,
                    publisher=instance.publisher,
                    site_name=instance.site_name,
                    site_url=instance.site_url,
                    source=BUILTIN_SOURCE_LABEL,
                    needs_browser=instance.needs_browser,
                    error=None,
                )
            )
        return tuple(rows)

    def reload(self) -> None:
        """Re-scan the scripts folder, without a restart.

        Nothing already resolved by :meth:`find` is affected -- a scrape in flight keeps the instance it
        was handed. The new scan replaces the old one all at once, so a concurrent `find` sees either the
        old state or the new one, never a mix.
        """
        folder = self.__folder if self.__folder is not None else self.__configured_folder()
        self.__state = self.__scan(folder)

    def find(self, url: str) -> SiteScraper | None:
        """Find the first scraper that claims ``url``: the scripts folder's, then the built-ins.

        :param url: the URL a scrape was asked to run against.
        :returns: a fresh instance of the first matching scraper, or `None` when none does.
        """
        for scraper_class in (*self.__state.folder_classes, *self.__builtins):
            instance = self.__instantiate(scraper_class)
            if instance is not None and instance.matches(url):
                return instance
        return None

    @staticmethod
    def __configured_folder() -> Path:
        """The folder the Scrapers settings page has saved.

        A local import: `rehuco_agent.settings` has no reason to import scraping back, but importing it
        at module scope here would still make every import of this module load the whole settings
        package, including its `QSettings` construction, for a call only :meth:`reload` makes.
        """
        from ..settings.scrapers_settings import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
            shared_scrapers_settings,
        )

        return shared_scrapers_settings().effective_scripts_folder

    @staticmethod
    def __scan(folder: Path) -> ScraperRegistry.State:
        """Scan ``folder`` for scrapers, tolerating a missing folder and a broken file alike.

        :param folder: the scripts folder.
        :returns: the modules found and the classes to try, both in scan order.
        """
        if not folder.is_dir():
            return ScraperRegistry.State(modules=(), folder_classes=())
        modules: list[LoadedScraperModule] = []
        classes: list[type[SiteScraper]] = []
        for path in sorted(folder.glob("*.py")):
            found_classes, found_instances, error = ScraperRegistry.__scan_file(path)
            modules.append(LoadedScraperModule(path=path, scrapers=found_instances, error=error))
            classes.extend(found_classes)
        return ScraperRegistry.State(modules=tuple(modules), folder_classes=tuple(classes))

    @staticmethod
    def __scan_file(
        path: Path,
    ) -> tuple[tuple[type[SiteScraper], ...], tuple[SiteScraper, ...], str | None]:
        """Load one file and collect every `SiteScraper` it defines.

        :param path: the file to load.
        :returns: the classes found, the instances made from them (for the table), and an error message
            when the file itself could not be loaded or executed -- never both a result and an error.
        """
        try:
            module = ScraperRegistry.__load_module(path)
        except Exception as error:  # pylint: disable=broad-exception-caught
            return (), (), f"{type(error).__name__}: {error}"
        classes: list[type[SiteScraper]] = []
        instances: list[SiteScraper] = []
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if candidate.__module__ != module.__name__:
                continue
            scraper_candidate = cast(type[SiteScraper], candidate)
            instance = ScraperRegistry.__instantiate(scraper_candidate)
            if instance is not None and isinstance(instance, SiteScraper):
                classes.append(scraper_candidate)
                instances.append(instance)
        return tuple(classes), tuple(instances), None

    @staticmethod
    def __load_module(path: Path) -> ModuleType:
        """Execute ``path`` as a standalone module, independent of `sys.path` or `sys.modules`.

        :param path: the file to load.
        :returns: the executed module object.
        :raises ImportError: when no loader can be built for ``path``.
        """
        module_name = f"{USER_SCRAPER_MODULE_PREFIX}.{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"{path} could not be loaded as a Python module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def __instantiate(scraper_class: type[SiteScraper]) -> SiteScraper | None:
        """Build a no-argument instance of ``scraper_class``, tolerating one that cannot be built this
        way.

        :param scraper_class: the class to instantiate.
        :returns: the instance, or `None` when construction failed -- a class requiring arguments is
            simply not a scraper this loader can build, not an error to report.
        """
        try:
            return scraper_class()
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.debug("%s could not be constructed with no arguments; skipped.", scraper_class, exc_info=True)
            return None


@lru_cache(maxsize=1)
def shared_scraper_registry() -> ScraperRegistry:
    """The single, process-wide `ScraperRegistry` both the Scrapers settings page and every `ScrapeJob`
    use -- without one shared instance, a Reload on the page would reload an object no job ever consults.

    :returns: the shared instance, already loaded from the configured scripts folder.
    """
    return ScraperRegistry()
