"""Tests for description image-reference rewriting ([[acquisition-tooling#tc-to-rehu]])."""

from collections.abc import Sequence

from pytest import mark, param
from rehuco_core import ScreenshotRename, rewrite_description_images


@mark.parametrize(
    "renames, description, expected",
    [
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg")],
            "![](cover)\n\nSome text.",
            "![](info00)\n\nSome text.",
            id="an_extensionless_reference_stays_extensionless",
        ),
        param(
            [ScreenshotRename("info01.jpg", "image-01.jpg")],
            "![](image-01.jpg)",
            "![](info01.jpg)",
            id="a_reference_with_an_extension_keeps_one",
        ),
        param(
            [ScreenshotRename("info00.png", "sample-00.png")],
            "![](cover.jpg)",
            "![](cover.jpg)",
            id="a_name_the_conversion_leaves_alone_is_left_as_it_was",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg")],
            "![](Cover.JPG)",
            "![](info00.jpg)",
            id="matching_is_case_insensitive",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg")],
            "![](images/cover.jpg)",
            "![](info00.jpg)",
            id="drops_a_leading_path_in_the_rewrite",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg")],
            '![My Photo](cover.jpg "A title")',
            '![My Photo](info00.jpg "A title")',
            id="preserves_alt_text_and_title",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg")],
            "![](random.png)",
            "![](random.png)",
            id="leaves_an_unrecognized_reference_untouched",
        ),
        param(
            [
                ScreenshotRename("info00.jpg", "cover.jpg"),
                ScreenshotRename("info01.jpg", "file-01.jpg"),
            ],
            "![](cover) ![](random.png) ![](file-01.jpg)",
            "![](info00) ![](random.png) ![](info01.jpg)",
            id="rewrites_multiple_references_independently",
        ),
        param([], "![](cover.jpg)", "![](cover.jpg)", id="empty_scan_leaves_it_untouched"),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg")],
            "Just some **prose**, no images here.",
            "Just some **prose**, no images here.",
            id="non_image_text_is_unaffected",
        ),
    ],
)
def test_rewrite_description_images(renames: Sequence[ScreenshotRename], description: str, expected: str) -> None:
    """`rewrite_description_images` rewrites every reference to a renamed file, in the form it was
    written in, and leaves everything else -- an image the conversion did not touch, prose, alt text,
    titles -- exactly as-is.

    **Test steps:**

    * rewrite ``description`` against ``renames``
    * verify the result matches ``expected``
    """
    assert rewrite_description_images(description, renames) == expected
