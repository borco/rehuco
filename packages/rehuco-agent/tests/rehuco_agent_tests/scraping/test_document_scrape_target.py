"""Tests for writing a scrape result onto a bare record (#682): the rules a drop fills an open document by
(:class:`~rehuco_agent.scraping.scrape_application.ScrapeApplication`), through
:class:`~rehuco_agent.scraping.document_scrape_target.DocumentScrapeTarget`.

The model's own side of the same rules -- a drop onto an open document -- is held by `test_scrape_actions*` and the
model's ``add_source`` tests; these hold what the shared rules do on a document no editor has open.
"""

import logging
from pathlib import Path

import pytest
from rehuco_agent.scraping.document_scrape_target import DocumentScrapeTarget
from rehuco_agent.scraping.results import ScrapedImage, ScrapeResult
from rehuco_core import SITE_ID_KEY, AssetLicense, RehuDocument

PAGE_URL = "https://www.fab.com/listings/1234"
"""The page every result below was read from."""


def asset_document(tmp_path: Path) -> RehuDocument:
    """A new asset record, not yet written.

    :param tmp_path: where it would be written.
    :returns: the document.
    """
    document = RehuDocument.new(tmp_path / "1234" / "info.rehu")
    document.set_active_type("asset")
    return document


def test_declared_fields_are_written_and_others_left_unset(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A field the record's type declares is written through its property, its JSON read into what the property
    holds; another is logged.

    **Test steps:**

    * apply a result with a core field, an asset's licenses as their JSON, and a Tutorial-only field
    * verify the first two are written, the licenses as entries, and the third is not and is logged
    """
    caplog.set_level(logging.INFO)
    document = asset_document(tmp_path)
    licenses = [{"license": "fab-standard", "url": "https://www.fab.com/eula"}, {"license": "fab-ue-only"}]
    result = ScrapeResult({"title": "Rock pack", "licenses": licenses, "advertised_duration": 60}, None, ())

    DocumentScrapeTarget(document).apply(result, publisher="Fab", page_url=PAGE_URL)

    assert document.title == "Rock pack"
    assert document.licenses == [AssetLicense("fab-standard", "https://www.fab.com/eula"), AssetLicense("fab-ue-only")]
    assert document.active_field("licenses") == licenses
    assert document.active_field("advertised_duration") is None
    assert "advertised_duration is not a field of this document's type" in caplog.text


def test_a_declared_field_with_no_property_is_written_into_the_block(tmp_path: Path) -> None:
    """A field a type declares that the document has no property for is written into the type's block as it came.

    **Test steps:**

    * apply a result with a tutorial's level onto a tutorial record
    * verify the block holds it
    """
    document = RehuDocument.new(tmp_path / "course" / "info.rehu")
    document.set_active_type("tutorial")

    DocumentScrapeTarget(document).apply(
        ScrapeResult({"level": ["beginner"]}, None, ()), publisher="X", page_url=PAGE_URL
    )

    assert document.active_field("level") == ["beginner"]


def test_the_page_becomes_the_primary_source_with_the_site_id(tmp_path: Path) -> None:
    """A new record's first source is the page read, carrying the scraper's publisher and the store's id.

    **Test steps:**

    * apply a result naming a store id onto an empty record
    * verify its one source is the page, with the publisher and the id
    """
    document = asset_document(tmp_path)

    DocumentScrapeTarget(document).apply(
        ScrapeResult({SITE_ID_KEY: "1234"}, None, ()), publisher="Fab", page_url=PAGE_URL
    )

    assert (document.url, document.publisher, document.site_id) == (PAGE_URL, "Fab", "1234")
    assert len(document.sources) == 1


def test_a_canonical_url_leads_and_takes_the_site_id(tmp_path: Path) -> None:
    """A scraper's canonical URL fills the primary ahead of the page, which follows it as a second source.

    **Test steps:**

    * apply a result naming a canonical URL and a store id onto an empty record
    * verify the canonical URL is the primary with the id, and the page a second source without it
    """
    document = asset_document(tmp_path)
    canonical = "https://www.fab.com/listings/1234-canonical"

    DocumentScrapeTarget(document).apply(
        ScrapeResult({"url": canonical, SITE_ID_KEY: "1234"}, None, ()), publisher="Fab", page_url=PAGE_URL
    )

    first, second = document.source_records
    assert (first["url"], first[SITE_ID_KEY]) == (canonical, "1234")
    assert second["url"] == PAGE_URL
    assert SITE_ID_KEY not in second


@pytest.mark.parametrize(
    ("markdown", "field", "expected"),
    [
        ("![](#image-01)", None, "![](info01)"),
        (None, "Plain notes", "Plain notes"),
    ],
    ids=["the-scrapes-own-markdown", "the-description-field"],
)
def test_the_description_is_the_scrapes_markdown_or_else_its_field(
    tmp_path: Path, markdown: str | None, field: str | None, expected: str
) -> None:
    """The scrape's Markdown names images as its screenshots are named; without it, a scraped description field is
    used.

    **Test steps:**

    * apply a result with Markdown naming an image placeholder, or with a description field only
    * verify the description is the Markdown naming ``info``'s screenshots, or the field
    """
    document = asset_document(tmp_path)
    fields = {} if field is None else {"description": field}

    DocumentScrapeTarget(document).apply(ScrapeResult(fields, markdown, ()), publisher="Fab", page_url=PAGE_URL)

    assert document.description == expected


def test_the_images_are_handed_back_for_the_caller_to_fetch(tmp_path: Path) -> None:
    """Writing the record fetches nothing; the images go back to whoever writes their files.

    **Test steps:**

    * apply a result naming two images
    * verify both come back, in order
    """
    images = (ScrapedImage(0, "https://cdn.example/0.png", None), ScrapedImage(1, "https://cdn.example/1.png", None))

    handed = DocumentScrapeTarget(asset_document(tmp_path)).apply(
        ScrapeResult({}, None, images), publisher="Fab", page_url=PAGE_URL
    )

    assert handed == images


def test_a_record_with_no_path_is_refused() -> None:
    """A record's screenshots are named by its file, so a record with none cannot take a result.

    **Test steps:**

    * apply a result onto a typed record with no path
    * verify it is refused
    """
    document = RehuDocument.new()
    document.set_active_type("asset")

    with pytest.raises(ValueError, match="needs its path"):
        DocumentScrapeTarget(document).apply(ScrapeResult({}, None, ()), publisher="Fab", page_url=PAGE_URL)
