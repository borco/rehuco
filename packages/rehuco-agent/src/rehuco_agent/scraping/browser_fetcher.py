"""The browser-driven `PageFetcher`: one short-lived Selenium session per scrape, and a wholly separate,
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

from ..pool_relay import PoolRelay
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

RESPONSE_STATUS_SCRIPT: Final = (
    "const entry = performance.getEntriesByType('navigation')[0]; return entry ? entry.responseStatus : null;"
)
"""Reads the loaded document's HTTP status from its Navigation Timing entry -- WebDriver itself has no
command for it. Verified against Firefox 156 (#369): ``200``, ``503``, and after a ``302`` the final
page's ``503``, which is what `~.results.Page.status` means. A browser without ``responseStatus``
answers `None` or ``0``, both read as "unknown"."""

LOGIN_PROCESS_TERMINATE_TIMEOUT_SECONDS: Final = 10
"""How long `PersonaBrowser.reset` waits for a still-open login window to exit after asking it to,
before giving up on asking nicely."""

LOGIN_PROCESS_KILL_TIMEOUT_SECONDS: Final = 5
"""How long `PersonaBrowser.reset` waits after forcing a still-open login window closed."""

LEASE_WAIT_SLICE_SECONDS: Final = 0.1
"""How often a lease waiting for the profile looks at its holder's stop request, so a scan held up behind another
holder can still be paused or canceled at once."""

PROFILE_IN_USE_HINT: Final = (
    " If the persona browser is open for login, close it first -- a persona profile can only be held "
    "open by one browser at a time."
)
"""Appended to a scrape's `FetchError` when the browser failed to start -- the profile-lock failure this
produces reads as an opaque driver error otherwise, and this is overwhelmingly the reason for it."""


class PersonaBrowser:
    """Owns the persona's two, mutually exclusive uses of its profile: `open_for_login` opens a plain
    browser window for the user to log in through, and a :class:`PersonaLease` runs one Selenium-driven
    scrape or scan at a time ([[acquisition-tooling#browser-persona]]). See the module docstring for why
    they are not the same session.

    One `threading.Lock` serializes every scrape, since `~.scraper_executor.ScraperExecutor` runs
    several at once and a persona profile is not safe to open twice at once. The login window is not
    covered by that lock -- it is a separate process the user drives, not this class's own work -- so a
    scrape attempted while it is open simply fails to start its own session, with a message naming why.

    **A library scan holds the profile for hours, and a drop must still get in** (#682): its lease gives the profile
    up between two of its pages whenever another one is waiting for it (:attr:`wanted`). A drop's lease is its
    scrape's, closed with it (:class:`BrowserPageFetcher`).
    """

    def __init__(self) -> None:
        self.__lock: Final = threading.Lock()
        self.__waiting_lock: Final = threading.Lock()
        self.__waiting = 0
        self.__login_processes: Final[dict[Browser, subprocess.Popen]] = {}

    @property
    def wanted(self) -> bool:
        """Whether a lease is waiting for the profile, so a scan holding it should give it up.

        :returns: whether one waits.
        """
        with self.__waiting_lock:
            return self.__waiting > 0

    def lease(self, browser: Browser, *, headless: bool, checkpoint: Callable[[], None] | None) -> PersonaLease:
        """Hold the persona for a run of fetches: a scrape's few pages, or a library scan's.

        :param browser: which browser's persona to use.
        :param headless: whether its sessions run with no visible window.
        :param checkpoint: the holder's own, called while it waits for the profile -- what it raises gives up waiting;
            ``None`` for a holder that is never stopped, a scrape.
        :returns: the lease, holding nothing until it is first asked for a session.
        """
        return PersonaLease(self, browser, headless=headless, checkpoint=checkpoint)

    def hold(self, browser: Browser, *, headless: bool, checkpoint: Callable[[], None] | None) -> WebDriver:
        """Take the profile and start a session on it, for :class:`PersonaLease`; :meth:`let_go` gives both back.

        Waiting for the profile counts as :attr:`wanted`, so a scan gives it up at its next page: a drop gets in, and
        two scans of different stores take turns rather than one waiting out the other.

        :param browser: which browser's persona to use.
        :param headless: whether the session runs with no visible window.
        :param checkpoint: called while waiting for the profile; what it raises leaves the profile untaken. ``None``
            waits plainly.
        :returns: the session.
        :raises FetchError: the browser could not be started; the profile is not held.
        """
        self.__take(checkpoint)
        try:
            return self.__start_scrape_driver(browser, headless=headless)
        except BaseException:
            self.__lock.release()
            raise

    def __take(self, checkpoint: Callable[[], None] | None) -> None:
        """Take the profile's lock, counted as waiting for it until it is held.

        :param checkpoint: called every :data:`LEASE_WAIT_SLICE_SECONDS` while waiting, for a holder that must stay
            stoppable; ``None`` waits plainly, as a scrape does.
        """
        with self.__waiting_lock:
            self.__waiting += 1
        try:
            if checkpoint is None:
                self.__lock.acquire()  # pylint: disable=consider-using-with  # released by the caller
            else:
                # released by the caller, as above
                while not self.__lock.acquire(timeout=LEASE_WAIT_SLICE_SECONDS):  # pylint: disable=consider-using-with
                    checkpoint()
        finally:
            with self.__waiting_lock:
                self.__waiting -= 1

    def let_go(self, driver: WebDriver) -> None:
        """Quit a session :meth:`hold` started and give the profile back.

        :param driver: the session.
        """
        try:
            self.__quit(driver)
        finally:
            self.__lock.release()

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


class PersonaLease:
    """A run of fetches on the persona, over one session: a scrape's few pages, or a library scan's thousands (#682).

    Its session is started on first use and kept between pages. A scan calls :meth:`yield_if_wanted` between two of
    them, which quits it when another lease is waiting, so a drop never queues behind hours of scanning; the next
    :meth:`driver` starts a fresh one once that one is done. Used on one thread, its holder's; :meth:`close` gives
    everything back.

    :param browser: the persona browser it leases from.
    :param persona: which browser's persona to use.
    :param headless: whether its sessions run with no visible window.
    :param checkpoint: the holder's own, called while it waits for the profile; ``None`` for one never stopped.
    """

    def __init__(
        self, browser: PersonaBrowser, persona: Browser, *, headless: bool, checkpoint: Callable[[], None] | None
    ) -> None:
        self.__browser: Final = browser
        self.__persona: Final = persona
        self.__headless: Final = headless
        self.__checkpoint: Final = checkpoint
        self.__driver: WebDriver | None = None

    def __enter__(self) -> PersonaLease:
        """Hold the lease for a ``with`` block; nothing is started until :meth:`driver` is asked.

        :returns: this lease.
        """
        return self

    def __exit__(self, *_: object) -> None:
        """Give everything back however the block ends (:meth:`close`)."""
        self.close()

    def driver(self) -> WebDriver:
        """The session to fetch with, started now if the lease holds none -- waiting, stoppably, while another holder
        has the profile.

        :returns: the session.
        :raises FetchError: the browser could not be started.
        """
        if self.__driver is None:
            self.__driver = self.__browser.hold(self.__persona, headless=self.__headless, checkpoint=self.__checkpoint)
        return self.__driver

    def fetch(self, url: str) -> Page:
        """Load ``url`` in the session, started now if the lease holds none.

        A failed load quits the session, which may be gone (a window closed by hand, a crash): the next fetch starts a
        fresh one rather than failing on the dead one.

        :param url: the address to fetch.
        :returns: the fetched page.
        :raises FetchError: the browser could not be started (including because a login window is currently holding
            the profile open), or navigation failed.
        """
        driver = self.driver()
        try:
            return self.__navigate(driver, url)
        except FetchError:
            self.close()
            raise

    def yield_if_wanted(self) -> bool:
        """Give the profile up if another lease is waiting for it.

        :returns: whether it was given up.
        """
        if self.__driver is None or not self.__browser.wanted:
            return False
        self.close()
        return True

    def close(self) -> None:
        """Quit the session and give the profile back, if held."""
        driver, self.__driver = self.__driver, None
        if driver is not None:
            self.__browser.let_go(driver)

    @staticmethod
    def __navigate(driver: WebDriver, url: str) -> Page:
        """Load ``url`` in ``driver``'s current tab and return it as a `Page`, with its HTTP status when
        the browser reports one -- so a scraper can read a transient refusal the same way it does from
        `~.http_fetcher.HttpPageFetcher` (#369)."""
        try:
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
            driver.get(url)
            WebDriverWait(driver, READY_STATE_POLL_SECONDS).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
            return Page(
                url=url,
                final_url=driver.current_url,
                html=driver.page_source,
                status=PersonaLease.__response_status(driver),
            )
        except WebDriverException as error:
            raise FetchError(f"Could not fetch {url} with the persona browser: {error}") from error

    @staticmethod
    def __response_status(driver: WebDriver) -> int | None:
        """The loaded document's HTTP status (:data:`RESPONSE_STATUS_SCRIPT`), or `None` when the browser
        cannot say -- never a reason to fail a fetch that loaded.

        :param driver: the session that just loaded the page.
        :returns: the status, or `None`.
        """
        try:
            status = driver.execute_script(RESPONSE_STATUS_SCRIPT)
        except WebDriverException:
            LOG.debug("The persona browser could not report the page's HTTP status.", exc_info=True)
            return None
        # bool is an int subclass, and 0 is what a browser without the field (or a cross-origin entry)
        # reports -- neither is a status
        if isinstance(status, bool) or not isinstance(status, int) or status <= 0:
            return None
        return status


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
    fires the work off, and :attr:`finished` reports back, emitted on the GUI thread through the application's
    `~rehuco_agent.pool_relay.PoolRelay` -- never by the worker on this object, which the page may be deleting.

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
        relay = PoolRelay.instance()
        QThreadPool.globalInstance().start(lambda: self.__run(relay, action))

    def __run(self, relay: PoolRelay, action: Callable[[], None]) -> None:
        """Do the work -- runs on the pool thread `start` handed it to -- and answer through ``relay``.

        :param relay: the application's relay.
        :param action: the persona call to make.
        """
        try:
            action()
        except (FetchError, OSError) as error:
            relay.post(self, self.__deliver, str(error))
        else:
            relay.post(self, self.__deliver, None)

    def __deliver(self, message: str | None) -> None:
        """Emit :attr:`finished` (GUI thread).

        :param message: ``None`` on success, the failure's message otherwise.
        """
        self.finished.emit(message)


class BrowserPageFetcher:
    """Satisfies `~.protocols.PageFetcher` by a lease of `shared_persona_browser`, configured from
    `ScrapersSettings`: one browser session for every page of a scrape, however many the scraper asks for, started
    with the first of them. :meth:`close` quits it, and is its owner's to call -- until then no other scrape gets the
    profile.

    :param settings: where the browser choice and the show-browser flag come from.
    """

    def __init__(self, settings: ScrapersSettings) -> None:
        self.__lease: Final = shared_persona_browser().lease(
            settings.browser, headless=not settings.show_browser, checkpoint=None
        )

    def fetch(self, url: str) -> Page:
        """Fetch ``url`` through this scrape's browser session.

        :param url: the address to fetch.
        :returns: the fetched page.
        :raises FetchError: the fetch failed.
        """
        return self.__lease.fetch(url)

    def close(self) -> None:
        """Quit the session and give the profile back, if one was started."""
        self.__lease.close()
