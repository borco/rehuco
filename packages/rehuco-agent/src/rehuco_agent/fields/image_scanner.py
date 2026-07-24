"""The image-resolution contract the field toolkit depends on ([[data-model#image-meanings]]).

The toolkit's widgets depend on this `Protocol`; the concrete, model-backed ``RehuDocumentImageScanner``
in the ``documents`` layer implements it -- the same inversion `FieldModel` applies to the view-model
binding, keeping the ``fields`` toolkit document-agnostic.
"""

from pathlib import Path
from typing import Protocol

from PySide6.QtGui import QImage


class ImageScanner(Protocol):
    """What a field widget needs to resolve a resource's screenshots and embedded images
    ([[data-model#image-meanings]]).

    The lightbox widgets (`ImageStrip`/`ImageSelector`) and the Markdown editor call :meth:`files`;
    the Markdown viewer calls :meth:`get_markdown_viewer_image`. The concrete scanner provides both.
    """

    def files(self) -> list[Path]:
        """Every recognized screenshot for this resource, as absolute paths.

        :returns: the matching paths.
        """
        ...  # pylint: disable=unnecessary-ellipsis

    def get_markdown_viewer_image(self, name: str, device_pixel_ratio: float = 1.0) -> QImage | None:
        """Resolve ``name`` against this resource's own directory, decoded and scaled for display.

        :param name: a bare filename (``"cover.jpg"``) or a ``file://`` URL naming it.
        :param device_pixel_ratio: the screen's device-pixel-ratio to tag the image for.
        :returns: the (possibly scaled) image, or ``None`` if unresolvable or undecodable.
        """
        ...  # pylint: disable=unnecessary-ellipsis
