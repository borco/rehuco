"""Tests for `ScraperRegistry` (#269).

Real disk I/O, no mocks (``disk``): loading a user's own script is `importlib` reading an actual file,
which a mocked filesystem cannot exercise -- the fact under test is that a plain ``.py`` file loads and
its classes are found, not this module's own dispatch logic.
"""

import importlib.util
from pathlib import Path

from pytest import mark
from pytest_mock import MockerFixture
from rehuco_agent.scraping.registry import ScraperRegistry, shared_scraper_registry
from rehuco_agent.scraping.results import Page, ScrapeResult

FOLDER_SCRAPER_SOURCE = """
class FolderScraper:
    label = "Folder"
    publisher = "Folder Co"
    site_name = "Folder"
    site_url = "https://example.com"
    needs_browser = False

    def matches(self, url):
        return "example.com" in url

    def scrape_page(self, page):
        raise NotImplementedError
"""

NO_SCRAPER_SOURCE = """
CONSTANT = 1

def helper():
    return CONSTANT
"""

BROKEN_SOURCE = "this is not valid python :::"

CONSTRUCTOR_ARGS_SOURCE = """
class NeedsArgs:
    def __init__(self, required):
        self.required = required

    label = "Needs Args"
    publisher = "Needs Args Co"
    site_name = "Needs Args"
    site_url = "https://example.com"
    needs_browser = False

    def matches(self, url):
        return True

    def scrape_page(self, page):
        raise NotImplementedError
"""


class BuiltinScraperStub:  # pylint: disable=missing-function-docstring
    """A built-in scraper class, for tests that check folder-first ordering."""

    label = "Built-in"
    publisher = "Built-in Co"
    site_name = "Built-in"
    site_url = "https://example.com"
    needs_browser = False

    def matches(self, url: str) -> bool:
        return "example.com" in url

    def scrape_page(self, page: Page) -> ScrapeResult:
        raise NotImplementedError


class BuiltinNeedsArgsStub:  # pylint: disable=missing-function-docstring
    """A built-in class this build never actually ships -- proves a built-in that cannot be
    constructed with no arguments is skipped in `rows` the same way a folder scraper's own is."""

    label = "Broken Built-in"
    publisher = "Broken Built-in Co"
    site_name = "Broken Built-in"
    site_url = "https://example.com"
    needs_browser = False

    def __init__(self, required: str) -> None:
        self.required = required

    def matches(self, url: str) -> bool:
        del url
        return True

    def scrape_page(self, page: Page) -> ScrapeResult:
        raise NotImplementedError


