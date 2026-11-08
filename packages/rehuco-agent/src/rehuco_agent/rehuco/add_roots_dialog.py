"""The Add Roots dialog: folders and ``.rehuroot`` files picked on the left, the roots they would make listed on the
right, added together on OK (#378, #514, #578, [[plugins#rehuco-dock]])."""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, override
from uuid import UUID

from PySide6.QtCore import QModelIndex, QPersistentModelIndex
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QListView, QPushButton, QWidget
from rehuco_core import CandidateKind, MappedRoot, RehucoFile, RootCandidate, RootPick

from ..settings.persistent_settings import persistent_settings
from ..settings.root_catalog_settings import RootLayout, shared_root_catalog_settings
from .add_roots_dialog_ui import Ui_AddRootsDialog
from .new_layout_dialog import NewLayoutDialog
from .root_candidate_delegate import RootCandidateDelegate
from .root_candidates_model import CandidateRole, RootCandidatesModel
from .root_overlap_check import RootOverlapCheck
from .roots_browser import RootsBrowser

NOTHING_STAGED: Final = "Pick folders or .rehuroot files on the left: the + on a row adds it, or every row selected."
CHECKING_ALL: Final = "Checking\N{HORIZONTAL ELLIPSIS}"
PLAN_FAILED: Final = "The roots could not be checked; the log says why. Take one out, or add one, to check again."


@dataclass(slots=True)
class Planning:
    """What the dialog plans against, and how its last plan stands.

    :param file: the catalog the roots would join; only read.
    :param mapped: its roots this machine reaches.
    :param unreachable: the ids of its roots known unreachable.
    :param serial: the serial of the plan out, or of the last one asked for; ``0`` before any.
    :param out: whether that plan has not answered yet.
    :param failed: whether it answered that it failed.
    :param picks: the picks it was asked about.
    """

    file: RehucoFile
    mapped: tuple[MappedRoot, ...]
    unreachable: frozenset[UUID]
    serial: int = 0
    out: bool = False
    failed: bool = False
    picks: tuple[RootPick, ...] = field(default_factory=tuple)


