"""Resolves the images a record's description embeds, for a view that is not showing the record as a document (#458)."""

from pathlib import Path

from PySide6.QtGui import QImage

from ..documents.rehu_document_image_scanner import markdown_viewer_image
from ..fields.image_scanner import AfterConversion, ScreenshotSet


class RecordImages:
    """The field toolkit's `ImageScanner` for a description shown beside the record it came from: it resolves an
    embedded image against the record's own folder and has no screenshots to offer.

    Which record is :attr:`record`, set by the view each time it shows another.
    """

    def __init__(self) -> None:
        self.record: Path | None = None
        """The record the description being shown belongs to; ``None`` resolves no image."""

    def files(self) -> list[Path]:
        """No screenshots: the view shows a description, not the record's images.

        :returns: an empty list.
        """
        return []

    def screenshots(self) -> ScreenshotSet:
        """No screenshots.

        :returns: an empty set.
        """
        return ScreenshotSet()

    def after_conversion(self) -> dict[str, AfterConversion] | None:
        """Nothing is converted here.

        :returns: ``None``.
        """
        return None

    def get_markdown_viewer_image(self, name: str, device_pixel_ratio: float = 1.0) -> QImage | None:
        """Resolve an embedded image against the record's folder, as the description dock does.

        :param name: a bare filename or a ``file://`` URL naming it.
        :param device_pixel_ratio: the screen's device-pixel-ratio to tag the image for.
        :returns: the image, or ``None`` if unresolvable or undecodable.
        """
        return markdown_viewer_image(self.record, name, device_pixel_ratio)
