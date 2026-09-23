"""Tests for the built-in Udemy scraper (#274)."""

import json
from typing import Final

from pytest import mark, param
from rehuco_agent.scraping.results import Page, ScrapeResult
from rehuco_agent.scraping.sites.udemy import COVER_SIZE_REWRITE, DURATION_TOKEN, Udemy

COURSE_URL: Final = "https://www.udemy.com/course/example-course/"

COURSE_LD_JSON: Final = {
    "@graph": [
        {
            "@type": "Course",
            "name": "Example Course: A Made-Up Curriculum",
            "description": ("Learn made-up things  Start from the basics and go all the way to advanced topics"),
            "author": [{"@type": "Person", "name": "Ann Author"}, {"@type": "Person", "name": "Bea Trainer"}],
            "image": "https://img-c.udemycdn.com/course/480x270/000000_0000.jpg",
            "hasCourseInstance": {"courseWorkload": "PT22H23M"},
        },
        {"@type": "BreadcrumbList", "itemListElement": []},
    ]
}

COURSE_HTML: Final = f"""
<script type="application/ld+json">{json.dumps(COURSE_LD_JSON)}</script>
<h1>Example Course: A Made-Up Curriculum</h1>
<div class="lede">
  <a href="/user/annauthor/">Ann Author</a>
  <a href="/user/beatrainer/">Bea Trainer</a>
  <span>Last updated 8/2025</span>
</div>
<div class="component-margin">
  <h2>What you'll learn</h2>
  <ul><li data-purpose="objective">You will learn a new skill.</li></ul>
</div>
<div class="component-margin">
  <h2 data-purpose="requirements-title">Requirements</h2>
  <p>Access to a computer with an internet connection.</p>
</div>
<div data-purpose="course-description">
  <h2>Description</h2>
  <p>Become skilled at the subject this made-up course teaches.</p>
  <button>Show moreShow less</button>
</div>
"""
"""A minimal, hand-written stand-in for a course landing page's markup (#274): only the elements
`Udemy.scrape_page` reads, not a copy of a real page."""


# region matches
@mark.parametrize(
    ("url", "expected"),
    [
        param(COURSE_URL, True, id="udemy-course"),
        param("https://www.udemy.com/", True, id="udemy-root"),
        param("https://www.artstation.com/marketplace/p/aBcDe/x", False, id="non-udemy"),
    ],
)
def test_matches(url: str, expected: bool) -> None:
    """`matches` is a plain host test, true for any `www.udemy.com` URL, false for anywhere else."""
    assert Udemy().matches(url) is expected


# endregion


# region scrape_page
def test_scrape_page_reads_title_and_authors() -> None:
    """The `Course` object's `name` becomes `title`; the lede's `/user/` links become `authors` records."""
    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=COURSE_HTML))

    assert result.fields["title"] == "Example Course: A Made-Up Curriculum"
    assert result.fields["authors"] == [
        {"name": "Ann Author", "url": "https://www.udemy.com/user/annauthor/"},
        {"name": "Bea Trainer", "url": "https://www.udemy.com/user/beatrainer/"},
    ]


def test_scrape_page_reads_released_and_duration() -> None:
    """`Last updated M/YYYY` becomes `YYYY-MM`; `courseWorkload` becomes seconds."""
    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=COURSE_HTML))

    assert result.fields["released"] == "2025-08"
    assert result.fields["advertised_duration"] == 80580


def test_scrape_page_reads_the_cover_image_at_the_cdn_native_size() -> None:
    """The `Course` object's `image` is rewritten from `480x270` to the CDN's native `750x422`."""
    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=COURSE_HTML))

    assert [image.slot for image in result.images] == [0]
    assert result.images[0].url == "https://img-c.udemycdn.com/course/750x422/000000_0000.jpg"
    assert result.images[0].referrer is None


def test_scrape_page_description_has_the_headline_and_the_three_blocks() -> None:
    """The description opens with the italic headline, then What you'll learn / Requirements / Description."""
    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=COURSE_HTML))

    assert result.description is not None
    assert result.description.startswith(
        "*Learn made-up things  Start from the basics and go all the way to advanced topics*"
    )
    assert "## What you'll learn" in result.description
    assert "## Requirements" in result.description
    assert "## Description" in result.description
    assert "Show more" not in result.description
    assert "![](" not in result.description


def test_scrape_page_on_an_unrelated_page_returns_an_empty_result() -> None:
    """A page with no `Course` object and no description blocks yields an empty result, never an exception."""
    html = "<html><body><p>Not a Udemy course page.</p></body></html>"

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result == ScrapeResult(fields={}, description=None, images=())


# endregion


# region partial pages -- each guard's own missing-piece path
def test_scrape_page_without_ld_json_sets_no_title_or_duration() -> None:
    """No `application/ld+json` block at all: no `title`, no `authors` fallback, no duration, no image."""
    html = '<div class="component-margin"><div data-purpose="objective">Learn things.</div></div>'

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert "title" not in result.fields
    assert "authors" not in result.fields
    assert "advertised_duration" not in result.fields
    assert not result.images


def test_scrape_page_ld_json_without_course_workload_leaves_duration_absent() -> None:
    """A `Course` object with no `hasCourseInstance` -- the issue's "no curriculum stats" page -- omits duration."""
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Course", "name": "A Course", "author": [{"@type": "Person", "name": "Someone"}]}'
        "</script>"
    )

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result.fields["title"] == "A Course"
    assert "advertised_duration" not in result.fields


