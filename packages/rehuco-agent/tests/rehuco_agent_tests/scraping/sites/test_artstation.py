"""Tests for the built-in ArtStation scraper (#273)."""

from pathlib import Path
from typing import Final

from pytest import mark, param
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.sites.artstation import FULL_SIZE_REWRITE, ArtStation

PRODUCT_URL: Final = "https://www.artstation.com/marketplace/p/dNeeJ/vertical-drill-tutorial"
PRODUCT_HTML: Final = (Path(__file__).parent / "fixtures" / "artstation_product.html").read_text(encoding="utf-8")

EXPECTED_TAGS: Final = (
    "game art",
    "hard surface",
    "lighting",
    "modeling",
    "props",
    "rendering",
    "texturing",
    "blender",
    "marmoset",
    "substance painter",
)

EXPECTED_IMAGE_URLS: Final = (
    "https://cdna.artstation.com/p/marketplace/presentation_assets/001/832/468/large/file.jpg?1657485870",
    "https://cdnb.artstation.com/p/marketplace/presentation_assets/001/832/469/large/file.jpg?1657485900",
    "https://cdna.artstation.com/p/marketplace/presentation_assets/001/832/470/large/file.jpg?1657485933",
    "https://cdnb.artstation.com/p/marketplace/presentation_assets/001/832/471/large/file.jpg?1657485965",
)


# region matches
@mark.parametrize(
    ("url", "expected"),
    [
        param(PRODUCT_URL, True, id="artstation-product"),
        param("https://www.artstation.com/", True, id="artstation-root"),
        param("https://www.udemy.com/course/vertical-drill-tutorial/", False, id="non-artstation"),
    ],
)
def test_matches(url: str, expected: bool) -> None:
    """`matches` is a plain host test, true for any `www.artstation.com` URL, false for anywhere else."""
    assert ArtStation().matches(url) is expected


# endregion


# region scrape_page
def test_scrape_page_reads_title_and_authors() -> None:
    """The header's `<h1>` and its `itemprop=name` author span become `title`/`authors`."""
    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=PRODUCT_HTML))

    assert result.fields["title"] == "Vertical Drill Tutorial"
    assert result.fields["authors"] == ["Milad Kambari"]


def test_scrape_page_reads_tags_excluding_the_generic_ones() -> None:
    """The generic `Tutorials`/`Other Tutorials` tags are dropped; the rest are lower-cased."""
    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=PRODUCT_HTML))

    assert result.fields["advertised_tags"] == list(EXPECTED_TAGS)


def test_scrape_page_reads_gallery_images_in_encounter_order() -> None:
    """Each gallery thumbnail's `data-src` becomes a `ScrapedImage`, slots 0-based in page order."""
    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=PRODUCT_HTML))

    assert [image.slot for image in result.images] == [0, 1, 2, 3]
    assert [image.url for image in result.images] == list(EXPECTED_IMAGE_URLS)
    assert all(image.referrer == PRODUCT_URL for image in result.images)


def test_scrape_page_description_has_no_embedded_image_placeholders() -> None:
    """Unlike tc4, images are never mentioned as `![](...)` links inside the description."""
    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=PRODUCT_HTML))

    assert result.description is not None
    assert "This is a full process of modeling" in result.description
    assert "![](" not in result.description


def test_scrape_page_on_an_unrelated_page_returns_an_empty_result() -> None:
    """A page with none of the expected blocks yields an empty result, never an exception."""
    html = "<html><body><p>Not an ArtStation product page.</p></body></html>"

    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=html))

    assert result == ScrapeResult(fields={}, description=None, images=())


# endregion


# region full-size rewrite
@mark.parametrize(
    ("data_src", "expected"),
    [
        param(
            "https://cdna.artstation.com/p/.../medium/file.jpg?1",
            "https://cdna.artstation.com/p/.../large/file.jpg?1",
            id="medium-to-large",
        ),
        param(
            "https://cdna.artstation.com/p/.../small_square/file.jpg",
            "https://cdna.artstation.com/p/.../large/file.jpg",
            id="small-square-to-large-no-query",
        ),
        param(
            "https://cdna.artstation.com/p/.../large/file.jpg?1",
            "https://cdna.artstation.com/p/.../large/file.jpg?1",
            id="already-large-is-a-no-op",
        ),
        param(
            "https://cdna.artstation.com/p/.../unknown_size/file.jpg",
            "https://cdna.artstation.com/p/.../unknown_size/file.jpg",
            id="unrecognized-segment-is-left-alone",
        ),
    ],
)
def test_full_size_rewrite(data_src: str, expected: str) -> None:
    """A known smaller ArtStation asset-size segment is rewritten to `large`; anything else is left as-is."""
    assert FULL_SIZE_REWRITE.sub(r"/large/\2", data_src) == expected


# endregion
