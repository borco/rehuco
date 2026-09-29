"""The maximized viewer the screenshots editor opens: the lightbox, plus curating keys (#370).

`ImageLightbox` stays read-only and stays the default everywhere else -- the document's strip, the Files
sub-dock, the Content Images dock. This subclass is what only the screenshots editor
(`~rehuco_agent.fields.widgets.image_selector.ImageSelector`) opens, over every one of its rows: it
names where each image stands in the curation, and turns Del / Space / C / Ctrl-moves into requests
the editor carries out. It never deletes, renames or reorders anything itself.
"""

from pathlib import Path
from typing import Any, Final, override

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QWidget

from .image_lightbox import ImageLightbox, ImageViewerMode
from .image_selector import MoveDirection
from .image_source import ImageDescription, ImageVisibility, ScreenshotKey, ScreenshotRowsImageSource

MOVE_KEYS: Final = {
    Qt.Key.Key_Home: MoveDirection.TOP,
    Qt.Key.Key_Up: MoveDirection.UP,
    Qt.Key.Key_Down: MoveDirection.DOWN,
    Qt.Key.Key_End: MoveDirection.BOTTOM,
}
"""The keys that, with Ctrl held, move the current image -- the editor list's own ordering keys."""


class CuratingImageLightbox(ImageLightbox):
    """An `ImageLightbox` over the screenshots editor's rows that curates them by request (#370).

    **What it adds** is exactly two things. A bold line in both info boxes -- the current image's and
    the hovered thumbnail's -- reading **visible**, **hidden** or **unconverted**. And the editor list's
    own keys, each turned into a request that carries the image's path:

    * Del -- :attr:`delete_requested`;
    * Space -- :attr:`visibility_toggle_requested`;
    * C -- :attr:`convert_requested`;
    * Ctrl+Home / Ctrl+Up / Ctrl+Down / Ctrl+End -- :attr:`move_requested`, with a `MoveDirection`.

    An **unconverted** image answers C and Del only, and a numbered one every key but C -- the rule the
    list's check box and buttons follow, decided here from the image's own visibility. Every other
    refusal (either end of the numbered set, a locked document) is the editor's: its actions are
    disabled, and a request that reaches one is dropped there. Every other key is the base viewer's,
    including bare Home / End, which the Ctrl moves are matched ahead of.

    **The owner re-points it** after every request lands, like any viewer (:meth:`set_source`): the
    rows' keys are the files themselves (`ScreenshotKey`), so it stays on a moved or converted image at
    its new position, and on whatever took a deleted one's place.

    :param source: the editor's rows (required) -- the only source that says where an image stands.
    :param current: the position to open on.
    :param mode: which surface to paint on.
    :param document: the open document this viewer belongs to.
    :param options: every keyword option `ImageLightbox` takes, passed straight through.
    """

    delete_requested = Signal(Path)
    """Fires with the current image's path on Del, for the editor to delete as its own Delete does."""

    visibility_toggle_requested = Signal(Path)
    """Fires with the current image's path on Space, for the editor to show or hide it."""

    convert_requested = Signal(Path)
    """Fires with the current image's path on C, for the editor to take it into the numbered set."""

    move_requested = Signal(Path, str)
    """Fires with the current image's path and a `MoveDirection` value on a Ctrl move."""

    def __init__(
        self,
        source: ScreenshotRowsImageSource,
        current: int,
        mode: ImageViewerMode,
        document: QWidget,
        **options: Any,
    ) -> None:
        super().__init__(source, current, mode, document, **options)

    @override
    def _info_emphasis(self, description: ImageDescription) -> str | None:
        """Where the image stands in the curation, when its source says.

        :param description: the image's description.
        :returns: ``visible``, ``hidden`` or ``unconverted``; ``None`` for a source that does not curate.
        """
        return description.visibility.value if description.visibility is not None else None

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Turn the curating keys into requests; hand every other key to the base viewer.

        :param event: the Qt key event.
        """
        path = self.__current_path()
        if path is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        unconverted = self.__current_visibility() is ImageVisibility.UNCONVERTED
        # an unconverted image takes C and Del only, a numbered one everything but C; a key that does
        # not apply is still this viewer's, swallowed rather than handed to the base as something else
        if ctrl and key in MOVE_KEYS:
            if not unconverted:
                self.move_requested.emit(path, MOVE_KEYS[Qt.Key(key)].value)
        elif not ctrl and key == Qt.Key.Key_Delete:
            self.delete_requested.emit(path)
        elif not ctrl and key == Qt.Key.Key_Space:
            if not unconverted:
                self.visibility_toggle_requested.emit(path)
        elif not ctrl and key == Qt.Key.Key_C:
            if unconverted:
                self.convert_requested.emit(path)
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def __current_path(self) -> Path | None:
        """The current image's path, as the rows named it.

        :returns: the path, or ``None`` on an empty set.
        """
        key = self.current_key
        return key.path if isinstance(key, ScreenshotKey) else None

    def __current_visibility(self) -> ImageVisibility | None:
        """Where the current image stands in the curation.

        :returns: its visibility, or ``None`` on an empty set.
        """
        if len(self.source) == 0:
            return None
        return self.source.describe(self.current_index).visibility
