"""The Tree sub-dock: the tutorial's videos as a tree, with the progress, stars and notes of each
([[plugins#video-tree]], #572)."""

import logging
from functools import partial
from pathlib import Path
from typing import Any, Final, override

import cbor2
from borco_pyside.widgets import RowBandDelegate
from PySide6.QtCore import QModelIndex, QPoint, Signal
from PySide6.QtGui import QAction, QShowEvent
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QMenu, QWidget
from rehuco_core import Relocation, tutorial_video_keys
from rehuco_core.access import KeyRelocation, ResourceKey

from ..resource_events import ResourceEvents
from ..settings.excluded_files_settings import shared_excluded_files_settings
from ..settings.videos_settings import shared_videos_settings
from .latest_runner import LatestRunner
from .rehu_document_model import RehuDocumentModel
from .video_row_actions import VideoRowActions
from .video_tree_model import (
    FAVORITE_COLUMN,
    KEY_ROLE,
    KIND_ROLE,
    LENGTH_COLUMN,
    MISSING_ROLE,
    NAME_COLUMN,
    PROGRESS_COLUMN,
    SECONDS_ROLE,
    NodeKind,
    VideoTreeModel,
)
from .video_tree_view_ui import Ui_VideoTreeView

LOG: Final = logging.getLogger(__name__)

SELECTED_STATE_KEY: Final = "selected"
CLOSED_STATE_KEY: Final = "closed"
"""The keys of a tree's saved state: its selected row, and the rows the reader closed."""

LIST_TAG: Final = "list"
"""What the runner that lists the tutorial's videos answers under."""


