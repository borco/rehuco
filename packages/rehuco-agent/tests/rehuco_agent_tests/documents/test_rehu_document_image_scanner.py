"""Tests for RehuDocumentImageScanner: composes a screenshot lister with Markdown-image resolution.

The listing rules live in ``rehuco_core`` (`scan_rehu_screenshot_files` / `scan_unconverted_screenshots`,
covered by their own tests); here `RehuDocumentImageScanner` is checked for delegating to whichever listers
it was built with, for keeping the two row kinds apart (#270), and for :meth:`get_markdown_viewer_image`.
"""

from pathlib import Path
from typing import Final
from unittest.mock import Mock

from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_image_scanner import RehuDocumentImageScanner
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_core import RehuDocument

FAKE_PATH: Final = Path("/fake/info.rehu")


def no_screenshots(_directory: Path, _stem: str) -> list[Path]:
    """A screenshot lister that resolves nothing -- for the image-resolution tests, which never list.

    :param _directory: the resource directory (unused).
    :param _stem: the filename base (unused).
    :returns: an empty list.
    """
    return []


def mock_decoded_image(mocker: MockerFixture, *, width: int, is_null: bool = False) -> tuple[Mock, Mock, Mock]:
    """Mock ``QImage`` construction in ``image_scanner`` to hand back a controllable fake image.

    :param mocker: pytest-mock fixture.
    :param width: the fake decoded image's reported width.
    :param is_null: whether the fake image should report itself as undecodable.
    :returns: ``(image, scaled, constructor)`` -- the fake decoded image, the fake it scales down to,
        and the mocked ``QImage`` constructor itself (to assert what path it was called with).
    """
    scaled = mocker.Mock()
    image = mocker.Mock()
    image.isNull.return_value = is_null
    image.width.return_value = width
    image.scaledToWidth.return_value = scaled
    constructor = mocker.patch("rehuco_agent.documents.rehu_document_image_scanner.QImage", return_value=image)
    return image, scaled, constructor


# region files() delegation
def test_files_delegates_to_the_lister_with_directory_and_stem(mocker: MockerFixture) -> None:
    """`files` calls the injected lister with the resource's ``(directory, stem)`` and returns its result.

    **Test steps:**

    * build a ``RehuDocumentImageScanner`` over a document at ``/fake/info.rehu`` with a stub lister
    * call ``files()``
    * verify the lister was called with ``(/fake, "info")`` and its list came straight back
    """
    listed = [Path("/fake/info00.jpg"), Path("/fake/info01.png")]
    lister = mocker.Mock(return_value=listed)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    assert RehuDocumentImageScanner(model, lister, no_screenshots).files() == listed
    lister.assert_called_once_with(Path("/fake"), "info")


def test_files_is_empty_without_a_path(mocker: MockerFixture) -> None:
    """A pathless document lists no screenshots, and the lister is never consulted.

    **Test steps:**

    * build a ``RehuDocumentImageScanner`` over a document that was never given a path
    * call ``files()``
    * verify it is empty and the lister was not called
    """
    lister = mocker.Mock()
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    assert RehuDocumentImageScanner(model, lister, no_screenshots).files() == []
    lister.assert_not_called()


def test_screenshots_keeps_the_two_kinds_apart(mocker: MockerFixture) -> None:
    """Both listers are asked for the same ``(directory, stem)``, and each fills its own half (#270).

    **Test steps:**

    * build a scanner over a numbered lister and an un-converted one
    * read ``screenshots()``
    * verify each half came from its own lister, and that ``files()`` is the two in that order
    """
    numbered = [Path("/fake/info00.jpg")]
    unconverted = [Path("/fake/cover.jpg")]
    lister = mocker.Mock(return_value=numbered)
    unconverted_lister = mocker.Mock(return_value=unconverted)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    scanner = RehuDocumentImageScanner(model, lister, unconverted_lister)
    screenshots = scanner.screenshots()

    assert screenshots.numbered == tuple(numbered)
    assert screenshots.unconverted == tuple(unconverted)
    assert scanner.files() == [*numbered, *unconverted]
    unconverted_lister.assert_called_with(Path("/fake"), "info")


def test_an_image_both_listers_report_is_numbered_once(mocker: MockerFixture) -> None:
    """The two listers are supplied independently, so nothing about them makes their answers disjoint.

    Listing one twice would put the same picture in the strip twice and offer Convert on a row the
    numbered half already accounts for.

    **Test steps:**

    * have both listers report the same file, plus one only the un-converted lister claims
    * read ``screenshots()``
    * verify the shared file is numbered only, and the other is the whole un-converted half
    """
    shared = Path("/fake/cover.jpg")
    lister = mocker.Mock(return_value=[shared])
    unconverted_lister = mocker.Mock(return_value=[shared, Path("/fake/sample-01.png")])
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    screenshots = RehuDocumentImageScanner(model, lister, unconverted_lister).screenshots()

    assert screenshots.numbered == (shared,)
    assert screenshots.unconverted == (Path("/fake/sample-01.png"),)


