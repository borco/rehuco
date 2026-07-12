"""Resolves a resource's screenshots for the lightbox and the Markdown viewer ([[data-model#image-meanings]]).

Both consumers go through one `ImageScanner`, built from the model so every lookup resolves against
*this resource's own directory*, independent of the process's current working directory -- the root
cause of a relative Markdown ``![](cover.jpg)`` reference only resolving when the app happened to be
launched from the file's own folder.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage
from rehuco_core import scan_tc_screenshots

from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings

if TYPE_CHECKING:
    from rehuco_agent.documents.rehu_document_model import RehuDocumentModel

IMAGE_EXTENSIONS: Final = (".jpg", ".jpeg", ".png", ".gif")
"""Screenshot file extensions :class:`RehuScanner` recognizes, matched case-insensitively."""


class ImageScanner:
    """Resolves one resource's screenshots against its own directory ([[data-model#image-meanings]]).

    Subclasses decide which files exist: :class:`RehuScanner` for the target ``.rehu`` ``{stem}NN``
    convention, :class:`TcScanner` for a legacy ``.tc``'s naming schemes
    ([[acquisition-tooling#tc-to-rehu]]). Both are used two ways: :meth:`files` feeds the lightbox
    (which stays completely unaware of either naming scheme), and :meth:`get_markdown_viewer_image`
    resolves a name embedded in the description's Markdown.

    :param model: the document this scanner resolves screenshots for.
    """

    def __init__(self, model: RehuDocumentModel) -> None:
        self._model: Final = model

    def files(self) -> list[Path]:
        """Every recognized screenshot for this resource, as absolute paths.

        :returns: the matching paths.
        """
        raise NotImplementedError

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
        path = self._model.path
        if path is None:
            return None
        filename = QUrl(name).fileName()
        return path.parent / filename if filename else None


class RehuScanner(ImageScanner):
    """The target ``.rehu`` screenshot convention: ``{stem}NN`` siblings ([[data-model#image-meanings]]).

    For ``info.rehu`` these are ``info00.jpg`` / ``info01.png`` / ...; for ``foo.rehu`` they are
    ``foo00.jpg`` / ... -- with an :data:`IMAGE_EXTENSIONS` extension, matched case-insensitively.
    ``path.stem`` is always the right prefix here (``"info"``/``"foo"``), unlike
    ``RehuDocumentModel.current_name`` -- that property answers a different question (the parent
    *folder's* name for a directory-scoped resource, used for rename suggestions).
    """

    def files(self) -> list[Path]:
        """Enumerate this resource's ``{stem}NN`` screenshot siblings, sorted by filename.

        :returns: the matching paths, or empty when the document has no path yet, its directory is
            missing/unreadable (e.g. an offline mount, [[mounts-and-storage#offline-mounts]]), or it
            holds none.
        """
        path = self._model.path
        if path is None:
            return []
        pattern = re.compile(rf"^{re.escape(path.stem)}\d{{2}}$", re.IGNORECASE)
        try:
            siblings = list(path.parent.iterdir())
        except OSError:
            return []
        matches = [
            sibling
            for sibling in siblings
            if sibling.suffix.lower() in IMAGE_EXTENSIONS and pattern.match(sibling.stem)
        ]
        return sorted(matches, key=lambda sibling: sibling.name)


class TcScanner(ImageScanner):
    """A legacy ``.tc``'s screenshots, via `rehuco_core.scan_tc_screenshots` ([[acquisition-tooling#tc-to-rehu]]).

    Shows exactly what a real conversion would keep -- each recognized slot's winner, not the losing
    smaller/duplicate variants.
    """

    def files(self) -> list[Path]:
        """Scan this resource's directory for legacy screenshots and return each slot's winner.

        :returns: the matching paths, or empty when the document has no path yet.
        """
        path = self._model.path
        if path is None:
            return []
        return [path.parent / rename.source_filename for rename in scan_tc_screenshots(path.parent, path.stem)]
