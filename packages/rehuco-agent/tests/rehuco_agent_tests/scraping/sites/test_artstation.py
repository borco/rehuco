"""Tests for the built-in ArtStation scraper (#273)."""

from typing import Final

from pytest import mark, param
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.sites.artstation import FULL_SIZE_REWRITE, ArtStation

PRODUCT_URL: Final = "https://www.artstation.com/marketplace/p/aBcDe/example-product-tutorial"
STORE_URL: Final = "https://anartist.artstation.com/store/aBcDe/example-product-tutorial"

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

STORE_HTML: Final = """
<div class="site-title title-font"><a href="/">Example Store</a></div>
<div class="product-page digital">
  <h1 class="product-title text-center">Example Store Product</h1>
  <div class="product-carousel-row js-product-carousel">
    <div class="product-carousel-item digital js-product-carousel-item" data-index="0" data-type="image">
      <div class="product-carousel-img digital">
        <img src="https://cdna.artstation.com/p/marketplace/presentation_assets/001/large/file.jpg?1" />
      </div>
    </div>
    <div class="product-carousel-item digital js-product-carousel-item" data-index="1" data-type="image">
      <div class="product-carousel-img digital">
        <img src="https://cdnb.artstation.com/p/marketplace/presentation_assets/002/large/file.jpg?2" />
      </div>
    </div>
  </div>
  <div class="product-description">
    <p>A wide-ranging store description that mentions a different artist by name and links to their
    own ArtStation profile inline (<a href="https://www.artstation.com/someoneelse">Someone Else</a>),
    prose the scraper does not mine for the author -- it reads the site title and the "Report"
    dropdown's link instead.</p>
  </div>
  <div class="report-section">
    <div class="dropdown">
      <ul class="dropdown-menu">
        <li class="dropdown-menu-item">
          <a href="https://www.artstation.com/examplestore" target="_blank">Content</a>
        </li>
        <li class="dropdown-menu-item">
          <a href="https://www.artstation.com/examplestore" target="_blank">User</a>
        </li>
      </ul>
    </div>
  </div>
</div>
"""
"""A minimal, hand-written stand-in for an artist store host's product page (#366) -- the storefront
template a saved real page turned out to use, distinct from :data:`PRODUCT_HTML`'s marketplace shape. The
description's inline profile link is a decoy: a different name/URL than the site title's, so a test catching
the wrong one fails loudly."""

EXPECTED_STORE_IMAGE_URLS: Final = (
    "https://cdna.artstation.com/p/marketplace/presentation_assets/001/large/file.jpg?1",
    "https://cdnb.artstation.com/p/marketplace/presentation_assets/002/large/file.jpg?2",
)

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
        param(STORE_URL, True, id="artstation-store"),
        param("https://someartist.artstation.com/store/xYz12/other-product", True, id="artstation-store-any-artist"),
        param("https://anartist.artstation.com/projects/aBcDe", False, id="artstation-portfolio-not-store"),
        param("https://magazine.artstation.com/2024/01/some-article", False, id="artstation-magazine"),
        param("https://cdna.artstation.com/p/assets/468/large/file.jpg", False, id="artstation-cdn-host"),
        param("https://www.udemy.com/course/example-course/", False, id="non-artstation"),
    ],
)
def test_matches(url: str, expected: bool) -> None:
    """`matches` accepts `www.artstation.com` and an artist's own store host at its `/store/<id>/<slug>`
    path (#366); any other host or path is left unmatched."""
    assert ArtStation().matches(url) is expected


# endregion


# region scrape_page
def test_scrape_page_on_the_marketplace_host_sets_no_url_field() -> None:
    """A `www.artstation.com` page leaves `url` unset (#366) -- `ScrapeJob.page_url` already supplies it,
    so the scraper does not repeat it."""
    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=PRODUCT_HTML))

    assert "url" not in result.fields


def test_scrape_page_on_the_store_host_sets_the_reconstructed_marketplace_url() -> None:
    """A store-host page (#366) sets `fields["url"]` to the `www.artstation.com` equivalent, so it becomes
    the primary source while the store URL actually fetched is recorded alongside it
    ([[acquisition-tooling#scraper-protocols]])."""
    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=STORE_HTML))

    assert result.fields["url"] == PRODUCT_URL


def test_scrape_page_on_the_store_host_reads_the_storefront_templates_own_markup() -> None:
    """The store template's own selectors (#366) -- `.product-title`, `.product-carousel-row` `<img
    src>`, the site title paired with the "Report" dropdown's link for `authors` -- are read;
    `advertised_tags` stays unset, since this template carries only broad site sections, not the
    marketplace's tag vocabulary."""
    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=STORE_HTML))

    assert result.fields["title"] == "Example Store Product"
    assert result.fields["authors"] == [{"name": "Example Store", "url": "https://www.artstation.com/examplestore"}]
    assert "advertised_tags" not in result.fields
    assert [image.slot for image in result.images] == [0, 1]
    assert [image.url for image in result.images] == list(EXPECTED_STORE_IMAGE_URLS)
    assert all(image.referrer == STORE_URL for image in result.images)
    assert result.description is not None
    assert "does not mine for the author" in result.description


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


