"""Live, reactive Markdown-rendering settings shared by every open document's viewer (#26, #47)."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal

from ..fields.widgets.markdown_view import DEFAULT_ENGINE
from .persistent_settings import persistent_settings

GROUP: Final = "markdown_rendering"
ENGINE_KEY: Final = "engine"
MARKDOWN_CSS_KEY: Final = "markdown_css"
MISTLETOE_CSS_KEY: Final = "mistletoe_css"
MAX_IMAGE_WIDTH_KEY: Final = "max_image_width"

DEFAULT_MAX_IMAGE_WIDTH: Final = 350
"""Default cap, in pixels, an embedded image is scaled to when no persisted value exists yet (a
fresh install with no ``.ini``) -- read by the document's `RehuDocumentImageScanner`, via
:attr:`MarkdownRenderingSettings.max_image_width`, on every image resolution."""


class MarkdownRenderingSettings(QObject):
    """App-wide Markdown-rendering settings: the renderer, its per-engine stylesheet, and the
    image-width cap (#26's constants, made configurable by #47's settings dialog).

    A reactive ``QObject`` (``SimpleProperty`` fields), not the plain dataclass every other
    settings section in this app uses -- every open document's description viewer follows the aggregate
    :attr:`description_rendering_changed`, so a Save on the settings page re-renders already-open
    viewers immediately, not just newly-opened ones. :func:`shared_markdown_rendering_settings` is
    the single, process-wide instance every consumer reads/writes; constructing a fresh one per
    reader would defeat the live-update wiring entirely, since each would get its own disconnected
    copy.

    :param parent: optional Qt parent.
    """

    engine = SimpleProperty(DEFAULT_ENGINE)
    """Which renderer to use -- a key of ``rehuco_agent.fields.widgets.markdown_view.RENDERERS``."""

    markdown_css = SimpleProperty("")
    """Stylesheet applied when :attr:`engine` is ``"markdown"``."""

    mistletoe_css = SimpleProperty("")
    """Stylesheet applied when :attr:`engine` is ``"mistletoe"``."""

    max_image_width = SimpleProperty(DEFAULT_MAX_IMAGE_WIDTH)
    """The width, in pixels, a rendered image is capped to."""

    description_rendering_changed = Signal()
    """Fires whenever a value affecting how a description renders changes -- the :attr:`engine`, the
    active engine's stylesheet (:attr:`css`), or the image-width cap. The single, engine-agnostic
    signal a description viewer follows, so it never subscribes to (or enumerates) the per-engine
    stylesheet signals; an edit to the *inactive* engine's stylesheet stays silent, since the
    effective render is unchanged."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # relay every render-affecting change into the one aggregate signal a viewer follows: the
        # engine and image-width cap pass straight through; a stylesheet edit only while its engine is
        # the active one (an inactive-engine edit changes nothing visible)
        self.engine_changed.connect(self.description_rendering_changed)  # type: ignore[attr-defined]
        self.max_image_width_changed.connect(self.description_rendering_changed)  # type: ignore[attr-defined]
        self.markdown_css_changed.connect(lambda *_: self.__on_css_changed("markdown"))  # type: ignore[attr-defined]
        self.mistletoe_css_changed.connect(lambda *_: self.__on_css_changed("mistletoe"))  # type: ignore[attr-defined]

    @property
    def css(self) -> str:
        """The stylesheet for whichever :attr:`engine` is currently selected."""
        return self.markdown_css if self.engine == "markdown" else self.mistletoe_css

    def __on_css_changed(self, engine: str) -> None:
        """Emit :attr:`description_rendering_changed` for ``engine``'s stylesheet edit, but only while
        it is the active engine.

        :param engine: the engine whose ``*_css`` just changed.
        """
        if self.engine == engine:
            self.description_rendering_changed.emit()

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.engine = cast(str, settings.value(ENGINE_KEY, DEFAULT_ENGINE, type=str))
        self.markdown_css = cast(str, settings.value(MARKDOWN_CSS_KEY, "", type=str))
        self.mistletoe_css = cast(str, settings.value(MISTLETOE_CSS_KEY, "", type=str))
        self.max_image_width = cast(int, settings.value(MAX_IMAGE_WIDTH_KEY, DEFAULT_MAX_IMAGE_WIDTH, type=int))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(ENGINE_KEY, self.engine)
        settings.setValue(MARKDOWN_CSS_KEY, self.markdown_css)
        settings.setValue(MISTLETOE_CSS_KEY, self.mistletoe_css)
        settings.setValue(MAX_IMAGE_WIDTH_KEY, self.max_image_width)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_markdown_rendering_settings() -> MarkdownRenderingSettings:
    """The single, process-wide `MarkdownRenderingSettings` instance, loaded from persistent
    storage on first call.

    :returns: the shared instance.
    """
    settings = MarkdownRenderingSettings()
    settings.load(persistent_settings())
    return settings
