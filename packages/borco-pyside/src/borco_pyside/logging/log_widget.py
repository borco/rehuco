"""One whole log surface: a bounded history, the controls that narrow it, and the table showing it."""

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import cbor2
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QSizePolicy, QToolBar, QWidget

from ..theming import ActionIconThemeHandler
from .log_bridge import DEFAULT_LOG_LIMIT, LogBridge
from .log_entry import LogEntry
from .log_filter_model import LogFilterModel
from .log_level_band import LogLevelBand
from .log_model import LogModel
from .log_widget_ui import Ui_LogWidget

STATE_SHOW_DEBUGS_KEY: Final = "show_debugs"
STATE_SHOW_INFOS_KEY: Final = "show_infos"
STATE_SHOW_WARNINGS_KEY: Final = "show_warnings"
STATE_SHOW_ERRORS_KEY: Final = "show_errors"
STATE_FOLLOW_TAIL_KEY: Final = "follow_tail"
STATE_SEARCH_KEY: Final = "search"

DROPPED_MESSAGE: Final = "{count} earlier records dropped"
"""What the footer says once the ring buffer has discarded anything.

A number, not *"some records were dropped"*: whether the answer to *"is anything missing"* is 3 or
3 000 changes what a reader does about it -- raise the limit, or stop reading this surface and go to
the file."""


@dataclass(frozen=True, slots=True)
class LogWidgetIcons:
    """The icons a :class:`LogWidget`'s toolbar draws its actions with -- SVG resource or file paths.

    Injected rather than shipped, because this package owns no icons and must not name an
    application's resource bundle. Each is handed to
    :class:`~borco_pyside.theming.ActionIconThemeHandler`, so it must be a genuinely monochrome SVG in
    the sense that recoloring requires.

    Every field defaults to empty, which leaves that action with its text and no icon -- a toolbar with
    labels is a working toolbar, and a caller adopting this widget should not have to draw six icons
    before it will run.
    """

    clear: str = ""
    """Empties this view's history."""

    follow_tail: str = ""
    """Toggles scrolling new records into view."""

    debugs: str = ""
    infos: str = ""
    warnings: str = ""
    errors: str = ""
    """One per :class:`~.log_level_band.LogLevelBand`, on the four independent band toggles."""


