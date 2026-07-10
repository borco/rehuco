"""A read-only Markdown viewer: renders Markdown to HTML into a `QTextBrowser`, capping over-wide
images ([[plugins#field-toolkit]]).

Rendering is isolated behind :func:`render_markdown` so the library/options can change (or become a
preference) without touching the widget. ``QTextBrowser`` renders Qt **rich text**, not a full
browser -- only a subset of HTML/CSS, no scripting, and it does not fetch network images -- so the
extension set is kept to what its engine actually renders.
"""

from typing import Any, Final, override

import markdown
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QImage, QTextDocument
from PySide6.QtWidgets import QTextBrowser, QWidget

MAX_IMAGE_WIDTH: Final = 350
"""Default cap, in pixels, on a rendered image's width -- an over-wide embedded image is scaled down
to fit rather than forcing the viewer wide. A constant for now; a future preferences slice makes it
(and the renderer choice and a custom stylesheet) configurable."""

MARKDOWN_EXTENSIONS: Final = ["fenced_code", "tables", "sane_lists", "nl2br"]
"""Python-Markdown extensions whose HTML the `QTextBrowser` rich-text engine can actually render."""


def render_markdown(text: str) -> str:
    """Render Markdown ``text`` to HTML.

    Isolated so the renderer (or its options) can change without touching the viewer.

    :param text: the Markdown source.
    :returns: the rendered HTML.
    """
    return markdown.markdown(text, extensions=MARKDOWN_EXTENSIONS)


class MarkdownView(QTextBrowser):
    """A read-only Markdown viewer ([[plugins#field-toolkit]]): renders via :func:`render_markdown`
    into the `QTextBrowser` rich-text engine, and scales any image wider than ``max_image_width`` down
    to it, so an over-wide image never forces the viewer wide.

    :param parent: optional Qt parent.
    :param max_image_width: the width, in pixels, images are capped to; defaults to :data:`MAX_IMAGE_WIDTH`.
    """

    def __init__(self, parent: QWidget | None = None, max_image_width: int = MAX_IMAGE_WIDTH) -> None:
        super().__init__(parent)
        self.__max_image_width = max_image_width
        self.setOpenExternalLinks(True)

    def set_markdown(self, text: str) -> None:
        """Render ``text`` and show it.

        :param text: the Markdown source.
        """
        self.setHtml(render_markdown(text))

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
