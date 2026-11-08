"""The Add Roots dialog's staging list: the paths picked, each with the line its last plan made (#578)."""

from collections.abc import Iterable, Sequence
from dataclasses import replace
from enum import IntEnum
from pathlib import Path
from typing import Any, override

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from rehuco_core import REHUROOT_SUFFIX, CandidateKind, RootCandidate, RootPick
from rehuco_core.root_candidates import path_key

from ..settings.root_catalog_settings import RootLayout

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a model method."""


class CandidateRole(IntEnum):
    """What a row of the staging list answers besides its text."""

    PICK = Qt.ItemDataRole.UserRole + 1
    """The :class:`~rehuco_core.RootPick`; writable as a whole is not offered -- see the next two."""

    LINE = Qt.ItemDataRole.UserRole + 2
    """The :class:`~rehuco_core.RootCandidate` the last plan made of it, or ``None`` while it is being checked."""

    KIND = Qt.ItemDataRole.UserRole + 3
    """The :class:`~rehuco_core.CandidateKind`, known from the path before any plan."""

    LABEL = Qt.ItemDataRole.UserRole + 4
    """A folder's label as typed, ``""`` for its folder's name; writable."""

    ROOT_FILE = Qt.ItemDataRole.UserRole + 5
    """A folder's root file as typed, ``""`` to follow its label; writable."""

    LAYOUT = Qt.ItemDataRole.UserRole + 6
    """The :class:`~.RootLayout` a folder starts with; writable."""

    TYPED = Qt.ItemDataRole.UserRole + 7
    """Write-only: the label and the root file together, as a ``(label, root_file)`` pair of texts -- one edit of the
    row, so the list is planned again once."""


