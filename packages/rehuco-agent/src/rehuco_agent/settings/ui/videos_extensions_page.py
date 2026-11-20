"""Videos / Extensions settings page: which files a scan measures as videos (#225, #692)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import VIDEO_EXTENSIONS

from ...item_action_icons import apply_item_action_icons
from ..persistent_settings import persistent_settings
from ..videos_settings import VideosSettings, normalize_extensions, shared_videos_settings
from .videos_extensions_page_ui import Ui_VideosExtensionsPage


class VideosExtensionsPage(QWidget):
    """Which files inside a tutorial are measured as videos -- a `StringListEditor` (#231) wearing this app's icons,
    exactly as the content-image list on `ImagesFilesPage` is.

    A sibling of `VideosProbePage` and `VideosPlayerPage` under the "Videos" group (#692), over the one
    `VideosSettings`: it stages and saves only the extension list. Staged in the widget until :meth:`save_changes`
    writes it and persists it.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_VideosExtensionsPage()
        self.__ui.setupUi(self)
        self.__ui.extensions_editor.defaults = VIDEO_EXTENSIONS
        apply_item_action_icons(self.__ui.extensions_editor)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether the staged extension list differs from what the shared settings currently hold."""
        # normalized before the comparison, so a row saving would drop anyway is not yet a change
        # and auto-apply does not tear a fresh insert out from under its open cell (#53)
        return normalize_extensions(self.__ui.extensions_editor.values) != shared_videos_settings().video_extensions

    def save_changes(self) -> None:
        """Push the staged extension list into the shared settings object and persist it.

        The editor is refilled from the saved set afterward rather than left as typed: normalization can change the
        list -- a blank or duplicated entry is dropped, ``MP4`` becomes ``.mp4``, and emptying it restores the
        shipped formats -- and a page still showing what was typed would disagree with what the next scan measures.
        """
        settings = shared_videos_settings()
        settings.extensions = normalize_extensions(self.__ui.extensions_editor.values)
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged extension list, re-seeding the editor from the shared settings."""
        self.__ui.extensions_editor.values = shared_videos_settings().video_extensions

    def seed_defaults(self) -> None:
        """Stage the factory list: what an unloaded `VideosSettings` resolves to (#342)."""
        self.__ui.extensions_editor.values = VideosSettings().video_extensions
