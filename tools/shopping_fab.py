"""Add the free Fab listings a results page shows to the account's library, one at a time (#687).

Usage::

    python -I tools/shopping_fab.py
    python -I tools/shopping_fab.py URL

With no address it opens the persona Firefox on Fab, undriven, and waits until its window is closed: sign in there,
and set *Content preferences > Show products in My Library* off so a results page lists only what is not owned yet.
Fab keeps both in the profile.

``URL`` is any Fab results page with its filters in the address: a category, a search, a publisher. The page is the
queue ([[acquisition-tooling#free-listings]]): the listings it shows are opened one by one, then the page is loaded
again, and what was added has left it. A listing already in the library is skipped, one offering *Add to My Library*
is added, and anything else is left alone and reported -- the tool never buys. Nothing is kept between runs: Fab
itself says what is owned, so a run stopped at any point is simply started again.

It reads like a person, a few seconds between pages, and stops at the first Cloudflare challenge. Ctrl+C stops it
cleanly. Every end prints how many listings were added and the address of each one that failed. Needs geckodriver and
Firefox; the persona profile must not be open in another Firefox.
"""

import argparse
import json
import random
import re
import subprocess  # nosec B404 -- starts geckodriver and Firefox, both named below
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

DEFAULT_PROFILE: Final = Path("C:/Users/iborc/Developer/__GAME_DEVELOPMENT/.selenium-persona/claude")
"""The persona's Firefox profile, the one the earlier Fab scans logged in with."""

FIREFOX: Final = Path("C:/Program Files/Mozilla Firefox/firefox.exe")
"""The browser :func:`login` starts by itself; a run goes through geckodriver, which finds it alone."""

PROFILE_LOCK: Final = "parent.lock"
"""The file a running Firefox holds open, unshared, in its profile: it is how :func:`login` knows the window has closed.
On Windows ``firefox.exe`` starts the browser and exits at once, so waiting on the process returns too early."""

LOCK_POLL_SECONDS: Final = 1.0

FIREFOX_PROCESSES: Final = (
    "Get-CimInstance Win32_Process -Filter \"Name='firefox.exe'\""
    " | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
)
"""The PowerShell that lists each running Firefox process with its command line, as JSON."""

CLOSE_GRACE_SECONDS: Final = 10.0
"""How long a browser asked to close is given before it is stopped by force."""

FAB_URL: Final = "https://www.fab.com/"
LISTING_URL: Final = "https://www.fab.com/listings/{}"

PORT: Final = 4446
"""Where geckodriver listens; the earlier scan script uses the port below it."""

CHALLENGE_TITLE: Final = "Just a moment..."
"""The title of Cloudflare's challenge page."""

LISTING_ID: Final = re.compile(r"/listings/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")

LISTING_LINKS_SCRIPT: Final = """return Array.from(document.querySelectorAll('a[href*="/listings/"]'), a => a.href);"""

SCROLL_SCRIPT: Final = "window.scrollTo(0, document.body.scrollHeight);"

STATE_SCRIPT: Final = """
const side = document.querySelector('main aside');
if (!side) return '';
const heading = Array.from(side.querySelectorAll('h2'), h => h.textContent.trim());
if (heading.includes('Saved in My Library')) return 'owned';
const labels = Array.from(side.querySelectorAll('.fabkit-Button-label'), s => s.textContent.trim());
if (labels.includes('Add to My Library')) return 'free';
return labels.length ? 'other' : '';
"""
"""What a listing's side panel offers: ``owned``, ``free`` (it can be added), ``other``, or empty while it renders."""

ADD_SCRIPT: Final = """
const side = document.querySelector('main aside');
const label = Array.from(side.querySelectorAll('.fabkit-Button-label'))
    .find(s => s.textContent.trim() === 'Add to My Library');
label.closest('button').click();
"""

ADDED: Final = "added"
OWNED: Final = "owned"
NOT_OFFERED: Final = "Add to My Library is not offered"
UNCONFIRMED: Final = "clicked, never shown as saved"

RENDER_POLLS: Final = 20
"""How many times a page is asked whether it has rendered, :data:`POLL_SECONDS` apart."""

