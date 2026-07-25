"""Where the maximized image viewer paints itself ([[plugins#tutorial-plugin]], #160)."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Final, cast

from PySide6.QtCore import QSettings

from ..fields.widgets.image_lightbox import ImageViewerMode
from .persistent_settings import persistent_settings

GROUP: Final = "image_viewer"
MODE_KEY: Final = "mode"

DEFAULT_MODE: Final = ImageViewerMode.DOCUMENT_OVERLAY
"""What a fresh install (no ``.ini`` yet) opens screenshots on: the least disruptive of the three --
the app stays where it was, and only the document being read is covered."""


@dataclass
class ImageViewerSettings:
    """The maximized image viewer's persisted presentation choice (#160)."""

    mode: ImageViewerMode = DEFAULT_MODE

    def load(self, settings: QSettings) -> None:
        """Replace the current mode with what's in persistent storage.

        A missing value -- or one this build doesn't recognize, e.g. an ``.ini`` written by a newer
        version offering a fourth surface -- falls back to :data:`DEFAULT_MODE` rather than raising:
        an unreadable preference must not stop a screenshot from opening at all.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        stored = cast(str, settings.value(MODE_KEY, DEFAULT_MODE.value, type=str))
        settings.endGroup()
        try:
            self.mode = ImageViewerMode(stored)
        except ValueError:
            self.mode = DEFAULT_MODE

    def save(self, settings: QSettings) -> None:
        """Save the current mode to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(MODE_KEY, self.mode.value)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_image_viewer_settings() -> ImageViewerSettings:
    """The single, process-wide `ImageViewerSettings` instance, loaded from persistent storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`: the settings page's
    Save must be what the next screenshot click reads, not a disconnected per-reader copy.

    A plain value read at open time, not a reactive `QObject` like
    :class:`~rehuco_agent.settings.markdown_rendering_settings.MarkdownRenderingSettings` -- nothing
    already on screen re-renders when it changes, since the mode only decides where the *next*
    viewer is built.

    :returns: the shared instance.
    """
    settings = ImageViewerSettings()
    settings.load(persistent_settings())
    return settings
