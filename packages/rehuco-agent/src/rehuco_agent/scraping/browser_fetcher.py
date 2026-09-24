"""The browser-driven `PageFetcher`: a short-lived Selenium session per scrape, and a wholly separate,
un-automated login browser, both on the app's own persona profile ([[acquisition-tooling#browser-persona]]).

**Login and scraping are two different processes, on purpose.** A Selenium/WebDriver session is flagged
as automated by the browser itself for as long as it runs, whatever it happens to be doing at that
moment -- Firefox's Marionette sets ``navigator.webdriver`` the instant remote control is enabled, not
only while a command is in flight, because the WebDriver spec requires it. Google and Cloudflare-grade
challenges key off exactly that flag, so a Selenium-controlled browser cannot sign in anywhere either of
them guards, no matter how it is driven or how long the user is given to answer a challenge by hand.
`open_for_login` therefore never touches Selenium at all: it launches the browser directly, the same way
double-clicking its icon would. What carries the login forward to a later, Selenium-driven scrape is not
a shared live session -- it is the **profile directory** the two share: cookies a plain login window
wrote are on disk before that window ever closes, and any later session opened on the same folder reads
them like any other returning visit. The one thing they cannot do is run at once: a profile can be held
open by only one browser process at a time, plain or Selenium-driven alike.
"""

import logging
import shutil
import subprocess  # nosec B404  # only ever runs a browser executable `find_browser_binary` resolved
import threading
from collections.abc import Callable
from functools import lru_cache
from typing import Final

from PySide6.QtCore import QObject, QThreadPool, Signal
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait

from ..settings.scrapers_settings import Browser, ScrapersSettings, persona_folder
from . import browser_drivers
from .protocols import FetchError
from .results import Page

LOG: Final = logging.getLogger(__name__)

PAGE_LOAD_TIMEOUT_SECONDS: Final = 30
"""How long one fetch waits for a page to finish loading -- the browser equivalent of
`~.http_fetcher.REQUEST_TIMEOUT_SECONDS`."""

READY_STATE_POLL_SECONDS: Final = 15
"""How long `fetch` waits for ``document.readyState`` to reach ``"complete"`` after a navigation."""

LOGIN_PROCESS_TERMINATE_TIMEOUT_SECONDS: Final = 10
"""How long `PersonaBrowser.reset` waits for a still-open login window to exit after asking it to,
before giving up on asking nicely."""

LOGIN_PROCESS_KILL_TIMEOUT_SECONDS: Final = 5
"""How long `PersonaBrowser.reset` waits after forcing a still-open login window closed."""

PROFILE_IN_USE_HINT: Final = (
    " If the persona browser is open for login, close it first -- a persona profile can only be held "
    "open by one browser at a time."
)
"""Appended to a scrape's `FetchError` when the browser failed to start -- the profile-lock failure this
produces reads as an opaque driver error otherwise, and this is overwhelmingly the reason for it."""


