"""The tutorial's videos as a tree, with what its user has watched, starred and written about each
([[plugins#video-tree]], #572)."""

import textwrap
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, override

from borco_pyside.core import ConnectionList
from PySide6.QtCore import QAbstractItemModel, QModelIndex, QObject, QPersistentModelIndex, Qt
from PySide6.QtGui import QFont
from rehuco_core import (
    NoteLine,
    content_path,
    is_valid_content_key,
    missing_progress_keys,
    natural_path_sort_key,
    note_lines,
)

from ..glyphs import FAVORITE_GLYPH
from .clock_text import clock_text
from .files_progress import MISSING_TOOLTIP, FilesProgress, RowProgress
from .rehu_document_model import RehuDocumentModel

NAME_COLUMN: Final = 0
PROGRESS_COLUMN: Final = 1
FAVORITE_COLUMN: Final = 2
LENGTH_COLUMN: Final = 3
COLUMN_COUNT: Final = 4

HEADERS: Final = ("Name", "Progress", "", "Length")

KEY_ROLE: Final = Qt.ItemDataRole.UserRole + 1
"""The content key a row stands for: a video's own, a note line's link's, else its video's; ``None`` for a folder."""

SECONDS_ROLE: Final = Qt.ItemDataRole.UserRole + 2
"""The time a bookmark line seeks to; ``None`` for every other row."""

MISSING_ROLE: Final = Qt.ItemDataRole.UserRole + 3
"""Whether the video a row stands for has no file on disk now."""

KIND_ROLE: Final = Qt.ItemDataRole.UserRole + 4
"""What the row is: a :class:`NodeKind`."""

TOOLTIP_COLUMNS: Final = 80
"""How wide a note's tooltip wraps: a note can run to pages, and a tooltip must not cover the screen."""

TOOLTIP_LINES: Final = 8
"""How many wrapped lines of a note its tooltip shows before it ends in an ellipsis."""

ELLIPSIS: Final = "…"


class NodeKind(StrEnum):
    """What a row of the tree is."""

    FOLDER = "folder"
    VIDEO = "video"
    NOTE = "note"


@dataclass(eq=False)
class VideoTreeNode:
    """One row of the tree.

    :param kind: what the row is.
    :param name: what its first column reads.
    :param key: a video's content key, a folder's key below the tutorial, or ``None`` for a note line.
    :param missing: whether a video's file is gone.
    :param line: a note line's content.
    :param parent: the row above, ``None`` for the invisible root.
    """

    kind: NodeKind
    name: str = ""
    key: str | None = None
    missing: bool = False
    line: NoteLine | None = None
    parent: VideoTreeNode | None = None
    children: list[VideoTreeNode] = field(default_factory=list)

    @property
    def row(self) -> int:
        """Where the row stands among its siblings."""
        return self.parent.children.index(self) if self.parent is not None else 0

    def signature(self) -> tuple[object, ...]:
        """What makes this row and everything under it the same rows as another's, whatever they say.

        :returns: the row's identity, then its children's.
        """
        return (
            self.kind,
            self.name,
            self.key,
            self.missing,
            self.line,
            tuple(child.signature() for child in self.children),
        )


