"""Tests for `start_driver` (the per-browser Selenium options) and `find_browser_binary`/`login_command`
(the plain, un-automated launch `PersonaBrowser.open_for_login` uses instead), both mocked (#278)."""

from pathlib import Path

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_agent.scraping.browser_drivers import (
    CHROMIUM_HEADLESS_ARG,
    FIREFOX_HEADLESS_ARG,
    find_browser_binary,
    login_command,
    start_driver,
)
from rehuco_agent.settings.scrapers_settings import Browser

PROFILE_FOLDER = Path("/fake/borco/rehuco-agent/persona/firefox")


def test_firefox_is_started_on_the_profile_folder_via_the_profile_argument(mocker: MockerFixture) -> None:
    """Firefox is started with ``-profile <folder>`` as command-line arguments, not
    `FirefoxOptions.profile` -- which would copy the profile to a temp directory and lose every login
    (#278).

    **Test steps:**

    * stand in for `webdriver.Firefox` and the profile folder's creation
    * start a non-headless Firefox driver
    * verify the arguments and that the folder was created
    """
    mkdir = mocker.patch.object(Path, "mkdir")
    options_cls = mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.FirefoxOptions")
    options = options_cls.return_value
    firefox = mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.Firefox")

    start_driver(Browser.FIREFOX, headless=False, profile_folder=PROFILE_FOLDER)

    mkdir.assert_called_once_with(parents=True, exist_ok=True)
    options.add_argument.assert_any_call("-profile")
    options.add_argument.assert_any_call(str(PROFILE_FOLDER))
    assert mocker.call(FIREFOX_HEADLESS_ARG) not in options.add_argument.call_args_list
    firefox.assert_called_once_with(options=options)


def test_firefox_headless_adds_the_headless_argument(mocker: MockerFixture) -> None:
    """Headless adds `-headless` ahead of the profile arguments (#278).

    **Test steps:**

    * stand in for `webdriver.Firefox`
    * start a headless Firefox driver
    * verify the headless argument was added
    """
    mocker.patch.object(Path, "mkdir")
    options_cls = mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.FirefoxOptions")
    options = options_cls.return_value
    mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.Firefox")

    start_driver(Browser.FIREFOX, headless=True, profile_folder=PROFILE_FOLDER)

    options.add_argument.assert_any_call(FIREFOX_HEADLESS_ARG)


def test_chrome_is_started_with_user_data_dir(mocker: MockerFixture) -> None:
    """Chrome is started with ``--user-data-dir`` naming the persona folder (#278).

    **Test steps:**

    * stand in for `webdriver.Chrome`
    * start a headless Chrome driver
    * verify the user-data-dir and headless arguments
    """
    mocker.patch.object(Path, "mkdir")
    options_cls = mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.ChromeOptions")
    options = options_cls.return_value
    chrome = mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.Chrome")

    start_driver(Browser.CHROME, headless=True, profile_folder=PROFILE_FOLDER)

    options.add_argument.assert_any_call(f"--user-data-dir={PROFILE_FOLDER}")
    options.add_argument.assert_any_call(CHROMIUM_HEADLESS_ARG)
    chrome.assert_called_once_with(options=options)


def test_edge_is_started_with_user_data_dir(mocker: MockerFixture) -> None:
    """Edge takes the same Chromium arguments as Chrome, through its own options and driver (#278).

    **Test steps:**

    * stand in for `webdriver.Edge`
    * start a non-headless Edge driver
    * verify the user-data-dir argument and that no headless flag was added
    """
    mocker.patch.object(Path, "mkdir")
    options_cls = mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.EdgeOptions")
    options = options_cls.return_value
    edge = mocker.patch("rehuco_agent.scraping.browser_drivers.webdriver.Edge")

    start_driver(Browser.EDGE, headless=False, profile_folder=PROFILE_FOLDER)

    options.add_argument.assert_any_call(f"--user-data-dir={PROFILE_FOLDER}")
    assert mocker.call(CHROMIUM_HEADLESS_ARG) not in options.add_argument.call_args_list
    edge.assert_called_once_with(options=options)


def test_find_browser_binary_tries_path_first(mocker: MockerFixture) -> None:
    """`shutil.which` is tried before any Windows-conventional path (#278).

    **Test steps:**

    * stand in for `shutil.which` answering a path
    * verify it is what comes back, and no Windows path is even checked
    """
    which = mocker.patch("rehuco_agent.scraping.browser_drivers.shutil.which", return_value="/usr/bin/firefox")
    is_file = mocker.patch.object(Path, "is_file")

    found = find_browser_binary(Browser.FIREFOX)

    assert found == Path("/usr/bin/firefox")
    which.assert_called_once_with("firefox")
    is_file.assert_not_called()


def test_find_browser_binary_falls_back_to_a_windows_path(mocker: MockerFixture) -> None:
    """With nothing on ``PATH``, a conventional Windows install location is tried (#278).

    **Test steps:**

    * stand in for `shutil.which` answering nothing, Windows as the platform, and one path existing
    * verify that path comes back
    """
    mocker.patch("rehuco_agent.scraping.browser_drivers.shutil.which", return_value=None)
    mocker.patch("rehuco_agent.scraping.browser_drivers.sys.platform", "win32")
    mocker.patch.object(Path, "is_file", return_value=True)

    found = find_browser_binary(Browser.CHROME)

    assert found == Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def test_find_browser_binary_answers_none_when_not_found(mocker: MockerFixture) -> None:
    """Neither ``PATH`` nor (on Windows) a conventional install location finding anything answers
    `None`, not an exception (#278)."""
    mocker.patch("rehuco_agent.scraping.browser_drivers.shutil.which", return_value=None)
    mocker.patch("rehuco_agent.scraping.browser_drivers.sys.platform", "win32")
    mocker.patch.object(Path, "is_file", return_value=False)

    assert find_browser_binary(Browser.EDGE) is None


