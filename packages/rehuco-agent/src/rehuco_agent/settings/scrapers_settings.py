"""Where the Scrapers settings page keeps the scripts folder, and the browser persona's own settings
([[acquisition-tooling#scraper-registry]], [[acquisition-tooling#browser-persona]]).

A plain `@dataclass`, like `ChecksumSettings` and `VideosSettings`: nothing already on screen renders
from this, it is read only when `rehuco_agent.scraping.registry.ScraperRegistry` reloads or a
`~rehuco_agent.scraping.scrape_job.ScrapeJob` picks a fetcher.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Final, cast

from PySide6.QtCore import QSettings

from .persistent_settings import APPLICATION_NAME, persistent_settings

GROUP: Final = "scrapers"
SCRIPTS_FOLDER_KEY: Final = "scripts_folder"
BROWSER_KEY: Final = "browser"
SHOW_BROWSER_KEY: Final = "show_browser"
BROWSER_SCRAPERS_KEY: Final = "browser_scrapers"


class Browser(StrEnum):
    """A browser the persona can drive -- every one Selenium Manager resolves a driver for and that
    takes a profile directory of its own. Safari has no such option, so it is left out."""

    FIREFOX = "firefox"
    CHROME = "chrome"
    EDGE = "edge"


def config_folder() -> Path:
    """This app's own config directory.

    Derived from `persistent_settings`'s own `.ini` location rather than `QStandardPaths.AppConfigLocation`
    -- that call needs an organization/application name set on `QCoreApplication`, which nothing in this
    app does today, while the `.ini`'s path already carries both. Its *parent* alone is the
    **organization** directory (``…/borco/``, shared by every borco app), so the application name is
    appended here to land under this app's own config directory specifically.

    :returns: this app's config directory. Not created by this call.
    """
    return Path(persistent_settings().fileName()).parent / APPLICATION_NAME


def default_scripts_folder() -> Path:
    """Where the scripts folder lives when nothing has been configured.

    :returns: the default scripts folder. Not created by this call; a registry reading a folder that
        does not exist simply finds no scripts in it.
    """
    return config_folder() / "scrapers"


def persona_folder(browser: Browser) -> Path:
    """Where ``browser``'s scraper persona profile lives -- the app's own browser identity, never the
    user's everyday one ([[acquisition-tooling#browser-persona]]).

    **This is a credential store.** It is never inside a resource folder, and nothing the app copies or
    syncs ever touches it. One folder per browser, since a Firefox profile and a Chromium user-data
    directory are not interchangeable formats.

    :param browser: which browser's persona to locate.
    :returns: the persona folder. Not created by this call.
    """
    return config_folder() / "persona" / browser.value


@dataclass
class ScrapersSettings:
    """Where the user's own scraper scripts live, and the browser persona's own settings.

    :attr:`scripts_folder` is stored as the page left it; what `ScraperRegistry` reads is
    :attr:`effective_scripts_folder`, the value it resolves to.
    """

    scripts_folder: str = ""
    """The configured scripts folder, or empty to use :func:`default_scripts_folder`."""

    browser: Browser = Browser.FIREFOX
    """Which browser the persona uses."""

    show_browser: bool = False
    """Whether a scrape shows its browser window rather than running headless -- a debugging switch."""

    browser_scrapers: frozenset[str] = field(default_factory=frozenset)
    """Keys (see `scraper_key`) of scrapers the user ticked **Use browser** for, beside every scraper
    whose own `~rehuco_agent.scraping.protocols.SiteScraper.needs_browser` already forces it."""

    @property
    def effective_scripts_folder(self) -> Path:
        """The folder `ScraperRegistry.reload` actually scans: :attr:`scripts_folder` when set, else
        :func:`default_scripts_folder`.
        """
        return Path(self.scripts_folder) if self.scripts_folder else default_scripts_folder()

    def uses_browser(self, scraper: object) -> bool:
        """Whether ``scraper`` is fetched through the persona browser: either it declares
        `~rehuco_agent.scraping.protocols.SiteScraper.needs_browser`, or the user ticked it in the
        Scrapers table.

        :param scraper: the scraper a scrape resolved to.
        :returns: whether the persona browser, not plain HTTP, should fetch its page.
        """
        if getattr(scraper, "needs_browser", False):
            return True
        return scraper_key(scraper) in self.browser_scrapers

    def load(self, settings: QSettings) -> None:
        """Replace the current value with what's in persistent storage.

        :param settings: the `QSettings` to read from.
        """
        settings.beginGroup(GROUP)
        self.scripts_folder = cast(str, settings.value(SCRIPTS_FOLDER_KEY, "", type=str))
        stored_browser = cast(str, settings.value(BROWSER_KEY, Browser.FIREFOX.value, type=str))
        try:
            self.browser = Browser(stored_browser)
        except ValueError:
            self.browser = Browser.FIREFOX
        self.show_browser = cast(bool, settings.value(SHOW_BROWSER_KEY, False, type=bool))
        stored_keys = cast(list[str], settings.value(BROWSER_SCRAPERS_KEY, [], type=list))
        self.browser_scrapers = frozenset(stored_keys)
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current value to persistent storage.

        :param settings: the `QSettings` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(SCRIPTS_FOLDER_KEY, self.scripts_folder)
        settings.setValue(BROWSER_KEY, self.browser.value)
        settings.setValue(SHOW_BROWSER_KEY, self.show_browser)
        settings.setValue(BROWSER_SCRAPERS_KEY, sorted(self.browser_scrapers))
        settings.endGroup()


def scraper_key(scraper: object) -> str:
    """A stable identity for ``scraper``'s class, to key :attr:`ScrapersSettings.browser_scrapers` by.

    A user script's module is prefixed ``rehuco_user_scrapers.`` by `ScraperRegistry`, so a key stays
    the same across reloads as long as the file's stem does not change.

    :param scraper: a scraper instance (built-in or from the scripts folder).
    :returns: ``"<module>.<qualname>"`` of its class.
    """
    cls = type(scraper)
    return f"{cls.__module__}.{cls.__qualname__}"


@lru_cache(maxsize=1)
def shared_scrapers_settings() -> ScrapersSettings:
    """The single, process-wide `ScrapersSettings` instance, loaded from persistent storage on first
    call -- the same shape, and for the same reason, as `shared_checksum_settings`: the settings page's
    Save must be what the next `ScraperRegistry.reload` and the next `ScrapeJob` read.

    :returns: the shared instance.
    """
    settings = ScrapersSettings()
    settings.load(persistent_settings())
    return settings
