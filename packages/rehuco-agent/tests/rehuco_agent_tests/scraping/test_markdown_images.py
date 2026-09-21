"""Tests for the scraped-description image rewrite (#269)."""

from rehuco_agent.scraping.markdown_images import rewrite_markdown_images, substitute_image_stem
from rehuco_agent.scraping.results import ScrapedImage


def test_rewrite_markdown_images_in_encounter_order() -> None:
    """Every image link is rewritten to a stem-less placeholder, in the order it appears, and the
    matching `ScrapedImage` triples come back in the same order (#269).

    **Test steps:**

    * rewrite a description holding two image links
    * verify the rewritten text carries the placeholders in order
    * verify the returned images carry the right slot, url and referrer, in order
    """
    markdown = "See ![first](https://example.com/a.jpg) and ![second](https://example.com/b.jpg)."

    rewritten, images = rewrite_markdown_images(markdown, referrer="https://example.com/page")

    assert rewritten == "See ![first](#image-00) and ![second](#image-01)."
    assert images == (
        ScrapedImage(slot=0, url="https://example.com/a.jpg", referrer="https://example.com/page"),
        ScrapedImage(slot=1, url="https://example.com/b.jpg", referrer="https://example.com/page"),
    )


def test_rewrite_markdown_images_first_slot_offsets_both() -> None:
    """`first_slot` shifts both the placeholder numbering and the returned slots -- how a scraper
    reserves lower slots for images it downloads without embedding, e.g. a cover at ``00`` (#269).

    **Test steps:**

    * rewrite a description holding one image link, with ``first_slot=1``
    * verify the placeholder and the returned slot both start at ``1``, not ``0``
    """
    rewritten, images = rewrite_markdown_images("![alt](https://example.com/a.jpg)", referrer=None, first_slot=1)

    assert rewritten == "![alt](#image-01)"
    assert images == (ScrapedImage(slot=1, url="https://example.com/a.jpg", referrer=None),)


def test_rewrite_markdown_images_drops_a_link_title_from_the_url() -> None:
    """An image link carrying a Markdown title -- ``![alt](url "title")`` -- yields the bare URL, not
    the URL with the title glued on (#269).

    **Test steps:**

    * rewrite a description holding one titled image link
    * verify the returned image's URL is the URL alone, and the placeholder replaced the whole link
    """
    rewritten, images = rewrite_markdown_images('![alt](https://example.com/a.jpg "A title")', referrer=None)

    assert rewritten == "![alt](#image-00)"
    assert images == (ScrapedImage(slot=0, url="https://example.com/a.jpg", referrer=None),)


def test_rewrite_markdown_images_with_no_images_changes_nothing() -> None:
    """A description with no image link is returned unchanged, with no images (#269).

    **Test steps:**

    * rewrite plain text holding no ``![]()`` link
    * verify the text is unchanged and no images were found
    """
    rewritten, images = rewrite_markdown_images("Just text, no pictures.", referrer=None)

    assert rewritten == "Just text, no pictures."
    assert not images


def test_substitute_image_stem_round_trips_to_the_real_name() -> None:
    """`substitute_image_stem` turns a placeholder back into a real `<stem>NN` name (#269).

    **Test steps:**

    * rewrite a description holding one image link
    * substitute a stem into the rewritten text
    * verify the placeholder became ``<stem>NN``
    """
    rewritten, _ = rewrite_markdown_images("![alt](https://example.com/a.jpg)", referrer=None)

    assert substitute_image_stem(rewritten, "my-tutorial") == "![alt](my-tutorial00)"


def test_substitute_image_stem_leaves_text_without_a_placeholder_alone() -> None:
    """Text carrying no placeholder is returned unchanged (#269).

    **Test steps:**

    * substitute a stem into text with no ``#image-NN`` placeholder
    * verify the text is unchanged
    """
    assert substitute_image_stem("Nothing to substitute here.", "my-tutorial") == "Nothing to substitute here."
