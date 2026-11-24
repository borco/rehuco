"""Starts a browser on a persona profile: either Selenium-driven, for a scrape, or a plain,
un-automated process, for the user to log in through ([[acquisition-tooling#browser-persona]]).
"""

import shutil
import sys
from pathlib import Path
from typing import Final

from selenium import webdriver

# The drivers come from their own modules, not `webdriver.Firefox` and the like: selenium resolves those through a
# lazy module `__getattr__`, which pylint reads as not callable on Windows and as callable on Linux, so a suppression
# there is wrong on one of the two.
from selenium.webdriver.chrome.webdriver import WebDriver as ChromeDriver
from selenium.webdriver.edge.webdriver import WebDriver as EdgeDriver
from selenium.webdriver.firefox.webdriver import WebDriver as FirefoxDriver
from selenium.webdriver.remote.webdriver import WebDriver

from ..settings.scrapers_settings import Browser

FIREFOX_HEADLESS_ARG: Final = "-headless"
CHROMIUM_HEADLESS_ARG: Final = "--headless=new"

FIREFOX_JSON_VIEWER_PREFERENCE: Final = "devtools.jsonview.enabled"
"""Whether Firefox shows a JSON document in its own viewer, which replaces the document with the viewer's markup: the
page a scrape reads then holds no JSON at all. Off, it shows the text in a ``<pre>``, as Chrome and Edge do."""

BROWSER_BINARY_NAMES: Final[dict[Browser, tuple[str, ...]]] = {
    Browser.FIREFOX: ("firefox",),
    Browser.CHROME: ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
    Browser.EDGE: ("microsoft-edge", "microsoft-edge-stable", "msedge"),
}
"""Executable names tried on ``PATH``, per browser -- what `shutil.which` finds on Linux/macOS, and
what a Windows install sometimes adds too."""

