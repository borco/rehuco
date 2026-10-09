"""What a Roots row offers: the entries of its context menu, the buttons of the details pane, and the action a
double-click runs (#469, [[plugins#rehuco-dock]]).

**A row's actions have one home**, here: :meth:`RootsRowActions.context_actions` is the menu,
:meth:`RootsRowActions.buttons` the details pane's buttons, :meth:`RootsRowActions.default_action` what a double-click
runs. The actions themselves are the panel's, shared by every row's menu and buttons -- which is why which one is bold
is decided each time a row is asked for.
"""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QModelIndex, QObject
from PySide6.QtGui import QAction, QFont
from rehuco_core import FileType

from .rehuco_roots_panel_ui import Ui_RehucoRootsPanel
from .roots_checksum_verbs import RootsChecksumVerbs
from .roots_folder_model import RootsFolderModel, RootsNodeKind
from .roots_management import companion_found, managing_record
from .roots_opening import RootsOpening


class RootsRowActions:
    """The actions a Roots row is offered, by what the row is.

    :param model: the Roots model.
    :param ui: the panel's actions.
    :param opening: what opens an image, an archive or a file, and offers its entries.
    :param verbs: the checksum verbs a row's menu or buttons end with.
    :param parent: owns the separators, which are made once: a root's menu has two groups to divide, and one action
        cannot sit twice in a menu, while the menu and the details pane ask for a row's actions on every selection.
    """

    def __init__(
        self,
        model: RootsFolderModel,
        ui: Ui_RehucoRootsPanel,
        opening: RootsOpening,
        verbs: RootsChecksumVerbs,
        parent: QObject,
    ) -> None:
        self.__model: Final = model
        self.__ui: Final = ui
        self.__opening: Final = opening
        self.__verbs: Final = verbs
        self.__separators: Final = (QAction(parent), QAction(parent))
        for separator in self.__separators:
            separator.setSeparator(True)

    def context_actions(self, index: QModelIndex) -> list[QAction]:
        """What the Roots view's context menu holds for a row (#469).

        A root: the folder filter and Open in file explorer, then the four moves, then Remove. A folder: **Open
        associated rehu** if it has one, **Create a rehu** if nothing manages it, the folder filter and Open in file
        explorer. A rehu record: Open and Open in file explorer. A checksum file: its associated rehu and Open in
        file explorer. Any other file: Open with its application, then its associated rehu or Create likewise, then
        Open in file explorer. A placeholder: nothing. **The checksum group comes last, under a separator**, from
        what manages the row (:meth:`__checksum_group`) -- a checksum file's own two verbs instead. The row's default
        action, which a double-click runs, is drawn bold.

        :param index: the row the menu is for.
        :returns: the actions in menu order, a separator among them where the groups change.
        """
        ui = self.__ui
        match self.__model.node_kind(index):
            case RootsNodeKind.ROOT:
                actions = [
                    ui.filter_folder_action,
                    ui.open_explorer_action,
                    self.__separators[0],
                    ui.move_to_top_action,
                    ui.move_up_action,
                    ui.move_down_action,
                    ui.move_to_bottom_action,
                    self.__separators[1],
                    ui.remove_root_action,
                ]
            case RootsNodeKind.FOLDER:
                actions = [
                    *self.__companion_actions(index),
                    ui.filter_folder_action,
                    ui.open_explorer_action,
                    *self.__checksum_group(index),
                ]
            case RootsNodeKind.FILE:
                file_type = self.__model.file_type_of(index)
                if file_type is FileType.RECORD:
                    actions = [ui.open_record_action, ui.open_explorer_action, *self.__checksum_group(index)]
                elif file_type is FileType.MANIFEST:
                    actions = [
                        *self.__companion_actions(index),
                        ui.open_explorer_action,
                        self.__separators[0],
                        *self.__verbs.verify_actions(index),
                    ]
                else:
                    actions = [
                        *self.__opening.actions(index),
                        *self.__companion_actions(index),
                        ui.open_explorer_action,
                        *self.__checksum_group(index, file_verbs=True),
                    ]
            case _:
                return []
        self.__mark_default(index)
        return actions

    def buttons(self, index: QModelIndex) -> tuple[list[QAction], QAction | None]:
        """What the details pane makes buttons of for a row (#469): the common and the harmless, one easy click each.

        **A button never starts something a reader could regret**: Open, Open in file explorer and the checksum
        group's bulk verb and *Verify this file now*. The folder filter, Create, Remove Root, the moves and adding or
        updating one file's checksum are in the context menu only.

        :param index: the row.
        :returns: the actions in order, and the default one. A root has one button, Open in file explorer: its grip
            moves it, and the rest stays in its menu.
        """
        ui = self.__ui
        match self.__model.node_kind(index):
            case RootsNodeKind.ROOT:
                return [ui.open_explorer_action], None
            case RootsNodeKind.FOLDER:
                opening = [ui.open_companion_action] if (companion_found(self.__model, index) is not None) else []
                actions = [*opening, ui.open_explorer_action, *self.__checksum_group(index)]
            case RootsNodeKind.FILE:
                file_type = self.__model.file_type_of(index)
                if file_type is FileType.RECORD:
                    actions = [ui.open_record_action, ui.open_explorer_action, *self.__checksum_group(index)]
                elif file_type is FileType.MANIFEST:
                    actions = [ui.open_explorer_action, self.__separators[0], *self.__verbs.verify_actions(index)]
                else:
                    # an archive's own rehu is opened from its pane as from its menu (#456); a file's is in its menu
                    found = file_type is FileType.ARCHIVE and companion_found(self.__model, index) is not None
                    actions = [
                        *self.__opening.actions(index),
                        *([ui.open_companion_action] if found else []),
                        ui.open_explorer_action,
                        *self.__checksum_group(index, file_verbs=True, buttons=True),
                    ]
            case _:
                return [], None
        self.__mark_default(index)
        return actions, self.default_action(index)

    def default_action(self, index: QModelIndex) -> QAction | None:
        """What a double-click on a row does, and what the details pane's Open button runs.

        :param index: the row.
        :returns: a folder's associated rehu if it has one, a record's Open, a checksum file's verify of what is
            old, any other file's Open with its application; ``None`` for a root and a placeholder, which only
            navigate, and for a folder with no rehu -- a double-click never creates one.
        """
        ui = self.__ui
        match self.__model.node_kind(index):
            case RootsNodeKind.FOLDER:
                return ui.open_companion_action if (companion_found(self.__model, index) is not None) else None
            case RootsNodeKind.FILE:
                file_type = self.__model.file_type_of(index)
                if file_type is FileType.RECORD:
                    return ui.open_record_action
                if file_type is FileType.MANIFEST:
                    # a checksum file is opened for what it is for: checking what is old, and recording what is new
                    return ui.verify_old_checksums_action
                return ui.open_lightbox_action if self.__opening.shows_in_lightbox(index) else ui.open_file_action
        return None

    def companion_action(self, index: QModelIndex) -> QAction:
        """What the associated rehu of a folder or file is asked for as: opening it if it is there, creating it if not.

        :param index: the folder or file.
        :returns: the open action or the create action.
        """
        ui = self.__ui
        if companion_found(self.__model, index) is not None:
            return ui.open_companion_action
        what = "folder" if self.__model.node_kind(index) is RootsNodeKind.FOLDER else "file"
        ui.create_companion_action.setText(f"Create a rehu for this {what}")
        return ui.create_companion_action

    def folder_record(self, index: QModelIndex) -> Path | None:
        """The record a folder row stands for, for the details pane.

        :param index: the row.
        :returns: the folder's ``info.rehu`` or ``info.tc``; ``None`` for any other row, or a folder without.
        """
        return companion_found(self.__model, index) if self.__model.node_kind(index) is RootsNodeKind.FOLDER else None

    def __mark_default(self, index: QModelIndex) -> None:
        """Draw the row's default action bold, and the others plain.

        The actions are shared by every row's menu and buttons, so which one is bold is decided each time a row is
        asked for.

        :param index: the row.
        """
        ui = self.__ui
        default = self.default_action(index)
        bold = QFont()
        bold.setBold(True)
        for action in (
            ui.open_record_action,
            ui.open_file_action,
            ui.open_lightbox_action,
            ui.open_companion_action,
            ui.create_companion_action,
            ui.filter_folder_action,
            ui.open_explorer_action,
            ui.verify_old_checksums_action,
            ui.verify_checksums_action,
        ):
            action.setFont(bold if action is default else QFont())

    def __checksum_group(self, index: QModelIndex, *, file_verbs: bool = False, buttons: bool = False) -> list[QAction]:
        """The checksum verbs a row's menu or buttons end with (:class:`~.roots_checksum_verbs.RootsChecksumVerbs`),
        under a separator.

        :param index: the folder or file.
        :param file_verbs: whether to add the file's own verbs.
        :param buttons: whether the group is for the details pane.
        :returns: the separator and the verbs; empty when nothing checksums the row.
        """
        verbs = self.__verbs.group(index, file_verbs=file_verbs, buttons=buttons)
        return [self.__separators[0], *verbs] if verbs else []

    def __companion_actions(self, index: QModelIndex) -> list[QAction]:
        """The associated-rehu entry of a folder's or file's menu: Open if it has one, **Create only where nothing
        manages it** -- not for a file an ``info.rehu`` already takes, nor a folder under one (#469).

        :param index: the folder or file.
        :returns: the one action, or none.
        """
        model = self.__model
        if companion_found(model, index) is not None or managing_record(model, index) is None:
            return [self.companion_action(index)]
        return []
