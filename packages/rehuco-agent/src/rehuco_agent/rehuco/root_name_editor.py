"""Editing a root's name in the Roots view's details pane (#514).

The name is the root's label, saved as typed -- empty included, in which case the column shows where the root is
(:attr:`~.roots_node.RootsNode.label`). While it is typed the column follows it, in memory only; the file is written
when the field is left.
"""

from collections.abc import Callable
from typing import cast

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMessageBox, QWidget
from rehuco_core import RehucoFile, RehucoRoot

from .root_catalog import RootCatalog
from .roots_folder_model import RootsFolderModel
from .roots_preview import RootsPreview


class RootNameEditor(QObject):
    """Connects the details pane's name field and its default-name button to the root that is current.

    :param catalog: the open catalog, whose file holds the labels.
    :param model: the Roots view's model, whose rows show the name while it is typed.
    :param preview: the details pane holding the field and its button.
    :param current_row: asked for the row the actions act on when it is a root row -- its place in the file -- else
        ``-1``.
    :param commit: saves an edit of a root, and shows it.
    :param owner: the widget a refusal is shown over; also this editor's parent.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        catalog: RootCatalog,
        model: RootsFolderModel,
        preview: RootsPreview,
        current_row: Callable[[], int],
        commit: Callable[[], None],
        owner: QWidget,
    ) -> None:
        super().__init__(owner)
        self.__catalog: RootCatalog = catalog
        self.__model: RootsFolderModel = model
        self.__preview: RootsPreview = preview
        self.__current_row: Callable[[], int] = current_row
        self.__commit: Callable[[], None] = commit
        self.__owner: QWidget = owner
        preview.root_name_edit.textEdited.connect(self.__on_typing)
        preview.root_name_edit.editingFinished.connect(self.__on_finished)
        preview.default_root_name_action.triggered.connect(self.__on_defaulted)

    def __named_root(self) -> RehucoRoot:
        """The root whose name the field shows: the current row, which is a root while the field is shown.

        :returns: the root as the file has it.
        """
        return cast(RehucoFile, self.__catalog.file).roots[self.__current_row()]

    def __on_typing(self, text: str) -> None:
        """Show what is typed as the root's name in the column, before it is saved.

        :param text: the field's text.
        """
        self.__model.set_root_name(self.__named_root().root_id, text.strip())

    def __on_defaulted(self) -> None:
        """Give the root its default name, and save it -- the button need not take the focus, so nothing else would.

        The field is set and the name saved from it, with no stop in the model on the way: telling the model first
        shows the row again, which puts the saved name back in a field that has lost the focus.
        """
        self.__preview.root_name_edit.setText(self.__preview.default_root_name)
        self.__on_finished()

    def __on_finished(self) -> None:
        """Rename the root to what was typed, as its label; nothing on disk changes.

        An empty name is kept as it is. A name another root already has is refused with a warning, and the field goes
        back to the label the root has.
        """
        file, row = self.__catalog.file, self.__current_row()
        if file is None or file.lock_reason is not None or row < 0:
            return
        root = file.roots[row]
        edit = self.__preview.root_name_edit
        name = edit.text().strip()
        if name == root.label:
            edit.setText(root.label)
            self.__model.set_root_name(root.root_id, root.label)
            return
        try:
            file.relabel_root(row, name)
        except ValueError as error:
            QMessageBox.warning(self.__owner, "Rename Root", str(error))
            edit.setText(root.label)
            self.__model.set_root_name(root.root_id, root.label)
            return
        self.__commit()
