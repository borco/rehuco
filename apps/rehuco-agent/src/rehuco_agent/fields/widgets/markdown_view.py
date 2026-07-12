"""A read-only Markdown viewer: renders Markdown to HTML into a content-sizing :class:`RichTextView`
([[plugins#field-toolkit]]).

Rendering is isolated behind :func:`render_markdown` so the library/options can change without
touching the widget. The underlying `RichTextView` renders Qt **rich text**, not a full browser --
only a subset of HTML/CSS, no scripting, and it does not fetch network images -- so the extension
set is kept to what its engine actually renders. Embedded images are resolved and width-capped by an
``ImageScanner`` ([[data-model#image-meanings]]), not by this widget -- Qt's own real
``loadResource()`` returns raw file bytes for a local image, never a decoded ``QImage``, so scaling
here directly would need to duplicate the scanner's own decode step anyway.
"""

from collections.abc import Callable
from typing import Any, Final, override

import markdown
from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import RichTextView
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QWidget

from rehuco_agent.documents.image_scanner import ImageScanner

DEFAULT_ENGINE: Final = "markdown"
"""The renderer used when nothing overrides it -- the engine this app always used before #47 made
it configurable."""

MARKDOWN_EXTENSIONS: Final = ["fenced_code", "tables", "sane_lists", "nl2br"]
"""Python-Markdown extensions whose HTML the `QTextBrowser` rich-text engine can actually render."""


def render_with_markdown_extension(text: str) -> str:
    """Render ``text`` via the `markdown` package, with :data:`MARKDOWN_EXTENSIONS`.

    :param text: the Markdown source.
    :returns: the rendered HTML.
    """
    return markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS)


def render_with_mistletoe(text: str) -> str:
    """Render ``text`` via the `mistletoe` package (CommonMark).

    Imports ``mistletoe`` lazily, on first use, not at module scope -- confirmed empirically to
    cost ~150ms to import (``mistletoe.core_tokens`` eagerly compiles its whole CommonMark regex
    set), roughly 3x ``markdown`` package's own import cost. Paying that only if/when this engine
    is actually selected keeps it off every app startup for the (likely common) case of a user who
    never switches away from the default :data:`DEFAULT_ENGINE`.

    :param text: the Markdown source.
    :returns: the rendered HTML.
    """
    import mistletoe  # pylint: disable=import-outside-toplevel

    return mistletoe.markdown(text)


RENDERERS: Final[dict[str, Callable[[str], str]]] = {
    "markdown": render_with_markdown_extension,
    "mistletoe": render_with_mistletoe,
}
"""Every renderer this app supports, keyed by the engine name used in settings (#47)."""


def render_markdown(text: str, engine: str = DEFAULT_ENGINE) -> str:
    """Render Markdown ``text`` to HTML using ``engine``.

    Isolated so the renderer (or its options) can change without touching the viewer.

    :param text: the Markdown source.
    :param engine: the renderer to use -- a key of :data:`RENDERERS`.
    :returns: the rendered HTML.
    :raises KeyError: if ``engine`` isn't a known renderer.
    """
    return RENDERERS[engine](text)


class MarkdownView(RichTextView):
    """A read-only Markdown viewer ([[plugins#field-toolkit]]): renders via :func:`render_markdown`
    into the content-sizing :class:`RichTextView`, applies a stylesheet to the rendered HTML, and
    resolves/width-caps embedded images through an ``ImageScanner``, so an over-wide image never
    forces the viewer wide and a relative reference resolves against the resource's own directory
    regardless of process CWD.

    Holds its own :attr:`image_scanner`, so it can re-render whenever that changes (e.g. a `.tc` ->
    `.rehu` conversion switching naming conventions, [[acquisition-tooling#tc-to-rehu]]) and pick up
    already-embedded images resolving correctly, without its owner re-rendering explicitly.

    :param parent: optional Qt parent.
    :param image_scanner: resolves an embedded image's filename to a scaled, ready-to-show image;
        omit for a viewer that can't resolve any (e.g. a bare instance in isolation/tests).
    :param engine: the renderer to use; defaults to :data:`DEFAULT_ENGINE`.
    :param css: stylesheet applied to the rendered HTML (``QTextDocument.setDefaultStyleSheet``);
        empty (no extra styling) by default.
    """

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """Resolves an embedded image's filename to a scaled, ready-to-show image; ``None`` resolves none."""

    def __init__(
        self,
        parent: QWidget | None = None,
        image_scanner: ImageScanner | None = None,
        engine: str = DEFAULT_ENGINE,
        css: str = "",
    ) -> None:
        super().__init__(parent)
        self.image_scanner = image_scanner
        self.__engine = engine
        self.__text = ""
        self.setOpenExternalLinks(True)
        self.document().setDefaultStyleSheet(css)
        changed = self.image_scanner_changed  # type: ignore[attr-defined]
        changed.connect(lambda _scanner: self.set_markdown(self.__text))

    def set_markdown(self, text: str) -> None:
        """Render ``text`` and show it.

        :param text: the Markdown source.
        """
        self.__text = text
        self.setHtml(render_markdown(text, self.__engine))

    def apply_rendering_settings(self, *, engine: str, css: str) -> None:
        """Update the renderer and stylesheet together, then re-render the current text once.

        A single combined call (rather than one setter per field) so a settings change touching
        more than one of these at once -- e.g. every field on a "Save" -- re-renders exactly once,
        not once per changed field. Re-rendering is also what picks up a changed image-width cap:
        the ``ImageScanner`` reads that setting live on each ``loadResource`` call, so it does not
        need to be threaded through here at all.

        :param engine: the renderer to use -- a key of :data:`RENDERERS`.
        :param css: the new stylesheet (``QTextDocument.setDefaultStyleSheet`` only takes effect on
            the next render, not retroactively on what's already shown -- this call re-renders).
        """
        self.__engine = engine
        self.document().setDefaultStyleSheet(css)
        self.set_markdown(self.__text)

    @override
    def loadResource(self, resource_type: int, name: QUrl | str) -> Any:
        """Load a document resource, resolving/scaling an image through :attr:`image_scanner`.

        Passes :meth:`devicePixelRatio` (this widget's *current* screen's ratio, which Qt keeps
        live as the window moves between differently-scaled monitors) down to the scanner, rather
        than the scanner assuming a fixed screen -- so a small image renders crisp regardless of
        which display it's actually being shown on.

        NOTE: this only re-tags an image when it is actually (re)loaded -- dragging an
        already-rendered window to a differently-scaled monitor with no other change does not by
        itself invalidate the ``QTextDocument``'s cached resource, so the image keeps the old
        screen's ratio until the next real render (an edit, a settings change, reopening). Closing
        that gap would need a ``screenChanged``-triggered re-render; not done here.

        :param resource_type: the `QTextDocument.ResourceType` selector.
        :param name: the resource URL.
        :returns: the scanner's resolved, width-capped image for an ``ImageResource``, when a
            scanner is attached and it resolves ``name``; otherwise whatever the base class's own
            (CWD-dependent, unscaled) resolution returns.
        """
        scanner = self.image_scanner
        if scanner is not None and resource_type == QTextDocument.ResourceType.ImageResource:
            # QUrl's Python str() gives a debug repr, not the URL text -- .toString() is the real one
            url = name if isinstance(name, QUrl) else QUrl(name)
            image = scanner.get_markdown_viewer_image(url.toString(), self.devicePixelRatio())
            if image is not None:
                return image
        return super().loadResource(resource_type, name)