class LogWidget(QWidget):
    """A log surface: its own bounded history, four band toggles, a search, a clear, and a followed tail.

    **Its history is its own.** Several of these exist at once -- one app-wide, one per thing with a
    log of its own -- and each holds its own :class:`~.log_model.LogModel`.
    Clearing this one empties this one: not another surface, and not what
    :class:`~.log_bridge.LogBridge` still holds for the next surface to attach. This is why
    :meth:`clear` reports nothing to the bridge, where the prior art wired its single view's ``cleared``
    signal back to the bridge's cache and so made emptying a view erase the replay.

    **The toggles are four, and independent** (:class:`~.log_level_band.LogLevelBand`). Turning debugs
    on does not drag in everything above them, and turning all four off shows nothing -- a state the
    reader chose.

    **Filtering hides; nothing is discarded.** Narrowing to errors and widening again brings back
    everything, including whatever arrived while the view was narrow -- the entries never left the
    model. Only :meth:`clear` and the ring buffer's cap remove anything.

    Satisfies `LogRecordSink` structurally by forwarding to its model, so it can be handed to
    :meth:`~.log_bridge.LogBridge.add_sink` directly -- though :meth:`attach_to` is the wiring worth
    using, since it also arranges the detach.

    :param parent: optional Qt parent.
    :param icons: the toolbar's icons; omitted leaves the actions text-only.
    :param band_colors: the level column's tint per band
        (:class:`~.log_level_delegate.LogLevelDelegate`).
    :param limit: how many entries this surface keeps; see :attr:`limit`.
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        icons: LogWidgetIcons | None = None,
        band_colors: Mapping[LogLevelBand, QColor] | None = None,
        limit: int = DEFAULT_LOG_LIMIT,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = LogModel(self, limit=limit)
        self.__proxy: Final = LogFilterModel(self)
        self.__proxy.setSourceModel(self.__model)

        self.__ui: Final = Ui_LogWidget()
        self.__ui.setupUi(self)

        self.__band_actions: Final[dict[LogLevelBand, QAction]] = {
            LogLevelBand.DEBUGS: self.__ui.show_debugs_action,
            LogLevelBand.INFOS: self.__ui.show_infos_action,
            LogLevelBand.WARNINGS: self.__ui.show_warnings_action,
            LogLevelBand.ERRORS: self.__ui.show_errors_action,
        }

        self.__setup_toolbar(icons or LogWidgetIcons())
        self.__setup_view(band_colors)
        self.__setup_controls()

    # region construction

    def __setup_toolbar(self, icons: LogWidgetIcons) -> None:
        """Build the control bar and theme each action's icon from ``icons``.

        The bar is built here rather than declared in the ``.ui``: Qt Designer offers no ``QToolBar``
        inside a plain widget form. The **actions** are declared there, which is what keeps their
        text, tooltips and checked defaults editable in Designer.

        :param icons: the icon per action.
        """
        ui = self.__ui
        toolbar = QToolBar(self)
        # what narrows the view first, then what follows it, and the one destructive control last, behind
        # a separator of its own -- clear is the only button here that cannot be undone
        toolbar.addActions(
            [ui.show_debugs_action, ui.show_infos_action, ui.show_warnings_action, ui.show_errors_action]
        )
        toolbar.addSeparator()
        toolbar.addAction(ui.follow_tail_action)
        toolbar.addSeparator()
        toolbar.addAction(ui.clear_action)
        # appended, so the search box (declared first in the ``.ui``) stays left of it; and held to its
        # buttons' own width, or the two would share the spare space and leave the search box half a row
        # wide for no reason -- what grows usefully here is the field you type in
        toolbar.setSizePolicy(QSizePolicy.Policy.Maximum, toolbar.sizePolicy().verticalPolicy())
        ui.controls_layout.addWidget(toolbar)

        for action, icon in (
            (ui.clear_action, icons.clear),
            (ui.follow_tail_action, icons.follow_tail),
            (ui.show_debugs_action, icons.debugs),
            (ui.show_infos_action, icons.infos),
            (ui.show_warnings_action, icons.warnings),
            (ui.show_errors_action, icons.errors),
        ):
            if icon:
                ActionIconThemeHandler(action, icon)

    def __setup_view(self, band_colors: Mapping[LogLevelBand, QColor] | None) -> None:
        """Point the view at the filtered model and hand it its tints.

        :param band_colors: the tint per band, or ``None`` to leave every band plain.
        """
        view = self.__ui.log_view
        view.setModel(self.__proxy)
        if band_colors is not None:
            view.band_colors = band_colors
        view.follow_tail = self.__ui.follow_tail_action.isChecked()

    def __setup_controls(self) -> None:
        """Wire the actions, the search box and the dropped-count footer.

        The follow-tail action is wired **both ways**: it drives the view, and the view drives it back
        -- because the view decides to stop following when the reader scrolls away, and a button
        claiming to follow while the view does not is worse than no button.
        """
        ui = self.__ui
        ui.clear_action.triggered.connect(self.clear)
        for band, action in self.__band_actions.items():
            action.toggled.connect(lambda checked, band=band: self.__proxy.set_band_visible(band, checked))
            self.__proxy.set_band_visible(band, action.isChecked())
        ui.follow_tail_action.toggled.connect(self.__on_follow_tail_toggled)
        ui.log_view.follow_tail_changed.connect(self.__on_view_follow_tail_changed)
        ui.search_edit.textChanged.connect(self.__on_search_changed)
        self.__model.dropped_changed.connect(self.__on_dropped_changed)

    # endregion

    # region the surface

    @property
    def model(self) -> LogModel:
        """This surface's own history -- the sink the bridge feeds."""
        return self.__model

    @property
    def limit(self) -> int:
        """How many entries this surface keeps before dropping its oldest.

        Never usefully larger than the bridge's own limit: the bridge's cache is also its queue, so
        entries beyond that were already dropped before they could arrive here (see
        :attr:`~.log_bridge.LogBridge.limit`).
        """
        return self.__model.limit

    @limit.setter
    def limit(self, limit: int) -> None:
        """Re-cap the history now, trimming the oldest rows if it no longer fits.

        :param limit: the new cap.
        """
        self.__model.limit = limit

    def clear(self) -> None:
        """Empty this surface, and only this surface."""
        self.__model.clear()

    def handle_log_records(self, entries: Sequence[LogEntry]) -> None:
        """Take a batch of entries -- the `LogRecordSink` contract, forwarded to the model.

        :param entries: the entries to append, oldest first.
        """
        self.__model.handle_log_records(entries)

    def attach_to(self, bridge: LogBridge, scope: Hashable | None = None) -> None:
        """Start receiving records from ``bridge``, replaying what it already holds.

        Attaches this widget's **model**, not the widget, and arranges the detach on the model's
        ``destroyed``: a bridge lives for the whole run while a per-resource surface lives as long as
        its document, so a closed document that stayed attached would leave the bridge dispatching
        into a deleted object on the next record.

        :param bridge: the bridge to receive from.
        :param scope: what this surface is the log *of*, or ``None`` for the app-wide surface, which
            sees every record, scoped or not.
        """
        if scope is None:
            bridge.add_sink(self.__model)
        else:
            bridge.add_scoped_sink(self.__model, scope)
        self.__model.destroyed.connect(lambda: bridge.remove_sink(self.__model))

    def detach_from(self, bridge: LogBridge) -> None:
        """Stop receiving records from ``bridge``, keeping every row already shown.

        What a re-scope is made of (a resource whose path changed): detach, then attach under the new
        scope. The rows stay because they are this surface's history of that same thing -- the thing
        was renamed, not replaced.

        :param bridge: the bridge to stop receiving from.
        """
        bridge.remove_sink(self.__model)

    # endregion

    # region controls

    def __on_follow_tail_toggled(self, checked: bool) -> None:
        """Apply the toolbar toggle to the view.

        :param checked: whether to follow.
        """
        self.__ui.log_view.follow_tail = checked

    def __on_view_follow_tail_changed(self, following: bool) -> None:
        """Keep the toolbar toggle showing what the view is actually doing.

        :param following: whether the view is now following.
        """
        self.__ui.follow_tail_action.setChecked(following)

    def __on_search_changed(self, text: str) -> None:
        """Narrow the view to messages containing ``text``.

        :param text: the substring to look for; empty stops searching.
        """
        self.__proxy.search = text

    def __on_dropped_changed(self, dropped: int) -> None:
        """Say how many entries this surface no longer holds, once there are any.

        :param dropped: the cumulative count.
        """
        self.__ui.dropped_label.setText(DROPPED_MESSAGE.format(count=dropped))
        self.__ui.dropped_label.setVisible(dropped > 0)

    # endregion

    # region saving and restoring the reader's choices

    def save_state(self) -> bytes:
        """Encode which bands are shown, whether the tail is followed, and what is searched for.

        The reader's *view* of the log, not the log: nothing here is an entry, so a restored surface
        starts from the bridge's replay under the filters it was left with.

        :returns: the blob, restorable by :meth:`restore_state`.
        """
        ui = self.__ui
        return cbor2.dumps(
            {
                STATE_SHOW_DEBUGS_KEY: ui.show_debugs_action.isChecked(),
                STATE_SHOW_INFOS_KEY: ui.show_infos_action.isChecked(),
                STATE_SHOW_WARNINGS_KEY: ui.show_warnings_action.isChecked(),
                STATE_SHOW_ERRORS_KEY: ui.show_errors_action.isChecked(),
                STATE_FOLLOW_TAIL_KEY: ui.follow_tail_action.isChecked(),
                STATE_SEARCH_KEY: ui.search_edit.text(),
            }
        )

    def restore_state(self, state: bytes) -> None:
        """Restore the reader's choices, key by key, keeping the current value for anything missing.

        Read defensively rather than all-or-nothing: every key here is independent, so a blob written
        before one of them existed is still a perfectly good answer about the others. An undecodable
        blob changes nothing at all.

        :param state: the blob from :meth:`save_state`.
        """
        try:
            values = cbor2.loads(state)
        except cbor2.CBORDecodeError:
            return
        if not isinstance(values, dict):
            return
        ui = self.__ui
        for key, action in (
            (STATE_SHOW_DEBUGS_KEY, ui.show_debugs_action),
            (STATE_SHOW_INFOS_KEY, ui.show_infos_action),
            (STATE_SHOW_WARNINGS_KEY, ui.show_warnings_action),
            (STATE_SHOW_ERRORS_KEY, ui.show_errors_action),
            (STATE_FOLLOW_TAIL_KEY, ui.follow_tail_action),
        ):
            stored = values.get(key)
            if isinstance(stored, bool):
                action.setChecked(stored)
        search = values.get(STATE_SEARCH_KEY)
        if isinstance(search, str):
            ui.search_edit.setText(search)

    # endregion
