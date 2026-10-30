"""What can be done to one video of a tutorial, as one set of actions for every dock that lists them
([[plugins#files-subdock]], [[plugins#video-tree]], #572)."""

from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from .rehu_document_model import RehuDocumentModel

FORGET_ICON_RESOURCE: Final = ":/icons/items_delete.svg"


class VideoRowActions(QObject):
    """*Favorite*, *Viewed* and *Forget*, shown only where they apply and acting on the video last shown for.

    The Files dock and the Tree dock each own one, so the two offer the same commands under the same words: a video
    of the tutorial can be starred and marked viewed, present or missing, and a missing one can be forgotten. Nothing
    is disabled in place of hidden -- a row an action does not apply to simply does not show it.

    :param model: the document the actions write through.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__key: str | None = None
        self.__missing = False
        self.__favorite: Final = self.__make_action("Favorite", "Star the selected video, or not.", checkable=True)
        self.__viewed: Final = self.__make_action(
            "Viewed", "Mark the selected video as watched to the end, or not.", checkable=True
        )
        self.__forget: Final = self.__make_action(
            "Forget", "Forget what is kept for the selected missing video: its progress, notes and star."
        )
        ActionIconThemeHandler(self.__forget, FORGET_ICON_RESOURCE)
        self.__favorite.triggered.connect(self.__on_favorite_triggered)
        self.__viewed.triggered.connect(self.__on_viewed_triggered)
        self.__forget.triggered.connect(self.__on_forget_triggered)
        self.show_for(None, missing=False)

    def __make_action(self, text: str, tooltip: str, *, checkable: bool = False) -> QAction:
        """A hidden action of this object's.

        :param text: its text.
        :param tooltip: what hovering it says.
        :param checkable: whether it is a toggle.
        :returns: the action.
        """
        action = QAction(text, self)
        action.setToolTip(tooltip)
        action.setCheckable(checkable)
        action.setVisible(False)
        return action

    @property
    def favorite_action(self) -> QAction:
        """Stars the video, or takes the star off; checked as it is. Shown for any video of the tutorial."""
        return self.__favorite

    @property
    def viewed_action(self) -> QAction:
        """Marks the video watched to the end, or not; checked as it is. Shown for any video of the tutorial."""
        return self.__viewed

    @property
    def forget_action(self) -> QAction:
        """Forgets everything kept about the video. Shown only for a missing one."""
        return self.__forget

    @property
    def actions(self) -> tuple[QAction, QAction, QAction]:
        """The three, in the order every surface lists them."""
        return self.__favorite, self.__viewed, self.__forget

    @property
    def any_visible(self) -> bool:
        """Whether any action applies to the video shown for."""
        return any(action.isVisible() for action in self.actions)

    def show_for(self, key: str | None, *, missing: bool) -> None:
        """Show the actions that apply to a video, ticked as it is, and aim them at it.

        :param key: the video's content key, or ``None`` for a row that is no video.
        :param missing: whether the video's file is gone.
        """
        self.__key = key
        self.__missing = missing
        has_video = key is not None
        self.__favorite.setVisible(has_video)
        self.__viewed.setVisible(has_video)
        self.__forget.setVisible(has_video and missing)
        if key is not None:
            entry = self.__model.progress_of(key)
            self.__favorite.setChecked(self.__model.is_favorite(key))
            self.__viewed.setChecked(entry is not None and entry.viewed)

    def __on_favorite_triggered(self, starred: bool) -> None:
        """Star or unstar the video.

        :param starred: the new state.
        """
        if self.__key is not None:  # pragma: no branch -- a hidden action cannot be triggered
            self.__model.record_notes(favorites={self.__key: starred})

    def __on_viewed_triggered(self, viewed: bool) -> None:
        """Record the video's *viewed* flag as the action now says, keeping the position it was left at.

        :param viewed: the new state.
        """
        if self.__key is None:  # pragma: no cover -- a hidden action cannot be triggered
            return
        entry = self.__model.progress_of(self.__key)
        self.__model.record_progress(self.__key, entry.position if entry is not None else 0.0, None, viewed=viewed)

    def __on_forget_triggered(self) -> None:
        """Forget what is kept about the missing video -- and only a missing one, whatever surface triggered it."""
        if self.__key is not None and self.__missing:
            self.__model.forget_progress(self.__key)