WINDOWS_BINARY_PATHS: Final[dict[Browser, tuple[Path, ...]]] = {
    Browser.FIREFOX: (
        Path(r"C:\Program Files\Mozilla Firefox\firefox.exe"),
        Path(r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"),
    ),
    Browser.CHROME: (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ),
    Browser.EDGE: (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ),
}
"""Conventional install locations tried on Windows when the executable is not on ``PATH`` -- true of
every browser here by default; only Firefox tends to add itself to ``PATH`` at all, and inconsistently."""


def find_browser_binary(browser: Browser) -> Path | None:
    """Locate ``browser``'s executable, for launching it directly -- the same problem Selenium Manager
    solves internally for :func:`start_driver`, solved again here in plain terms since
    :func:`login_command`'s caller never goes through Selenium at all.

    :param browser: which browser to find.
    :returns: its executable path, or `None` if this function does not know where to find it.
    """
    for name in BROWSER_BINARY_NAMES[browser]:
        found = shutil.which(name)
        if found:
            return Path(found)
    if sys.platform == "win32":
        for candidate in WINDOWS_BINARY_PATHS[browser]:
            if candidate.is_file():
                return candidate
    return None


def login_command(browser: Browser, profile_folder: Path, url: str | None = None) -> list[str]:
    """The command line for a **plain, un-automated** ``browser`` window on ``profile_folder`` -- no
    Selenium, no WebDriver, no headless or automation flags of any kind, so the browser Google or
    Cloudflare sees is an ordinary one, not one flagged as scriptable for its whole session
    ([[acquisition-tooling#browser-persona]]).

    Launching this a second time while the first is still running does not open a second window: every
    browser here refuses two processes on the same profile and instead relays the request to the
    already-running one, which raises its own window -- exactly the "already open, bring it forward"
    behavior double-clicking a running browser's icon gives, needing nothing of our own to reproduce.
    Passed a ``url`` that second time, the same relaying opens it as a **new tab** in that window,
    rather than only focusing it -- what lets clicking a scraper's site link in the Scrapers table
    behave the same whether or not the persona browser already happens to be open.

    :param browser: which browser to launch.
    :param profile_folder: the persona profile to open. Created if it does not exist yet.
    :param url: a page to open immediately -- the new tab (or, with nothing already running, the first
        one) loads this instead of the browser's own default start page. `None` opens on nothing in
        particular, the shape **Open the browser** wants.
    :returns: the command line, ready for `subprocess.Popen`.
    :raises FileNotFoundError: ``browser`` was not found on this machine.
    """
    profile_folder.mkdir(parents=True, exist_ok=True)
    binary = find_browser_binary(browser)
    if binary is None:
        raise FileNotFoundError(f"{browser.value.capitalize()} was not found on this machine.")
    if browser is Browser.FIREFOX:
        command = [str(binary), "-profile", str(profile_folder)]
    else:
        command = [str(binary), f"--user-data-dir={profile_folder}"]
    if url is not None:
        command.append(url)
    return command


def start_driver(browser: Browser, *, headless: bool, profile_folder: Path) -> WebDriver:
    """Start a Selenium-driven ``browser`` on ``profile_folder``, for a scrape -- creating the folder
    first if needed.

    Selenium Manager resolves each browser's driver binary automatically, downloading it into its own
    cache on first use -- there is nothing else to install beyond the browser itself. **This session is
    always flagged as automated**, for as long as it runs, regardless of activity: that is what makes
    it unsuitable for signing in anywhere Google- or Cloudflare-grade detection watches for it, which is
    exactly why logging in goes through :func:`login_command` instead
    ([[acquisition-tooling#browser-persona]]).

    :param browser: which browser to start.
    :param headless: whether to start with no visible window.
    :param profile_folder: the persona profile to open. Created if it does not exist yet.
    :returns: the started driver. The caller owns it, and must call `WebDriver.quit` when done with it.
    :raises selenium.common.exceptions.WebDriverException: the browser or its driver could not be
        started (not installed, a version mismatch, the profile already open elsewhere -- including by
        a plain login window :func:`login_command` started).
    """
    profile_folder.mkdir(parents=True, exist_ok=True)
    if browser is Browser.FIREFOX:
        return start_firefox(headless=headless, profile_folder=profile_folder)
    return start_chromium(browser, headless=headless, profile_folder=profile_folder)


def start_firefox(*, headless: bool, profile_folder: Path) -> WebDriver:
    """Start Firefox on ``profile_folder``, for :func:`start_driver`.

    ``-profile`` is a command-line argument, not `FirefoxOptions.profile`: that property copies the
    profile into a temporary directory before launching, which would make every login vanish the
    moment the browser closes. The JSON viewer is off (:data:`FIREFOX_JSON_VIEWER_PREFERENCE`), so a scraper that
    reads a site's JSON gets it here as it does over plain HTTP; the preference stays in the profile.
    """
    options = webdriver.FirefoxOptions()
    options.set_preference(FIREFOX_JSON_VIEWER_PREFERENCE, False)
    if headless:
        options.add_argument(FIREFOX_HEADLESS_ARG)
    options.add_argument("-profile")
    options.add_argument(str(profile_folder))
    return FirefoxDriver(options=options)


def start_chromium(browser: Browser, *, headless: bool, profile_folder: Path) -> WebDriver:
    """Start Chrome or Edge on ``profile_folder``, via ``--user-data-dir``, for :func:`start_driver`."""
    if browser is Browser.CHROME:
        chrome_options = webdriver.ChromeOptions()
        add_chromium_arguments(chrome_options, headless=headless, profile_folder=profile_folder)
        return ChromeDriver(options=chrome_options)
    edge_options = webdriver.EdgeOptions()
    add_chromium_arguments(edge_options, headless=headless, profile_folder=profile_folder)
    return EdgeDriver(options=edge_options)


def add_chromium_arguments(
    options: webdriver.ChromeOptions | webdriver.EdgeOptions, *, headless: bool, profile_folder: Path
) -> None:
    """Add the headless flag (when asked) and the persona's ``--user-data-dir`` to ``options``, shared
    between Chrome and Edge -- both take the same Chromium command-line arguments."""
    if headless:
        options.add_argument(CHROMIUM_HEADLESS_ARG)
    options.add_argument(f"--user-data-dir={profile_folder}")
