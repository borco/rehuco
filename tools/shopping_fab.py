"""Add the free Fab listings a results page shows to the account's library, one at a time (#687).

Usage::

    python -I tools/shopping_fab.py [--profile PROFILE]
    python -I tools/shopping_fab.py [--profile PROFILE] [--debug] URL
    python -I tools/shopping_fab.py [--profile PROFILE] --remove-profile

``PROFILE`` is the persona's Firefox profile folder, by default :data:`DEFAULT_PROFILE`: one kept for this tool, never
an everyday browser's. ``--remove-profile`` deletes that folder, logins and all, and exits; the next run starts a fresh,
logged-out one. ``--debug`` prints, under each listing's line, how long each of its steps took.

With no address it opens the persona Firefox on Fab, undriven, and waits until its window is closed: sign in there,
and set *Content preferences > Show products in My Library* off so a results page lists only what is not owned yet.
Fab keeps both in the profile.

``URL`` is any Fab results page with its filters in the address: a category, a search, a publisher. The page is the
queue ([[acquisition-tooling#free-listings]]): each listing it shows is added from its card there, through the card's
own *Add to My Library* button, without opening the listing; then the page is loaded again, and what was added has
left it. A card without that button is left alone and reported -- the tool never buys. Nothing is kept between runs:
Fab itself says what is owned, so a run stopped at any point is simply started again.

It reads like a person, a few seconds between listings, and stops at the first Cloudflare challenge. Ctrl+C stops it
cleanly. Every end prints how many listings were added and the address of each one that failed. Needs geckodriver and
Firefox; the persona profile must not be open in another Firefox.

Tips:

* **One run can cover every category.** The address is only a results page, so a search page takes the same filters
  as a category page does::

      https://www.fab.com/search?sellers=<seller id>&sellers=<seller id>&is_free=1

  The seller ids are in the address of a publisher's own page and of a category page filtered to that publisher.
  Open the address in a browser first: it should list the free items of those sellers across categories.
* **It is safe to stop and start again at any point.** An added listing leaves the results page, so a restart, or a
  narrower address (one category, one seller), picks up only what is missing.
* **Depending on the size of the list, it can take days to complete.** Start with the narrower address of what is
  wanted first.
* **A challenge page ends the run.** Run with no address, pass the challenge by hand in the persona, close its window,
  and start the address run again.
* **If the pace is the problem**, shorten the pause between listings (:data:`PAUSE_SECONDS`); it also makes the
  session look less like a person.
"""

import argparse
import json
import random
import re
import shutil
import subprocess  # nosec B404 -- starts geckodriver and Firefox, both named below
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

# region Waits -- every pause and time limit the tool has, in seconds unless the name says otherwise

PAUSE_SECONDS: Final = (1.0, 5.0)
"""The wait between two listings, drawn at random from this range so the pace reads like a person's. Most of the time a
listing takes is this pause."""

CARD_POLL_SECONDS: Final = 0.25
"""The pause between two looks at a card: while its *Add to My Library* appears under the pointer, and after it was
clicked. A look runs a script in the page and asks nothing of Fab, so looking often costs no requests; it only stops a
change that has arrived from waiting long to be seen."""

HOVER_TIMEOUT_SECONDS: Final = 3.0
"""How long a card under the pointer gets to show its *Add to My Library*, looked at every :data:`CARD_POLL_SECONDS`,
before the listing is reported as not offered."""

CONFIRM_TIMEOUT_SECONDS: Final = 30.0
"""How long a clicked card gets to say *Saved in My Library*, looked at every :data:`CARD_POLL_SECONDS`, before the
listing is reported as never confirmed."""

POLL_SECONDS: Final = 1.5
"""The pause between two looks at a results page: before the first, and after each scroll, so the listings the scroll
asks Fab for have time to arrive."""

STABLE_ROUNDS: Final = 8
"""A results page is done once this many looks in a row, :data:`POLL_SECONDS` apart and each after a scroll, found no
further listing: about 12 seconds of nothing new."""

MAX_SCROLLS: Final = 400
"""The most looks one load of a results page gets, :data:`POLL_SECONDS` apart: about 10 minutes. It only bounds a page
that keeps changing without showing anything untried; :data:`STABLE_ROUNDS` ends a normal one long before."""

COMMAND_TIMEOUT_SECONDS: Final = 120
"""How long one WebDriver command may take before it fails with :class:`OSError`. Going to a page waits for the page to
load, so this is also the limit on a page that never finishes loading."""

DRIVER_START_SECONDS: Final = 2.0
"""How long geckodriver is given to start listening before the browser session is asked of it."""