class RootCandidatesModel(QAbstractListModel):
    """The paths picked to become roots, in the order they were, each with what the last plan made of it.

    **A pick a picked ``.rehuroot`` stands for is kept but not shown** -- the plan left it out -- so it comes back if
    the file is taken out. A pick no plan has seen yet is shown, its line ``None``, until one has. Rows change as a
    whole (a reset) only when picks come or go from what is shown; a plan that shows the same picks only refreshes
    them, so an editor open on a row stays open.

    :param default_layout: the preset a folder starts with.
    :param parent: optional Qt parent.
    """

    picks_changed = Signal()
    """A pick came, went or was edited in a way the plan depends on: it is to be planned again."""

    def __init__(self, default_layout: RootLayout, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__default_layout = default_layout
        self.__picks: list[RootPick] = []
        self.__lines: dict[str, RootCandidate] = {}
        """The last plan's lines, by their pick's path."""
        self.__planned: set[str] = set()
        """The picks the last plan saw, kept or not."""
        self.__layouts: dict[str, RootLayout] = {}
        self.__shown: list[RootPick] = []

    @property
    def picks(self) -> tuple[RootPick, ...]:
        """Every pick, shown or not, in the order they were made."""
        return tuple(self.__picks)

    @property
    def checking(self) -> bool:
        """Whether a shown pick has no line yet."""
        return any(path_key(pick.path) not in self.__lines for pick in self.__shown)

    @property
    def addable(self) -> tuple[RootCandidate, ...]:
        """The lines OK adds, in order: those that can be added, a folder's with the layouts and fallbacks of its
        preset."""
        lines: list[RootCandidate] = []
        for pick in self.__shown:
            line = self.__lines.get(path_key(pick.path))
            if line is None or not line.addable:
                continue
            if line.kind is CandidateKind.FOLDER:
                layout = self.layout_of(pick)
                line = replace(line, layouts=dict(layout.layouts), fallbacks=dict(layout.fallbacks))
            lines.append(line)
        return tuple(lines)

    def layout_of(self, pick: RootPick) -> RootLayout:
        """The preset a folder starts with.

        :param pick: the folder's pick.
        :returns: the one chosen for it, or the default.
        """
        return self.__layouts.get(path_key(pick.path), self.__default_layout)

    def stage(self, paths: Iterable[Path]) -> int:
        """Add paths as picks, after the others; one already picked, in any spelling, is passed over.

        :param paths: the paths, in order.
        :returns: how many were added.
        """
        known = {path_key(pick.path) for pick in self.__picks}
        added = 0
        for path in paths:
            key = path_key(path)
            if key not in known:
                known.add(key)
                self.__picks.append(RootPick(path))
                added += 1
        if added:
            self.__show()
            self.picks_changed.emit()
        return added

    def remove(self, row: int) -> None:
        """Take a shown pick out.

        :param row: its row.
        """
        key = path_key(self.__shown[row].path)
        self.__picks = [pick for pick in self.__picks if path_key(pick.path) != key]
        self.__layouts.pop(key, None)
        self.__show()
        self.picks_changed.emit()

    def set_plan(self, picks: Sequence[RootPick], lines: Sequence[RootCandidate]) -> None:
        """Take a plan's lines.

        :param picks: the picks the plan was made of -- a plan of picks since changed is still taken for those it saw.
        :param lines: its lines.
        """
        self.__planned = {path_key(pick.path) for pick in picks}
        self.__lines = {path_key(line.pick.path): line for line in lines}
        self.__show()

    def __show(self) -> None:
        """Bring the rows in line with the picks and the plan: a reset when the picks shown change, else a refresh."""
        shown = [
            pick
            for pick in self.__picks
            if path_key(pick.path) in self.__lines or path_key(pick.path) not in self.__planned
        ]
        if [path_key(pick.path) for pick in shown] != [path_key(pick.path) for pick in self.__shown]:
            self.beginResetModel()
            self.__shown = shown
            self.endResetModel()
        elif shown:
            self.__shown = shown
            self.dataChanged.emit(self.index(0), self.index(len(shown) - 1))

    # region Qt model interface

    @override
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: N802  (Qt API name)
        return 0 if parent.isValid() else len(self.__shown)

    @override
    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled
        if self.data(index, CandidateRole.KIND) == CandidateKind.FOLDER:
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    @override
    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pylint: disable=too-many-return-statements
        if not index.isValid():
            return None
        pick = self.__shown[index.row()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return str(pick.path)
        if role == CandidateRole.PICK:
            return pick
        if role == CandidateRole.LINE:
            return self.__lines.get(path_key(pick.path))
        if role == CandidateRole.KIND:
            return RootCandidatesModel.kind_of(pick.path)
        if role == CandidateRole.LABEL:
            return pick.label or ""
        if role == CandidateRole.ROOT_FILE:
            return "" if pick.root_file is None else str(pick.root_file)
        if role == CandidateRole.LAYOUT:
            return self.layout_of(pick)
        return None

    @override
    def setData(self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or self.data(index, CandidateRole.KIND) != CandidateKind.FOLDER:
            return False
        row = index.row()
        pick = self.__shown[row]
        if role == CandidateRole.LAYOUT and isinstance(value, RootLayout):
            if value == self.layout_of(pick):
                return False
            self.__layouts[path_key(pick.path)] = value  # pylint: disable=unsupported-assignment-operation
            self.dataChanged.emit(index, index)
            return True
        if role == CandidateRole.LABEL:
            changed = replace(pick, label=str(value).strip() or None)
        elif role == CandidateRole.ROOT_FILE:
            changed = replace(pick, root_file=RootCandidatesModel.__typed_path(value))
        elif role == CandidateRole.TYPED and isinstance(value, tuple) and len(value) == 2:
            label, root_file = value
            changed = replace(
                pick, label=str(label).strip() or None, root_file=RootCandidatesModel.__typed_path(root_file)
            )
        else:
            return False
        if changed == pick:
            return False
        self.__picks[self.__picks.index(pick)] = changed  # pylint: disable=unsupported-assignment-operation
        self.__shown[row] = changed  # pylint: disable=unsupported-assignment-operation
        self.dataChanged.emit(index, index)
        self.picks_changed.emit()
        return True

    # endregion

    @staticmethod
    def __typed_path(value: object) -> Path | None:
        """A root file as typed.

        :param value: the field's text.
        :returns: the path, or ``None`` for a field left empty.
        """
        text = str(value).strip()
        return Path(text) if text else None

    @staticmethod
    def kind_of(path: Path) -> CandidateKind:
        """What a picked path is, by its name alone.

        :param path: the path.
        :returns: a root file for a ``.rehuroot``, else a folder.
        """
        return CandidateKind.FILE if path.suffix.casefold() == REHUROOT_SUFFIX else CandidateKind.FOLDER