POLL_SECONDS: Final = 1.5

STABLE_ROUNDS: Final = 8
"""A results page has nothing more to show once this many looks in a row found no further listing."""

MAX_SCROLLS: Final = 400

PAUSE_SECONDS: Final = (6.0, 12.0)
"""The range the wait between two listings is drawn from."""

MAX_BROKEN: Final = 3
"""Listings in a row that broke (never confirmed, or an error) before the run gives up: the page has changed."""

INTERRUPTED: Final = 130
"""The exit status of a run stopped with Ctrl+C."""


class Challenge(Exception):
    """Cloudflare answered with its challenge page."""


@dataclass
class Tally:
    """What a run did, listing by listing."""

    added: int = 0
    owned: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    """Each listing that was neither added nor owned: its address and what went wrong."""

    def record(self, listing: str, result: str) -> None:
        """Count one listing's result.

        :param listing: the listing's id.
        :param result: :data:`ADDED`, :data:`OWNED`, or what went wrong.
        """
        if result == ADDED:
            self.added += 1
        elif result == OWNED:
            self.owned += 1
        else:
            self.failed.append((LISTING_URL.format(listing), result))

    def summary(self) -> str:
        """The run in a few lines.

        :returns: the counts, then each failed listing's address on a line of its own with its reason.
        """
        lines = [f"Added: {self.added}", f"Already owned: {self.owned}", f"Failed: {len(self.failed)}"]
        lines += [f"{url}  ({reason})" for url, reason in self.failed]
        return "\n".join(lines)


def profile_in_use(profile: Path) -> bool:
    """Whether a Firefox is running on a profile.

    :param profile: the profile's folder.
    :returns: ``True`` while a browser holds the profile's lock.
    """
    try:
        with (profile / PROFILE_LOCK).open("rb"):
            return False
    except FileNotFoundError:
        return False
    except PermissionError:
        return True


def browsers_on(profile: Path, processes: object) -> list[int]:
    """The Firefox processes running a profile: the ones whose command line names it.

    Only the browser's main process names the profile; its content processes do not, and closing the main one closes
    them.

    :param profile: the profile's folder.
    :param processes: what :data:`FIREFOX_PROCESSES` printed, parsed: one ``{ProcessId, CommandLine}`` object, a list
        of them, or ``None`` when no Firefox runs.
    :returns: their process ids.
    """
    rows = processes if isinstance(processes, list) else [processes]
    wanted = f"-profile {profile}".replace("/", "\\").casefold()
    return [
        row["ProcessId"]
        for row in rows
        if isinstance(row, dict) and wanted in str(row.get("CommandLine") or "").replace("/", "\\").casefold()
    ]


def close_browser(profile: Path) -> None:  # pragma: no cover -- a live Firefox, tried by hand
    """Close the persona's Firefox and wait until the profile is free.

    A Ctrl+C does not close it: ``firefox.exe`` hands the window to a browser process outside the console, and one
    seen after a Ctrl+C had lost its window and kept running. So it is asked to close as its window would be, and
    stopped by force when the profile is still held after :data:`CLOSE_GRACE_SECONDS`.

    :param profile: the profile's folder.
    """
    listed = subprocess.run(  # nosec B603 B607 -- a fixed command, PowerShell from the PATH
        ["powershell", "-NoProfile", "-Command", FIREFOX_PROCESSES], capture_output=True, text=True, check=False
    )
    pids = [str(pid) for pid in browsers_on(profile, json.loads(listed.stdout or "null"))]
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid], capture_output=True, check=False)  # nosec B603 B607 -- fixed
    waited = 0.0
    while profile_in_use(profile):
        if waited >= CLOSE_GRACE_SECONDS:
            for pid in pids:
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, check=False)  # nosec B603 B607
            pids = []
        time.sleep(LOCK_POLL_SECONDS)
        waited += LOCK_POLL_SECONDS


