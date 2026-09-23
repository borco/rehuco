"""Tests for `PersonaBrowser` and `BrowserPageFetcher`: no real browser or process, `start_driver` and
`subprocess.Popen` both mocked (#278)."""

import subprocess
from unittest.mock import MagicMock

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping.browser_fetcher import BrowserPageFetcher, PersonaBrowser, shared_persona_browser
from rehuco_agent.scraping.protocols import FetchError
from rehuco_agent.scraping.results import Page
from rehuco_agent.settings.scrapers_settings import Browser, ScrapersSettings, persona_folder
from selenium.common.exceptions import WebDriverException

URL = "https://example.com/page"


def fake_driver(mocker: MockerFixture, *, final_url: str = URL, html: str = "<html></html>") -> MagicMock:
    """A `WebDriver` stand-in whose navigation resolves immediately with a ready page."""
    driver = mocker.Mock()
    driver.execute_script.return_value = "complete"
    driver.current_url = final_url
    driver.page_source = html
    return driver


def fake_process(mocker: MockerFixture, *, alive: bool = True) -> MagicMock:
    """A `subprocess.Popen` stand-in.

    :param alive: whether :meth:`poll` answers `None` (still running) or an exit code.
    """
    process = mocker.Mock()
    process.poll.return_value = None if alive else 0
    return process


# region open_for_login


def test_open_for_login_launches_the_plain_command_and_tracks_the_process(mocker: MockerFixture) -> None:
    """Opening for login runs `login_command`'s plain command line through a bare `subprocess.Popen`
    -- never Selenium -- and keeps the process, for a later `reset` to find (#278).

    **Test steps:**

    * stand in for `login_command` and `subprocess.Popen`
    * open for login
    * verify the command was built for the browser's persona folder and run through Popen
    """
    process = fake_process(mocker)
    popen = mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", return_value=process)
    login_command = mocker.patch(
        "rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox", "-profile", "x"]
    )
    browser = PersonaBrowser()

    browser.open_for_login(Browser.FIREFOX)

    login_command.assert_called_once_with(Browser.FIREFOX, persona_folder(Browser.FIREFOX), None)
    popen.assert_called_once_with(["firefox", "-profile", "x"])


def test_open_for_login_passes_a_url_through_to_login_command(mocker: MockerFixture) -> None:
    """A ``url`` passed to `open_for_login` reaches `login_command`, for it to append as a trailing
    argument -- what lets a scraper's own site link open as a new tab in an already-open persona window
    (#278).

    **Test steps:**

    * stand in for `login_command` and `subprocess.Popen`
    * open for login with a url
    * verify `login_command` was called with it
    """
    process = fake_process(mocker)
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", return_value=process)
    login_command = mocker.patch(
        "rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox", "-profile", "x", "url"]
    )
    browser = PersonaBrowser()

    browser.open_for_login(Browser.FIREFOX, "https://example.com/page")

    login_command.assert_called_once_with(Browser.FIREFOX, persona_folder(Browser.FIREFOX), "https://example.com/page")


def test_open_for_login_with_no_url_passes_none_through_to_login_command(mocker: MockerFixture) -> None:
    """With no ``url`` (the default), `login_command` still receives `None` explicitly, its own "open on
    nothing in particular" shape (#278)."""
    process = fake_process(mocker)
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", return_value=process)
    login_command = mocker.patch(
        "rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox", "-profile", "x"]
    )
    browser = PersonaBrowser()

    browser.open_for_login(Browser.FIREFOX)

    login_command.assert_called_once_with(Browser.FIREFOX, persona_folder(Browser.FIREFOX), None)


def test_open_for_login_with_a_live_process_launches_again_without_replacing_it(mocker: MockerFixture) -> None:
    """Calling Open for login a second time while the first is still alive launches the command again
    (the browser's own single-instance-per-profile remoting brings the window forward) but keeps
    tracking the *original* process, not the new short-lived one the OS remoting call itself is (#278).

    **Test steps:**

    * open for login, with a process that answers alive
    * open for login again, with a second Popen call answering a different process
    * reset, and verify the *first* process was the one asked to terminate
    """
    first = fake_process(mocker, alive=True)
    second = fake_process(mocker, alive=False)
    popen = mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", side_effect=[first, second])
    mocker.patch("rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox"])
    mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree")
    browser = PersonaBrowser()

    browser.open_for_login(Browser.FIREFOX)
    browser.open_for_login(Browser.FIREFOX)

    assert popen.call_count == 2
    browser.reset(Browser.FIREFOX)
    first.terminate.assert_called_once_with()
    second.terminate.assert_not_called()


def test_open_for_login_with_a_dead_tracked_process_launches_fresh(mocker: MockerFixture) -> None:
    """A previously-tracked process that has since exited is replaced by the new one (#278).

    **Test steps:**

    * open for login, with a process that has already exited
    * open for login again, with a second, alive process
    * reset, and verify the *second* process is the one tracked now
    """
    first = fake_process(mocker, alive=False)
    second = fake_process(mocker, alive=True)
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", side_effect=[first, second])
    mocker.patch("rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox"])
    mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree")
    browser = PersonaBrowser()

    browser.open_for_login(Browser.FIREFOX)
    browser.open_for_login(Browser.FIREFOX)

    browser.reset(Browser.FIREFOX)
    second.terminate.assert_called_once_with()


