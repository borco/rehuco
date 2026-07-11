"""A read-only Markdown viewer: renders Markdown to HTML into a content-sizing :class:`RichTextView`,
capping over-wide images ([[plugins#field-toolkit]]).

Rendering is isolated behind :func:`render_markdown` so the library/options can change without
touching the widget. The underlying `RichTextView` renders Qt **rich text**, not a full browser --
only a subset of HTML/CSS, no scripting, and it does not fetch network images -- so the extension
set is kept to what its engine actually renders.
"""

from collections.abc import Callable
from typing import Any, Final, override

import markdown
from borco_pyside.widgets import RichTextView
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QWidget

DEFAULT_ENGINE: Final = "markdown"
"""The renderer used when nothing overrides it -- the engine this app always used before #47 made
it configurable."""

MAX_IMAGE_WIDTH: Final = 350
"""Default cap, in pixels, on a rendered image's width -- an over-wide embedded image is scaled down
to fit rather than forcing the viewer wide."""

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
    scales any image wider than ``max_image_width`` down to it, so an over-wide image never forces
    the viewer wide.

    :param parent: optional Qt parent.
    :param engine: the renderer to use; defaults to :data:`DEFAULT_ENGINE`.
    :param css: stylesheet applied to the rendered HTML (``QTextDocument.setDefaultStyleSheet``);
        empty (no extra styling) by default.
    :param max_image_width: the width, in pixels, images are capped to; defaults to
        :data:`MAX_IMAGE_WIDTH`.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        engine: str = DEFAULT_ENGINE,
        css: str = "",
        max_image_width: int = MAX_IMAGE_WIDTH,
    ) -> None:
        super().__init__(parent)
        self.__engine = engine
        self.__max_image_width = max_image_width
        self.__text = ""
        self.setOpenExternalLinks(True)
        self.document().setDefaultStyleSheet(css)

    def set_markdown(self, text: str) -> None:
        """Render ``text`` and show it.

        :param text: the Markdown source.
        """
        self.__text = text
        self.setHtml(render_markdown(text, self.__engine))

    def apply_rendering_settings(self, *, engine: str, css: str, max_image_width: int) -> None:
        """Update the renderer, stylesheet, and image-width cap together, then re-render the
        current text once.

        A single combined call (rather than one setter per field) so a settings change touching
        more than one of these at once -- e.g. every field on a "Save" -- re-renders exactly once,
        not once per changed field.

        :param engine: the renderer to use -- a key of :data:`RENDERERS`.
        :param css: the new stylesheet (``QTextDocument.setDefaultStyleSheet`` only takes effect on
            the next render, not retroactively on what's already shown -- this call re-renders).
        :param max_image_width: the new image-width cap, in pixels.
        """
        self.__engine = engine
        self.__max_image_width = max_image_width
        self.document().setDefaultStyleSheet(css)
        self.set_markdown(self.__text)

    @override
    def loadResource(self, resource_type: int, name: QUrl | str) -> Any:
        """Load a document resource, scaling an over-wide image down to ``max_image_width``.

        :param resource_type: the `QTextDocument.ResourceType` selector.
        :param name: the resource URL.
        :returns: the resource -- an image is returned width-capped, everything else untouched.
        """
        resource = super().loadResource(resource_type, name)
        if (
            resource_type == QTextDocument.ResourceType.ImageResource
            and isinstance(resource, QImage)
            and resource.width() > self.__max_image_width
        ):
            return resource.scaledToWidth(self.__max_image_width, Qt.TransformationMode.SmoothTransformation)
        return resource