def test_find_browser_binary_skips_windows_paths_off_windows(mocker: MockerFixture) -> None:
    """Off Windows, nothing on ``PATH`` answers `None` outright -- the conventional Windows install
    locations are never even consulted (#278).

    **Test steps:**

    * stand in for `shutil.which` answering nothing and a non-Windows platform
    * verify `None` comes back without `Path.is_file` ever being asked
    """
    mocker.patch("rehuco_agent.scraping.browser_drivers.shutil.which", return_value=None)
    mocker.patch("rehuco_agent.scraping.browser_drivers.sys.platform", "linux")
    is_file = mocker.patch.object(Path, "is_file")

    assert find_browser_binary(Browser.EDGE) is None
    is_file.assert_not_called()


def test_login_command_creates_the_profile_folder_and_uses_the_found_binary(mocker: MockerFixture) -> None:
    """`login_command` creates the folder first, then builds Firefox's plain ``-profile`` command line
    -- no headless flag, no automation option of any kind (#278).

    **Test steps:**

    * stand in for finding the binary and the folder's creation
    * ask for Firefox's login command
    * verify the folder was created and the command line
    """
    mkdir = mocker.patch.object(Path, "mkdir")
    binary = Path("/usr/bin/firefox")
    mocker.patch("rehuco_agent.scraping.browser_drivers.find_browser_binary", return_value=binary)

    command = login_command(Browser.FIREFOX, PROFILE_FOLDER)

    mkdir.assert_called_once_with(parents=True, exist_ok=True)
    assert command == [str(binary), "-profile", str(PROFILE_FOLDER)]


def test_login_command_for_a_chromium_browser_uses_user_data_dir(mocker: MockerFixture) -> None:
    """Chrome and Edge take the same ``--user-data-dir`` argument as the Selenium-driven launch does,
    minus anything Selenium-specific (#278)."""
    mocker.patch.object(Path, "mkdir")
    binary = Path("/usr/bin/chrome")
    mocker.patch("rehuco_agent.scraping.browser_drivers.find_browser_binary", return_value=binary)

    command = login_command(Browser.CHROME, PROFILE_FOLDER)

    assert command == [str(binary), f"--user-data-dir={PROFILE_FOLDER}"]


def test_login_command_raises_when_the_browser_is_not_found(mocker: MockerFixture) -> None:
    """A browser `find_browser_binary` cannot locate is reported plainly, naming the browser (#278)."""
    mocker.patch.object(Path, "mkdir")
    mocker.patch("rehuco_agent.scraping.browser_drivers.find_browser_binary", return_value=None)

    with raises(FileNotFoundError, match="Firefox"):
        login_command(Browser.FIREFOX, PROFILE_FOLDER)


def test_login_command_appends_a_url_for_firefox(mocker: MockerFixture) -> None:
    """A ``url`` is appended as a trailing argument to Firefox's ``-profile`` command line -- what lets
    a scraper's own site link open as a new tab in an already-open persona window, or the first tab of
    a freshly-launched one (#278).

    **Test steps:**

    * stand in for finding the binary and the folder's creation
    * ask for Firefox's login command with a url
    * verify the command line ends with it
    """
    mocker.patch.object(Path, "mkdir")
    binary = Path("/usr/bin/firefox")
    mocker.patch("rehuco_agent.scraping.browser_drivers.find_browser_binary", return_value=binary)

    command = login_command(Browser.FIREFOX, PROFILE_FOLDER, url="https://example.com/page")

    assert command == [str(binary), "-profile", str(PROFILE_FOLDER), "https://example.com/page"]


def test_login_command_appends_a_url_for_a_chromium_browser(mocker: MockerFixture) -> None:
    """A ``url`` is appended as a trailing argument to Chrome/Edge's ``--user-data-dir`` command line too
    (#278)."""
    mocker.patch.object(Path, "mkdir")
    binary = Path("/usr/bin/chrome")
    mocker.patch("rehuco_agent.scraping.browser_drivers.find_browser_binary", return_value=binary)

    command = login_command(Browser.CHROME, PROFILE_FOLDER, url="https://example.com/page")

    assert command == [str(binary), f"--user-data-dir={PROFILE_FOLDER}", "https://example.com/page"]


def test_login_command_appends_nothing_when_no_url_is_given(mocker: MockerFixture) -> None:
    """With no ``url`` (the default), the command line is unchanged from the plain profile-only shape --
    the existing behavior, kept (#278)."""
    mocker.patch.object(Path, "mkdir")
    binary = Path("/usr/bin/firefox")
    mocker.patch("rehuco_agent.scraping.browser_drivers.find_browser_binary", return_value=binary)

    command = login_command(Browser.FIREFOX, PROFILE_FOLDER)

    assert command == [str(binary), "-profile", str(PROFILE_FOLDER)]
