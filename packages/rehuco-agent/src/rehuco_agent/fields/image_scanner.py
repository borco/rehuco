"""The image-resolution contract the field toolkit depends on ([[data-model#image-meanings]]).

The toolkit's widgets depend on this `Protocol`; the concrete, model-backed ``RehuDocumentImageScanner``
in the ``documents`` layer implements it -- the same inversion `FieldModel` applies to the view-model
binding, keeping the ``fields`` toolkit document-agnostic.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PySide6.QtGui import QImage


@dataclass(frozen=True, slots=True)
class ScreenshotSet:
    """A resource's screenshots, the two kinds kept apart ([[data-model#image-meanings]], #270).

    Both kinds are screenshots and the curated-out list governs both; what separates them is that only
    the numbered ones hold a *position*, which is why the curation editor lists them first and greys
    the reorder buttons on the rest. Every other reader wants them as one sequence and gets it from
    :meth:`paths`.

    :ivar numbered: the ``<stem>NN`` set, in slot order -- the orderable half.
    :ivar unconverted: the pattern-matched images that have no slot yet
        ([[acquisition-tooling#screenshot-schemes]]), in natural-sort order.
    :ivar shared_directory: whether another record sits in the same directory
        ([[data-model#resource-scoping]]), which makes every :attr:`unconverted` image claimable --
        and deletable -- from that record's dock too.
    """

    numbered: tuple[Path, ...] = ()
    unconverted: tuple[Path, ...] = ()
    shared_directory: bool = False

    def paths(self) -> list[Path]:
        """Every screenshot, numbered first and un-converted after.

        The order the strip and the lightbox show them in (#281), and the order the curation editor
        lists its rows in.

        :returns: the whole set as one list.
        """
        return [*self.numbered, *self.unconverted]


@dataclass(frozen=True, slots=True)
class AfterConversion:
    """What one pattern-matched image is once a `.tc` -> `.rehu` conversion has run (#293).

    Declared here, beside :class:`ScreenshotSet`, because it is part of the :class:`ImageScanner`
    contract the toolkit's curation editor reads -- the ``documents`` layer fills it in from the
    conversion's own dry-run plan, and the widget never learns where it came from.

    :ivar name: the filename the image has afterwards -- the ``<stem>NN`` it is renamed to, or its own
        name when the conversion leaves it alone. What the *After conversion* cell shows.
    :ivar reason: why it keeps its own name, in the conversion's vocabulary; empty for a renamed image.
        What the cell's tooltip says.
    """

    name: str
    reason: str = ""

    @property
    def kept(self) -> bool:
        """Whether the conversion leaves this image under its own name."""
        return bool(self.reason)


class ImageScanner(Protocol):
    """What a field widget needs to resolve a resource's screenshots and embedded images
    ([[data-model#image-meanings]]).

    The strip (`ImageStrip`) and the Markdown editor call :meth:`files`, which is every screenshot as
    one sequence; the curation editor calls :meth:`screenshots`, because it is the one surface that
    treats the two kinds differently, and :meth:`after_conversion`, because it is the one surface with
    a column for it (#293); the Markdown viewer calls :meth:`get_markdown_viewer_image`. The concrete
    scanner provides all four.
    """

    def files(self) -> list[Path]:  # pyright: ignore[reportReturnType]
        """Every recognized screenshot for this resource, as absolute paths.

        :returns: :meth:`ScreenshotSet.paths` of :meth:`screenshots` -- the numbered set first, then
            the pattern-matched images that have no slot yet.
        """

    def screenshots(self) -> ScreenshotSet:  # pyright: ignore[reportReturnType]
        """Every recognized screenshot for this resource, the two kinds kept apart (#270).

        :returns: the set; see :class:`ScreenshotSet`.
        """

    def after_conversion(self) -> dict[str, AfterConversion] | None:  # pyright: ignore[reportReturnType]
        """What each pattern-matched image is once this resource is converted (#293) -- the curation
        editor's *After conversion* column reads this, and only ever while the document is a legacy
        ``.tc``.

        :returns: ``{filename: outcome}``, or ``None`` when there is nothing to convert (a ``.rehu``,
            or a document with no directory to scan yet) -- which is what hides the column.
        """

    def get_markdown_viewer_image(self, name: str, device_pixel_ratio: float = 1.0) -> QImage | None:
        """Resolve ``name`` against this resource's own directory, decoded and scaled for display.

        :param name: a bare filename (``"cover.jpg"``) or a ``file://`` URL naming it.
        :param device_pixel_ratio: the screen's device-pixel-ratio to tag the image for.
        :returns: the (possibly scaled) image, or ``None`` if unresolvable or undecodable.
        """