def test_screenshots_reports_a_shared_directory(mocker: MockerFixture) -> None:
    """Another record beside this one makes every un-converted image claimable -- and deletable -- there.

    **Test steps:**

    * mock ``other_record_stems`` to report a sibling, then to report none
    * read ``screenshots()`` each time
    * verify ``shared_directory`` follows it
    """
    stems = mocker.patch("rehuco_agent.documents.rehu_document_image_scanner.other_record_stems", return_value=("foo",))
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))
    scanner = RehuDocumentImageScanner(model, no_screenshots, no_screenshots)

    assert scanner.screenshots().shared_directory

    stems.return_value = ()

    assert not scanner.screenshots().shared_directory


def test_screenshots_is_empty_without_a_path(mocker: MockerFixture) -> None:
    """A pathless document reports no screenshots of either kind, and neither lister is consulted.

    **Test steps:**

    * build a scanner over a document that was never given a path
    * read ``screenshots()``
    * verify both halves are empty and neither lister was called
    """
    lister = mocker.Mock()
    unconverted_lister = mocker.Mock()
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    screenshots = RehuDocumentImageScanner(model, lister, unconverted_lister).screenshots()

    assert not screenshots.numbered
    assert not screenshots.unconverted
    lister.assert_not_called()
    unconverted_lister.assert_not_called()


# endregion


# region get_markdown_viewer_image (convention-independent, implemented once)
def test_get_markdown_viewer_image_resolves_a_bare_filename(mocker: MockerFixture) -> None:
    """A bare filename resolves against the document's own directory, independent of process CWD.

    **Test steps:**

    * mock ``QImage`` construction to report an in-cap image
    * resolve ``"cover.jpg"`` on a document at ``/fake/info.rehu``
    * verify ``QImage`` was constructed with the path under ``/fake``, and that image is returned
    """
    image, _, constructor = mock_decoded_image(mocker, width=100)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("cover.jpg")

    assert result is image
    constructor.assert_called_once_with(str(Path("/fake/cover.jpg")))
    image.setDevicePixelRatio.assert_called_once_with(1.0)


def test_get_markdown_viewer_image_resolves_a_file_url(mocker: MockerFixture) -> None:
    """A ``file://`` URL resolves to the same filename as a bare name would.

    **Test steps:**

    * mock ``QImage`` construction to report an in-cap image
    * resolve ``"file:///elsewhere/cover.jpg"`` on a document at ``/fake/info.rehu``
    * verify it still resolves against ``/fake`` (the *document's* directory, not the URL's own)
    """
    image, _, _ = mock_decoded_image(mocker, width=100)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image(
        "file:///elsewhere/cover.jpg"
    )

    assert result is image


def test_get_markdown_viewer_image_scales_an_over_cap_image(mocker: MockerFixture) -> None:
    """An image wider than the live max-width setting is scaled down to it.

    **Test steps:**

    * set the shared Markdown-rendering settings' ``max_image_width`` to 100
    * mock ``QImage`` construction to report a 400px-wide image
    * verify the scaled-down image (not the original) is returned, and scaling used the live cap
    """
    image, scaled, _ = mock_decoded_image(mocker, width=400)
    shared_markdown_rendering_settings().max_image_width = 100
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("cover.jpg")

    assert result is scaled
    image.scaledToWidth.assert_called_once()
    assert image.scaledToWidth.call_args[0][0] == 100


def test_get_markdown_viewer_image_leaves_an_in_cap_image_untouched(mocker: MockerFixture) -> None:
    """An image no wider than the cap is returned as-is, never scaled.

    **Test steps:**

    * mock ``QImage`` construction to report an 80px-wide image, cap well above that
    * verify the original (unscaled) image is returned
    """
    image, _, _ = mock_decoded_image(mocker, width=80)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("cover.jpg")

    assert result is image
    image.scaledToWidth.assert_not_called()
    image.setDevicePixelRatio.assert_called_once_with(1.0)


def test_get_markdown_viewer_image_tags_the_result_with_the_callers_device_pixel_ratio(
    mocker: MockerFixture,
) -> None:
    """The returned image is tagged with whatever ``device_pixel_ratio`` the caller passed, so a
    small image renders crisp on a scaled display instead of Qt silently stretching raw pixels to
    fill the extra physical space (confirmed against a real 125%-scaled display).

    **Test steps:**

    * mock ``QImage`` construction to report a 300px-wide image
    * resolve with ``device_pixel_ratio=1.25``
    * verify the image is tagged 1.25 and is *not* scaled -- 300 raw px is still under the
      DPR-adjusted cap (350 * 1.25 = 437), even though it would exceed the un-adjusted 350 cap if
      a wider image were used
    """
    image, _, _ = mock_decoded_image(mocker, width=300)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image(
        "cover.jpg", device_pixel_ratio=1.25
    )

    assert result is image
    image.setDevicePixelRatio.assert_called_once_with(1.25)
    image.scaledToWidth.assert_not_called()