def test_open_for_login_reports_a_missing_browser(mocker: MockerFixture) -> None:
    """`login_command`'s `FileNotFoundError` becomes a `FetchError` naming the browser (#278)."""
    mocker.patch(
        "rehuco_agent.scraping.browser_drivers.login_command",
        side_effect=FileNotFoundError("Firefox was not found on this machine."),
    )
    browser = PersonaBrowser()

    with raises(FetchError, match="Firefox"):
        browser.open_for_login(Browser.FIREFOX)


def test_open_for_login_reports_a_process_that_could_not_start(mocker: MockerFixture) -> None:
    """A `Popen` failure (e.g. permission denied) becomes a `FetchError` too (#278)."""
    mocker.patch("rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox"])
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", side_effect=OSError("denied"))
    browser = PersonaBrowser()

    with raises(FetchError, match="Firefox"):
        browser.open_for_login(Browser.FIREFOX)


# endregion


# region fetch


def test_fetch_starts_navigates_and_quits_a_fresh_session_every_time(mocker: MockerFixture) -> None:
    """Every fetch starts its own short-lived Selenium session and quits it -- there is no live session
    to reuse any more, login and scraping being different processes entirely (#278).

    **Test steps:**

    * stand in for `start_driver`
    * fetch twice
    * verify a fresh driver was started, navigated and quit, both times
    """
    drivers = [fake_driver(mocker), fake_driver(mocker)]
    start_driver = mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", side_effect=drivers)
    browser = PersonaBrowser()

    browser.fetch(URL, Browser.FIREFOX, headless=True)
    browser.fetch(URL, Browser.FIREFOX, headless=True)

    assert start_driver.call_count == 2
    for driver in drivers:
        driver.get.assert_called_once_with(URL)
        driver.quit.assert_called_once_with()


def test_fetch_quits_the_driver_even_when_not_headless(mocker: MockerFixture) -> None:
    """A visible fetch is quit just the same as a headless one -- unlike the old live-session design,
    nothing about `fetch` is left running for `open_for_login` to find, since the two no longer share
    anything but the profile folder (#278)."""
    driver = fake_driver(mocker)
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", return_value=driver)
    browser = PersonaBrowser()

    browser.fetch(URL, Browser.FIREFOX, headless=False)

    driver.quit.assert_called_once_with()


def test_fetch_returns_the_fetched_page(mocker: MockerFixture) -> None:
    """A successful fetch returns the page the driver resolved (#278)."""
    driver = fake_driver(mocker, final_url="https://example.com/final", html="<p>hi</p>")
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", return_value=driver)
    browser = PersonaBrowser()

    page = browser.fetch(URL, Browser.FIREFOX, headless=True)

    assert page == Page(url=URL, final_url="https://example.com/final", html="<p>hi</p>")


def test_a_driver_that_fails_to_quit_is_tolerated(mocker: MockerFixture) -> None:
    """A driver whose own `quit` raises -- the process was likely already gone -- does not fail the
    fetch that already succeeded (#278)."""
    driver = fake_driver(mocker)
    driver.quit.side_effect = OSError("already gone")
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", return_value=driver)
    browser = PersonaBrowser()

    page = browser.fetch(URL, Browser.FIREFOX, headless=True)  # must not raise

    assert page.url == URL


def test_a_webdriverexception_during_navigation_becomes_a_fetcherror(mocker: MockerFixture) -> None:
    """A `WebDriverException` while loading the page is wrapped as `FetchError`, and the driver is still
    quit (#278).

    **Test steps:**

    * stand in for a driver whose navigation raises
    * fetch
    * verify `FetchError` is raised, naming the URL, and the driver was quit anyway
    """
    driver = fake_driver(mocker)
    driver.get.side_effect = WebDriverException("boom")
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", return_value=driver)
    browser = PersonaBrowser()

    with raises(FetchError, match=URL):
        browser.fetch(URL, Browser.FIREFOX, headless=True)

    driver.quit.assert_called_once_with()


def test_a_failed_start_names_the_persona_being_possibly_open_for_login(mocker: MockerFixture) -> None:
    """A `WebDriverException` starting the driver -- the shape a locked profile fails with -- points at
    the login window as the likely cause, since that failure otherwise reads as an opaque driver error
    (#278)."""
    mocker.patch("rehuco_agent.scraping.browser_drivers.start_driver", side_effect=WebDriverException("in use"))
    browser = PersonaBrowser()

    with raises(FetchError, match="persona browser is open for login"):
        browser.fetch(URL, Browser.FIREFOX, headless=True)


def test_a_missing_selenium_install_becomes_a_fetcherror_naming_the_browser(mocker: MockerFixture) -> None:
    """`browser_drivers` failing to import (selenium, or the browser's own bindings, missing) is
    reported as a clear `FetchError` naming the browser (#278)."""
    mocker.patch.dict("sys.modules", {"rehuco_agent.scraping.browser_drivers": None})
    browser = PersonaBrowser()

    with raises(FetchError, match="Firefox"):
        browser.fetch(URL, Browser.FIREFOX, headless=True)


