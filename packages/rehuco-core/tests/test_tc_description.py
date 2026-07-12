"""Tests for description image-reference rewriting ([[acquisition-tooling#tc-to-rehu]])."""

from collections.abc import Sequence

from pytest import mark, param
from rehuco_core import ScreenshotRename, rewrite_description_images


@mark.parametrize(
    "renames, description, expected",
    [
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))],
            "![](cover)\n\nSome text.",
            "![](info00.jpg)\n\nSome text.",
            id="bare_extensionless_reference_matches",
        ),
        param(
            [ScreenshotRename("info00.png", "sample-00.png", ("sample-00.png",))],
            "![](sample-00.png)",
            "![](info00.png)",
            id="full_filename_reference_matches",
        ),
        param(
            [ScreenshotRename("info00.png", "sample-00.png", ("cover.jpg", "sample-00.png"))],
            "![](cover.jpg)",
            "![](info00.png)",
            id="losing_variant_rewrites_to_the_winner",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))],
            "![](Cover.JPG)",
            "![](info00.jpg)",
            id="matching_is_case_insensitive",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))],
            "![](images/cover.jpg)",
            "![](info00.jpg)",
            id="drops_a_leading_path_in_the_rewrite",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))],
            '![My Photo](cover.jpg "A title")',
            '![My Photo](info00.jpg "A title")',
            id="preserves_alt_text_and_title",
        ),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))],
            "![](random.png)",
            "![](random.png)",
            id="leaves_an_unrecognized_reference_untouched",
        ),
        param(
            [
                ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",)),
                ScreenshotRename("info01.jpg", "file-01.jpg", ("file-01.jpg",)),
            ],
            "![](cover.jpg) ![](random.png) ![](file-01.jpg)",
            "![](info00.jpg) ![](random.png) ![](info01.jpg)",
            id="rewrites_multiple_references_independently",
        ),
        param([], "![](cover.jpg)", "![](cover.jpg)", id="empty_scan_leaves_it_untouched"),
        param(
            [ScreenshotRename("info00.jpg", "cover.jpg", ("cover.jpg",))],
            "Just some **prose**, no images here.",
            "Just some **prose**, no images here.",
            id="non_image_text_is_unaffected",
        ),
    ],
)
def test_rewrite_description_images(renames: Sequence[ScreenshotRename], description: str, expected: str) -> None:
    """`rewrite_description_images` rewrites every recognized reference and leaves everything else
    -- unrecognized references, prose, alt text, titles -- exactly as-is.

    **Test steps:**

    * rewrite ``description`` against ``renames``
    * verify the result matches ``expected``
    """
    assert rewrite_description_images(description, renames) == expected
