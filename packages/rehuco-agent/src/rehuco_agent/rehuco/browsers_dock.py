"""The Browsers dock: every browser over the open Root Catalog's cache, each in a sub-dock of its own (#396, #461,
[[plugins#rehuco-dock]]).
"""

import logging
import sqlite3
from typing import Final, cast

import PySide6QtAds as QtAds
from borco_pyside.qtads import (
    QtAdsAutoHideButtonSuppressor,
    QtAdsFocusTracker,
    QtAdsLayout,
    QtAdsPinGuard,
    QtAdsTabContextActions,
    remove_dock_widget,
)
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QMainWindow, QMenu, QWidget
from rehuco_core import CatalogField, CatalogQuery, CatalogRow, RehucoFile

from ..dock_maximize import attach_maximize_handler
from ..filter_urls import filter_url_token
from ..glyphs import TAB_CLOSE_GLYPH
from ..settings.catalog_state_store import BrowserState, CatalogState, CatalogStateStore
from .browser_presets import DEFAULT_PRESET, BrowserPreset, browser_presets
from .root_catalog import RootCatalog
from .table_browser import TableBrowser

LOG: Final = logging.getLogger(__name__)

NEW_BROWSER_ICON: Final = ":/icons/browser_add.svg"
RENAME_BROWSER_ICON: Final = ":/icons/browser_rename.svg"
CLONE_BROWSER_ICON: Final = ":/icons/browser_clone.svg"


