"""The one scrolling column a settings *group* is shown through: its pages' blocks, in order (#230)."""

from collections.abc import Sequence
from typing import Final

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class SettingsBlockColumn(QWidget):
    """Shows the blocks of several settings pages as one column, each page's under its own heading.

    A **block** is one of a page's top-level labelled ``QFrame``s -- the same unit the frame filter
    shows and hides ([[appendices.settings-pages]]), and the smallest thing the settings tree can point
    at. A group row carries no page of its own, so what it has to show is the blocks of every page
    under it.

    **Blocks rather than whole pages**, because a page's layout is written for being shown alone: zero
    margins, a trailing spacer so its blocks sit at the top of a taller viewport, and sometimes one
    block stretched to fill what is left. Stacked, every one of those turns against the column -- each
    page's spacer claims a share of the height and spreads the pages apart, and the stretch has to be
    argued back down. Taking only the blocks leaves that layout where it is right: on the page's own
    view. Here the column supplies the one trailing stretch, and each block takes the height it asks
    for.

    A heading is shown only while the page under it still has a visible block
    (:meth:`sync_headings`) -- a title standing over a gap promises settings the filter removed.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__layout: Final = QVBoxLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        # the one stretch in the column, always its last item: everything is inserted before it, so
        # the blocks pack from the top and it alone takes whatever height they leave over
        self.__layout.addStretch()
        self.__sections: list[tuple[QLabel, Sequence[QFrame]]] = []

    def set_sections(self, sections: Sequence[tuple[str, Sequence[QFrame]]]) -> None:
        """Rebuild the column from ``sections``, in the order given.

        Rebuilt wholesale on every showing rather than patched: a block may have been taken back by its
        own page's view in between, and re-inserting only what left would append it after the blocks
        that stayed, putting the column out of tree order.

        :param sections: each page's heading text paired with the blocks to show beneath it.
        """
        self.__clear()
        for title, blocks in sections:
            heading = QLabel(title, self)
            font = heading.font()
            font.setBold(True)
            heading.setFont(font)
            self.__insert(heading)
            for block in blocks:
                self.__adopt(block)
            self.__sections.append((heading, blocks))
        self.sync_headings()

    def sync_headings(self) -> None:
        """Show each heading only while its page has a block left for it to head (#230).

        Called after every re-filter: which blocks survive is the filter's business, and which headings
        that leaves standing is this column's.
        """
        for heading, blocks in self.__sections:
            heading.setVisible(any(block.isVisibleTo(self) for block in blocks))

    def __clear(self) -> None:
        """Empty the column, deleting its headings and releasing its blocks back to their pages.

        A block is only *released* -- taken out of this layout and left parentless -- never deleted: it
        belongs to the page that built it, which puts it back into its own layout when shown alone.
        """
        for index in reversed(range(self.__layout.count() - 1)):  # the trailing stretch stays
            if (item := self.__layout.takeAt(index)) is None:  # pragma: no cover  (index is in range)
                continue
            if (widget := item.widget()) is None:  # pragma: no cover  (only widgets are inserted)
                continue
            widget.setParent(None)  # noqa: FURB199
            if isinstance(widget, QLabel):
                widget.deleteLater()
        self.__sections.clear()

    def __adopt(self, block: QFrame) -> None:
        """Take ``block`` out of whatever layout currently holds it and add it to this column.

        A widget has one parent, so this is always detach-then-attach. Leaving the old layout's item
        behind is what makes a widget appear in two places at once and then vanish from both.

        :param block: the page block to take over.
        """
        if (owner := block.parentWidget()) is not None and (layout := owner.layout()) is not None:
            layout.removeWidget(block)
        self.__insert(block)

    def __insert(self, widget: QWidget) -> None:
        """Add ``widget`` to the column, before the trailing stretch.

        :param widget: the heading or block to add.
        """
        self.__layout.insertWidget(self.__layout.count() - 1, widget)