def login(profile: Path) -> int:  # pragma: no cover -- a live Firefox, tried by hand
    """Open the persona's Firefox, undriven, and wait, as long as it takes, until its window is closed or Ctrl+C.

    :param profile: the profile to run on.
    :returns: the process's exit status: 1 when the persona is open elsewhere already, 130 on Ctrl+C.
    """
    if profile_in_use(profile):
        print("The persona is already open in another Firefox; close it first.")
        return 1
    print("Sign in and set the content preferences, then close the browser window.")
    command = [str(FIREFOX), "-no-remote", "-profile", str(profile), FAB_URL]
    subprocess.run(command, check=False)  # nosec B603 -- a fixed command; it returns once the browser is started
    try:
        while not profile_in_use(profile):  # the browser takes its profile a moment after firefox.exe returns
            time.sleep(LOCK_POLL_SECONDS)
        while profile_in_use(profile):
            time.sleep(LOCK_POLL_SECONDS)
    except KeyboardInterrupt:
        print("Closing the browser.", flush=True)
        try:
            close_browser(profile)
        except KeyboardInterrupt:
            print("Stopped waiting; the browser may still be open.")
        return INTERRUPTED
    print("The browser is closed.")
    return 0


def listing_ids(links: list[str]) -> list[str]:
    """The listings a page's links name.

    :param links: the links' addresses.
    :returns: each listing's id once, in the order first met.
    """
    found = (LISTING_ID.search(link) for link in links)
    return list(dict.fromkeys(match.group(1) for match in found if match))


