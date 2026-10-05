"""A context menu on a `QHeaderView` that shows and hides its sections, with a header state to persist."""

from PySide6.QtCore import QAbstractItemModel, QByteArray, QObject, QPoint, Qt, Signal
from PySide6.QtWidgets import QHeaderView, QMenu


class HeaderSectionsMenu(QObject):
    """Lets the reader choose which columns (or rows) a header shows, and carries that choice as bytes.

    Attached to a header, it makes the sections movable and answers the header's context menu with one
    checkable action per section, labeled from the model's header data. Toggling an action hides or shows
    its section; the last visible section cannot be hidden, so the view never ends up blank with no
    menu entry visible to bring a section back from.

    Nothing here is stored: :meth:`save_state` and :meth:`restore_state` wrap the header's own state
    (visibility, order and width together), and the consumer decides where the bytes live. The menu is
    built from the header each time it opens, so its checkmarks are read from the header's current state
    and cannot disagree with it -- after a restore, after the model's column count changed, or after
    anything else hid a section.

    :attr:`sections_visibility_changed` says when the menu or a restore changed which sections show, so a consumer
    that mirrors or persists that choice can follow it. A section hidden by anyone else calling the header directly
    is not reported: the header itself has no signal for it.

    :param header: the header to attach to; this object is parented to it and lives as long as it does.
    """

    sections_visibility_changed: Signal = Signal()
    """Emitted once the menu or :meth:`restore_state` has shown or hidden a section."""

    def __init__(self, header: QHeaderView) -> None:
        super().__init__(header)
        self.__header = header
        header.setSectionsMovable(True)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self.__on_context_menu_requested)

    def build_menu(self) -> QMenu:
        """Build the menu for the header's present state.

        :returns: a menu of one checkable action per section, checked while the section is shown; the
            action of the only visible section is disabled. Empty while the header has no model.
        """
        menu = QMenu(self.__header)
        model = self.__header.model()
        if model is None:
            return menu
        last_visible = self.__visible_count() == 1
        for section in range(self.__header.count()):
            label = model.headerData(section, self.__header.orientation(), Qt.ItemDataRole.DisplayRole)
            action = menu.addAction(str(label) if label is not None else str(section + 1))
            action.setCheckable(True)
            shown = not self.__header.isSectionHidden(section)
            action.setChecked(shown)
            action.setEnabled(not (shown and last_visible))
            action.toggled.connect(lambda checked, index=section: self.__set_shown(index, checked))
        return menu

    def save_state(self) -> bytes:
        """The header's visibility, order and widths together.

        :returns: the bytes of ``QHeaderView.saveState()``, for :meth:`restore_state` to take back.
        """
        return bytes(self.__header.saveState().data())

    def restore_state(self, state: bytes) -> bool:
        """Apply bytes :meth:`save_state` produced.

        A state the header does not accept leaves every section shown, so a stale setting costs the
        reader their layout and never a column. Qt refuses corrupt bytes itself; a state saved from a
        header with *more* sections than the model has it accepts, by growing the header past the model
        (confirmed on 6.x) -- that one is refused here and the header put back as it was. A state saved
        from fewer sections than the model has applies to the sections it knows and **shows** the rest,
        whatever they were before (confirmed on 6.x): a consumer whose newer sections start hidden hides
        them again.

        :param state: the bytes to apply.
        :returns: whether the header accepted them; never while it has no model to lay out.
        """
        model = self.__header.model()
        if model is None:
            return False
        hidden = self.__hidden_sections()
        snapshot = self.__header.saveState()
        restored = self.__header.restoreState(QByteArray(state))
        if restored and self.__header.count() != self.__section_count(model):
            self.__header.restoreState(snapshot)
            restored = False
        if not restored or self.__visible_count() == 0:
            for section in range(self.__header.count()):
                self.__header.setSectionHidden(section, False)
            restored = False
        if self.__hidden_sections() != hidden:
            self.sections_visibility_changed.emit()
        return restored

    def __section_count(self, model: QAbstractItemModel) -> int:
        """How many sections the model has for this header's orientation.

        :param model: the header's model.
        :returns: its column count for a horizontal header, its row count for a vertical one.
        """
        root = self.__header.rootIndex()
        horizontal = self.__header.orientation() == Qt.Orientation.Horizontal
        return model.columnCount(root) if horizontal else model.rowCount(root)

    def __visible_count(self) -> int:
        """How many sections are shown.

        :returns: the header's section count less its hidden ones.
        """
        return self.__header.count() - self.__header.hiddenSectionCount()

    def __hidden_sections(self) -> frozenset[int]:
        """Which sections are hidden.

        :returns: their logical indexes.
        """
        return frozenset(section for section in range(self.__header.count()) if self.__header.isSectionHidden(section))

    def __set_shown(self, section: int, shown: bool) -> None:
        """Show or hide one section, refusing to hide the last one shown.

        :param section: the section's logical index.
        :param shown: whether it is to be shown.
        """
        if not shown and self.__visible_count() <= 1 and not self.__header.isSectionHidden(section):
            return
        if self.__header.isSectionHidden(section) != shown:
            return
        self.__header.setSectionHidden(section, not shown)
        self.sections_visibility_changed.emit()

    def __on_context_menu_requested(self, position: QPoint) -> None:
        """Open the menu where the header was right-clicked.

        :param position: the click's position in the header's coordinates.
        """
        # the menu is parented to the header so a theme or palette change reaches it, which means
        # nothing else lets go of it: delete it once it is dismissed, or every right-click leaks one
        menu = self.build_menu()
        menu.exec(self.__header.mapToGlobal(position))
        menu.deleteLater()
