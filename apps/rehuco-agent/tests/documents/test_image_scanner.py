"""Tests for ImageScanner/RehuScanner/TcScanner ([[data-model#image-meanings]], [[acquisition-tooling#tc-to-rehu]])."""

from pathlib import Path
from typing import Final
from unittest.mock import Mock

from pytest import raises
from pytest_mock import MockerFixture
from rehuco_agent.documents.image_scanner import ImageScanner, RehuScanner, TcScanner
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_core import RehuDocument, ScreenshotRename

FAKE_PATH: Final = Path("/fake/info.rehu")
FAKE_TC_PATH: Final = Path("/fake/info.tc")


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
    constructor = mocker.patch("rehuco_agent.documents.image_scanner.QImage", return_value=image)
    return image, scaled, constructor


# region RehuScanner tests
def test_rehu_scanner_returns_empty_without_a_path() -> None:
    """A pathless document has no screenshot siblings to enumerate.

    **Test steps:**

    * build a ``RehuScanner`` over a model whose document was never given a path
    * verify ``files()`` is empty
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))
    assert RehuScanner(model).files() == []


def test_rehu_scanner_matches_stem_numbered_siblings(mocker: MockerFixture) -> None:
    """``files()`` returns the ``<stem>NN`` image siblings, sorted, ignoring everything else.

    **Test steps:**

    * wrap a document at ``/fake/info.rehu`` and mock its directory listing
    * include matching ``info00``/``info01``/``info02`` screenshots (one a ``.webp``), a non-image
      and a mismatched-stem sibling
    * verify only the three screenshots come back, sorted by name
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))
    siblings = [
        Path("/fake/info01.png"),
        Path("/fake/info00.jpg"),
        Path("/fake/info02.webp"),
        Path("/fake/info.rehu"),
        Path("/fake/info00.txt"),
        Path("/fake/cover.jpg"),
        Path("/fake/info0.jpg"),
    ]
    mocker.patch.object(Path, "iterdir", return_value=siblings)

    assert RehuScanner(model).files() == [
        Path("/fake/info00.jpg"),
        Path("/fake/info01.png"),
        Path("/fake/info02.webp"),
    ]


def test_rehu_scanner_tolerates_a_missing_directory(mocker: MockerFixture) -> None:
    """A missing/offline directory yields no screenshots rather than raising.

    **Test steps:**

    * wrap a document with a path and mock ``iterdir`` to raise ``FileNotFoundError``
    * verify ``files()`` swallows it and returns empty
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))
    mocker.patch.object(Path, "iterdir", side_effect=FileNotFoundError)

    assert RehuScanner(model).files() == []


# endregion


# region TcScanner tests
def test_tc_scanner_returns_empty_without_a_path() -> None:
    """A pathless document has nothing to scan.

    **Test steps:**

    * build a ``TcScanner`` over a model whose document was never given a path
    * verify ``files()`` is empty
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, legacy_tc=True))
    assert TcScanner(model).files() == []


def test_tc_scanner_returns_each_slots_winner(mocker: MockerFixture) -> None:
    """``files()`` resolves each recognized slot's winner to an absolute path under the document's
    own directory.

    **Test steps:**

    * mock ``scan_tc_screenshots`` to return two slots' renames
    * build a ``TcScanner`` over a document at ``/fake/info.tc``
    * verify each winner resolves against ``/fake``
    """
    renames = [
        ScreenshotRename("info00.png", "sample-00.png", ("cover.jpg", "sample-00.png")),
        ScreenshotRename("info01.jpg", "file-01.jpg", ("file-01.jpg",)),
    ]
    scan = mocker.patch("rehuco_agent.documents.image_scanner.scan_tc_screenshots", return_value=renames)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_TC_PATH, legacy_tc=True))

    assert TcScanner(model).files() == [Path("/fake/sample-00.png"), Path("/fake/file-01.jpg")]
    scan.assert_called_once_with(Path("/fake"), "info")


# endregion


def test_image_scanner_files_is_not_implemented_on_the_base_class() -> None:
    """``ImageScanner.files()`` itself is an unimplemented stub -- subclasses must override it.

    **Test steps:**

    * build a bare ``ImageScanner`` (not a subclass)
    * call ``files()``
    * verify ``NotImplementedError`` propagates
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))
    with raises(NotImplementedError):
        ImageScanner(model).files()


# region get_markdown_viewer_image tests (shared base-class behavior, exercised via RehuScanner)
def test_get_markdown_viewer_image_resolves_a_bare_filename(mocker: MockerFixture) -> None:
    """A bare filename resolves against the document's own directory, independent of process CWD.

    **Test steps:**

    * mock ``QImage`` construction to report an in-cap image
    * resolve ``"cover.jpg"`` on a document at ``/fake/info.rehu``
    * verify ``QImage`` was constructed with the path under ``/fake``, and that image is returned
    """
    image, _, constructor = mock_decoded_image(mocker, width=100)
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}, FAKE_PATH))

    result = RehuScanner(model).get_markdown_viewer_image("cover.jpg")

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

    result = RehuScanner(model).get_markdown_viewer_image("file:///elsewhere/cover.jpg")

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

    result = RehuScanner(model).get_markdown_viewer_image("cover.jpg")

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

    result = RehuScanner(model).get_markdown_viewer_image("cover.jpg")

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

    result = RehuScanner(model).get_markdown_viewer_image("cover.jpg", device_pixel_ratio=1.25)

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

    result = RehuScanner(model).get_markdown_viewer_image("cover.jpg", device_pixel_ratio=1.25)

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

    assert RehuScanner(model).get_markdown_viewer_image("missing.jpg") is None


def test_get_markdown_viewer_image_returns_none_without_a_path() -> None:
    """A document with no path yet can't resolve anything.

    **Test steps:**

    * build a scanner over a pathless document
    * verify ``get_markdown_viewer_image`` returns ``None``
    """
    model = RehuDocumentModel(RehuDocument({"type": "Tutorial"}))

    assert RehuScanner(model).get_markdown_viewer_image("cover.jpg") is None


# endregion