class PersonaBrowser:
    """Owns the persona's two, mutually exclusive uses of its profile: `open_for_login` opens a plain
    browser window for the user to log in through, and `fetch` runs one Selenium-driven scrape at a
    time ([[acquisition-tooling#browser-persona]]). See the module docstring for why they are not the
    same session.

    One `threading.Lock` serialises every scrape, since `~.scraper_executor.ScraperExecutor` runs
    several at once and a persona profile is not safe to open twice at once. The login window is not
    covered by that lock -- it is a separate process the user drives, not this class's own work -- so a
    scrape attempted while it is open simply fails to start its own session, with a message naming why.
    """

    def __init__(self) -> None:
        self.__lock: Final = threading.Lock()
        self.__login_processes: Final[dict[Browser, subprocess.Popen]] = {}

    def open_for_login(self, browser: Browser, url: str | None = None) -> None:
        """Launch (or, if one is already open, just bring forward) a plain, un-automated ``browser``
        window on its persona, for the user to log in to any site by hand.

        :param browser: which browser's persona to open.
        :param url: a page to open immediately -- a new tab in an already-open window, or the first tab
            of a freshly-launched one. `None` opens on nothing in particular, what **Open the browser**
            itself asks for; a scraper's own site link passes its `~.protocols.SiteScraper.site_url`.
        :raises FetchError: ``browser`` could not be found or started.
        """
        existing = self.__login_processes.get(browser)
        already_open = existing is not None and existing.poll() is None
        try:
            process = self.__start_login_process(browser, url)
        except (FileNotFoundError, OSError) as error:
            raise FetchError(f"Could not open {browser.value.capitalize()}: {error}") from error
        if not already_open:
            self.__login_processes[browser] = process  # pylint: disable=unsupported-assignment-operation

    def fetch(self, url: str, browser: Browser, *, headless: bool) -> Page:
        """Fetch ``url`` on a short-lived Selenium session on the persona, quit once done.

        :param url: the address to fetch.
        :param browser: which browser's persona to use.
        :param headless: whether the session runs with no visible window.
        :returns: the fetched page.
        :raises FetchError: the browser could not be started (including because a login window is
            currently holding the profile open), or navigation failed.
        """
        with self.__lock:
            driver = self.__start_scrape_driver(browser, headless=headless)
            try:
                return self.__navigate(driver, url)
            finally:
                self.__quit(driver)

    def reset(self, browser: Browser) -> None:
        """Close any open login window and delete ``browser``'s persona folder, so the next use starts
        from a clean, logged-out profile.

        :param browser: which browser's persona to reset.
        :raises OSError: the folder could not be deleted, e.g. a file inside it is still locked by a
            process that has not exited yet.
        """
        process = self.__login_processes.pop(browser, None)
        if process is not None and process.poll() is None:
            self.__terminate_login_process(process)
        shutil.rmtree(persona_folder(browser), ignore_errors=False)

    def __start_login_process(self, browser: Browser, url: str | None) -> subprocess.Popen:
        """Launch ``browser`` plainly on its persona folder -- no Selenium involved at all.

        :param url: a page to open immediately, or `None` -- see :meth:`open_for_login`.
        :raises FileNotFoundError: ``browser`` was not found on this machine.
        :raises OSError: the process could not be started.
        """
        command = browser_drivers.login_command(browser, persona_folder(browser), url)
        return subprocess.Popen(command)  # nosec B603  # a resolved executable and fixed arguments, never a shell

    @staticmethod
    def __terminate_login_process(process: subprocess.Popen) -> None:
        """Ask a still-open login window to close, then force it if it does not -- so a reset never
        deletes a profile a live browser process still has files open in."""
        process.terminate()
        try:
            process.wait(timeout=LOGIN_PROCESS_TERMINATE_TIMEOUT_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        process.kill()
        try:
            process.wait(timeout=LOGIN_PROCESS_KILL_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            LOG.warning("The persona browser did not exit after being killed; the reset may fail to delete it.")

    def __navigate(self, driver: WebDriver, url: str) -> Page:
        """Load ``url`` in ``driver``'s current tab and return it as a `Page`."""
        try:
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
            driver.get(url)
            WebDriverWait(driver, READY_STATE_POLL_SECONDS).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            return Page(url=url, final_url=driver.current_url, html=driver.page_source)
        except WebDriverException as error:
            raise FetchError(f"Could not fetch {url} with the persona browser: {error}") from error

    @staticmethod
    def __start_scrape_driver(browser: Browser, *, headless: bool) -> WebDriver:
        """Start a fresh Selenium session on ``browser``'s persona folder, for one scrape.

        :raises FetchError: the browser or its driver could not be started.
        """
        try:
            return browser_drivers.start_driver(browser, headless=headless, profile_folder=persona_folder(browser))
        except WebDriverException as error:
            raise FetchError(
                f"Could not start {browser.value.capitalize()} for a scrape: {error}.{PROFILE_IN_USE_HINT}"
            ) from error

    @staticmethod
    def __quit(driver: WebDriver) -> None:
        """Quit ``driver``, tolerating a process that already went away."""
        try:
            driver.quit()
        except Exception:  # pylint: disable=broad-exception-caught
            LOG.debug("Quitting the persona browser raised; the process was likely already gone.", exc_info=True)


@lru_cache(maxsize=1)
def shared_persona_browser() -> PersonaBrowser:
    """The single, process-wide `PersonaBrowser`.

    :returns: the shared instance.
    """
    return PersonaBrowser()


class PersonaAction(QObject):
    """Runs one action against the persona browser -- opening it for login, or resetting it -- on a
    pooled worker thread, so neither can freeze the Scrapers settings page (#278). Resetting can take a
    few seconds: it may have to wait out a still-open login window before it can delete the profile.

    The same shape as `rehuco_agent.fields.background_measurement.BackgroundMeasurement`: :meth:`start`
    fires the work off, and :attr:`finished` reports back. `QThreadPool`'s automatic connection type
    marshals the emit from the worker thread onto whatever thread a connected slot lives on -- there is
    nothing GUI-specific here to justify an explicit queued connection.

    Runs on `QThreadPool.globalInstance()`, not `~.scraper_executor.ScraperExecutor`'s dedicated pool:
    a settings-page action, not a scrape, that should neither compete with that pool's four-scrape
    budget nor be capped by it.
    """

    finished = Signal(object)
    """Fires once ``action`` returns, with `None` on success or its exception's message on failure."""

    def start(self, action: Callable[[], None]) -> None:
        """Run ``action``, off the calling thread.

        :param action: the persona call to make -- `PersonaBrowser.open_for_login` or
            `PersonaBrowser.reset`, both already bound to their browser argument.
        """
        QThreadPool.globalInstance().start(lambda: self.__run(action))

    def __run(self, action: Callable[[], None]) -> None:
        """Do the work -- runs on the pool thread `start` handed it to."""
        try:
            action()
        except (FetchError, OSError) as error:
            self.finished.emit(str(error))
        else:
            self.finished.emit(None)


# one method is the design, not an omission -- see the docstring below
# pylint: disable-next=too-few-public-methods
class BrowserPageFetcher:
    """Satisfies `~.protocols.PageFetcher` by delegating to `shared_persona_browser`, configured from
    `ScrapersSettings`.

    :param settings: where the browser choice and the show-browser flag come from.
    """

    def __init__(self, settings: ScrapersSettings) -> None:
        self.__settings: Final = settings

    def fetch(self, url: str) -> Page:
        """Fetch ``url`` through the persona browser :attr:`__settings` configures.

        :param url: the address to fetch.
        :returns: the fetched page.
        :raises FetchError: the fetch failed.
        """
        return shared_persona_browser().fetch(url, self.__settings.browser, headless=not self.__settings.show_browser)
