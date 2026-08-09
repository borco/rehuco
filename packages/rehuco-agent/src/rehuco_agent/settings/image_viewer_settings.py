"""How screenshots are presented, in the strip and maximized ([[plugins#tutorial-plugin]], #160, #161)."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings

from ..fields.images_field import IMAGE_STRIP_HEIGHT
from ..fields.widgets.image_lightbox import DEFAULT_STRIP_HEIGHT, ImageViewerMode
from .persistent_settings import persistent_settings

GROUP: Final = "image_viewer"
MODE_KEY: Final = "mode"
STRIP_VISIBLE_KEY: Final = "strip_visible"
PREVIEW_IMAGE_HEIGHT_KEY: Final = "preview_image_height"
LIGHTBOX_IMAGE_HEIGHT_KEY: Final = "lightbox_image_height"
PREVIEW_WRAP_KEY: Final = "preview_wrap"
PREVIEWS_VISIBLE_KEY: Final = "previews_visible"

DEFAULT_MODE: Final = ImageViewerMode.DOCUMENT_OVERLAY
"""What a fresh install (no ``.ini`` yet) opens screenshots on: the least disruptive of the three --
the app stays where it was, and only the document being read is covered."""

DEFAULT_STRIP_VISIBLE: Final = False
"""Whether a maximized screenshot starts with its thumbnail row shown (#161). Off: the point of
maximizing is the screenshot itself, and the row is one click away whenever it is wanted."""

DEFAULT_PREVIEW_WRAP: Final = False
"""Whether a document's own image strip wraps its thumbnails over several rows (#70). Off: one row is
the compact shape the viewer is laid out around, and it leaves the space below it to the description."""

DEFAULT_PREVIEWS_VISIBLE: Final = True
"""Whether a document's own image strip is shown, on a fresh install with nothing persisted (#71). On:
previews are the normal state, and the app-wide grave-accent toggle (``Ctrl+Shift+``, backtick) is the
exception -- e.g. clearing screenshots off screen before sharing it."""

DEFAULT_PREVIEW_IMAGE_HEIGHT: Final = IMAGE_STRIP_HEIGHT
DEFAULT_LIGHTBOX_IMAGE_HEIGHT: Final = DEFAULT_STRIP_HEIGHT
"""How tall a screenshot is in a document's own image strip and in the maximized viewer's thumbnail
row. Each is read from the widget that implements the strip rather than restated here -- the same
direction :class:`ImageViewerMode` is imported in, so a widget's own natural size and the setting that
overrides it can never drift apart."""


class ImageViewerSettings(QObject):
    """How screenshots are presented, in the strip and maximized (#160, #161).

    A reactive ``QObject`` (``SimpleProperty`` fields), following
    :class:`~rehuco_agent.settings.markdown_rendering_settings.MarkdownRenderingSettings` rather than
    the plain dataclass most of this app's settings sections use: applying the settings page has to
    show its effect on what is **already on screen** -- every open document's strip resizes and takes
    up the chosen layout (#70), and every open maximized viewer resizes and shows or hides its own row
    -- which is the whole point of having an Apply button to watch. :func:`shared_image_viewer_settings`
    is the single, process-wide instance every consumer reads and subscribes to; a fresh one per reader
    would get its own disconnected copy and defeat the live-update wiring entirely.

    :attr:`mode` alone stays read-at-open-time: it decides where the *next* viewer is built, and
    nothing already on screen can follow a change to it.

    :attr:`strip_visible` is the **starting point** a document that has never shown a row opens with;
    a document remembers its own row in its saved layout from then on. Applying it does reach the
    viewers currently open, so the change is visible where the user is looking, but it is never
    written back here by a toggle inside one.

    :attr:`previews_visible` is the app-wide grave-accent toggle's own state (``Ctrl+Shift+``,
    backtick, #71), and unlike the two above it is written back **by the toggle itself**: it has no
    Apply button behind it and no settings page to be saved from, so the moment it is clicked is the
    only moment there is to record it (`MainWindow.__on_image_previews_toggled`). Persisted rather
    than session-only because a user who declutters previews away is stating a preference, not
    borrowing the screen for a minute -- having to re-hide them on every launch would be the friction
    the toggle exists to remove.

    :param parent: optional Qt parent.
    """

    mode = SimpleProperty[ImageViewerMode](DEFAULT_MODE)
    """Which surface a maximized screenshot opens on."""

    strip_visible = SimpleProperty(DEFAULT_STRIP_VISIBLE)
    """Whether a maximized screenshot starts with its thumbnail row shown."""

    preview_wrap = SimpleProperty(DEFAULT_PREVIEW_WRAP)
    """Whether a document's own image strip wraps its thumbnails instead of keeping them on one row."""

    previews_visible = SimpleProperty(DEFAULT_PREVIEWS_VISIBLE)
    """Whether a document's own image strip is shown, app-wide (#71) -- the grave-accent toggle's own
    state (``Ctrl+Shift+``, backtick), persisted as it is clicked."""

    preview_image_height = SimpleProperty(DEFAULT_PREVIEW_IMAGE_HEIGHT)
    """How tall a screenshot is in a document's own image strip."""

    lightbox_image_height = SimpleProperty(DEFAULT_LIGHTBOX_IMAGE_HEIGHT)
    """How tall a screenshot is in the maximized viewer's own thumbnail row."""

    def load(self, settings: QSettings) -> None:
        """Replace the current choices with what's in persistent storage.

        A missing mode -- or one this build doesn't recognize, e.g. an ``.ini`` written by a newer
        version offering a fourth surface -- falls back to :data:`DEFAULT_MODE` rather than raising:
        an unreadable preference must not stop a screenshot from opening at all.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        stored = cast(str, settings.value(MODE_KEY, DEFAULT_MODE.value, type=str))
        self.strip_visible = cast(bool, settings.value(STRIP_VISIBLE_KEY, DEFAULT_STRIP_VISIBLE, type=bool))
        self.preview_wrap = cast(bool, settings.value(PREVIEW_WRAP_KEY, DEFAULT_PREVIEW_WRAP, type=bool))
        self.previews_visible = cast(bool, settings.value(PREVIEWS_VISIBLE_KEY, DEFAULT_PREVIEWS_VISIBLE, type=bool))
        self.preview_image_height = cast(
            int, settings.value(PREVIEW_IMAGE_HEIGHT_KEY, DEFAULT_PREVIEW_IMAGE_HEIGHT, type=int)
        )
        self.lightbox_image_height = cast(
            int, settings.value(LIGHTBOX_IMAGE_HEIGHT_KEY, DEFAULT_LIGHTBOX_IMAGE_HEIGHT, type=int)
        )
        settings.endGroup()
        try:
            self.mode = ImageViewerMode(stored)
        except ValueError:
            self.mode = DEFAULT_MODE

    def save(self, settings: QSettings) -> None:
        """Save the current choices to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(MODE_KEY, self.mode.value)
        settings.setValue(STRIP_VISIBLE_KEY, self.strip_visible)
        settings.setValue(PREVIEW_WRAP_KEY, self.preview_wrap)
        settings.setValue(PREVIEWS_VISIBLE_KEY, self.previews_visible)
        settings.setValue(PREVIEW_IMAGE_HEIGHT_KEY, self.preview_image_height)
        settings.setValue(LIGHTBOX_IMAGE_HEIGHT_KEY, self.lightbox_image_height)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_image_viewer_settings() -> ImageViewerSettings:
    """The single, process-wide `ImageViewerSettings` instance, loaded from persistent storage on
    first call -- the same shape, and for the same reason, as
    :func:`~rehuco_agent.settings.identity_settings.shared_identity_settings`: the settings page's
    Save must be what the next screenshot click reads, not a disconnected per-reader copy.

    :returns: the shared instance.
    """
    settings = ImageViewerSettings()
    settings.load(persistent_settings())
    return settings