class AddRootsDialog(QDialog):
    """Asks for the roots to add to a catalog: folders and existing ``.rehuroot`` files, many at once.

    **On the left, a file browser** (:class:`~.roots_browser.RootsBrowser`) opening in the ``.rehuco``'s folder; the
    ``+`` of a row stages it, or every row selected with it, and a path already staged is passed over. **On the right,
    the staging list**: a ``.rehuroot`` shows what it holds and where this machine finds it; a folder shows its label,
    its root file and its preset, editable in place. **Every change of the list is planned again** off the GUI thread
    (:meth:`~rehuco_core.RootPlanner.plan`): a folder a staged ``.rehuroot`` stands for is left out of the list, and
    what cannot be added says why and is skipped. OK adds the rest, and waits for no plan to be out.

    What a folder's root is mapped to, and what it lives on, are not asked: the folder is where it is, its storage
    detected. **Scan after adding** shows the Root Catalog setting of that name and writes it back, saved, however the
    dialog closes, like a dialog's geometry.

    :param file: the catalog the roots would join; only read.
    :param mapped: its roots this machine reaches.
    :param unreachable: the ids of its roots known unreachable.
    :param parent: optional Qt parent.
    """

    def __init__(
        self,
        file: RehucoFile,
        mapped: Sequence[MappedRoot],
        unreachable: Collection[UUID],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_AddRootsDialog()
        self.__ui.setupUi(self)
        self.__planning: Final = Planning(file, tuple(mapped), frozenset(unreachable))
        settings = shared_root_catalog_settings()
        self.__ui.scan_after_adding_check_box.setChecked(settings.scan_after_adding)
        self.__model: Final = RootCandidatesModel(settings.default_layouts[0], self)
        self.__delegate: Final = RootCandidateDelegate(lambda: shared_root_catalog_settings().default_layouts, self)
        view = self.__ui.staging_view
        view.setModel(self.__model)
        view.setItemDelegate(self.__delegate)
        view.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.__check: Final = RootOverlapCheck(self)
        self.__check.planned.connect(self.__on_planned)
        self.__model.picks_changed.connect(self.__plan)
        self.__model.modelReset.connect(self.__open_editors)
        self.__model.dataChanged.connect(self.__on_rows_changed)
        self.__delegate.remove_requested.connect(self.__on_remove)
        self.__delegate.new_layout_requested.connect(self.__on_new_layout)
        settings.default_layouts_changed.connect(self.__on_presets_changed)
        self.__ui.browser.add_requested.connect(self.stage)
        self.__ui.splitter.setSizes([400, 600])
        if file.path is not None:
            self.__ui.browser.show_folder(file.path.parent)
        self.__update()

    @property
    def browser(self) -> RootsBrowser:
        """The file browser on the left, for tests."""
        return self.__ui.browser

    @property
    def staging_view(self) -> QListView:
        """The staging list, for tests."""
        return self.__ui.staging_view

    @property
    def model(self) -> RootCandidatesModel:
        """The staging list's rows, for tests."""
        return self.__model

    @property
    def status(self) -> str:
        """What the line under the list says."""
        return self.__ui.status_label.text()

    @property
    def candidates(self) -> tuple[RootCandidate, ...]:
        """What OK adds, in order -- a folder's lines carrying its preset's layouts and fallbacks."""
        return self.__model.addable

    @property
    def scan_after_adding(self) -> bool:
        """Whether the checkbox asks for the new roots to be scanned."""
        return self.__ui.scan_after_adding_check_box.isChecked()

    @property
    def scan_after_adding_check_box(self) -> QCheckBox:
        """The *Scan after adding* checkbox, for tests."""
        return self.__ui.scan_after_adding_check_box

    @property
    def ok_button(self) -> QPushButton:
        """The OK button: enabled while something can be added and nothing is being checked."""
        return self.__ui.button_box.button(QDialogButtonBox.StandardButton.Ok)

    def stage(self, paths: Sequence[Path]) -> None:
        """Add paths to the list, as the ``+`` of the browser does; one already there is passed over, quietly.

        :param paths: the paths, in order.
        """
        self.__model.stage(paths)

    def ask_new_layout(self, taken: frozenset[str]) -> RootLayout | None:
        """Ask for a new preset. The one modal behind *New layout…*, so a test replaces it per instance.

        :param taken: the presets' names, which the new one may not take.
        :returns: the preset, or ``None`` if the dialog was cancelled.
        """
        dialog = NewLayoutDialog(taken, self)
        try:
            return dialog.preset if dialog.exec() == QDialog.DialogCode.Accepted else None
        finally:
            dialog.deleteLater()

    @override
    def done(self, result: int) -> None:
        """Remember the *Scan after adding* choice, on every exit path, hear no more plans, and close.

        :param result: the dialog's result code, passed straight through to :meth:`QDialog.done`.
        """
        settings = shared_root_catalog_settings()
        if settings.scan_after_adding != self.scan_after_adding:
            settings.scan_after_adding = self.scan_after_adding
            settings.save(persistent_settings())
        settings.default_layouts_changed.disconnect(self.__on_presets_changed)
        self.__check.stop()
        super().done(result)

    def __plan(self) -> None:
        """Plan the picks again, off the GUI thread; an answer for an earlier plan will be dropped."""
        planning = self.__planning
        planning.picks = self.__model.picks
        planning.failed = False
        planning.out = bool(planning.picks)
        if planning.out:
            planning.serial = self.__check.plan(planning.file, planning.picks, planning.mapped, planning.unreachable)
        else:
            self.__model.set_plan((), ())
        self.__update()

    def __on_planned(self, serial: int, lines: tuple[RootCandidate, ...] | None) -> None:
        """Show the plan asked for last; an earlier one is dropped.

        :param serial: the plan's serial.
        :param lines: its lines, or ``None`` when it failed.
        """
        planning = self.__planning
        if serial != planning.serial:
            return
        planning.out = False
        if lines is None:
            planning.failed = True
        else:
            self.__model.set_plan(planning.picks, lines)
        self.__update()

    def __open_editors(self) -> None:
        """Open each folder's editors, which stay open; the rows were all made anew."""
        view = self.__ui.staging_view
        for row in range(self.__model.rowCount()):
            index = self.__model.index(row)
            if index.data(CandidateRole.KIND) == CandidateKind.FOLDER:
                view.openPersistentEditor(index)

    def __on_rows_changed(self, top_left: QModelIndex, bottom_right: QModelIndex) -> None:
        """Have the list measure the changed rows again: a line saying why one cannot be added makes it taller.

        :param top_left: the first row changed.
        :param bottom_right: the last.
        """
        for row in range(top_left.row(), bottom_right.row() + 1):
            self.__delegate.sizeHintChanged.emit(self.__model.index(row))
        self.__update()

    def __on_remove(self, held: QPersistentModelIndex) -> None:
        """Take a row out.

        :param held: the row.
        """
        if held.isValid():
            self.__model.remove(held.row())

    def __on_new_layout(self, held: QPersistentModelIndex) -> None:
        """Ask for a new preset, save it with the others, and give it to the folder that asked.

        :param held: the folder's row.
        """
        settings = shared_root_catalog_settings()
        layout = self.ask_new_layout(frozenset(preset.label for preset in settings.default_layouts))
        if layout is None:
            return
        settings.default_layouts = (*settings.default_layouts, layout)
        settings.save(persistent_settings())
        if held.isValid():
            self.__model.setData(held, layout, CandidateRole.LAYOUT)

    def __on_presets_changed(self) -> None:
        """Offer the presets as they are now in every folder's combo."""
        if self.__model.rowCount():
            self.__model.dataChanged.emit(self.__model.index(0), self.__model.index(self.__model.rowCount() - 1))

    def __update(self) -> None:
        """Say how the list stands, and let OK through only while something can be added and nothing is checked."""
        busy = self.__planning.out or self.__model.checking
        addable = len(self.__model.addable)
        if self.__planning.failed:
            text = PLAN_FAILED
        elif busy:
            text = CHECKING_ALL
        elif not self.__model.rowCount():
            text = NOTHING_STAGED
        else:
            skipped = self.__model.rowCount() - addable
            text = f"{addable} to add" + (f", {skipped} left out" if skipped else "") + "."
        self.__ui.status_label.setText(text)
        self.ok_button.setEnabled(addable > 0 and not busy and not self.__planning.failed)