@mark.disk
def test_folder_scraper_wins_over_built_in_for_the_same_host(tmp_path: Path) -> None:
    """A scripts-folder scraper matching the same host as a built-in is tried first (#269).

    **Test steps:**

    * write a folder scraper claiming ``example.com``
    * build a registry over that folder plus a built-in claiming the same host
    * find a scraper for an ``example.com`` URL
    * verify the folder scraper, not the built-in, is returned
    """
    (tmp_path / "folder_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)

    registry = ScraperRegistry(folder=tmp_path, builtins=(BuiltinScraperStub,))

    scraper = registry.find("https://example.com/page")

    assert scraper is not None
    assert scraper.label == "Folder"


@mark.disk
def test_a_file_that_fails_to_import_is_reported_but_not_fatal(tmp_path: Path) -> None:
    """A broken script is reported on its own row, and does not stop the rest of the folder loading
    (#269).

    **Test steps:**

    * write one broken file and one valid file
    * build a registry over the folder
    * verify the broken file's row carries an error and no scrapers
    * verify the valid file's scraper is still found
    """
    (tmp_path / "broken_scraper.py").write_text(BROKEN_SOURCE)
    (tmp_path / "folder_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)

    registry = ScraperRegistry(folder=tmp_path)

    broken_row = next(module for module in registry.modules if module.path.name == "broken_scraper.py")
    assert broken_row.error is not None
    assert not broken_row.scrapers
    assert registry.find("https://example.com/page") is not None


@mark.disk
def test_reload_picks_up_a_new_file(tmp_path: Path) -> None:
    """Adding a file after construction is picked up by :meth:`~ScraperRegistry.reload`, without a
    restart (#269).

    **Test steps:**

    * build a registry over an empty folder
    * verify no scraper matches yet
    * write a scraper file, then reload
    * verify the scraper is now found
    """
    registry = ScraperRegistry(folder=tmp_path)
    assert registry.find("https://example.com/page") is None

    (tmp_path / "folder_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)
    registry.reload()

    assert registry.find("https://example.com/page") is not None


@mark.disk
def test_find_returns_none_for_a_host_no_scraper_matches(tmp_path: Path) -> None:
    """No match is `None`, never an error (#269).

    **Test steps:**

    * build a registry over a folder holding a scraper for a different host
    * find a scraper for an unrelated URL
    * verify `None` is returned
    """
    (tmp_path / "folder_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)
    registry = ScraperRegistry(folder=tmp_path)

    assert registry.find("https://unrelated.test/page") is None


@mark.disk
def test_a_file_defining_no_scraper_contributes_nothing(tmp_path: Path) -> None:
    """A file that loads cleanly but defines no `SiteScraper` is not an error (#269).

    **Test steps:**

    * write a file defining only a constant and a helper function
    * build a registry over the folder
    * verify the row carries no error and no scrapers
    """
    (tmp_path / "no_scraper.py").write_text(NO_SCRAPER_SOURCE)

    registry = ScraperRegistry(folder=tmp_path)

    row = registry.modules[0]
    assert row.error is None
    assert not row.scrapers


@mark.disk
def test_a_class_needing_constructor_arguments_is_skipped_not_an_error(tmp_path: Path) -> None:
    """A class this loader cannot build with no arguments is simply not a scraper, not a load failure
    (#269).

    **Test steps:**

    * write a file defining a class whose constructor requires an argument
    * build a registry over the folder
    * verify the row carries no error and no scrapers
    """
    (tmp_path / "needs_args.py").write_text(CONSTRUCTOR_ARGS_SOURCE)

    registry = ScraperRegistry(folder=tmp_path)

    row = registry.modules[0]
    assert row.error is None
    assert not row.scrapers


@mark.disk
def test_find_builds_a_fresh_instance_every_call(tmp_path: Path) -> None:
    """`find` never hands out the same instance twice, so concurrent scrapes for the same host never
    share one user-written object's state (#269).

    **Test steps:**

    * build a registry over a folder holding one scraper
    * find a scraper for the same URL twice
    * verify the two results are different objects
    """
    (tmp_path / "folder_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)
    registry = ScraperRegistry(folder=tmp_path)

    first = registry.find("https://example.com/page")
    second = registry.find("https://example.com/page")

    assert first is not None
    assert second is not None
    assert first is not second


@mark.disk
def test_a_script_named_after_a_real_module_does_not_shadow_it(tmp_path: Path) -> None:
    """A user script called ``requests.py`` loads under its own prefixed name, and the real `requests`
    package is unaffected (#269).

    **Test steps:**

    * write a scraper file named ``requests.py``
    * build a registry over the folder
    * verify its scraper is still found
    * verify the real ``requests`` package still imports normally afterward
    """
    (tmp_path / "requests.py").write_text(FOLDER_SCRAPER_SOURCE)

    registry = ScraperRegistry(folder=tmp_path)

    assert registry.find("https://example.com/page") is not None
    import requests as real_requests  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    assert hasattr(real_requests, "get")


@mark.disk
def test_missing_folder_loads_as_no_modules(tmp_path: Path) -> None:
    """A scripts folder that does not exist loads as empty, not as an error (#269).

    **Test steps:**

    * build a registry over a folder path that was never created
    * verify no modules were found and nothing matches
    """
    registry = ScraperRegistry(folder=tmp_path / "does-not-exist")

    assert not registry.modules
    assert registry.find("https://example.com/page") is None


@mark.disk
def test_rows_lists_a_scraper_per_row_folder_first_then_built_in(tmp_path: Path) -> None:
    """`rows` has one entry per scraper -- the folder's, then the built-ins -- and one entry for a file
    contributing none (#278).

    **Test steps:**

    * write a folder scraper
    * build a registry over that folder plus a built-in
    * verify the rows: the folder scraper first, then the built-in, each carrying a key
    """
    (tmp_path / "folder_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)
    registry = ScraperRegistry(folder=tmp_path, builtins=(BuiltinScraperStub,))

    rows = registry.rows

    assert [row.label for row in rows] == ["Folder", "Built-in"]
    assert [row.publisher for row in rows] == ["Folder Co", "Built-in Co"]
    assert [row.source for row in rows] == ["folder_scraper.py", "Built-in"]
    assert all(row.key is not None for row in rows)


@mark.disk
def test_rows_carries_needs_browser_per_scraper(tmp_path: Path) -> None:
    """A scraper's `needs_browser` is carried onto its row, for the table's checkbox (#278).

    **Test steps:**

    * write a scraper declaring ``needs_browser = True``
    * build a registry over that folder
    * verify the row's flag
    """
    (tmp_path / "gated_scraper.py").write_text(
        FOLDER_SCRAPER_SOURCE.replace("needs_browser = False", "needs_browser = True")
    )
    registry = ScraperRegistry(folder=tmp_path)

    assert registry.rows[0].needs_browser is True


@mark.disk
def test_rows_has_no_key_for_an_empty_or_broken_file(tmp_path: Path) -> None:
    """A file defining no scraper, and a file that failed to load, carry `None` keys (#278).

    **Test steps:**

    * write an empty-contribution file and a broken file
    * build a registry over the folder
    * verify neither row carries a key, and the broken one carries its error
    """
    (tmp_path / "no_scraper.py").write_text(NO_SCRAPER_SOURCE)
    (tmp_path / "broken_scraper.py").write_text(BROKEN_SOURCE)
    registry = ScraperRegistry(folder=tmp_path, builtins=())

    rows = {row.source: row for row in registry.rows}

    assert rows["no_scraper.py"].key is None
    assert rows["broken_scraper.py"].key is None
    assert rows["broken_scraper.py"].error is not None


def test_rows_skips_a_built_in_that_cannot_be_constructed_with_no_arguments(tmp_path: Path) -> None:
    """A built-in class that cannot be built with no arguments contributes no row, the same way an
    unbuildable folder scraper is skipped rather than reported as an error (#278).

    **Test steps:**

    * build a registry with a built-in requiring a constructor argument, alongside a real one
    * verify only the real built-in shows up in `rows`
    """
    registry = ScraperRegistry(folder=tmp_path, builtins=(BuiltinNeedsArgsStub, BuiltinScraperStub))

    rows = registry.rows

    assert [row.label for row in rows] == ["Built-in"]


def test_shared_scraper_registry_is_a_singleton() -> None:
    """The shared accessor returns the same instance every call -- what lets the settings page's
    Reload and every `ScrapeJob` see the same state (#269).

    **Test steps:**

    * call `shared_scraper_registry` twice
    * verify both calls return the same object
    """
    assert shared_scraper_registry() is shared_scraper_registry()


@mark.disk
def test_a_class_a_script_imports_is_never_mistaken_for_one_it_defines(tmp_path: Path) -> None:
    """Only classes the file itself defines are candidates; a class it merely imports is skipped
    without ever being constructed (#269).

    **Test steps:**

    * write a scraper file that also imports a stdlib class into its namespace
    * build a registry over the folder
    * verify exactly the file's own scraper was found, and the row carries no error
    """
    (tmp_path / "folder_scraper.py").write_text("from pathlib import PurePath\n" + FOLDER_SCRAPER_SOURCE)

    registry = ScraperRegistry(folder=tmp_path)

    row = registry.modules[0]
    assert row.error is None
    assert [scraper.label for scraper in row.scrapers] == ["Folder"]


@mark.disk
def test_a_file_no_loader_can_be_built_for_is_reported(tmp_path: Path, mocker: MockerFixture) -> None:
    """A file `importlib` cannot even build a spec for is an error row, not a crash (#269).

    **Test steps:**

    * write a scraper file, and make spec building answer nothing for it
    * build a registry over the folder
    * verify the row carries an ``ImportError`` and no scrapers
    """
    (tmp_path / "folder_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)
    mocker.patch.object(importlib.util, "spec_from_file_location", return_value=None)

    registry = ScraperRegistry(folder=tmp_path)

    row = registry.modules[0]
    assert row.error is not None
    assert row.error.startswith("ImportError")
    assert not row.scrapers