LOCK_POLL_SECONDS: Final = 1.0
"""How often the profile's lock is checked while the login window is waited on: for the browser to take the profile,
for its window to close, and for it to close after a Ctrl+C. The login wait itself has no limit; Ctrl+C ends it."""

CLOSE_GRACE_SECONDS: Final = 10.0
"""How long a browser asked to close, after a Ctrl+C in the login wait, is given before it is stopped by force."""

# endregion

DEFAULT_PROFILE: Final = Path(__file__).resolve().parent.parent / ".local_settings" / "persona" / "shopping_fab"
"""The persona's Firefox profile: in the checkout's git-ignored ``.local_settings``, beside the dev agent's own
``persona/firefox``. Created, empty, on first use."""

FIREFOX: Final = Path("C:/Program Files/Mozilla Firefox/firefox.exe")
"""The browser :func:`login` starts by itself; a run goes through geckodriver, which finds it alone."""

PROFILE_LOCK: Final = "parent.lock"
"""The file a running Firefox holds open, unshared, in its profile: it is how :func:`login` knows the window has closed.
On Windows ``firefox.exe`` starts the browser and exits at once, so waiting on the process returns too early."""

FIREFOX_PROCESSES: Final = (
    "Get-CimInstance Win32_Process -Filter \"Name='firefox.exe'\""
    " | Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"
)
"""The PowerShell that lists each running Firefox process with its command line, as JSON."""

FAB_URL: Final = "https://www.fab.com/"
LISTING_URL: Final = "https://www.fab.com/listings/{}"

PORT: Final = 4446
"""Where geckodriver listens; the earlier scan script uses the port below it."""

DRIVER_HOST: Final = "127.0.0.1"
"""Where geckodriver is reached. Not ``localhost``: on Windows that is tried first as IPv6, which geckodriver does not
listen on, and every command then waited about 2 seconds for the fall-back to IPv4."""
CHALLENGE_TITLE: Final = "Just a moment..."
"""The title of Cloudflare's challenge page."""

LISTING_ID: Final = re.compile(r"/listings/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")

LISTING_LINKS_SCRIPT: Final = """return Array.from(document.querySelectorAll('a[href*="/listings/"]'), a => a.href);"""

SCROLL_SCRIPT: Final = "window.scrollTo(0, document.body.scrollHeight);"

CARD_SCRIPT: Final = """
const id = arguments[0];
const link = document.querySelector(`a[href="/listings/${id}"]`);
if (!link) return null;
let card = link;
while (card.parentElement && Array.from(card.parentElement.querySelectorAll('a[href*="/listings/"]'))
        .every(a => a.getAttribute('href').includes(id))) {
    card = card.parentElement;
}
card.scrollIntoView({block: 'center'});
return card;
"""
"""A listing's card on the results page, scrolled into view, given the listing's id; ``null`` when it is not on the
page. The card is the widest element around the listing's link that holds no other listing's link."""

CARD_STATE_SCRIPT: Final = """
const [card, click] = arguments;
if (!card.isConnected) return 'gone';
const saved = 'Saved in My Library';
if (card.textContent.includes(saved) || card.querySelector(`[aria-label="${saved}"], [title="${saved}"]`)) {
    return 'saved';
}
const button = card.querySelector('button[aria-label="Add to My Library"]');
if (!button) return 'none';
if (click) button.click();
return 'free';
"""
"""What a card offers, given the card and whether to click: ``saved`` once it says *Saved in My Library*, ``free``
while it has an *Add to My Library* button (clicked when asked), ``none`` when it has neither, ``gone`` when it has
left the page. Fab puts the button on a card only while the pointer is over it."""

CARD_SAVED: Final = "saved"
CARD_FREE: Final = "free"
CARD_NONE: Final = "none"
CARD_GONE: Final = "gone"

ADDED: Final = "added"
OWNED: Final = "owned"
NOT_OFFERED: Final = "no Add to My Library on its card"
LEFT_THE_PAGE: Final = "its card left the results page before it was clicked"
UNCONFIRMED: Final = "clicked, never shown as added"

MAX_BROKEN: Final = 3
"""Listings in a row that broke (never confirmed, or an error) before the run gives up: the page has changed."""

SECONDS_PER_HOUR: Final = 3600

PROGRESS_INDENT: Final = 18
"""How far a ``--debug`` line is indented: to where the address starts on the :func:`progress_line` above it."""

PAGE_LOAD_STRATEGY: Final = "eager"
"""When going to a page returns: once its document is parsed, not after every image, font and script has loaded too.
The results page's cards are waited on by themselves (:data:`POLL_SECONDS`), so nothing later on the page is
needed."""

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