class Browser:  # pragma: no cover -- a live Firefox, tried by hand
    """The persona Firefox, driven through geckodriver's WebDriver endpoint.

    :param profile: the Firefox profile to run on.
    """

    def __init__(self, profile: Path) -> None:
        # A group of its own, so a Ctrl+C in the console reaches this script alone and the session is ended properly.
        own_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        # It lives until close(), so no with block can hold it. nosec B603 B607: a fixed command, from the PATH.
        self.__driver: Final = subprocess.Popen(  # nosec  # pylint: disable=consider-using-with
            ["geckodriver", "--port", str(PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=own_group,
        )
        time.sleep(2)
        try:
            options = {"args": ["-profile", str(profile)]}
            capabilities = {"alwaysMatch": {"browserName": "firefox", "moz:firefoxOptions": options}}
            self.__session: Final[str] = self.__call("POST", "/session", {"capabilities": capabilities})["sessionId"]
        except BaseException:
            self.__driver.terminate()
            raise

    def __call(self, method: str, path: str, body: object = None) -> Any:
        """Send one WebDriver command.

        :param method: the HTTP method.
        :param path: the command's path under the endpoint.
        :param body: its JSON body, if it has one.
        :returns: the command's value.
        :raises OSError: geckodriver did not answer, or refused the command.
        """
        request = urllib.request.Request(
            f"http://localhost:{PORT}{path}",
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310 -- localhost, http by constant
            return json.loads(response.read())["value"]

    def open(self, url: str) -> None:
        """Go to a page.

        :param url: the page.
        :raises Challenge: Cloudflare's challenge page came back instead.
        :raises OSError: geckodriver did not answer, or refused the command.
        """
        self.__call("POST", f"/session/{self.__session}/url", {"url": url})
        time.sleep(POLL_SECONDS)
        if self.run("return document.title") == CHALLENGE_TITLE:
            raise Challenge(url)

    def run(self, script: str) -> Any:
        """Run a script in the page.

        :param script: the script, returning its value.
        :returns: what it returned.
        :raises OSError: geckodriver did not answer, or refused the command.
        """
        return self.__call("POST", f"/session/{self.__session}/execute/sync", {"script": script, "args": []})

    def close(self) -> None:
        """End the session, which closes the browser, and stop geckodriver."""
        try:
            self.__call("DELETE", f"/session/{self.__session}")
        except OSError as error:
            print(f"The browser session did not end cleanly: {error}")
        finally:
            self.__driver.terminate()


def untried_listings(browser: Browser, url: str, tried: set[str]) -> list[str]:  # pragma: no cover -- a live Firefox
    """Load the results page and take the listings it shows that this run has not opened.

    The page is scrolled only when everything it shows has been tried already.

    :param browser: the browser.
    :param url: the results page.
    :param tried: the listings this run has opened.
    :returns: the untried listings' ids, in page order; empty when the page has no more.
    :raises Challenge: Cloudflare's challenge page came back instead.
    """
    browser.open(url)
    shown = -1
    stable = 0
    for _ in range(MAX_SCROLLS):
        time.sleep(POLL_SECONDS)
        ids = listing_ids(browser.run(LISTING_LINKS_SCRIPT))
        if fresh := [listing for listing in ids if listing not in tried]:
            return fresh
        stable = stable + 1 if len(ids) == shown else 0
        shown = len(ids)
        if stable == STABLE_ROUNDS:
            break
        browser.run(SCROLL_SCRIPT)
    return []


def wait_for_state(browser: Browser, wanted: frozenset[str]) -> str:  # pragma: no cover -- a live Firefox
    """Wait until a listing's side panel shows one of the states asked for.

    :param browser: the browser, on a listing.
    :param wanted: the states to wait for.
    :returns: the state reached, or the last one seen when none of them came.
    """
    state = ""
    for _ in range(RENDER_POLLS):
        state = browser.run(STATE_SCRIPT)
        if state in wanted:
            break
        time.sleep(POLL_SECONDS)
    return state


def add_listing(browser: Browser, listing: str) -> str:  # pragma: no cover -- a live Firefox, tried by hand
    """Add one listing to the library if Fab offers it.

    :param browser: the browser.
    :param listing: the listing's id.
    :returns: :data:`ADDED`, :data:`OWNED`, or what went wrong.
    :raises Challenge: Cloudflare's challenge page came back instead.
    """
    try:
        browser.open(LISTING_URL.format(listing))
        state = wait_for_state(browser, frozenset({"owned", "free", "other"}))
        if state == "owned":
            return OWNED
        if state != "free":
            return NOT_OFFERED
        browser.run(ADD_SCRIPT)
        return ADDED if wait_for_state(browser, frozenset({"owned"})) == "owned" else UNCONFIRMED
    except OSError as error:
        return f"error: {error}"


def shop(browser: Browser, url: str, tally: Tally) -> None:  # pragma: no cover -- a live Firefox, tried by hand
    """Add what a results page shows, loading it again until it shows nothing untried.

    :param browser: the browser.
    :param url: the results page.
    :param tally: where each listing's result is counted.
    :raises Challenge: Cloudflare's challenge page came back instead.
    """
    tried: set[str] = set()
    broken = 0
    while ids := untried_listings(browser, url, tried):
        for listing in ids:
            tried.add(listing)
            result = add_listing(browser, listing)
            tally.record(listing, result)
            print(f"{len(tried)} {result}: {LISTING_URL.format(listing)}", flush=True)
            broken = broken + 1 if result not in (ADDED, OWNED, NOT_OFFERED) else 0
            if broken == MAX_BROKEN:
                print(f"{MAX_BROKEN} listings in a row broke; stopping.")
                return
            time.sleep(random.uniform(*PAUSE_SECONDS))  # nosec B311 -- a pause, not a secret
    print("Nothing left on the page to try.")


def main() -> int:  # pragma: no cover -- a live Firefox, tried by hand
    """Run the tool.

    :returns: the process's exit status: 1 when a challenge page stopped the run, 130 when Ctrl+C did.
    """
    parser = argparse.ArgumentParser(description="Add a Fab results page's free listings to the library.")
    parser.add_argument("url", nargs="?", help="a Fab results page; without one, the persona opens for signing in")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="the persona's Firefox profile")
    arguments = parser.parse_args()
    if arguments.url is None:
        return login(arguments.profile)
    tally = Tally()
    status = 0
    browser = Browser(arguments.profile)
    try:
        shop(browser, arguments.url, tally)
    except Challenge as challenge:
        print(f"Cloudflare challenge at {challenge}; stopping. Run with no address, pass it by hand, and start again.")
        status = 1
    except KeyboardInterrupt:
        print("Stopped by Ctrl+C.")
        status = INTERRUPTED
    finally:
        browser.close()
        print(tally.summary())
    return status


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