class BrowsersDock(QMainWindow):  # pylint: disable=too-many-instance-attributes
    """A nested dock shell holding any number of **table browsers** over the resources the open
    :class:`~.root_catalog.RootCatalog`'s ``.rehudb`` cache lists -- and nothing else (#461): the roots are the
    Root Catalog dock's, and this shell has no toolbar. New Table Browser is an action the ``Browsers`` menu and
    this dock's title bar carry; Rename Browser only the menu, since each browser's own Rename and Clone sit on its
    sub-dock's title bar and tab menu.

    **Browsers are the agent's, not the catalog's.** Each is a closable sub-dock named by a stable id, with a name,
    a filter and a header state. They are remembered per catalog, with where every sub-dock sits, in a
    :class:`~rehuco_agent.settings.catalog_state_store.CatalogStateStore` keyed by the rehuco id: read when the
    catalog opens a file and written when it lets one go (:attr:`~.root_catalog.RootCatalog.closing`).
    ``rehuco-core`` and the ``.rehuco`` know nothing of them. A catalog with none saved opens with one default
    browser.

    :param catalog: the open catalog, whose rows every browser reads.
    :param parent: optional Qt parent.
    :param stylesheet_host: the widget carrying the dock styling for the whole nest -- normally the window's
        outermost ``CDockManager``.
    :param catalog_store: where each catalog's browsers and layout are remembered; the app's own by default.
    """

    open_requested: Signal = Signal(object)
    """Emitted with a resource's absolute :class:`~pathlib.Path` when its row is double-clicked. Typed as
    plain ``object`` for the reason ``DocumentsDock.open_requested`` is."""

    resource_selected: Signal = Signal(object)
    """Emitted with the ``(root_id, relative)`` key of the **current** browser's one selected row, or ``None`` when
    its selection is not one row (#381) -- the browser's own :attr:`TableBrowser.current_changed`, passed on while
    that browser is the current one. A browser behind another is not being read, so what happens to its rows (a
    rename, a rescan) says nothing about what the reader is looking at. Typed as plain ``object``, as above."""

    def __init__(
        self,
        catalog: RootCatalog,
        parent: QWidget | None = None,
        *,
        stylesheet_host: QWidget | None = None,
        catalog_store: CatalogStateStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.__catalog: Final = catalog
        self.__catalog_store: Final = catalog_store if catalog_store is not None else CatalogStateStore()

        self.__browsers: Final[dict[QtAds.CDockWidget, TableBrowser]] = {}
        """Every browser's dock, in the order the browsers were added."""

        self.__dock_manager: Final = QtAds.CDockManager(self)
        self.__focus_tracker: Final = QtAdsFocusTracker(
            self.__dock_manager, close_glyph=TAB_CLOSE_GLYPH, stylesheet_host=stylesheet_host
        )
        # pinning belongs to the window's own docks, and this shell's sub-docks live inside one of them
        QtAdsAutoHideButtonSuppressor(self.__dock_manager)
        # and a pin the button never offered is undone as it happens (#491)
        QtAdsPinGuard(self.__dock_manager, pins=False)
        self.__maximize_handler: Final = attach_maximize_handler(self.__dock_manager)
        self.__tab_menus: Final = QtAdsTabContextActions(self.__dock_manager)

        self.__new_browser_action: Final = QAction("New Table Browser", self)
        self.__new_browser_action.setToolTip(
            "Add a table browser over this catalog's resources; its menu starts one from a preset."
        )
        self.__presets_menu: Final = self.__make_presets_menu()
        self.__rename_browser_action: Final = QAction("Rename Browser...", self)
        self.__rename_browser_action.setToolTip("Rename the current browser.")
        for action, icon in (
            (self.__new_browser_action, NEW_BROWSER_ICON),
            (self.__rename_browser_action, RENAME_BROWSER_ICON),
        ):
            ActionIconThemeHandler(action, icon)
        self.__new_browser_action.triggered.connect(lambda _checked=False: self.__on_new_browser())
        self.__rename_browser_action.triggered.connect(self.__on_rename_current_browser)

        self.__focus_tracker.current_dock_changed.connect(self.__update_enablement)
        catalog.opened.connect(self.__open_browsers)
        catalog.closing.connect(self.__on_closing)
        catalog.refreshed.connect(self.__refresh)
        catalog.rows_changed.connect(self.__update_in_place)
        catalog.rehuco_path_changed.connect(self.__update_enablement)
        self.__update_enablement()

    # region the browsers

    @property
    def title_bar_actions(self) -> list[QAction]:
        """What the dock holding this shell shows on its title bar: New Table Browser. Not Rename Browser -- the
        current browser's own title bar already carries its Rename."""
        return [self.__new_browser_action]

    @property
    def browsers(self) -> tuple[TableBrowser, ...]:
        """Every browser, in the order they were added."""
        return tuple(self.__browsers.values())

    def open_browsers(self) -> tuple[TableBrowser, ...]:
        """Every browser whose sub-dock is open, in the order they were added -- the set the Browsers menu lists."""
        return tuple(browser for dock, browser in self.__browsers.items() if not dock.isClosed())

    def focused_browser(self) -> TableBrowser | None:
        """The browser the Browsers menu checks: :attr:`current_browser`, under the name its menu reads it by."""
        return self.current_browser

    def focus_browser(self, browser: TableBrowser) -> None:
        """Show ``browser``'s sub-dock, bring its tab to the front and make it the current one.

        :param browser: one of :attr:`browsers`.
        """
        dock = self.browser_dock(browser)
        dock.toggleView(True)
        dock.setAsCurrentTab()
        self.__focus_tracker.set_current_dock(dock)

    @property
    def current_browser(self) -> TableBrowser | None:
        """The browser whose sub-dock is the focus tracker's current one, or ``None`` while none is. The preview
        shows this browser's selection (:attr:`resource_selected`, #381)."""
        current = self.__focus_tracker.current_dock
        return None if current is None else self.__browsers.get(current)

    def browser_dock(self, browser: TableBrowser) -> QtAds.CDockWidget:
        """The sub-dock holding ``browser``.

        :param browser: one of :attr:`browsers`.
        :returns: its dock.
        """
        return next(dock for dock, held in self.__browsers.items() if held is browser)

    def set_filter_token(self, field: CatalogField, value: str) -> bool:
        """Filter the current browser on ``value`` in ``field``, replacing any filter on that field it had
        ([[plugins#rehuco-dock]]): what a click-to-filter link and the Roots view's folder filter do.

        The current browser is the focused one, else the first one open -- every sub-dock of this shell is a browser,
        so none is current only while none is on screen or focus never settled on one. With none open, a default
        browser is opened to carry the filter.

        :param field: the field to filter on.
        :param value: the value, as its resource spells it.
        :returns: whether it was set; never while no catalog is open.
        """
        if self.__catalog.file is None:
            return False
        browser = self.__filter_target()
        if browser is None:
            browser = self.__new_browser()
        else:
            self.focus_browser(browser)
        browser.set_token(field.value, value)
        return True

    def apply_filter_url(self, url: str) -> bool:
        """Set the filter a click-to-filter link stands for on the current browser (:meth:`set_filter_token`).

        :param url: a ``filter://`` link ([[plugins#filter-urls]]).
        :returns: whether a filter was set; not for a link that names none, nor while no catalog is open.
        """
        token = filter_url_token(url)
        if token is None:
            LOG.warning("Not a filter link: %s", url)
            return False
        return self.set_filter_token(*token)

    @property
    def new_browser_action(self) -> QAction:
        """Adds a table browser."""
        return self.__new_browser_action

    @property
    def presets_menu(self) -> QMenu:
        """New Table Browser's menu: one entry per :func:`~.browser_presets.browser_presets`."""
        return self.__presets_menu

    @property
    def rename_browser_action(self) -> QAction:
        """Renames the current browser."""
        return self.__rename_browser_action

    def ask_browser_name(self, current: str, title: str = "Rename Browser") -> str | None:
        """Ask for a browser's name; the one modal behind a rename and a clone, so a test replaces it per instance.

        :param current: the name the box opens on.
        :param title: the box's title.
        :returns: the typed name, or ``None`` if the box was cancelled.
        """
        name, accepted = QInputDialog.getText(self, title, "Name:", text=current)
        return name if accepted else None

    def __filter_target(self) -> TableBrowser | None:
        """The browser a filter set from outside lands on; see :meth:`set_filter_token`.

        :returns: the browser, or ``None`` while none is open.
        """
        if self.current_browser is not None:
            return self.current_browser
        opened = self.open_browsers()
        return opened[0] if opened else None

    def __update_enablement(self) -> None:
        """Enable New Browser while a catalog is open to hold it, and Rename Browser while a browser is the current
        sub-dock."""
        self.__new_browser_action.setEnabled(self.__catalog.file is not None)
        self.__rename_browser_action.setEnabled(self.current_browser is not None)

    # endregion

    # region reading the rows

    def __refresh(self) -> None:
        """Read every browser's rows again -- one read per distinct query, browsers filtering alike sharing it.

        A read failure keeps what is on screen: the cache is disposable and the next scan rebuilds it, so a log
        line is the proportionate answer.
        """
        if self.__catalog.file is None:
            return
        matching: dict[CatalogQuery, list[CatalogRow]] = {}
        try:
            for browser in self.__browsers.values():
                if browser.query not in matching:
                    matching[browser.query] = self.__catalog.rows(browser.query)
        except sqlite3.Error as error:
            LOG.error("Could not read the cache of %s: %s", self.__catalog.rehuco_path, error)
            return
        root_paths = self.__catalog.root_paths()
        for browser in self.__browsers.values():
            browser.set_rows(matching[browser.query], root_paths)

    def __fill(self, browser: TableBrowser) -> None:
        """Read one browser's rows again: a browser added after the others were read, or one whose filter changed.

        :param browser: the browser.
        """
        if self.__catalog.file is None:
            return
        try:
            rows = self.__catalog.rows(browser.query)
        except sqlite3.Error as error:
            LOG.error("Could not read the cache of %s: %s", self.__catalog.rehuco_path, error)
            return
        browser.set_rows(rows, self.__catalog.root_paths())

    def __update_in_place(self, affected: set[int]) -> None:
        """Show what a change did to ``affected`` rows in every browser, each row changed, moved, inserted or removed
        where it stands -- one read of just those rows per distinct query, never a reset (#379).

        :param affected: the ids of every row the change may have touched.
        """
        if self.__catalog.file is None:  # pragma: no cover  (only announced with a file open)
            return
        fresh: dict[CatalogQuery, list[CatalogRow]] = {}
        try:
            for browser in self.__browsers.values():
                if browser.query not in fresh:
                    fresh[browser.query] = self.__catalog.rows(browser.query, ids=affected)
        except sqlite3.Error as error:
            LOG.error("Could not read the cache of %s: %s", self.__catalog.rehuco_path, error)
            return
        for browser in self.__browsers.values():
            browser.update_rows(affected, fresh[browser.query])

    # endregion

    # region opening and closing a catalog's browsers

    def __open_browsers(self, file: RehucoFile) -> None:
        """Build ``file``'s browsers as the catalog remembered them -- one default one if it remembered none --
        and put every sub-dock back where it sat. Their rows are read when the catalog says it
        :attr:`~.root_catalog.RootCatalog.refreshed`, right after.

        The layout defines the browsers (#102): each sub-dock's entry carries its browser, which is built as the
        restore reaches it.

        :param file: the catalog just opened.
        """
        state = self.__catalog_store.load(file.rehuco_id)
        # every browser of the catalog is built from the layout and placed as it is added, so none is unnamed
        QtAdsLayout(self.__dock_manager, pins=False).restore(
            state.layout, place_unnamed=lambda dock: None, create_dock=self.__create_browser_dock
        )
        if not self.__browsers:
            self.__add_browser(TableBrowser())
        self.__update_enablement()

    def __create_browser_dock(self, name: str, state: bytes | None) -> QtAds.CDockWidget | None:
        """Build the browser a restored layout names, from what its entry carries.

        :param name: the sub-dock's object name -- the browser's id.
        :param state: the entry's :class:`BrowserState`, as bytes.
        :returns: the browser's sub-dock, or ``None`` if the entry carries no browser of that id.
        """
        saved = BrowserState.from_bytes(state) if state is not None else None
        if saved is None or str(saved.browser_id) != name:
            return None
        return self.__add_browser(TableBrowser(saved))

    def __on_closing(self, file: RehucoFile) -> None:
        """Remember ``file``'s browsers and layout, then close every browser.

        :param file: the catalog being let go.
        """
        self.__remember_catalog(file)
        for dock in list(self.__browsers):
            self.__remove_browser(dock)
        self.__update_enablement()

    def __remember_catalog(self, file: RehucoFile) -> None:
        """Write ``file``'s browsers, and where every sub-dock sits, to the catalog store.

        :param file: the catalog being left.
        """
        with self.__maximize_handler.unmaximized():
            layout = QtAdsLayout(self.__dock_manager).save(self.__browser_state)
        self.__catalog_store.save(file.rehuco_id, CatalogState(layout))

    def __browser_state(self, dock: QtAds.CDockWidget) -> bytes | None:
        """What a browser's sub-dock entry carries: the browser itself.

        :param dock: one of this shell's sub-docks.
        :returns: its browser's :class:`BrowserState`, as bytes.
        """
        browser = self.__browsers.get(dock)
        return browser.state().to_bytes() if browser is not None else None

    # endregion

    # region one browser

    def __add_browser(self, browser: TableBrowser, *, beside: QtAds.CDockWidget | None = None) -> QtAds.CDockWidget:
        """Put ``browser`` in a closable sub-dock named by its id, with its own actions on the dock's title bar and
        tab menu.

        :param browser: the browser to show.
        :param beside: the sub-dock whose tab strip to join; see :meth:`__place`.
        :returns: its sub-dock.
        """
        features = QtAds.CDockWidget.DockWidgetFeature
        dock = QtAds.CDockWidget(self.__dock_manager, browser.name)
        dock.setObjectName(str(browser.browser_id))
        # [x] deletes the browser, which is this shell's to do: QtAds would only hide it
        dock.setFeatures(
            features.CustomCloseHandling
            | features.DockWidgetClosable
            | features.DockWidgetFocusable
            | features.DockWidgetMovable
        )
        dock.setWidget(browser)
        dock.setTitleBarActions(self.__browser_actions(dock))
        # registered before it is placed: placing it can make it the current sub-dock, and whoever hears that asks
        # which browser it is
        self.__browsers[dock] = browser  # pylint: disable=unsupported-assignment-operation
        self.__place(dock, beside)
        browser.row_activated.connect(self.open_requested)
        browser.query_changed.connect(lambda: self.__fill(browser))
        browser.current_changed.connect(lambda key: self.__on_current_changed(browser, key))
        dock.closeRequested.connect(lambda: self.__close_browser(dock))
        return dock

    def __on_current_changed(self, browser: TableBrowser, key: object) -> None:
        """Pass a browser's selection on as :attr:`resource_selected`, when it is the current browser's (#381).

        :param browser: the browser whose selection changed.
        :param key: its one selected row's ``(root_id, relative)``, or ``None``.
        """
        if browser is self.current_browser:
            self.resource_selected.emit(key)

    def __place(self, dock: QtAds.CDockWidget, beside: QtAds.CDockWidget | None = None) -> None:
        """Add a browser's sub-dock to the manager: into the tab strip of ``beside``, else of the first browser that
        is on screen, else as the manager's first area; and give its tab its actions.

        :param dock: the browser's sub-dock, not on the manager.
        :param beside: the sub-dock whose tab strip to join.
        """
        anchor = (
            beside
            if beside is not None
            else next((other for other in self.__browsers if other.dockAreaWidget() is not None), None)
        )
        area = None if anchor is None else anchor.dockAreaWidget()
        if area is not None:
            self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock, area)
        else:
            self.__dock_manager.addDockWidget(QtAds.CenterDockWidgetArea, dock)
        self.__tab_menus.add(dock, dock.titleBarActions(), lambda: self.__focus_tracker.set_current_dock(dock))

    def __browser_actions(self, dock: QtAds.CDockWidget) -> list[QAction]:
        """Rename and Clone for ``dock``'s browser, bound to that dock whichever one is current. Deleting is its [x].

        :param dock: the browser's sub-dock.
        :returns: the actions, in menu order.
        """
        rename = QAction("Rename...", dock)
        rename.triggered.connect(lambda: self.__rename_browser(dock))
        clone = QAction("Clone...", dock)
        clone.triggered.connect(lambda: self.__clone_browser(dock))
        for action, icon in ((rename, RENAME_BROWSER_ICON), (clone, CLONE_BROWSER_ICON)):
            ActionIconThemeHandler(action, icon)
        return [rename, clone]

    def __remove_browser(self, dock: QtAds.CDockWidget) -> None:
        """Take ``dock`` off the manager and delete it, with its browser.

        :param dock: the browser's sub-dock.
        """
        self.__browsers.pop(dock, None)
        remove_dock_widget(self.__dock_manager, dock)
        dock.deleteLater()

    def __make_presets_menu(self) -> QMenu:
        """Give New Table Browser its menu of presets (#400): a click on the action is still a default browser, and
        the action carries the menu wherever it sits -- a title bar's drop-down, a submenu of ``Browsers``.

        :returns: the menu.
        """
        menu = QMenu(self)
        for preset in browser_presets():
            action = menu.addAction(preset.label)
            action.triggered.connect(lambda _checked=False, preset=preset: self.__on_new_browser(preset))
        self.__new_browser_action.setMenu(menu)
        return menu

    def __on_new_browser(self, preset: BrowserPreset = DEFAULT_PRESET) -> None:
        """Add a table browser as ``preset`` starts one and make it current.

        :param preset: what it starts as.
        """
        if self.__catalog.file is not None:
            self.__new_browser(preset)

    def __new_browser(self, preset: BrowserPreset = DEFAULT_PRESET) -> TableBrowser:
        """Add a table browser as ``preset`` starts one, filled, and make it current.

        :param preset: what it starts as.
        :returns: the new browser.
        """
        browser = TableBrowser(preset=preset)
        dock = self.__add_browser(browser)
        self.__fill(browser)
        self.__focus_tracker.set_current_dock(dock)
        return browser

    def __on_rename_current_browser(self) -> None:
        """Rename the current browser, if one is."""
        current = self.__focus_tracker.current_dock
        if current in self.__browsers:
            self.__rename_browser(cast(QtAds.CDockWidget, current))

    def __rename_browser(self, dock: QtAds.CDockWidget) -> None:
        """Ask for a new name for ``dock``'s browser and set it: on the dock's ``windowTitle`` and the browser.
        Never the dock's ``objectName`` -- ``CDockManager`` keys its registry by the name a dock was added under,
        and a changed one dangles (#364). An empty or unchanged name is a cancel.

        :param dock: the browser's sub-dock.
        """
        browser = self.__browsers[dock]
        name = self.ask_browser_name(browser.name)
        name = name.strip() if name is not None else ""
        if name and name != browser.name:
            browser.name = name
            dock.setWindowTitle(name)

    def __clone_browser(self, dock: QtAds.CDockWidget) -> None:
        """Ask for a name and add a copy of ``dock``'s browser -- the same filter and columns -- beside it.

        :param dock: the sub-dock of the browser to copy.
        """
        source = self.__browsers[dock]
        name = self.ask_browser_name(f"{source.name} copy", "Clone Browser")
        name = name.strip() if name is not None else ""
        if not name:
            return
        clone = TableBrowser(source.clone_state(name))
        clone_dock = self.__add_browser(clone, beside=dock)
        self.__fill(clone)
        self.__focus_tracker.set_current_dock(clone_dock)

    def __close_browser(self, dock: QtAds.CDockWidget) -> None:
        """Delete ``dock``'s browser, as its [x] asks: a browser is only a view, so nothing is asked first.

        :param dock: the browser's sub-dock.
        """
        if dock in self.__browsers:
            self.__remove_browser(dock)
            self.__update_enablement()

    # endregion
