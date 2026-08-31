"""Live, reactive description-editor settings shared by every open document's editor (#69):
line numbers, line endings, wrap long lines."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal

from .persistent_settings import persistent_settings

GROUP: Final = "description_editor"
SHOW_LINE_NUMBERS_KEY: Final = "show_line_numbers"
SHOW_LINE_ENDINGS_KEY: Final = "show_line_endings"
WRAP_LONG_LINES_KEY: Final = "wrap_long_lines"


class DescriptionEditorSettings(QObject):
    """App-wide description-editor settings (#69): the line-number margin, the visible end-of-line
    glyph, and wrapping long lines. All three default on, matching the behaviour `MarkdownEdit`
    hard-coded before this setting existed, so an existing install sees no change until one is
    actually flipped.

    A reactive ``QObject`` like its sibling
    :class:`~rehuco_agent.settings.markdown_rendering_settings.MarkdownRenderingSettings`, and for
    the same reason: every open document's description editor follows the aggregate
    :attr:`description_editor_changed`, so a Save on the settings page restyles already-open
    editors immediately, not just newly-opened ones. :func:`shared_description_editor_settings` is
    the single, process-wide instance every consumer reads/writes; a fresh instance per reader
    would defeat the live-update wiring entirely.

    :param parent: optional Qt parent.
    """

    show_line_numbers = SimpleProperty(True)
    """Whether a description editor shows its line-number margin."""

    show_line_endings = SimpleProperty(True)
    """Whether a description editor draws a visible end-of-line glyph."""

    wrap_long_lines = SimpleProperty(True)
    """Whether a description editor wraps long lines instead of scrolling horizontally."""

    description_editor_changed = Signal()
    """Fires whenever any of the three editor settings changes -- the single, aggregate signal an
    open editor follows, so it re-applies all three wholesale and never needs to know which moved."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.show_line_numbers_changed.connect(self.description_editor_changed)  # type: ignore[attr-defined]
        self.show_line_endings_changed.connect(self.description_editor_changed)  # type: ignore[attr-defined]
        self.wrap_long_lines_changed.connect(self.description_editor_changed)  # type: ignore[attr-defined]

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.show_line_numbers = cast(bool, settings.value(SHOW_LINE_NUMBERS_KEY, True, type=bool))
        self.show_line_endings = cast(bool, settings.value(SHOW_LINE_ENDINGS_KEY, True, type=bool))
        self.wrap_long_lines = cast(bool, settings.value(WRAP_LONG_LINES_KEY, True, type=bool))
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(SHOW_LINE_NUMBERS_KEY, self.show_line_numbers)
        settings.setValue(SHOW_LINE_ENDINGS_KEY, self.show_line_endings)
        settings.setValue(WRAP_LONG_LINES_KEY, self.wrap_long_lines)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_description_editor_settings() -> DescriptionEditorSettings:
    """The single, process-wide `DescriptionEditorSettings` instance, loaded from persistent
    storage on first call.

    :returns: the shared instance.
    """
    settings = DescriptionEditorSettings()
    settings.load(persistent_settings())
    return settings