class VideoTreeModel(QAbstractItemModel):
    """A tutorial's videos in natural path order, under their folders, each with the lines of its notes beneath it.

    The rows are the videos on disk (:meth:`set_videos`) and the ones only the user's data remembers -- listed in
    their folder as *missing* ([[field-schema#video-notes]]). The progress words are the Files rows' own
    (:class:`~rehuco_agent.documents.files_progress.FilesProgress`). It holds no view state, so the dock and the
    player's overlay (#575) can each show the same instance.

    A change of progress redraws the rows in place; a change in what the rows are -- a note edited, a video forgotten
    -- resets the model.

    :param model: the document read for the user's data.
    :param parent: optional Qt parent.
    """

    def __init__(self, model: RehuDocumentModel, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__keys_on_disk: tuple[str, ...] | None = None
        self.__current: str | None = None
        self.__root = VideoTreeNode(NodeKind.FOLDER)
        self.__videos: dict[str, VideoTreeNode] = {}
        self.__progress: FilesProgress | None = None
        self.__connections: Final = ConnectionList()
        self.__connections.connect(model.progress_changed, self.refresh)
        self.__connections.connect(model.notes_changed, self.refresh)

    def detach(self) -> None:
        """Stop following the document, before this model is destroyed."""
        self.__connections.clear()

    @staticmethod
    def tooltip_text(text: str) -> str:
        """A note line as a tooltip: wrapped, and cut short with an ellipsis rather than covering the screen.

        :param text: the line.
        :returns: at most :data:`TOOLTIP_LINES` lines of :data:`TOOLTIP_COLUMNS` columns.
        """
        wrapped = textwrap.wrap(text, TOOLTIP_COLUMNS)
        if len(wrapped) <= TOOLTIP_LINES:
            return "\n".join(wrapped)
        kept = wrapped[:TOOLTIP_LINES]
        kept[-1] = kept[-1].rstrip() + ELLIPSIS
        return "\n".join(kept)

    # region What it shows

    def set_videos(self, keys_on_disk: tuple[str, ...] | None) -> None:
        """Take the videos the tutorial's folder holds now.

        :param keys_on_disk: their content keys, or ``None`` while they are not known -- which shows nothing.
        """
        self.__keys_on_disk = keys_on_disk
        self.refresh()

    def set_current(self, key: str | None) -> None:
        """Mark the video the player has loaded.

        :param key: its content key, or ``None`` for none.
        """
        before, self.__current = self.__current, key
        for changed in (before, key):
            node = self.__videos.get(changed) if changed is not None else None
            if node is not None:
                index = self.__index_of(node)
                self.dataChanged.emit(index, index.siblingAtColumn(COLUMN_COUNT - 1))

    @property
    def current_key(self) -> str | None:
        """The video marked as the player's."""
        return self.__current

    def index_of_video(self, key: str) -> QModelIndex:
        """Where a video's row is.

        :param key: its content key.
        :returns: the row's index, invalid when the tree has no such video.
        """
        node = self.__videos.get(key)
        return self.__index_of(node) if node is not None else QModelIndex()

    def refresh(self) -> None:
        """Read the document again: redraw in place when the rows are the same, else rebuild them."""
        rebuilt = self.__build()
        self.__progress = self.__snapshot()
        if rebuilt.signature() == self.__root.signature():
            self.__redraw(self.__root)
            return
        self.beginResetModel()
        self.__root = rebuilt
        self.__videos = self.__collect(rebuilt)
        self.endResetModel()

    def __snapshot(self) -> FilesProgress | None:
        """The user's watching as of now.

        :returns: it, or ``None`` when the videos on disk are not known.
        """
        path = self.__model.path
        if self.__keys_on_disk is None or path is None:
            return None
        return FilesProgress(
            path.parent,
            self.__model.progress_entries(),
            self.__model.measured_videos(),
            self.__keys_on_disk,
            self.__model.video_data_keys(),
        )

    def __build(self) -> VideoTreeNode:
        """The rows the document and the videos on disk make now.

        :returns: the invisible root, with the tree beneath it.
        """
        root = VideoTreeNode(NodeKind.FOLDER)
        on_disk = self.__keys_on_disk
        if on_disk is None or self.__model.path is None:
            return root
        path = self.__model.path
        gone = [
            key
            for key in missing_progress_keys(on_disk, self.__model.video_data_keys())
            if is_valid_content_key(path, key)
        ]
        present = set(on_disk)
        folders: dict[str, VideoTreeNode] = {"": root}
        for key in sorted({*on_disk, *gone}, key=natural_path_sort_key):
            parent = root
            *parts, _file = key.split("/")
            for depth, part in enumerate(parts, start=1):
                folder_key = "/".join(parts[:depth])
                if folder_key not in folders:
                    folders[folder_key] = self.__attach(parent, VideoTreeNode(NodeKind.FOLDER, part, folder_key))
                parent = folders[folder_key]
            self.__add_video(parent, content_path(path, key).stem, key, missing=key not in present)
        return root

    def __add_video(self, parent: VideoTreeNode, name: str, key: str, *, missing: bool) -> None:
        """Put a video under its folder, with a row for each line of its notes beneath it.

        :param parent: the folder's row.
        :param name: what the row reads: the file's name without its extension.
        :param key: the video's content key.
        :param missing: whether its file is gone.
        """
        video = self.__attach(parent, VideoTreeNode(NodeKind.VIDEO, name, key, missing=missing))
        for line in note_lines(self.__model.video_notes_of(key)):
            self.__attach(video, VideoTreeNode(NodeKind.NOTE, line.text, line.key, line=line))

    @staticmethod
    def __attach(parent: VideoTreeNode, node: VideoTreeNode) -> VideoTreeNode:
        """Put a row under another.

        :param parent: the row above.
        :param node: the row.
        :returns: ``node``.
        """
        node.parent = parent
        parent.children.append(node)
        return node

    @staticmethod
    def __collect(node: VideoTreeNode) -> dict[str, VideoTreeNode]:
        """Index the videos under a row by key.

        :param node: the row to start from.
        :returns: the videos' rows.
        """
        videos: dict[str, VideoTreeNode] = {}
        for child in node.children:
            if child.kind is NodeKind.VIDEO and child.key is not None:
                videos[child.key] = child
            videos.update(VideoTreeModel.__collect(child))
        return videos

    def __redraw(self, node: VideoTreeNode) -> None:
        """Tell the views every row under one may read differently now.

        :param node: the row whose children are redrawn, then theirs.
        """
        if not node.children:
            return
        parent = self.__index_of(node)
        self.dataChanged.emit(self.index(0, 0, parent), self.index(len(node.children) - 1, COLUMN_COUNT - 1, parent))
        for child in node.children:
            self.__redraw(child)

    def __index_of(self, node: VideoTreeNode) -> QModelIndex:
        """Where a row is.

        :param node: the row.
        :returns: its first column's index; invalid for the root.
        """
        if node is self.__root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row, 0, node)

    # endregion

    # region QAbstractItemModel

    @override
    def index(self, row: int, column: int, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> QModelIndex:
        owner = parent.internalPointer() if parent.isValid() else self.__root
        if not self.hasIndex(row, column, parent) or not isinstance(owner, VideoTreeNode):
            return QModelIndex()
        return self.createIndex(row, column, owner.children[row])

    @override
    def parent(self, child: QModelIndex | QPersistentModelIndex) -> QModelIndex:  # type: ignore[override]
        node = child.internalPointer() if child.isValid() else None
        if not isinstance(node, VideoTreeNode) or node.parent is None or node.parent is self.__root:
            return QModelIndex()
        return self.createIndex(node.parent.row, 0, node.parent)

    @override
    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.column() > 0:
            return 0
        owner = parent.internalPointer() if parent.isValid() else self.__root
        return len(owner.children) if isinstance(owner, VideoTreeNode) else 0

    @override
    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        del parent
        return COLUMN_COUNT

    @override
    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    @override
    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        node = index.internalPointer() if index.isValid() else None
        if not isinstance(node, VideoTreeNode):
            return None
        if role in (KIND_ROLE, KEY_ROLE, SECONDS_ROLE, MISSING_ROLE):
            return self.__row_role(node, role)
        return self.__cell_role(node, index.column(), role)

    # endregion

    # region What a row says

    def __row_role(self, node: VideoTreeNode, role: int) -> Any:
        """What a row answers to the roles callers ask it.

        :param node: the row.
        :param role: one of :data:`KIND_ROLE`, :data:`KEY_ROLE`, :data:`SECONDS_ROLE` and :data:`MISSING_ROLE`.
        :returns: the answer.
        """
        if role == KIND_ROLE:
            return node.kind
        if role == KEY_ROLE:
            return self.__target_key(node)
        if role == SECONDS_ROLE:
            return node.line.seconds if node.line is not None else None
        return self.__is_missing(node)

    def __cell_role(self, node: VideoTreeNode, column: int, role: int) -> Any:
        """What a cell answers to the roles a view draws it with.

        :param node: the row.
        :param column: the column.
        :param role: the role.
        :returns: the answer, ``None`` for a role the cell has nothing for.
        """
        if role == Qt.ItemDataRole.DisplayRole:
            return self.__text(node, column)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self.__tooltip(node, column)
        if role == Qt.ItemDataRole.FontRole:
            return self.__font(node, column)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self.__alignment(column)
        return None

    def __target_key(self, node: VideoTreeNode) -> str | None:
        """The video a row stands for.

        :param node: the row.
        :returns: a video's key; a note line's link's, else its video's; ``None`` for a folder.
        """
        if node.kind is NodeKind.VIDEO:
            return node.key
        if node.kind is NodeKind.NOTE and node.parent is not None:
            return node.key if node.key is not None else node.parent.key
        return None

    def __is_missing(self, node: VideoTreeNode) -> bool:
        """Whether the video a row stands for has no file now.

        :param node: the row.
        :returns: ``True`` for a missing video, and for a note line whose video is missing or not in the tutorial.
        """
        if node.kind is NodeKind.FOLDER:
            return False
        key = self.__target_key(node)
        target = self.__videos.get(key) if key is not None else None
        return target is None or target.missing

    def __row_progress(self, node: VideoTreeNode) -> RowProgress | None:
        """What a folder's or video's row ends with.

        :param node: the row.
        :returns: the words, or ``None`` for a row that has none.
        """
        progress, path = self.__progress, self.__model.path
        if progress is None or path is None or node.key is None:
            return None
        if node.kind is NodeKind.FOLDER:
            return progress.for_folder(path.parent / node.key)
        if node.kind is NodeKind.VIDEO:
            return progress.for_video(node.key, missing=node.missing)
        return None

    def __length(self, node: VideoTreeNode) -> float | None:
        """A video's length.

        :param node: the row.
        :returns: the seconds, or ``None`` when not known.
        """
        progress = self.__progress
        if node.kind is not NodeKind.VIDEO or node.key is None or progress is None:
            return None
        facts = progress.measured.get(node.key)
        entry = progress.entries.get(node.key)
        length = facts.duration if facts is not None else (entry.duration if entry is not None else None)
        return length if length is not None and length > 0 else None

    def __text(self, node: VideoTreeNode, column: int) -> str:
        """What a cell reads.

        :param node: the row.
        :param column: the column.
        :returns: the text, empty for a cell with none.
        """
        if column == NAME_COLUMN:
            return node.name
        if column == PROGRESS_COLUMN:
            progress = self.__row_progress(node)
            return progress.text if progress is not None else ""
        if column == LENGTH_COLUMN:
            length = self.__length(node)
            return clock_text(round(length * 1000)) if length is not None else ""
        if node.kind is NodeKind.VIDEO and node.key is not None and self.__model.is_favorite(node.key):
            return FAVORITE_GLYPH.codepoint
        return ""

    def __tooltip(self, node: VideoTreeNode, column: int) -> str:
        """What hovering a cell says.

        :param node: the row.
        :param column: the column.
        :returns: the text, empty for none.
        """
        if node.kind is NodeKind.NOTE:
            return self.tooltip_text(node.name)
        if node.kind is NodeKind.VIDEO and column == NAME_COLUMN:
            return f"{node.key}\n{MISSING_TOOLTIP}" if node.missing else node.key or ""
        if column == PROGRESS_COLUMN:
            progress = self.__row_progress(node)
            return progress.tooltip if progress is not None else ""
        return ""

    def __font(self, node: VideoTreeNode, column: int) -> QFont | None:
        """The font of a cell that does not use the view's: a video's name is bold for the player's and italic when
        missing, and the star is a glyph of the icon font.

        :param node: the row.
        :param column: the column.
        :returns: the font, or ``None`` for the view's own.
        """
        if column == FAVORITE_COLUMN:
            return QFont(FAVORITE_GLYPH.family)
        if column != NAME_COLUMN or node.kind is not NodeKind.VIDEO:
            return None
        font = QFont()
        font.setBold(node.key == self.__current)
        font.setItalic(node.missing)
        return font

    @staticmethod
    def __alignment(column: int) -> int | None:
        """How a cell is aligned.

        :param column: the column.
        :returns: the alignment flags, or ``None`` for the view's own.
        """
        if column == FAVORITE_COLUMN:
            return int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        if column in (PROGRESS_COLUMN, LENGTH_COLUMN):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    # endregion