# endregion


# region reset


def test_reset_with_no_login_process_only_deletes_the_folder(mocker: MockerFixture) -> None:
    """Reset with nothing open just deletes the folder (#278)."""
    rmtree = mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree")
    browser = PersonaBrowser()

    browser.reset(Browser.CHROME)

    rmtree.assert_called_once_with(persona_folder(Browser.CHROME), ignore_errors=False)


def test_reset_terminates_a_live_login_process_before_deleting(mocker: MockerFixture) -> None:
    """Reset asks a still-open login window to close, and waits for it, before deleting the profile it
    holds open (#278).

    **Test steps:**

    * open for login, with a process that reports alive until asked to terminate
    * reset
    * verify terminate was called and the folder was deleted only after
    """
    process = fake_process(mocker, alive=True)
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", return_value=process)
    mocker.patch("rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox"])
    rmtree = mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree")
    browser = PersonaBrowser()
    browser.open_for_login(Browser.FIREFOX)

    browser.reset(Browser.FIREFOX)

    process.terminate.assert_called_once_with()
    process.wait.assert_called_once()
    rmtree.assert_called_once_with(persona_folder(Browser.FIREFOX), ignore_errors=False)


def test_reset_kills_a_login_process_that_does_not_terminate(mocker: MockerFixture) -> None:
    """A login window that ignores `terminate` is force-killed rather than left blocking the reset
    forever (#278)."""
    process = fake_process(mocker, alive=True)
    process.wait.side_effect = [subprocess.TimeoutExpired(cmd="firefox", timeout=10), None]
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", return_value=process)
    mocker.patch("rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox"])
    mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree")
    browser = PersonaBrowser()
    browser.open_for_login(Browser.FIREFOX)

    browser.reset(Browser.FIREFOX)

    process.kill.assert_called_once_with()


def test_reset_logs_a_warning_when_a_killed_process_still_does_not_exit(mocker: MockerFixture) -> None:
    """A login window that outlives even `kill` -- the last resort after `terminate` already failed --
    is logged and tolerated rather than raised, so a reset that cannot confirm the process is gone
    still goes on to try deleting the folder (#278)."""
    process = fake_process(mocker, alive=True)
    process.wait.side_effect = subprocess.TimeoutExpired(cmd="firefox", timeout=10)
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", return_value=process)
    mocker.patch("rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox"])
    rmtree = mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree")
    browser = PersonaBrowser()
    browser.open_for_login(Browser.FIREFOX)

    browser.reset(Browser.FIREFOX)  # must not raise

    process.kill.assert_called_once_with()
    rmtree.assert_called_once()


def test_reset_does_not_delete_twice_in_a_row_without_reopening(mocker: MockerFixture) -> None:
    """A second reset with no login reopened in between does not try to terminate a process again --
    the tracked one was already popped (#278)."""
    process = fake_process(mocker, alive=True)
    mocker.patch("rehuco_agent.scraping.browser_fetcher.subprocess.Popen", return_value=process)
    mocker.patch("rehuco_agent.scraping.browser_drivers.login_command", return_value=["firefox"])
    mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree")
    browser = PersonaBrowser()
    browser.open_for_login(Browser.FIREFOX)
    browser.reset(Browser.FIREFOX)
    process.terminate.reset_mock()

    browser.reset(Browser.FIREFOX)

    process.terminate.assert_not_called()


def test_reset_propagates_a_delete_failure(mocker: MockerFixture) -> None:
    """A folder `shutil.rmtree` cannot delete (e.g. a file still locked) is not swallowed (#278)."""
    mocker.patch("rehuco_agent.scraping.browser_fetcher.shutil.rmtree", side_effect=OSError("locked"))
    browser = PersonaBrowser()

    with raises(OSError, match="locked"):
        browser.reset(Browser.FIREFOX)


# endregion


def test_shared_persona_browser_is_a_singleton() -> None:
    """The shared accessor returns the same instance every call (#278)."""
    assert shared_persona_browser() is shared_persona_browser()


def test_browser_page_fetcher_delegates_to_the_shared_persona_browser(mocker: MockerFixture) -> None:
    """`BrowserPageFetcher.fetch` delegates to `shared_persona_browser`, with the browser and headless
    flag settings ask for (#278).

    **Test steps:**

    * stand in for the shared persona browser
    * fetch through a `BrowserPageFetcher` built with ``show_browser=True``
    * verify the delegate was called with the configured browser and ``headless=False``
    """
    page = Page(url=URL, final_url=URL, html="<html></html>")
    persona_browser = mocker.Mock(fetch=mocker.Mock(return_value=page))
    mocker.patch("rehuco_agent.scraping.browser_fetcher.shared_persona_browser", return_value=persona_browser)

    settings = ScrapersSettings(browser=Browser.CHROME, show_browser=True)
    fetcher = BrowserPageFetcher(settings)

    result = fetcher.fetch(URL)

    persona_browser.fetch.assert_called_once_with(URL, Browser.CHROME, headless=False)
    assert result is page