def test_scrape_page_on_a_store_host_with_no_product_markup_carries_only_the_url() -> None:
    """A store-host page with none of the storefront template's blocks still reconstructs `url` (#366)
    -- that reconstruction depends only on the URL shape, never the markup -- but sets nothing else."""
    html = "<html><body><p>Not a store product page.</p></body></html>"

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert result == ScrapeResult(fields={"url": PRODUCT_URL}, description=None, images=())


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


def test_scrape_page_store_page_without_a_carousel_row_has_no_images() -> None:
    """A store-host page with no `.product-carousel-row` at all contributes no image (#366)."""
    html = '<h1 class="product-title">A Product</h1>'

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert not result.images


def test_scrape_page_store_carousel_item_without_an_img_is_skipped() -> None:
    """A `.product-carousel-item` with no `<img>` child contributes no image (#366)."""
    html = '<div class="product-carousel-row"><div class="product-carousel-item"></div></div>'

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert not result.images


def test_scrape_page_store_carousel_img_without_src_is_skipped() -> None:
    """A `.product-carousel-item`'s `<img>` with no `src` attribute contributes no image (#366)."""
    html = '<div class="product-carousel-row"><div class="product-carousel-item"><img /></div></div>'

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert not result.images


def test_scrape_page_store_host_without_a_site_title_sets_no_authors() -> None:
    """Neither a `.site-title a` nor an `og:site_name` leaves `authors` unset (#366) -- there is no name to
    report even a plain-name fallback for."""
    html = '<div class="report-section"><a href="https://www.artstation.com/someone">User</a></div>'

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert "authors" not in result.fields


def test_scrape_page_store_host_without_a_report_link_sets_a_plain_name() -> None:
    """A site title with no matching "Report" dropdown link falls back to a plain name, not a record
    (#366) -- the same fallback the marketplace page's author link uses for a missing `href`."""
    html = '<div class="site-title title-font"><a href="/">Example Store</a></div>'

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert result.fields["authors"] == ["Example Store"]


def test_scrape_page_store_host_without_a_site_title_falls_back_to_og_site_name() -> None:
    """No `.site-title a` at all falls back to the `og:site_name` meta tag for the name (#366) -- present
    for social sharing regardless of which preset theme the store uses."""
    html = (
        '<meta property="og:site_name" content="Meta Studio" />'
        '<div class="report-section"><a href="https://www.artstation.com/metastudio">User</a></div>'
    )

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert result.fields["authors"] == [{"name": "Meta Studio", "url": "https://www.artstation.com/metastudio"}]


def test_scrape_page_store_host_prefers_the_site_title_over_og_site_name() -> None:
    """A non-empty `.site-title` wins over `og:site_name` -- the meta tag is a fallback for a theme
    without a site title, not a second opinion on one that has it."""
    html = (
        '<meta property="og:site_name" content="Meta Studio" />'
        '<div class="site-title title-font"><a href="/">Real Store</a></div>'
    )

    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=html))

    assert result.fields["authors"] == ["Real Store"]


# endregion


# region canonical URL reconstruction (#366)
@mark.parametrize(
    ("store_url", "expected"),
    [
        param(STORE_URL, PRODUCT_URL, id="basic-store-url"),
        param(
            "https://someartist.artstation.com/store/xYz12/other-product/",
            "https://www.artstation.com/marketplace/p/xYz12/other-product",
            id="trailing-slash-is-stripped",
        ),
    ],
)
def test_scrape_page_reconstructs_the_marketplace_url_from_any_store_host(store_url: str, expected: str) -> None:
    """The `<id>`/`<slug>` pair carries over unchanged; only the host and the `/store/` -> `/marketplace/p/`
    segment change."""
    result = ArtStation().scrape_page(Page(url=store_url, final_url=store_url, html="<html></html>"))

    assert result.fields["url"] == expected


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


def test_scrape_page_result_passes_the_scrape_result_schema() -> None:
    """A real product page's result validates against `SCRAPE_RESULT_SCHEMA` (#340) -- a built-in scraper
    is checked the same way a user script's return value is."""
    result = ArtStation().scrape_page(Page(url=PRODUCT_URL, final_url=PRODUCT_URL, html=PRODUCT_HTML))

    assert ScrapeResult.coerce(result) == result


def test_scrape_page_result_with_a_reconstructed_url_passes_the_scrape_result_schema() -> None:
    """A store-host page's result (#366), `url` field included, validates the same way."""
    result = ArtStation().scrape_page(Page(url=STORE_URL, final_url=STORE_URL, html=STORE_HTML))

    assert ScrapeResult.coerce(result) == result