def test_get_markdown_viewer_image_scales_using_the_device_pixel_ratio_adjusted_cap(
    mocker: MockerFixture,
) -> None:
    """The width cap itself scales with ``device_pixel_ratio``, not just the tagging -- an image
    that would exceed the nominal cap can still fit once the caller's screen scaling is accounted
    for, and vice versa the scale target is computed in raw pixels, not logical ones.

    **Test steps:**

    * set the live max-width setting to 350 (the default)
    * mock a 400px-wide image, resolved with ``device_pixel_ratio=1.25`` (raw cap becomes 437)
    * verify it is *not* scaled, since 400 < 437 -- it would have been scaled at ``dpr=1.0``
    """
    image, scaled, _ = mock_decoded_image(mocker, width=400)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image(
        "cover.jpg", device_pixel_ratio=1.25
    )

    assert result is image
    assert result is not scaled
    image.scaledToWidth.assert_not_called()


def test_get_markdown_viewer_image_returns_none_for_an_undecodable_file(mocker: MockerFixture) -> None:
    """An undecodable (or missing) file resolves to ``None``, not a crash.

    **Test steps:**

    * mock ``QImage`` construction to report a null image
    * verify ``get_markdown_viewer_image`` returns ``None``
    """
    mock_decoded_image(mocker, width=0, is_null=True)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    assert (
        RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("missing.jpg") is None
    )


def test_get_markdown_viewer_image_returns_none_for_a_name_with_no_filename(mocker: MockerFixture) -> None:
    """A reference naming no file at all -- an empty name, or a URL ending in a directory -- resolves
    to ``None`` before anything is decoded.

    **Test steps:**

    * mock ``QImage`` construction so any decode attempt is visible
    * resolve ``""`` and ``"file:///elsewhere/"`` on a document at ``/fake/info.rehu``
    * verify both return ``None`` and ``QImage`` was never constructed
    """
    _, _, constructor = mock_decoded_image(mocker, width=100)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))
    scanner = RehuDocumentImageScanner(model, no_screenshots, no_screenshots)

    assert scanner.get_markdown_viewer_image("") is None
    assert scanner.get_markdown_viewer_image("file:///elsewhere/") is None
    constructor.assert_not_called()


def test_get_markdown_viewer_image_returns_none_without_a_path() -> None:
    """A document with no path yet can't resolve anything.

    **Test steps:**

    * build a scanner over a pathless document
    * verify ``get_markdown_viewer_image`` returns ``None``
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    assert (
        RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("cover.jpg") is None
    )


# endregion


# region extension-less references (#281)
def test_get_markdown_viewer_image_resolves_an_extension_less_reference(mocker: MockerFixture) -> None:
    """``![](info00)`` -- the number-preserving conversion's own reference shape (#288) -- resolves by
    trying each of ``IMAGE_EXTENSIONS`` in turn and taking the first that exists on disk.

    **Test steps:**

    * report only ``info00.png`` as existing on disk
    * mock ``QImage`` construction to report an in-cap image
    * resolve the extension-less name ``"info00"``
    * verify ``QImage`` was constructed with the ``.png`` candidate, and that image is returned
    """
    image, _, constructor = mock_decoded_image(mocker, width=100)
    png_path = Path("/fake/info00.png")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self == png_path)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("info00")

    assert result is image
    constructor.assert_called_once_with(str(png_path))


def test_get_markdown_viewer_image_tries_extensions_in_order(mocker: MockerFixture) -> None:
    """When more than one candidate extension exists, the first in ``IMAGE_EXTENSIONS`` order wins.

    **Test steps:**

    * report both ``info00.jpg`` and ``info00.png`` as existing on disk
    * mock ``QImage`` construction to report an in-cap image
    * resolve the extension-less name ``"info00"``
    * verify ``QImage`` was constructed with the ``.jpg`` candidate -- earlier in ``IMAGE_EXTENSIONS``
    """
    image, _, constructor = mock_decoded_image(mocker, width=100)
    jpg_path = Path("/fake/info00.jpg")
    png_path = Path("/fake/info00.png")
    mocker.patch.object(Path, "exists", autospec=True, side_effect=lambda self: self in (jpg_path, png_path))
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("info00")

    assert result is image
    constructor.assert_called_once_with(str(jpg_path))


def test_get_markdown_viewer_image_returns_none_when_no_extension_candidate_exists(mocker: MockerFixture) -> None:
    """An extension-less name with no matching file on disk resolves to ``None``, never a guess.

    **Test steps:**

    * report nothing as existing on disk
    * resolve the extension-less name ``"info00"``
    * verify ``get_markdown_viewer_image`` returns ``None``
    """
    mocker.patch.object(Path, "exists", autospec=True, return_value=False)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    assert RehuDocumentImageScanner(model, no_screenshots, no_screenshots).get_markdown_viewer_image("info00") is None


# endregion
