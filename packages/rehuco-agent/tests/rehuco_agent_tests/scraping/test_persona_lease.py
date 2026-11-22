"""Tests for `PersonaLease`: a library scan's long hold on the persona, which gives the profile up to a drop's
one-shot fetch between two of its pages (#682). No real browser: `start_driver` is mocked."""

import threading
from collections.abc import Callable
from time import monotonic, sleep
from typing import Final

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping.browser_fetcher import PersonaBrowser
from rehuco_agent.scraping.protocols import FetchError
from rehuco_agent.settings.scrapers_settings import Browser
from selenium.common.exceptions import WebDriverException

from .test_browser_fetcher import URL, fake_driver

TIMEOUT: Final = 5.0
"""How long a test waits for the other thread, in seconds."""


def wait_until(predicate: Callable[[], bool]) -> bool:
    """Wait for ``predicate`` to hold, for at most :data:`TIMEOUT`.

    :param predicate: the condition.
    :returns: whether it held in time.
    """
    deadline = monotonic() + TIMEOUT
    while monotonic() < deadline:
        if predicate():
            return True
        sleep(0.001)
    return False


def nothing() -> None:
    """A holder that is never asked to stop."""


def test_a_lease_starts_its_session_on_first_use_and_keeps_it(mocker: MockerFixture) -> None:
    """A scan pays for one session, not one per page.

    **Test steps:**

    * lease the persona, then ask for its session twice
    * verify one driver was started, and it is the one handed back both times
    * close the lease and verify the driver was quit
    """
    driver = fake_driver(mocker)
    start_driver = mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", return_value=driver)
    lease = PersonaBrowser().lease(Browser.FIREFOX, headless=True, checkpoint=nothing)

    assert start_driver.call_count == 0
    assert lease.driver() is driver
    assert lease.driver() is driver

    assert start_driver.call_count == 1
    lease.close()
    driver.quit.assert_called_once_with()


def test_a_lease_yields_only_to_a_waiting_fetch_which_then_runs(mocker: MockerFixture) -> None:
    """A drop waiting for the profile gets it at the scan's next page; a scan with no drop keeps its session.

    **Test steps:**

    * lease the persona and start its session
    * verify it does not yield while nobody waits
    * start a one-shot fetch on another thread and wait until it is waiting
    * verify the lease yields, the fetch then runs, and the lease's next session is a fresh one
    """
    leased, fetched, restarted = fake_driver(mocker), fake_driver(mocker), fake_driver(mocker)
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", side_effect=[leased, fetched, restarted])
    browser = PersonaBrowser()
    lease = browser.lease(Browser.FIREFOX, headless=True, checkpoint=nothing)
    lease.driver()
    assert lease.yield_if_wanted() is False

    fetch = threading.Thread(target=browser.fetch, args=(URL, Browser.FIREFOX), kwargs={"headless": True})
    fetch.start()
    assert wait_until(lambda: browser.wanted)

    assert lease.yield_if_wanted() is True
    fetch.join(TIMEOUT)
    assert not fetch.is_alive()
    leased.quit.assert_called_once_with()
    fetched.get.assert_called_once_with(URL)
    assert browser.wanted is False
    assert lease.driver() is restarted
    lease.close()


def test_a_lease_that_holds_no_session_does_not_yield(mocker: MockerFixture) -> None:
    """Between a yield and its next page, a lease has nothing to give up.

    **Test steps:**

    * lease the persona without starting a session
    * verify it does not yield
    """
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver")

    assert PersonaBrowser().lease(Browser.FIREFOX, headless=True, checkpoint=nothing).yield_if_wanted() is False


def test_a_session_that_fails_to_start_leaves_the_profile_free(mocker: MockerFixture) -> None:
    """A lease that cannot start its browser holds nothing, so a later fetch is not blocked by it.

    **Test steps:**

    * make the first start fail, the next succeed
    * ask a lease for its session and verify it fails with a fetch error
    * fetch once and verify it runs
    """
    driver = fake_driver(mocker)
    mocker.patch(
        "rehuco_agent.scraping.browser_drivers.start_driver", side_effect=[WebDriverException("in use"), driver]
    )
    browser = PersonaBrowser()

    with raises(FetchError):
        browser.lease(Browser.FIREFOX, headless=True, checkpoint=nothing).driver()

    browser.fetch(URL, Browser.FIREFOX, headless=True)
    driver.get.assert_called_once_with(URL)


def test_leaving_a_lease_gives_the_profile_back(mocker: MockerFixture) -> None:
    """A scan's lease is closed however its run ends, so its session never outlives it.

    **Test steps:**

    * use a lease as a context manager and start its session inside
    * verify the session was quit on leaving, and a fetch then runs
    """
    leased, fetched = fake_driver(mocker), fake_driver(mocker)
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", side_effect=[leased, fetched])
    browser = PersonaBrowser()

    with browser.lease(Browser.FIREFOX, headless=True, checkpoint=nothing) as lease:
        lease.driver()

    leased.quit.assert_called_once_with()
    browser.fetch(URL, Browser.FIREFOX, headless=True)
    fetched.get.assert_called_once_with(URL)


def test_closing_a_lease_that_never_started_quits_nothing(mocker: MockerFixture) -> None:
    """A scan stopped before its first page held no session, and closing it starts none.

    **Test steps:**

    * lease the persona and close it without asking for a session
    * verify no browser was ever started
    """
    start_driver = mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver")

    PersonaBrowser().lease(Browser.FIREFOX, headless=True, checkpoint=nothing).close()

    start_driver.assert_not_called()


def test_a_lease_waiting_for_a_held_profile_is_wanted_and_gets_it_once_let_go(mocker: MockerFixture) -> None:
    """Two scans of different stores take turns: the one waiting counts as wanted, so the holder gives the profile up.

    **Test steps:**

    * hold the profile with one lease
    * ask a second lease for its session on another thread, and wait until the profile reads as wanted
    * have the first lease yield, and verify the second then started its session
    """
    first, second = fake_driver(mocker), fake_driver(mocker)
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", side_effect=[first, second])
    browser = PersonaBrowser()
    holder = browser.lease(Browser.FIREFOX, headless=True, checkpoint=nothing)
    holder.driver()
    waiter = browser.lease(Browser.FIREFOX, headless=True, checkpoint=nothing)
    started: list[object] = []
    thread = threading.Thread(target=lambda: started.append(waiter.driver()))
    thread.start()
    assert wait_until(lambda: browser.wanted)

    assert holder.yield_if_wanted() is True

    thread.join(TIMEOUT)
    assert started == [second]
    assert browser.wanted is False
    waiter.close()


def test_a_lease_waiting_for_the_profile_can_be_stopped(mocker: MockerFixture) -> None:
    """A scan held up behind another holder still obeys a pause or a cancel, and leaves the profile untaken.

    **Test steps:**

    * hold the profile with one lease
    * ask a second lease, whose checkpoint raises, for its session
    * verify it gave up with what the checkpoint raised, is no longer counted as waiting, and started nothing
    """
    held = fake_driver(mocker)
    start_driver = mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", return_value=held)
    browser = PersonaBrowser()
    holder = browser.lease(Browser.FIREFOX, headless=True, checkpoint=nothing)
    holder.driver()

    def stop() -> None:
        """A holder asked to pause.

        :raises InterruptedError: always.
        """
        raise InterruptedError("paused")

    with raises(InterruptedError):
        browser.lease(Browser.FIREFOX, headless=True, checkpoint=stop).driver()

    assert browser.wanted is False
    assert start_driver.call_count == 1
    holder.close()
