"""The table a reader actually reads a log in -- wrapped rows, and a tail it can follow."""

from collections.abc import Mapping
from typing import Final, override

from PySide6.QtCore import QAbstractItemModel, QAbstractProxyModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QKeySequence, QResizeEvent
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView, QWidget

from .log_level_band import LogLevelBand
from .log_level_delegate import LogLevelDelegate
from .log_message_delegate import LogMessageDelegate
from .log_model import LEVEL_COLUMN, MESSAGE_COLUMN, LogModel

COPY_COLUMN_SEPARATOR: Final = "\t"
"""What :meth:`LogView.copy_selected` puts between a row's level and its message.

A tab: what a spreadsheet, an editor and a chat box all accept, and what survives being pasted into a
bug report as two columns rather than one run-on line."""


class LogView(QTableView):
    """A read-only, row-selecting table over a log model, with the two log delegates installed.

    **It follows the tail while the reader is at the tail.** During a long job the useful behaviour is
    for new records to scroll into view; the moment a reader scrolls back to read something, it must
    stop, or the thing they were reading is yanked away. So following is not a mode the reader sets --
    it is a fact about where they are: at the bottom, it follows; anywhere above it, it does not; back
    at the bottom, it follows again.

    That state is read from the **vertical scrollbar's position**, not from wheel events. A wheel hook
    sees only one of the several ways to leave the bottom -- a scrollbar drag, ``Page Up``, ``Home``,
    a keyboard selection, a touchpad fling and a programmatic scroll all miss it -- and a reader who
    left by any of those would have the view keep jumping. The scrollbar is where all of them end up.

    :attr:`follow_tail` is still settable, because the reader is owed a way to say *"stay at the
    bottom"* without holding the scrollbar there, and a way to stop following without scrolling away.

    :param parent: optional Qt parent. First and positional, because Qt Designer constructs a promoted
        custom widget as ``LogView(parent)`` and nothing else -- the tints arrive later, through
        :attr:`band_colors`.
    """

    follow_tail_changed = Signal(bool)
    """Fires when following starts or stops, however it was decided -- the reader scrolling away, the
    reader coming back, or :attr:`follow_tail` being set. What a toggle button in a toolbar stays in
    step with, including when the scroll position is what changed it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__follow_tail = True
        self.__scrolling_to_tail = False
        self.__level_delegate: Final = LogLevelDelegate(self)

        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setShowGrid(False)
        self.setGridStyle(Qt.PenStyle.NoPen)
        self.setCornerButtonEnabled(False)
        self.setWordWrap(True)
        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        # the message delegate reports a wrapped message's real height; without this the view would ask
        # for a uniform one and clip every line but the first
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

        self.setItemDelegateForColumn(LEVEL_COLUMN, self.__level_delegate)
        self.setItemDelegateForColumn(MESSAGE_COLUMN, LogMessageDelegate(self))

        # the visible affordance for copying -- a right-click menu holding the one action this view
        # offers, which also carries the platform copy shortcut (scoped to this widget's subtree, so
        # two log views in one window are never ambiguous about who Ctrl+C belongs to)
        self.__copy_action: Final = QAction("&Copy", self)
        self.__copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.__copy_action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.__copy_action.triggered.connect(self.copy_selected)
        self.addAction(self.__copy_action)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

        self.verticalScrollBar().valueChanged.connect(self.__on_scrolled)

    @property
    def copy_action(self) -> QAction:
        """Copies the selected rows to the clipboard -- the context menu's one entry."""
        return self.__copy_action

    @property
    def band_colors(self) -> dict[LogLevelBand, QColor]:
        """The tint the level column paints per band -- see
        :attr:`~.log_level_delegate.LogLevelDelegate.band_colors`."""
        return self.__level_delegate.band_colors

    @band_colors.setter
    def band_colors(self, band_colors: Mapping[LogLevelBand, QColor]) -> None:
        """Repaint the level column with new tints.

        The repaint is this class's to do: the delegate holds the colors but owns no viewport, so
        setting them there alone would leave the rows already on screen painted in the old ones until
        something else happened to invalidate them.

        :param band_colors: the new tint per band.
        """
        self.__level_delegate.band_colors = band_colors
        self.viewport().update()

    # region following the tail

    @property
    def follow_tail(self) -> bool:
        """Whether new rows scroll into view as they arrive.

        Setting it to ``True`` jumps to the bottom at once, rather than waiting for the next record --
        a reader turning it on is asking to see the end of the log now.
        """
        return self.__follow_tail

    @follow_tail.setter
    def follow_tail(self, follow: bool) -> None:
        """Start or stop following, reporting the change through :attr:`follow_tail_changed`.

        :param follow: whether to follow.
        """
        if follow == self.__follow_tail:
            return
        self.__follow_tail = follow
        self.follow_tail_changed.emit(follow)
        if follow:
            self.scroll_to_tail()

    def scroll_to_tail(self) -> None:
        """Scroll to the last row, without that scroll being read as the reader moving.

        Guarded because :meth:`scrollToBottom` moves the scrollbar, which is the very thing
        :meth:`__on_scrolled` watches to decide whether following should stop. Unguarded, an
        off-by-one landing (a row taller than the viewport, a resize mid-scroll) would look like a
        reader who had scrolled up, and following would switch itself off while trying to follow.
        """
        self.__scrolling_to_tail = True
        try:
            self.scrollToBottom()
        finally:
            self.__scrolling_to_tail = False

    def at_tail(self) -> bool:
        """Whether the view is scrolled to the bottom.

        :returns: ``True`` at the bottom, and for a log short enough to need no scrolling at all --
            which is *also* the bottom, and where a reader would expect the next record to appear.
        """
        scroll_bar = self.verticalScrollBar()
        return scroll_bar.value() >= scroll_bar.maximum()

    def __on_scrolled(self, value: int) -> None:
        """Follow, or stop following, according to where the reader has scrolled to.

        :param value: the scrollbar's new value; read through :meth:`at_tail` rather than compared
            here, since "at the bottom" is a property of the bar's range and not of one number.
        """
        del value
        if self.__scrolling_to_tail:
            return
        self.follow_tail = self.at_tail()

    @override
    def setModel(self, model: QAbstractItemModel | None) -> None:  # noqa: N802  (Qt API name)
        """Install ``model`` and start following its inserted rows.

        The connection is made here rather than in ``__init__`` because the model arrives later, and it
        is made to ``rowsInserted`` on the **view's** model (the proxy, normally) so a row hidden by a
        filter does not scroll the view to a row it will not show. The outgoing model is disconnected,
        or it would keep scrolling a view that is showing something else entirely.

        :param model: the model to show, or ``None`` to show nothing.
        """
        previous = self.model()
        if previous is not None:
            previous.rowsInserted.disconnect(self.__on_rows_inserted)
        super().setModel(model)
        if model is not None:
            model.rowsInserted.connect(self.__on_rows_inserted)

    def __on_rows_inserted(self, parent: QModelIndex, first: int, last: int) -> None:
        """Keep the newest row in view, if the reader is at the tail.

        :param parent: the parent index rows were inserted under; unused, the log is flat.
        :param first: first inserted row; unused.
        :param last: last inserted row; unused.
        """
        del parent, first, last
        if self.__follow_tail:
            self.scroll_to_tail()

    # endregion

    # region copying

    def copy_selected(self) -> None:
        """Put the selected rows on the clipboard, one line each, level then message.

        Rows rather than cells, matching the view's own row selection: a reader copying a log line
        wants the line. Nothing is copied when nothing is selected -- deliberately not "everything",
        which would silently replace a clipboard the reader had filled elsewhere.
        """
        rows = sorted(index.row() for index in self.selectionModel().selectedRows())
        if not rows:
            return
        model = self.model()
        lines = [
            COPY_COLUMN_SEPARATOR.join(
                str(model.index(row, column).data(Qt.ItemDataRole.DisplayRole) or "")
                for column in (LEVEL_COLUMN, MESSAGE_COLUMN)
            )
            for row in rows
        ]
        QGuiApplication.clipboard().setText("\n".join(lines))

    # endregion

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt API name)
        """Re-measure every row against the new width, and stay at the tail if following.

        A narrower message wraps onto more lines, so the heights the message delegate reported are
        wrong the moment the column changes width; ``ResizeToContents`` alone does not re-ask on a
        viewport resize.

        :param event: the resize event.
        """
        super().resizeEvent(event)
        self.resizeRowsToContents()
        if self.__follow_tail:
            self.scroll_to_tail()

    def source_log_model(self) -> LogModel | None:
        """The :class:`~.log_model.LogModel` behind this view, through any number of proxies.

        Lets a host reach the model that actually holds the entries (to clear it, or to re-cap it)
        without knowing how many proxies it put in between.

        :returns: the log model, or ``None`` if there is none at the end of the chain.
        """
        model = self.model()
        while isinstance(model, QAbstractProxyModel):
            model = model.sourceModel()
        return model if isinstance(model, LogModel) else None
