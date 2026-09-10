"""Resolves a resource's screenshots for the lightbox and the Markdown viewer ([[data-model#image-meanings]]).

Composes two orthogonal concerns rather than subclassing per naming scheme: *which* files are the
resource's screenshots -- supplied as two core, ``list[Path]``-returning listers, one per row kind
(`rehuco_core.scan_rehu_screenshot_files` and `rehuco_core.scan_unconverted_screenshots`, #270) -- and
how an embedded Markdown image name resolves to a decoded, width-capped `QImage`, which is implemented
once here. Both lookups resolve against *this resource's own directory*, independent of the process's
current working directory.

The concrete side of the field toolkit's `ImageScanner` protocol: it lives here in the ``documents``
layer (constructed by `RehuDocumentModel`, reading the app's Markdown settings), while the toolkit's
widgets depend only on that interface -- the same split as `FieldModel` / `RehuDocumentModel`.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage
from rehuco_core import IMAGE_EXTENSIONS, other_record_stems

from ..fields.image_scanner import AfterConversion, ScreenshotSet
from ..settings.markdown_rendering_settings import shared_markdown_rendering_settings

if TYPE_CHECKING:
    from .rehu_document_model import RehuDocumentModel

type ScreenshotLister = Callable[[Path, str], list[Path]]
"""Lists a resource's screenshot files from its ``(directory, stem)`` -- either
`rehuco_core.scan_rehu_screenshot_files` or `rehuco_core.scan_unconverted_screenshots`, which share
that signature."""

type AfterConversionLister = Callable[[Path, str], dict[str, AfterConversion]]
"""Says what each pattern-matched image in one ``(directory, stem)`` is once its `.tc` is converted --
`~rehuco_agent.documents.tc_conversion_outcomes.scan_after_conversion`, with the configured patterns
already bound (#293)."""


class RehuDocumentImageScanner:
    """Resolves one resource's screenshots against its own directory ([[data-model#image-meanings]]).

    Built from the model plus one lister per row kind, so the naming rules live as pure functions in
    ``rehuco_core`` rather than as scanner subclasses here. :meth:`screenshots` keeps the two kinds
    apart for the curation editor; :meth:`files` hands every other reader the pair as one sequence;
    :meth:`get_markdown_viewer_image` resolves a name embedded in the description's Markdown, which
    depends on neither kind and is implemented once. Implements the field toolkit's `ImageScanner`
    protocol, so the toolkit's widgets depend on that interface, not on this concrete class
    ([[plugins#field-toolkit]]).

    :param model: the document this scanner resolves screenshots for.
    :param lister: lists the ``<stem>NN`` files on disk, given the resource's ``(directory, stem)``.
    :param unconverted_lister: lists the pattern-matched images that have no slot yet, given the same
        ``(directory, stem)``.
    :param after_conversion: says what each pattern-matched image is once the resource is converted,
        given the same ``(directory, stem)`` (#293) -- what :meth:`after_conversion` reads on a
        ``.tc``; never called on a ``.rehu``, where there is nothing left to convert. ``None`` -- the
        default -- leaves :meth:`after_conversion` answering ``None`` outright, for a scanner built
        (as most tests do) with nothing to say about it.

    All three listers are taken as arguments rather than called directly so the choice, and the binding
    of the configured patterns (#281), is made in one place: `RehuDocumentModel.__make_image_scanner`.
    """

    def __init__(
        self,
        model: RehuDocumentModel,
        lister: ScreenshotLister,
        unconverted_lister: ScreenshotLister,
        after_conversion: AfterConversionLister | None = None,
    ) -> None:
        self.__model: Final = model
        self.__lister: Final = lister
        self.__unconverted_lister: Final = unconverted_lister
        self.__after_conversion: Final = after_conversion

    def files(self) -> list[Path]:
        """Every recognized screenshot for this resource, as absolute paths.

        :returns: :meth:`ScreenshotSet.paths` of :meth:`screenshots` -- the numbered set first, then
            the pattern-matched images that have no slot yet (#270).
        """
        return self.screenshots().paths()

    def screenshots(self) -> ScreenshotSet:
        """Every recognized screenshot for this resource, the two kinds kept apart (#270).

        Empty, without touching the directory, while the model is still a
        :attr:`~RehuDocumentModel.pending` session-restore placeholder (#66): both listers are
        directory scans, which can block on an offline mount ([[mounts-and-storage#offline-mounts]]),
        and the strip/selector call this while merely being built. The deferred load rebuilds the
        whole form (``active_block_changed``), so the rebuilt widgets re-ask once the answer is real.

        An image the two listers both report is **numbered, once**. The two are supplied
        independently, so nothing about their types makes their answers disjoint; a picture listed
        twice would appear twice in the strip and be offered Convert on a row already accounted for,
        which is a worse failure than the set difference costs.

        :returns: the set; see :class:`~rehuco_agent.fields.image_scanner.ScreenshotSet`. Empty when
            the document has no path yet or is still pending.
        """
        path = self.__model.path
        if path is None or self.__model.pending:
            return ScreenshotSet()
        directory, stem = path.parent, path.stem
        numbered = self.__lister(directory, stem)
        listed = set(numbered)
        return ScreenshotSet(
            numbered=tuple(numbered),
            unconverted=tuple(
                candidate for candidate in self.__unconverted_lister(directory, stem) if candidate not in listed
            ),
            shared_directory=bool(other_record_stems(directory, stem)),
        )

    def after_conversion(self) -> dict[str, AfterConversion] | None:
        """What each pattern-matched image is once this resource is converted (#293).

        ``None`` off anything that is not a legacy ``.tc`` with a real path to scan and an
        ``after_conversion`` lister to ask -- a ``.rehu`` has nothing left to convert, a path-less or
        :attr:`~RehuDocumentModel.pending` document has no directory to read -- which is what the
        images dock's *After conversion* column reads as "hide me". Read fresh from the lister on every
        call rather than cached here, the same as :meth:`screenshots` -- the caller (`ImageSelector`)
        asks once per rebuild, not once per row.

        :returns: ``{filename: outcome}``, or ``None``; see
            `~rehuco_agent.documents.tc_conversion_outcomes.after_conversion`.
        """
        if self.__after_conversion is None:
            return None
        path = self.__model.path
        if path is None or self.__model.pending or not self.__model.document.legacy_tc:
            return None
        return self.__after_conversion(path.parent, path.stem)

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

        An extension-less ``name`` (``![](info00)``, the number-preserving conversion's own reference
        shape, #288) tries each of :data:`~rehuco_core.IMAGE_EXTENSIONS` in turn and returns the first
        that exists on disk -- so a reorder that swaps a `.png` into a slot a `.jpg` used to hold still
        resolves without the description needing an edit of its own.

        :param name: a bare filename, an extension-less slot name, or a ``file://`` URL naming it.
        :returns: the resolved path, or ``None`` if the document has no path yet, ``name`` is empty, or
            no candidate extension exists on disk.
        """
        path = self.__model.path
        if path is None:
            return None
        filename = QUrl(name).fileName()
        if not filename:
            return None
        candidate = path.parent / filename
        if candidate.suffix:
            return candidate
        for extension in IMAGE_EXTENSIONS:
            with_extension = path.parent / f"{filename}{extension}"
            if with_extension.exists():
                return with_extension
        return None