def progress_line(added: int, elapsed: float, index: int, listing: str, result: str) -> str:
    """The line printed after one listing: the listing's place in the run, the average speed in listings added per
    hour, and its address, in aligned columns.

    :param added: how many listings the run has added so far.
    :param elapsed: the seconds since the run started.
    :param index: the listing's place in the run, from 1.
    :param listing: the listing's id.
    :param result: :data:`ADDED`, :data:`OWNED`, or what went wrong; anything but :data:`ADDED` follows the address.
    :returns: the line, without its newline.
    """
    speed = added / elapsed * SECONDS_PER_HOUR if elapsed > 0 else 0.0
    line = f"{index:5d}  {speed:7.2f}/h  {LISTING_URL.format(listing)}"
    return line if result == ADDED else f"{line}  ({result})"


class Laps:
    """The time each step of one piece of work took, for ``--debug``: each lap runs from the previous one, or from when
    the laps were started."""

    def __init__(self) -> None:
        self.__last = time.monotonic()
        self.__laps: Final[list[tuple[str, float]]] = []

    def lap(self, name: str) -> None:
        """End a step.

        :param name: the step's name.
        """
        now = time.monotonic()
        self.__laps.append((name, now - self.__last))
        self.__last = now

    def line(self) -> str:
        """The steps on one line, each with its seconds, in the order they ended.

        :returns: the line, without its newline.
        """
        return "  ".join(f"{name} {seconds:5.2f}s" for name, seconds in self.__laps)


def remove_profile(profile: Path) -> int:
    """Delete a persona's profile folder and say what was deleted.

    :param profile: the profile's folder.
    :returns: the process's exit status: 1 when a Firefox is running on it, which is left alone, else 0.
    """
    if profile_in_use(profile):
        print(f"The profile at {profile} is open in a Firefox; close it first. Nothing was deleted.")
        return 1
    if not profile.exists():
        print(f"There is no profile at {profile}; nothing was deleted.")
        return 0
    shutil.rmtree(profile)
    print(f"Deleted the profile at {profile}.")
    return 0


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
        time.sleep(DRIVER_START_SECONDS)
        try:
            options = {"args": ["-profile", str(profile)]}
            capabilities = {
                "alwaysMatch": {
                    "browserName": "firefox",
                    "moz:firefoxOptions": options,
                    "pageLoadStrategy": PAGE_LOAD_STRATEGY,
                }
            }
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
            f"http://{DRIVER_HOST}:{PORT}{path}",
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        # B310 is safe here: the address is this machine's, and its http scheme a constant.
        with urllib.request.urlopen(request, timeout=COMMAND_TIMEOUT_SECONDS) as response:  # nosec B310
            return json.loads(response.read())["value"]

    def open(self, url: str) -> None:
        """Go to a page.

        :param url: the page.
        :raises Challenge: Cloudflare's challenge page came back instead.
        :raises OSError: geckodriver did not answer, or refused the command.
        """
        self.__call("POST", f"/session/{self.__session}/url", {"url": url})  # returns once its document is ready
        if self.run("return document.title") == CHALLENGE_TITLE:
            raise Challenge(url)

    def run(self, script: str, *args: object) -> Any:
        """Run a script in the page.

        :param script: the script, returning its value.
        :param args: what the script reads as ``arguments``.
        :returns: what it returned.
        :raises OSError: geckodriver did not answer, or refused the command.
        """
        return self.__call("POST", f"/session/{self.__session}/execute/sync", {"script": script, "args": list(args)})

    def hover(self, element: object) -> None:
        """Move the browser's own pointer onto the middle of an element, as a person's mouse would.

        :param element: the element, as a script returned it.
        :raises OSError: geckodriver did not answer, or refused the command.
        """
        move = {"type": "pointerMove", "duration": 0, "origin": element, "x": 0, "y": 0}
        pointer = {"type": "pointer", "id": "mouse", "parameters": {"pointerType": "mouse"}, "actions": [move]}
        self.__call("POST", f"/session/{self.__session}/actions", {"actions": [pointer]})

    def close(self) -> None:
        """End the session, which closes the browser, and stop geckodriver."""
        try:
            self.__call("DELETE", f"/session/{self.__session}")
        except OSError as error:
            print(f"The browser session did not end cleanly: {error}")
        finally:
            self.__driver.terminate()