class VideoTreeView(QWidget):  # pylint: disable=too-many-instance-attributes
    """One document's tree of videos.

    It lists the tutorial's videos the way the player's playlist does, so the two agree on the order, and shows them
    through a :class:`~rehuco_agent.documents.video_tree_model.VideoTreeModel`. **A hidden dock reads nothing**: a
    listing asked for while hidden only flags the tree stale, and :meth:`showEvent` catches it up. A double-click
    reports the video to play and, on a bookmark line, the time to start it at; a missing video reports nothing.

    :param model: the document.
    :param parent: optional Qt parent.
    :param resource_events: the app's change feed to follow; a private one when not given.
    :param tree: the rows to show when another view's are to be shown again (#575); that view detaches them, and a
        view of its own is made when not given.
    :param compact: whether to show the name and the progress alone, with no header: the player's ``T`` panel.
    """

    video_activated = Signal(str, object)
    """Emitted ``(content key, seconds or None)`` for a double-click on a video, or on a line of its notes: the video
    to play and where to start it, ``None`` for where it was left. The document decides what plays it."""

    video_clicked = Signal(str)
    """Emitted with the content key of the video a click landed on -- its row, or a bookmark of its notes -- present
    or missing (#573): the notes dock shows that video's notes, without the player loading it."""

    def __init__(
        self,
        model: RehuDocumentModel,
        parent: QWidget | None = None,
        resource_events: ResourceEvents | None = None,
        *,
        tree: VideoTreeModel | None = None,
        compact: bool = False,
    ) -> None:
        super().__init__(parent)
        self.__document: Final = model
        self.__events: Final = resource_events if resource_events is not None else ResourceEvents(parent=self)
        self.__stale = True
        self.__collapsed: set[str] = set()
        """The videos and folders the reader closed, by key; everything else is open."""
        self.__restoring = False
        self.__held_item: tuple[str, str, object] | None = None
        """The row the session remembers as selected, until the rows are listed ([[plugins#session-restore]])."""
        self.__selected: str | None = None
        """The video selected as the tree is about to be rebuilt, which the reset clears."""
        self.__scroll_pending = False
        """Whether the current video is to be brought into view once the rows are listed: it was asked for before."""
        self.__owns_tree: Final = tree is None

        self.__ui: Final = Ui_VideoTreeView()
        self.__ui.setupUi(self)
        self.__tree: Final = tree if tree is not None else VideoTreeModel(model, self)
        self.__actions: Final = VideoRowActions(model, self)
        self.__lister: Final = LatestRunner(self)
        self.__lister.read.connect(self.__on_listed)

        view = self.__ui.tree_view
        view.setModel(self.__tree)
        view.setItemDelegate(RowBandDelegate(view))
        header = view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        for column in (PROGRESS_COLUMN, FAVORITE_COLUMN, LENGTH_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        if compact:
            view.setHeaderHidden(True)
            for column in (FAVORITE_COLUMN, LENGTH_COLUMN):
                view.setColumnHidden(column, True)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.doubleClicked.connect(self.__on_double_clicked)
        view.clicked.connect(self.__on_clicked)
        view.customContextMenuRequested.connect(self.__on_context_menu)
        view.selectionModel().selectionChanged.connect(self.__update_actions)
        view.expanded.connect(self.__on_expanded)
        view.collapsed.connect(self.__on_collapsed)
        # a redraw in place changes what the ticks say: a video viewed to its end, a star set from the Files dock
        self.__tree.dataChanged.connect(self.__update_actions)
        self.__tree.modelAboutToBeReset.connect(self.__on_about_to_reset)
        self.__tree.modelReset.connect(self.__on_reset)
        model.path_changed.connect(self.refresh)  # type: ignore[attr-defined]
        model.active_block_changed.connect(self.refresh)
        self.__events.moved.connect(self.__on_moved)
        self.__events.changed.connect(self.__on_files_changed)
        self.__events.folder_changed.connect(self.__on_folder_changed)
        self.__events.root_stale.connect(self.refresh)
        if tree is not None:
            # rows listed before this view was made reset nothing here: opened as a reset opens them
            self.__on_reset()
        self.__update_actions()

    def detach(self) -> None:
        """Stop following the document and the app's change feed, before this view is destroyed."""
        self.__lister.discard()
        if self.__owns_tree:
            self.__tree.detach()
        self.__document.path_changed.disconnect(self.refresh)  # type: ignore[attr-defined]
        self.__document.active_block_changed.disconnect(self.refresh)
        self.__events.moved.disconnect(self.__on_moved)
        self.__events.changed.disconnect(self.__on_files_changed)
        self.__events.folder_changed.disconnect(self.__on_folder_changed)
        self.__events.root_stale.disconnect(self.refresh)

    @property
    def tree(self) -> VideoTreeModel:
        """The model the view shows, which the player's overlay shows too (#575)."""
        return self.__tree

    @property
    def title_bar_actions(self) -> list[QAction]:
        """*Favorite*, *Viewed* and *Forget*, for the dock's title bar; each shows only where it applies."""
        return list(self.__actions.actions)

    @property
    def row_actions(self) -> VideoRowActions:
        """The actions on the selected row."""
        return self.__actions

    # region Reading

    def refresh(self, *_args: object) -> None:
        """List the tutorial's videos again, off the GUI thread; nothing while hidden.

        :param _args: whatever value the triggering signal carried; unused.
        """
        if not self.isVisible():
            self.__stale = True
            return
        self.__stale = False
        path = self.__document.path
        if path is None or not self.__document.watches_progress:
            self.__lister.discard()
            self.__tree.set_videos(None)
            return
        self.__lister.start(
            LIST_TAG,
            partial(
                tutorial_video_keys,
                path,
                video_extensions=shared_videos_settings().video_extensions,
                excluded_patterns=shared_excluded_files_settings().excluded_file_patterns,
            ),
        )
        # a renamed video takes its data with it as the files are listed; a no-op where nothing moved
        self.__document.reattach_renamed_progress()

    @override
    def showEvent(self, event: QShowEvent) -> None:
        """Catch up a listing deferred while hidden.

        :param event: the Qt show event, forwarded to the base class.
        """
        super().showEvent(event)
        if self.__stale:
            self.refresh()

    def __on_listed(self, _tag: str, result: object) -> None:
        """Show the videos the listing found.

        :param _tag: what the list was for.
        :param result: the videos' content keys, or the error listing them ended in.
        """
        if isinstance(result, Exception):
            LOG.warning("The tutorial's videos could not be listed for the tree: %s", result)
            self.__tree.set_videos(None)
            return
        self.__tree.set_videos(tuple(str(key) for key in result))  # type: ignore[attr-defined]

    def __on_moved(self, moved: KeyRelocation) -> None:
        """Read again after a rename that touched the tutorial's folder.

        :param moved: the rename's executed plan.
        """
        path = self.__document.path
        relocation = moved.to_local()
        if path is not None and relocation.touches(path.parent):
            self.refresh()

    def __on_files_changed(self, keys: tuple[ResourceKey, ...]) -> None:
        """Read again when a file beneath the tutorial's folder was written, created or deleted.

        :param keys: the files that changed.
        """
        if any(self.__is_beneath(key.path) for key in keys):
            self.refresh()

    def __on_folder_changed(self, directory: ResourceKey) -> None:
        """Read again when a folder's listing beneath the tutorial's folder changed.

        :param directory: the folder whose listing changed.
        """
        if self.__is_beneath(directory.path):
            self.refresh()

    def __is_beneath(self, path: Path) -> bool:
        """Whether ``path`` is the tutorial's folder or anywhere under it.

        :param path: the announced path.
        :returns: whether a listing of the tutorial could show it, or show it differently.
        """
        record = self.__document.path
        if record is None:
            return False
        folder_parts = Relocation.path_parts(record.parent)
        return Relocation.path_parts(path)[: len(folder_parts)] == folder_parts

    # endregion

    # region What the reader sees

    def save_state(self) -> bytes:
        """Encode the selected row and the rows the reader closed, for the dock's entry in the layout
        ([[plugins#session-restore]]).

        :returns: the state, restorable by :meth:`restore_state`.
        """
        held = self.__held_item
        return cbor2.dumps(
            {
                SELECTED_STATE_KEY: list(held) if held is not None else self.__selected_item(),
                CLOSED_STATE_KEY: sorted(self.__collapsed),
            }
        )

    def restore_state(self, state: bytes) -> None:
        """Restore what :meth:`save_state` encoded; the selected row waits for the rows to be listed. Nothing follows
        the selection coming back: only a click shows a video's notes.

        :param state: the blob; one that cannot be read leaves everything as it is, and each value costs only itself.
        """
        try:
            values: Any = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return
        if not isinstance(values, dict):
            return
        closed = values.get(CLOSED_STATE_KEY)
        if isinstance(closed, list):
            self.__collapsed = {key for key in closed if isinstance(key, str)}
            self.__close_rows()
        selected = values.get(SELECTED_STATE_KEY)
        if isinstance(selected, list) and len(selected) == 3 and all(isinstance(part, str) for part in selected[:2]):
            self.__held_item = tuple(selected)  # type: ignore[assignment]
            self.__select_held_item()

    def __selected_item(self) -> list[object] | None:
        """What the selected row is, in a form that outlives the rows.

        :returns: its kind, its video's or folder's key, and a note line's time; ``None`` with nothing selected.
        """
        indexes = self.__ui.tree_view.selectionModel().selectedRows()
        if not indexes:
            return None
        index = indexes[0]
        kind = index.data(KIND_ROLE)
        if kind == NodeKind.FOLDER:
            return [NodeKind.FOLDER.value, self.__folder_key(index), None]
        if kind == NodeKind.NOTE:
            return [NodeKind.NOTE.value, str(index.parent().data(KEY_ROLE)), index.data(SECONDS_ROLE)]
        return [NodeKind.VIDEO.value, str(index.data(KEY_ROLE)), None]

    def __index_of_item(self, kind: str, key: str, seconds: object) -> QModelIndex:
        """Find a row :meth:`__selected_item` described.

        :param kind: its kind.
        :param key: its video's or folder's key.
        :param seconds: a note line's time.
        :returns: the row, invalid when it is not there.
        """
        if kind == NodeKind.FOLDER.value:
            return self.__folder_index(key)
        video = self.__tree.index_of_video(key)
        if kind != NodeKind.NOTE.value or not video.isValid():
            return video
        rows = (self.__tree.index(row, 0, video) for row in range(self.__tree.rowCount(video)))
        return next((row for row in rows if row.data(SECONDS_ROLE) == seconds), QModelIndex())

    def __select_held_item(self) -> None:
        """Select the row the session remembers, once there are rows to look in; one no longer there is let go."""
        held = self.__held_item
        if held is None or self.__tree.rowCount() == 0:
            return
        self.__held_item = None
        index = self.__index_of_item(*held)
        if index.isValid() and self.__is_shown(index):
            self.__ui.tree_view.setCurrentIndex(index)

    def set_current(self, key: str | None) -> None:
        """Mark the video the player has loaded and bring it into view.

        :param key: its content key, or ``None`` for none.
        """
        self.__tree.set_current(key)
        self.scroll_to_current()

    def scroll_to_current(self) -> None:
        """Bring the current video into view; once the rows are listed, when they are not yet."""
        key = self.__tree.current_key
        self.__scroll_pending = key is not None and not self.__tree.index_of_video(key).isValid()
        self.__show_current()

    def __show_current(self) -> None:
        """Open the way to the current video and scroll to it."""
        key = self.__tree.current_key
        index = self.__tree.index_of_video(key) if key is not None else QModelIndex()
        if not index.isValid():
            return
        view = self.__ui.tree_view
        self.__restoring = True
        try:
            parent = index.parent()
            while parent.isValid():
                view.expand(parent)
                parent = parent.parent()
        finally:
            self.__restoring = False
        view.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    def __on_about_to_reset(self) -> None:
        """Note the selected video before the reset clears the selection."""
        self.__selected = self.__selected_key()

    def __on_reset(self) -> None:
        """Open everything but what the reader closed, and keep the selected video selected -- the reader's place,
        not the player's: the current video is brought into view when it changes, never by a rebuild."""
        view = self.__ui.tree_view
        selected = self.__selected
        self.__restoring = True
        try:
            view.expandAll()
        finally:
            self.__restoring = False
        self.__close_rows()
        if self.__scroll_pending:
            # the player's video was asked for before the rows were listed: shown once they are, and never by a rebuild
            self.__scroll_pending = False
            self.__show_current()
        if selected is not None:
            index = self.__tree.index_of_video(selected)
            # selecting a row under a closed folder would open it again: a row the reader cannot see is let go
            if index.isValid() and self.__is_shown(index):
                view.setCurrentIndex(index)
        self.__select_held_item()
        self.__update_actions()

    def __close_rows(self) -> None:
        """Close the rows the reader closed."""
        self.__restoring = True
        try:
            for key in self.__collapsed:
                index = self.__tree.index_of_video(key)
                if not index.isValid():
                    index = self.__folder_index(key)
                if index.isValid():
                    self.__ui.tree_view.collapse(index)
        finally:
            self.__restoring = False

    def __is_shown(self, index: QModelIndex) -> bool:
        """Whether every folder above a row is open.

        :param index: the row.
        :returns: whether the row is in view, scrolling aside.
        """
        parent = index.parent()
        while parent.isValid():
            if not self.__ui.tree_view.isExpanded(parent):
                return False
            parent = parent.parent()
        return True

    def __folder_index(self, folder_key: str, parent: QModelIndex | None = None) -> QModelIndex:
        """Where a folder's row is.

        :param folder_key: the folder's key below the tutorial.
        :param parent: where to look, the top by default.
        :returns: the row's index, invalid when there is no such folder.
        """
        parent = parent if parent is not None else QModelIndex()
        for row in range(self.__tree.rowCount(parent)):
            index = self.__tree.index(row, NAME_COLUMN, parent)
            if index.data(KIND_ROLE) != NodeKind.FOLDER:
                continue
            if self.__folder_key(index) == folder_key:
                return index
            found = self.__folder_index(folder_key, index)
            if found.isValid():
                return found
        return QModelIndex()

    def __folder_key(self, index: QModelIndex) -> str:
        """A folder row's key: its names from the top, joined.

        :param index: the folder's index.
        :returns: the key.
        """
        names = []
        current = index
        while current.isValid():
            names.append(str(current.data()))
            current = current.parent()
        return "/".join(reversed(names))

    def __on_expanded(self, index: QModelIndex) -> None:
        """Remember the reader opened a row.

        :param index: the row.
        """
        if not self.__restoring:
            self.__collapsed.discard(self.__closable_key(index))

    def __on_collapsed(self, index: QModelIndex) -> None:
        """Remember the reader closed a row.

        :param index: the row.
        """
        if not self.__restoring:
            self.__collapsed.add(self.__closable_key(index))

    def __closable_key(self, index: QModelIndex) -> str:
        """What a row that can be closed is remembered by.

        :param index: a folder or a video.
        :returns: the video's key, or the folder's.
        """
        if index.data(KIND_ROLE) == NodeKind.VIDEO:
            return str(index.data(KEY_ROLE))
        return self.__folder_key(index)

    # endregion

    # region Acting on a row

    def __selected_key(self) -> str | None:
        """The video the selected row stands for.

        :returns: its key, or ``None`` when nothing is selected or the row is a folder.
        """
        video = self.__selected_video()
        key = video.data(KEY_ROLE) if video.isValid() else None
        return key if isinstance(key, str) else None

    def __selected_video(self) -> QModelIndex:
        """The video row the selection stands for: the selected row, or a selected note line's video.

        :returns: the row's index, invalid when nothing is selected or a folder is.
        """
        indexes = self.__ui.tree_view.selectionModel().selectedRows()
        index = indexes[0] if indexes else QModelIndex()
        return index.parent() if index.data(KIND_ROLE) == NodeKind.NOTE else index

    def __update_actions(self, *_args: object) -> None:
        """Show what can be done to the selected row.

        :param _args: whatever the triggering signal carried; unused.
        """
        video = self.__selected_video()
        key = video.data(KEY_ROLE) if video.isValid() else None
        self.__actions.show_for(key if isinstance(key, str) else None, missing=bool(video.data(MISSING_ROLE)))

    def __on_context_menu(self, position: QPoint) -> None:
        """Offer the actions of the row under the cursor: it is selected first. No menu for a row with none.

        :param position: where the click landed, in the viewport's coordinates.
        """
        view = self.__ui.tree_view
        index = view.indexAt(position)
        if index.isValid():
            view.setCurrentIndex(index)
        self.__update_actions()
        actions = [action for action in self.__actions.actions if action.isVisible()]
        if not actions:
            return
        menu = QMenu(self)
        try:
            menu.addActions(actions)
            menu.exec(view.viewport().mapToGlobal(position))
        finally:
            menu.deleteLater()

    def __on_clicked(self, index: QModelIndex) -> None:
        """Report the video of the row the reader clicked, for its notes: a bookmark's is the video whose notes hold
        it, whichever video its link names; a folder names none.

        :param index: the clicked row.
        """
        kind = index.data(KIND_ROLE)
        key = (index.parent() if kind == NodeKind.NOTE else index).data(KEY_ROLE)
        if kind != NodeKind.FOLDER and isinstance(key, str):
            self.video_clicked.emit(key)

    def __on_double_clicked(self, index: QModelIndex) -> None:
        """Play the video of the row the reader double-clicked, from the bookmark's time on a bookmark line.

        :param index: the activated row.
        """
        kind = index.data(KIND_ROLE)
        if kind == NodeKind.FOLDER:
            self.__ui.tree_view.setExpanded(index, not self.__ui.tree_view.isExpanded(index))
            return
        key = index.data(KEY_ROLE)
        if not isinstance(key, str) or index.data(MISSING_ROLE):
            return
        self.video_activated.emit(key, index.data(SECONDS_ROLE))

    # endregion
