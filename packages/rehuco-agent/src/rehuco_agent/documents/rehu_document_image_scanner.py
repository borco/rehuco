"""Resolves a resource's screenshots for the lightbox and the Markdown viewer ([[data-model#image-meanings]]).

Composes two orthogonal concerns rather than subclassing per naming scheme: *which* files are the
resource's screenshots -- the one convention-varying piece, supplied as a core, ``list[Path]``-returning
``lister`` (`rehuco_core.scan_rehu_screenshot_files` for a ``.rehu``, `rehuco_core.scan_tc_screenshot_files`
for a legacy ``.tc``) -- and how an embedded Markdown image name resolves to a decoded, width-capped
`QImage`, which never varies and is implemented once here. Both lookups resolve against *this resource's
own directory*, independent of the process's current working directory.

The concrete side of the field toolkit's `ImageScanner` protocol: it lives here in the ``documents``
layer (constructed by `RehuDocumentModel`, reading the app's Markdown settings), while the toolkit's
widgets depend only on that interface -- the same split as `FieldModel` / `RehuDocumentModel`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage

from ..settings.markdown_rendering_settings import shared_markdown_rendering_settings

if TYPE_CHECKING:
    from .rehu_document_model import RehuDocumentModel

type ScreenshotLister = Callable[[Path, str], list[Path]]
"""Lists a resource's screenshot files from its ``(directory, stem)`` -- e.g.
`rehuco_core.scan_rehu_screenshot_files` or `rehuco_core.scan_tc_screenshot_files`."""


class RehuDocumentImageScanner:
    """Resolves one resource's screenshots against its own directory ([[data-model#image-meanings]]).

    Built from the model plus a screenshot ``lister`` -- the one convention-varying piece -- so the
    naming schemes live as pure functions in ``rehuco_core`` (`scan_rehu_screenshot_files` /
    `scan_tc_screenshot_files`), not as scanner subclasses here. :meth:`files` feeds the lightbox
    (which stays unaware of any naming scheme) through that lister; :meth:`get_markdown_viewer_image`
    resolves a name embedded in the description's Markdown -- convention-independent, so implemented
    once. Implements the field toolkit's `ImageScanner` protocol, so the toolkit's widgets depend on
    that interface, not on this concrete class ([[plugins#field-toolkit]]).

    :param model: the document this scanner resolves screenshots for.
    :param lister: lists this resource's screenshot files given its ``(directory, stem)``.
    """

    def __init__(self, model: RehuDocumentModel, lister: ScreenshotLister) -> None:
        self.__model: Final = model
        self.__lister: Final = lister

    def files(self) -> list[Path]:
        """Every recognized screenshot for this resource, as absolute paths.

        :returns: the matching paths via this resource's screenshot ``lister``, or empty when the
            document has no path yet.
        """
        path = self.__model.path
        if path is None:
            return []
        return self.__lister(path.parent, path.stem)

    def get_markdown_viewer_image(self, name: str, device_pixel_ratio: float = 1.0) -> QImage | None:
        """Resolve ``name`` against this resource's own directory, decode it, and scale/tag it for
        the live Markdown max-image-width setting and the caller's current screen.

        ``device_pixel_ratio`` is the caller's to supply (e.g. ``QWidget.devicePixelRatio()``), not
        looked up here, since only the widget actually being painted knows which screen it's
        currently on -- a window can be dragged to a different, differently-scaled monitor, so
        there is no single fixed "the" screen to assume. Tagging the returned image with the right
        ratio (rather than leaving it at the default ``1.0``) is what makes a small image render
        crisp on a scaled (e.g. 125%) display instead of Qt silently stretching the raw pixels to
        fill the extra physical space.

        :param name: a bare filename (``"cover.jpg"``) or a ``file://`` URL naming it.
        :param device_pixel_ratio: the screen's device-pixel-ratio to tag the image for.
        :returns: the (possibly scaled) image, or ``None`` if unresolvable or undecodable.
        """
        path = self.__resolved(name)
        if path is None:
            return None
        image = QImage(str(path))
        if image.isNull():
            return None
        max_width = round(shared_markdown_rendering_settings().max_image_width * device_pixel_ratio)
        if image.width() > max_width:
            image = image.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        image.setDevicePixelRatio(device_pixel_ratio)
        return image

    def __resolved(self, name: str) -> Path | None:
        """Resolve ``name`` to an absolute path under this resource's own directory.

        :param name: a bare filename or a ``file://`` URL naming it.
        :returns: the resolved path, or ``None`` if the document has no path yet or ``name`` is empty.
        """
        path = self.__model.path
        if path is None:
            return None
        filename = QUrl(name).fileName()
        return path.parent / filename if filename else None
