"""The ``authors`` record editor: one row per author, name and author-page URL
([[plugins#field-toolkit]], [[field-schema#authors]]).
"""

from collections.abc import Sequence
from typing import Final, cast, override

from borco_pyside.widgets import ContentSizedTableView, ItemListEditor
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QDropEvent, QShowEvent
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QWidget
from rehuco_core import AuthorEntry

from ...item_action_icons import apply_item_action_icons
from ...scraping.url_drop import UrlDrop
from .authors_table_model import NAME_COLUMN, URL_COLUMN, AuthorsTableModel


class UrlCellDropFilter(QObject):
    """Sets the URL cell a link is dropped on, ahead of whoever else takes drops around the table.

    **Watches the ancestors, not the table.** A drag is delivered to the nearest widget under the cursor
    that accepts drops, and every one of them keeps the drag until it ends -- so a table that accepted
    drops itself would take them from the Main Editor dock's scrape, and could not hand a drop on to it
    afterwards. The table is left not accepting, and this filter is installed on each ancestor that does
    (:meth:`attach`), where it sees the whole drag: it takes only a link over a URL cell, and every other
    drop, or drag, goes on to the ancestor's own handling untouched. It is installed last, so it runs
    first, which is what makes a drop aimed at a cell win over a handler that would take it for the
    whole editor. The link is a **plain URL** here: no link text is read, and the cell is set whether or
    not the row has a name yet.

    With no ancestor accepting drops there is nobody to take them from, so the viewport accepts them.

    :param table: the table whose URL cells take the drop; the model behind it is what is written to.
    """

    def __init__(self, table: ContentSizedTableView) -> None:
        super().__init__(table)
        self.__table: Final = table

    def attach(self) -> None:
        """Watch the drops that reach the table: on each ancestor that accepts them, or on the viewport."""
        viewport = self.__table.viewport()
        takers = []
        ancestor = self.__table.parentWidget()
        while ancestor is not None:
            if ancestor.acceptDrops():
                takers.append(ancestor)
            ancestor = ancestor.parentWidget()
        if not takers:
            viewport.setAcceptDrops(True)
            takers.append(viewport)
        for taker in takers:
            taker.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """See :meth:`QObject.eventFilter`.

        :param watched: a widget this filter was attached to.
        :param event: the event to inspect.
        :returns: whether the event was a link over a URL cell, and consumed here.
        """
        if event.type() not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            return False
        drop_event = cast(QDropEvent, event)
        drop = UrlDrop.parse(drop_event.mimeData())
        if drop is None:
            return False
        # positions arrive in the watched widget's own coordinates
        point = self.__table.viewport().mapFrom(cast(QWidget, watched), drop_event.position().toPoint())
        index = self.__table.indexAt(point)
        if not index.isValid() or index.column() != URL_COLUMN:
            return False
        drop_event.acceptProposedAction()
        if event.type() == QEvent.Type.Drop:
            self.__table.model().setData(index, drop.url)
        return True


class AuthorsListEditor(ItemListEditor):
    """The record-list half of the ``authors`` editor: `ItemListEditor`'s machinery over an
    :class:`AuthorsTableModel` ([[field-schema#authors]]).

    Everything about *how* the list is edited -- the insert/edit/delete buttons, the four move buttons,
    the keys, one model call per edit, the abandoned-insert rule -- comes from the base, which is the
    whole reason the record editor and the settings pages' `StringListEditor` behave the same way
    without either knowing about the other. What is here is what a list of **authors** is: two columns,
    and no Reset -- hidden outright, since there is no such thing as a default set of authors to
    restore, not merely none *right now*.

    The name column is the one an insert opens, but the base counts a row blank only while **both** cells
    are: a row can be started from its URL (typed, or a link dropped on the cell) before it has a name,
    and stays -- flagged, and left out of the value until it has one (:class:`AuthorsTableModel`) --
    unless the user leaves it with nothing in either cell.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        model = AuthorsTableModel()
        table = ContentSizedTableView()
        super().__init__(table, model, parent)
        self.__model: Final = model
        """The same model the base holds, kept at its concrete type -- the base knows only
        ``QAbstractItemModel``, and the entries are what this widget is for."""

        # a row is one author, so a click anywhere on it acts on that author; multi-select would
        # promise a bulk edit none of the actions here can carry out
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        # the row numbers say nothing -- credit order is read off the rows themselves
        table.verticalHeader().setVisible(False)
        # banded rows already separate one entry from the next; a grid on top of them draws a table
        # where there are only two fields per author
        table.setShowGrid(False)
        # one line per author: a table wraps its cells by default, so a long URL in a narrow column
        # grows its row to two lines -- and a view sized to its rows then reports a height measured
        # before the columns were laid out, which clips the last entry off the bottom
        table.setWordWrap(False)
        header = table.horizontalHeader()
        # both stretched to half the width each: a name and a link are each unbounded, so neither gets
        # to take the row -- and with the two always summing to the viewport there is nothing to scroll
        # sideways to, which is why the bar is off rather than merely unused
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(URL_COLUMN, QHeaderView.ResizeMode.Stretch)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # a default author list would be someone else's authors -- there is no reset concept here at
        # all, not just none configured, so the button is hidden rather than left disabled
        self.item_actions.reset_action.setVisible(False)
        # the same glyphs the settings pages' string lists wear, from the one place that names them
        apply_item_action_icons(self)
        self.__url_drops: Final = UrlCellDropFilter(table)

    @override
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt override)
        """Start watching for links dropped on a URL cell, once the ancestors that take drops are known.

        :param event: the show event.
        """
        self.__url_drops.attach()
        super().showEvent(event)

    @property
    def entries(self) -> tuple[AuthorEntry, ...]:
        """Every author, in row order, in canonical minimal form ([[field-schema#authors]])."""
        return self.__model.entries

    def set_entries(self, entries: Sequence[AuthorEntry]) -> None:
        """Show ``entries``, reporting one edit if that changed anything.

        :param entries: the authors list to show, in order.
        """
        self.__model.set_entries(entries)