def test_scrape_page_malformed_ld_json_is_ignored() -> None:
    """A `<script type="application/ld+json">` block that is not valid JSON is skipped, not an exception."""
    html = '<script type="application/ld+json">{not json</script>'

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result.fields == {}


def test_scrape_page_authors_without_user_links_falls_back_to_plain_names() -> None:
    """No `/user/` link anywhere on the page: `authors` falls back to the `Course` object's plain names."""
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Course", "name": "A Course", '
        '"author": [{"@type": "Person", "name": "Ann Author"}]}'
        "</script>"
    )

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result.fields["authors"] == ["Ann Author"]


def test_scrape_page_without_last_updated_text_leaves_released_absent() -> None:
    """No "Last updated" text on the page: `released` is left unset, not guessed."""
    html = '<script type="application/ld+json">{"@type": "Course", "name": "A Course"}</script>'

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert "released" not in result.fields


def test_scrape_page_course_without_a_name_or_authors_sets_neither_field() -> None:
    """A `Course` object with no `name` and no `author`, on a page with no `/user/` link, leaves `title` and
    `authors` unset -- never an empty list ([[acquisition-tooling#scraper-protocols]]: absent, not a guess)."""
    html = '<script type="application/ld+json">{"@type": "Course"}</script>'

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert "title" not in result.fields
    assert "authors" not in result.fields


def test_scrape_page_duplicate_and_empty_author_links_are_skipped() -> None:
    """A repeated `/user/` href contributes once; a link with no text contributes nothing."""
    html = (
        '<script type="application/ld+json">{"@type": "Course", "name": "A Course"}</script>'
        '<a href="/user/annauthor/">Ann Author</a>'
        '<a href="/user/annauthor/">Ann Author</a>'
        '<a href="/user/empty/"></a>'
    )

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result.fields["authors"] == [{"name": "Ann Author", "url": "https://www.udemy.com/user/annauthor/"}]


def test_scrape_page_absolute_user_link_is_an_author_record() -> None:
    """An absolute `https://www.udemy.com/user/...` href is an instructor link too, kept as given."""
    html = (
        '<script type="application/ld+json">{"@type": "Course", "name": "A Course"}</script>'
        '<a href="https://www.udemy.com/user/annauthor/">Ann Author</a>'
    )

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result.fields["authors"] == [{"name": "Ann Author", "url": "https://www.udemy.com/user/annauthor/"}]


def test_scrape_page_duration_matching_but_carrying_no_token_is_absent() -> None:
    """A bare `PT` matches the pattern but carries no `H`/`M`/`S` token, so the duration stays absent."""
    html = (
        '<script type="application/ld+json">'
        '{"@type": "Course", "name": "A Course", "hasCourseInstance": {"courseWorkload": "PT"}}'
        "</script>"
    )

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert "advertised_duration" not in result.fields


def test_scrape_page_skips_a_non_course_graph_entry_before_the_course_one() -> None:
    """A `@graph` entry that is not a `Course` (e.g. `BreadcrumbList`) is skipped, not mistaken for one."""
    html = (
        '<script type="application/ld+json">{"@graph": ['
        '{"@type": "BreadcrumbList", "itemListElement": []}, '
        '{"@type": "Course", "name": "A Course"}'
        "]}</script>"
    )

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result.fields["title"] == "A Course"


def test_scrape_page_skips_a_script_block_whose_graph_has_no_course_entry() -> None:
    """A whole `<script>` block with no `Course` anywhere in it is skipped for the next block, not fatal."""
    html = (
        '<script type="application/ld+json">{"@graph": [{"@type": "BreadcrumbList"}]}</script>'
        '<script type="application/ld+json">{"@type": "Course", "name": "A Course"}</script>'
    )

    result = Udemy().scrape_page(Page(url=COURSE_URL, final_url=COURSE_URL, html=html))

    assert result.fields["title"] == "A Course"


# endregion


# region duration parsing
@mark.parametrize(
    ("workload", "expected_seconds"),
    [
        param("PT22H23M", 80580, id="hours-and-minutes"),
        param("PT45M", 2700, id="minutes-only"),
        param("PT2H", 7200, id="hours-only"),
        param("PT30S", 30, id="seconds-only"),
        param("garbage", None, id="unparseable-is-absent"),
        param("PT", None, id="no-token-recognized-is-absent"),
    ],
)
def test_duration_parsing(workload: str, expected_seconds: int | None) -> None:
    """`courseWorkload`'s ISO 8601 duration parses to seconds; anything unrecognized is `None`, not `0`."""
    match = DURATION_TOKEN.fullmatch(workload)
    if expected_seconds is None:
        assert match is None or not any(match.groups())
    else:
        assert match is not None
        hours, minutes, seconds = (int(group) if group else 0 for group in match.groups())
        assert hours * 3600 + minutes * 60 + seconds == expected_seconds


# endregion


# region cover size rewrite
@mark.parametrize(
    ("image_url", "expected"),
    [
        param(
            "https://img-c.udemycdn.com/course/480x270/000000_0000.jpg",
            "https://img-c.udemycdn.com/course/750x422/000000_0000.jpg",
            id="480x270-to-750x422",
        ),
        param(
            "https://img-c.udemycdn.com/course/750x422/000000_0000.jpg",
            "https://img-c.udemycdn.com/course/750x422/000000_0000.jpg",
            id="already-750x422-is-a-no-op",
        ),
    ],
)
def test_cover_size_rewrite(image_url: str, expected: str) -> None:
    """A `Course.image`'s Next.js resize segment is rewritten to the CDN's native `750x422`."""
    assert COVER_SIZE_REWRITE.sub("/course/750x422/", image_url) == expected


# endregion
