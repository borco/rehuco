"""Tests for the ``--scrape``/``--scrape-schema`` CLI (#340)."""

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest import mark
from pytest_mock import MockerFixture
from rehuco_agent.scraping.cli import scrape_url_to_json, write_scrape_schema
from rehuco_agent.scraping.registry import ScraperRegistry
from rehuco_agent.scraping.results import SCRAPE_RESULT_SCHEMA_TEXT, Page, ScrapeResult
from requests import RequestException

URL = "https://example.com/page"

FOLDER_SCRAPER_SOURCE = """
class ExampleScraper:
    label = "Example"
    publisher = "Example Co"
    needs_browser = False

    def matches(self, url):
        return "example.com" in url

    def scrape_page(self, page):
        return {"fields": {"title": "From folder"}}
"""


@dataclass
class FakeScraper:  # pylint: disable=missing-function-docstring
    """A minimal `SiteScraper`, standing in for whatever `ScraperRegistry.find` returns."""

    result: object
    label: str = "Fake"
    publisher: str = "Fake Co"
    needs_browser: bool = False

    def matches(self, url: str) -> bool:
        del url
        return True

    def scrape_page(self, page: Page) -> object:
        del page
        return self.result


def _mock_registry(mocker: MockerFixture, scraper: FakeScraper | None) -> None:
    """Patch `ScraperRegistry` (as `cli` imports it) so `find` returns ``scraper``."""
    registry = mocker.Mock(spec=ScraperRegistry)
    registry.find.return_value = scraper
    mocker.patch("rehuco_agent.scraping.cli.ScraperRegistry", return_value=registry)


# region write_scrape_schema
def test_write_scrape_schema_writes_the_bundled_schema_verbatim(tmp_path: Path) -> None:
    """The written file is the checked-in schema, byte for byte -- not a re-serialization of it."""
    path = tmp_path / "schema.json"

    assert write_scrape_schema(path) == 0
    assert path.read_text(encoding="utf-8") == SCRAPE_RESULT_SCHEMA_TEXT


# endregion


# region scrape_url_to_json
def test_scrape_url_to_json_prints_to_stdout(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """With the fetcher mocked, a successful scrape's JSON goes to stdout and the exit code is 0."""
    scraper = FakeScraper(result=ScrapeResult(fields={"title": "T"}, description=None, images=()))
    _mock_registry(mocker, scraper)
    mocker.patch(
        "rehuco_agent.scraping.http_fetcher.HttpPageFetcher.fetch",
        return_value=Page(url=URL, final_url=URL, html="<html></html>"),
    )

    assert scrape_url_to_json(URL, scrapers_folder=None, output=None) == 0
    assert json.loads(capsys.readouterr().out) == {"fields": {"title": "T"}, "description": None, "images": []}


def test_scrape_url_to_json_prints_non_ascii_as_utf8(mocker: MockerFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """A title outside the console's code page reaches stdout intact, as UTF-8 -- never a
    `UnicodeEncodeError` from a cp1252 redirect, and never escaped to `\\uXXXX`."""
    scraper = FakeScraper(result=ScrapeResult(fields={"title": "日本語 — é"}, description=None, images=()))
    _mock_registry(mocker, scraper)
    mocker.patch(
        "rehuco_agent.scraping.http_fetcher.HttpPageFetcher.fetch",
        return_value=Page(url=URL, final_url=URL, html="<html></html>"),
    )

    assert scrape_url_to_json(URL, scrapers_folder=None, output=None) == 0
    out = capsys.readouterr().out
    assert "日本語 — é" in out
    assert json.loads(out)["fields"]["title"] == "日本語 — é"


def test_scrape_url_to_json_writes_to_output(mocker: MockerFixture, tmp_path: Path) -> None:
    """`--output PATH` writes the JSON there instead of stdout."""
    scraper = FakeScraper(result=ScrapeResult(fields={"title": "T"}, description=None, images=()))
    _mock_registry(mocker, scraper)
    mocker.patch(
        "rehuco_agent.scraping.http_fetcher.HttpPageFetcher.fetch",
        return_value=Page(url=URL, final_url=URL, html="<html></html>"),
    )
    output = tmp_path / "result.json"

    assert scrape_url_to_json(URL, scrapers_folder=None, output=output) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["fields"] == {"title": "T"}


def test_scrape_url_to_json_exits_1_when_no_scraper_matches(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """No scraper for the host exits 1 with the reason on stderr."""
    _mock_registry(mocker, None)

    assert scrape_url_to_json(URL, scrapers_folder=None, output=None) == 1
    assert "No scraper matches" in capsys.readouterr().err


def test_scrape_url_to_json_exits_1_when_the_fetch_fails(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fetch failure exits 1 with the reason on stderr."""
    _mock_registry(mocker, FakeScraper(result=ScrapeResult(fields={}, description=None, images=())))
    mocker.patch("rehuco_agent.scraping.http_fetcher.HttpPageFetcher.fetch", side_effect=RequestException("boom"))

    assert scrape_url_to_json(URL, scrapers_folder=None, output=None) == 1
    assert "Could not fetch" in capsys.readouterr().err


def test_scrape_url_to_json_exits_1_when_the_result_is_invalid(
    mocker: MockerFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """A result failing the scrape-result schema exits 1, naming the scraper and the path."""
    bad_result = ScrapeResult(fields={"current_size": 5}, description=None, images=())
    _mock_registry(mocker, FakeScraper(result=bad_result, label="Bad"))
    mocker.patch(
        "rehuco_agent.scraping.http_fetcher.HttpPageFetcher.fetch",
        return_value=Page(url=URL, final_url=URL, html="<html></html>"),
    )

    assert scrape_url_to_json(URL, scrapers_folder=None, output=None) == 1
    assert "Bad returned an invalid result" in capsys.readouterr().err


@mark.disk
def test_scrapers_folder_builds_the_registry_over_that_folder_only(
    mocker: MockerFixture, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--scrapers-folder DIR` finds a script in `DIR` and never reads the saved Scrapers setting."""
    (tmp_path / "example_scraper.py").write_text(FOLDER_SCRAPER_SOURCE)
    settings = mocker.patch("rehuco_agent.settings.scrapers_settings.shared_scrapers_settings")
    mocker.patch(
        "rehuco_agent.scraping.http_fetcher.HttpPageFetcher.fetch",
        return_value=Page(url=URL, final_url=URL, html="<html></html>"),
    )

    assert scrape_url_to_json(URL, scrapers_folder=tmp_path, output=None) == 0
    assert json.loads(capsys.readouterr().out)["fields"] == {"title": "From folder"}
    settings.assert_not_called()


# endregion
