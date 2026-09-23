"""Tests for the built-in ArtStation scraper (#273)."""

from typing import Final

from pytest import mark, param
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.sites.artstation import FULL_SIZE_REWRITE, ArtStation

PRODUCT_URL: Final = "https://www.artstation.com/marketplace/p/aBcDe/example-product-tutorial"

PRODUCT_HTML: Final = """
<div class="productPage-header">
  <h1>Example Product Tutorial</h1>
  <div class="productPage-header-author">
    <a itemprop="url" href="https://www.artstation.com/annauthor/store">
      <span itemprop="name">Ann Author</span>
    </a>
  </div>
</div>
<div class="productPage-gallery-col">
  <button class="image-gallery-thumbnail">
    <img data-src="https://cdna.artstation.com/p/assets/468/large/file.jpg?1" />
  </button>
  <button class="image-gallery-thumbnail">
    <img data-src="https://cdnb.artstation.com/p/assets/469/large/file.jpg?2" />
  </button>
  <button class="image-gallery-thumbnail">
    <img data-src="https://cdna.artstation.com/p/assets/470/large/file.jpg?3" />
  </button>
  <button class="image-gallery-thumbnail">
    <img data-src="https://cdnb.artstation.com/p/assets/471/large/file.jpg?4" />
  </button>
  <div class="productPage-tags">
    <a class="productPage-tag">Tutorials</a>
    <a class="productPage-tag">Other Tutorials</a>
    <a class="productPage-tag">Game Art</a>
    <a class="productPage-tag">Hard Surface</a>
    <a class="productPage-tag">Lighting</a>
    <a class="productPage-tag">Modeling</a>
    <a class="productPage-tag">Props</a>
    <a class="productPage-tag">Rendering</a>
    <a class="productPage-tag">Texturing</a>
    <a class="productPage-tag">Blender</a>
    <a class="productPage-tag">Marmoset</a>
    <a class="productPage-tag">Substance Painter</a>
  </div>
  <div class="product-description">
    <p>This is a full process of modeling, unwrapping, and texturing a made-up prop in the lovely
    blender and substance painter! You should have basic knowledge of these tools.</p>
  </div>
</div>
"""
"""A minimal, hand-written stand-in for a product page's markup (#273): only the elements
`ArtStation.scrape_page` reads, not a copy of a real page."""

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
    "https://cdna.artstation.com/p/assets/468/large/file.jpg?1",
    "https://cdnb.artstation.com/p/assets/469/large/file.jpg?2",
    "https://cdna.artstation.com/p/assets/470/large/file.jpg?3",
    "https://cdnb.artstation.com/p/assets/471/large/file.jpg?4",
)


# region matches
@mark.parametrize(
    ("url", "expected"),
    [
        param(PRODUCT_URL, True, id="artstation-product"),
        param("https://www.artstation.com/", True, id="artstation-root"),
        param("https://www.udemy.com/course/example-course/", False, id="non-artstation"),
    ],
)
def test_matches(url: str, expected: bool) -> None:
    """`matches` is a plain host test, true for any `www.artstation.com` URL, false for anywhere else."""
    assert ArtStation().matches(url) is expected


# endregion


# region scrape_page
def test_scrape_page_reads_title_and_authors() -> None:
    """The header's `<h1>` becomes `title`; its `itemprop=url` author link becomes a name+url `authors` record."""
    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=PRODUCT_HTML))

    assert result.fields["title"] == "Example Product Tutorial"
    assert result.fields["authors"] == [{"name": "Ann Author", "url": "https://www.artstation.com/annauthor/store"}]


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


# region partial pages -- each guard's own missing-piece path
def test_scrape_page_header_present_without_an_h1_or_author() -> None:
    """A header block with neither an `<h1>` nor the author span sets neither field."""
    html = '<div class="productPage-header"></div>'

    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=html))

    assert "title" not in result.fields
    assert "authors" not in result.fields


def test_scrape_page_author_link_without_an_href_sets_a_plain_name() -> None:
    """An `itemprop=url` author link with no `href` falls back to a plain name string, not a record."""
    html = (
        '<div class="productPage-header"><div class="productPage-header-author">'
        '<a itemprop="url"><span itemprop="name">Ann Author</span></a></div></div>'
    )

    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=html))

    assert result.fields["authors"] == ["Ann Author"]


def test_scrape_page_tags_block_with_only_excluded_tags_sets_no_field() -> None:
    """`advertised_tags` is left unset, not set to an empty list, when nothing survives the exclusion."""
    html = (
        '<div class="productPage-gallery-col"><div class="productPage-tags">'
        '<a class="productPage-tag">Tutorials</a></div></div>'
    )

    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=html))

    assert "advertised_tags" not in result.fields


def test_scrape_page_gallery_without_a_tags_block_or_description() -> None:
    """A gallery with neither `.productPage-tags` nor `.product-description` yields no tags/description."""
    html = '<div class="productPage-gallery-col"><div class="unrelated"></div></div>'

    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=html))

    assert "advertised_tags" not in result.fields
    assert result.description is None


def test_scrape_page_thumbnail_button_without_an_img_is_skipped() -> None:
    """A thumbnail `<button>` with no `<img>` child contributes no image."""
    html = '<div class="productPage-gallery-col"><button class="image-gallery-thumbnail"></button></div>'

    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=html))

    assert not result.images


def test_scrape_page_thumbnail_img_without_data_src_is_skipped() -> None:
    """A thumbnail `<img>` with no `data-src` attribute contributes no image."""
    html = '<div class="productPage-gallery-col"><button class="image-gallery-thumbnail"><img /></button></div>'

    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=html))

    assert not result.images


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