def untried_listings(browser: Browser, url: str, tried: set[str]) -> list[str]:  # pragma: no cover -- a live Firefox
    """Load the results page and take the listings it shows that this run has not tried.

    The page is scrolled only when everything it shows has been tried already.

    :param browser: the browser.
    :param url: the results page.
    :param tried: the listings this run has tried.
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


def add_listing(browser: Browser, listing: str) -> str:  # pragma: no cover -- a live Firefox, tried by hand
    """Add one listing to the library from its card on the results page, if the card offers it.

    The pointer is moved onto the card, which is what makes Fab put *Add to My Library* on it; the button is clicked,
    and the add counts as confirmed once the card says *Saved in My Library*.

    :param browser: the browser, on the results page.
    :param listing: the listing's id.
    :returns: :data:`ADDED`, :data:`OWNED`, or what went wrong.
    """
    try:
        card = browser.run(CARD_SCRIPT, listing)
        if card is None:
            return LEFT_THE_PAGE
        browser.hover(card)
        state = wait_for_card(browser, card, HOVER_TIMEOUT_SECONDS, frozenset({CARD_FREE, CARD_SAVED, CARD_GONE}))
        if state == CARD_SAVED:
            return OWNED
        if state == CARD_GONE:
            return LEFT_THE_PAGE
        if state != CARD_FREE:
            return NOT_OFFERED
        browser.run(CARD_STATE_SCRIPT, card, True)
        saved = wait_for_card(browser, card, CONFIRM_TIMEOUT_SECONDS, frozenset({CARD_SAVED})) == CARD_SAVED
        return ADDED if saved else UNCONFIRMED
    except OSError as error:
        return f"error: {error}"


def wait_for_card(  # pragma: no cover -- a live Firefox, tried by hand
    browser: Browser, card: object, timeout: float, wanted: frozenset[str]
) -> str:
    """Look at a card every :data:`CARD_POLL_SECONDS` until it is in one of the states asked for.

    :param browser: the browser, on the results page.
    :param card: the card, as :data:`CARD_SCRIPT` returned it.
    :param timeout: how long to look, in seconds.
    :param wanted: the states to wait for.
    :returns: the state reached, or the last one seen when none of them came in time.
    """
    deadline = time.monotonic() + timeout
    while True:
        state = browser.run(CARD_STATE_SCRIPT, card, False)
        if state in wanted or time.monotonic() >= deadline:
            return state
        time.sleep(CARD_POLL_SECONDS)


def shop(browser: Browser, url: str, tally: Tally, debug: bool) -> None:  # pragma: no cover -- a live Firefox
    """Add what a results page shows, loading it again until it shows nothing untried.

    :param browser: the browser.
    :param url: the results page.
    :param tally: where each listing's result is counted.
    :param debug: also print how long each step took, under the line of the results page or listing it belongs to.
    :raises Challenge: Cloudflare's challenge page came back instead.
    """
    tried: set[str] = set()
    broken = 0
    started = time.monotonic()
    laps = Laps()
    while ids := untried_listings(browser, url, tried):
        laps.lap("results")
        if debug:
            print(f"{'':{PROGRESS_INDENT}}{laps.line()}", flush=True)
        for listing in ids:
            laps = Laps()
            tried.add(listing)
            result = add_listing(browser, listing)
            laps.lap("add")
            tally.record(listing, result)
            print(progress_line(tally.added, time.monotonic() - started, len(tried), listing, result), flush=True)
            broken = broken + 1 if result not in (ADDED, OWNED, NOT_OFFERED) else 0
            if broken == MAX_BROKEN:
                print(f"{MAX_BROKEN} listings in a row broke; stopping.")
                return
            time.sleep(random.uniform(*PAUSE_SECONDS))  # nosec B311 -- a pause, not a secret
            laps.lap("pause")
            if debug:
                print(f"{'':{PROGRESS_INDENT}}{laps.line()}", flush=True)
        laps = Laps()
    print("Nothing left on the page to try.")


def main() -> int:  # pragma: no cover -- a live Firefox, tried by hand
    """Run the tool.

    :returns: the process's exit status: 1 when a challenge page stopped the run, 130 when Ctrl+C did.
    """
    parser = argparse.ArgumentParser(description="Add a Fab results page's free listings to the library.")
    parser.add_argument("url", nargs="?", help="a Fab results page; without one, the persona opens for signing in")
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE, help="the persona's Firefox profile folder")
    parser.add_argument("--remove-profile", action="store_true", help="delete the persona's profile folder and exit")
    parser.add_argument("--debug", action="store_true", help="also print how long each step of each listing took")
    arguments = parser.parse_args()
    if arguments.remove_profile:
        return remove_profile(arguments.profile)
    arguments.profile.mkdir(parents=True, exist_ok=True)
    if arguments.url is None:
        return login(arguments.profile)
    tally = Tally()
    status = 0
    browser = Browser(arguments.profile)
    try:
        shop(browser, arguments.url, tally, arguments.debug)
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
