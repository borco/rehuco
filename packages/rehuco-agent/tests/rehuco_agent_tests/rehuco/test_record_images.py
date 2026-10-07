"""Tests for the image resolver a record's description uses outside a document view (#458)."""

from pathlib import Path

from rehuco_agent.fields.image_scanner import ScreenshotSet
from rehuco_agent.rehuco.record_images import RecordImages


def test_it_offers_no_screenshots_and_converts_nothing() -> None:
    """A description shown beside its record has no image strip behind it (#458).

    **Test steps:**

    * ask a fresh resolver for its files, its screenshots and what a conversion left
    * verify there are no files, an empty screenshot set and no conversion map
    """
    images = RecordImages()

    assert not images.files()
    assert images.screenshots() == ScreenshotSet()
    assert images.after_conversion() is None


def test_it_resolves_nothing_until_a_record_is_set() -> None:
    """With no record there is no folder to resolve an embedded image against (#458).

    **Test steps:**

    * ask for an image by name before any record is set
    * verify nothing is returned, and that the record is ``None``
    """
    images = RecordImages()

    assert images.record is None
    assert images.get_markdown_viewer_image("a.png") is None
    images.record = Path("/fake/info.rehu")
    assert images.record == Path("/fake/info.rehu")
