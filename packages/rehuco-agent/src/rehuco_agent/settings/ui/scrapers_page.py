"""Scrapers settings page: the scripts folder, what loaded from it, and the browser persona (#269,
[[acquisition-tooling#browser-persona]])."""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

from borco_pyside.file_browser import reveal_in_file_browser
from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ...scraping.browser_fetcher import PersonaAction, shared_persona_browser
from ...scraping.registry import shared_scraper_registry
from ..persistent_settings import persistent_settings
from ..scrapers_settings import Browser, ScrapersSettings, persona_folder, shared_scrapers_settings
from .scrapers_checkbox_delegate import ScrapersCheckboxDelegate
from .scrapers_page_ui import Ui_ScrapersPage
from .scrapers_row_delegate import ScrapersRowDelegate
from .scrapers_scraper_column_delegate import ScrapersScraperColumnDelegate
from .scrapers_table_model import SCRAPER_COLUMN, USE_BROWSER_COLUMN, ScrapersTableModel

REVEAL_HINT: Final = {"win32": "Show in Explorer", "darwin": "Reveal in Finder"}.get(
    sys.platform, "Show in file manager"
)
"""What a click on a path link does, named for its tooltip -- the same wording
`rehuco_agent.fields.path_field.REVEAL_HINT` uses."""

BROWSER_LABELS: Final[tuple[tuple[Browser, str], ...]] = (
    (Browser.FIREFOX, "Firefox"),
    (Browser.CHROME, "Chrome"),
    (Browser.EDGE, "Edge"),
)
"""The combo box's entries, in the order they are added -- `Browser`'s own declaration order."""

RESET_PERSONA_QUESTION: Final = (
    "This deletes the {browser} persona's browser profile, logging it out of every site. "
    "A fresh, empty profile is created the next time it is used. Continue?"
)


class ScrapersPage(QWidget):
    """Configure the folder `rehuco_agent.scraping.registry.ScraperRegistry` loads user scripts from,
    and the browser persona `~rehuco_agent.scraping.browser_fetcher.BrowserPageFetcher` fetches through.

    Edits are staged until :meth:`save_changes` pushes them into the shared
    `rehuco_agent.settings.scrapers_settings.ScrapersSettings`, persists them, and reloads the shared
    registry -- so Save is what makes a new folder or a newly-ticked scraper take effect, the same as
    every other settings page. **Open the browser** and **Reset persona…** are the two exceptions: they
    act on the persona immediately, against whichever browser is currently staged in the combo, rather
    than being staged settings of their own.

    **Reload always scans the saved folder, never the one currently typed**: the table's header names
    that folder, so a path being edited is never confused with what the table already shows.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ScrapersPage()
        self.__ui.setupUi(self)
        for _browser, label in BROWSER_LABELS:
            self.__ui.browser_combo.addItem(label)
        self.__model: Final = ScrapersTableModel(self)
        self.__ui.scrapers_table.setModel(self.__model)
        self.__ui.scrapers_table.setItemDelegate(ScrapersRowDelegate(self))
        self.__ui.scrapers_table.setItemDelegateForColumn(USE_BROWSER_COLUMN, ScrapersCheckboxDelegate(self))
        scraper_column_delegate = ScrapersScraperColumnDelegate(self)
        scraper_column_delegate.link_activated.connect(self.__on_site_link_activated)
        self.__ui.scrapers_table.setItemDelegateForColumn(SCRAPER_COLUMN, scraper_column_delegate)
        self.__ui.persona_path_link.linkActivated.connect(self.__on_path_link_activated)
        self.__ui.scanned_path_link.linkActivated.connect(self.__on_path_link_activated)
        self.__ui.browse_button.clicked.connect(self.__on_browse_clicked)
        self.__ui.reload_button.clicked.connect(self.__on_reload_clicked)
        self.__ui.browser_combo.currentIndexChanged.connect(self.__update_persona_path_link)
        self.__ui.open_browser_button.clicked.connect(self.__on_open_browser_clicked)
        self.__ui.reset_persona_button.clicked.connect(self.__on_reset_persona_clicked)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether any staged value differs from what the shared settings currently hold."""
        settings = shared_scrapers_settings()
        return (
            self.__ui.folder_edit.text() != settings.scripts_folder
            or self.__staged_browser() != settings.browser
            or self.__ui.show_browser_check.isChecked() != settings.show_browser
            or self.__model.browser_scrapers() != settings.browser_scrapers
        )

    def save_changes(self) -> None:
        """Persist every staged value and reload the shared registry from the folder."""
        settings = shared_scrapers_settings()
        settings.scripts_folder = self.__ui.folder_edit.text()
        settings.browser = self.__staged_browser()
        settings.show_browser = self.__ui.show_browser_check.isChecked()
        settings.browser_scrapers = self.__model.browser_scrapers()
        settings.save(persistent_settings())
        shared_scraper_registry().reload()
        self.__refresh_table()

    def drop_changes(self) -> None:
        """Discard every staged edit, re-seeding the fields from the shared settings."""
        settings = shared_scrapers_settings()
        self.__ui.folder_edit.setText(settings.scripts_folder)
        self.__set_staged_browser(settings.browser)
        self.__ui.show_browser_check.setChecked(settings.show_browser)
        self.__refresh_table()
        self.__model.set_browser_scrapers(settings.browser_scrapers)

    def seed_defaults(self) -> None:
        """Stage every factory value: what an unloaded `ScrapersSettings` holds (#342). The table's
        rows are left alone: they always show the *saved* folder's scan, never the one being typed."""
        defaults = ScrapersSettings()
        self.__ui.folder_edit.setText(defaults.scripts_folder)
        self.__set_staged_browser(defaults.browser)
        self.__ui.show_browser_check.setChecked(defaults.show_browser)
        self.__model.set_browser_scrapers(defaults.browser_scrapers)

    def __refresh_table(self) -> None:
        """Show the registry's current rows, and name the folder they came from."""
        registry = shared_scraper_registry()
        self.__model.set_rows(registry.rows)
        folder = shared_scrapers_settings().effective_scripts_folder
        self.__set_path_link(self.__ui.scanned_path_link, folder)

    def __on_site_link_activated(self, href: str) -> None:
        """Open a clicked Scraper-cell link in the persona browser -- a new tab if it is already open,
        a fresh window otherwise, both `~.browser_fetcher.PersonaBrowser.open_for_login`'s own doing.

        :param href: the site URL `~.scrapers_scraper_column_delegate.ScrapersScraperColumnDelegate`
            reported as clicked.
        """
        browser = self.__staged_browser()
        self.__run_persona_action(
            lambda: shared_persona_browser().open_for_login(browser, href), self.__on_open_finished
        )

    def __staged_browser(self) -> Browser:
        """Which `Browser` the combo box currently shows, by its position among :data:`BROWSER_LABELS`."""
        return BROWSER_LABELS[self.__ui.browser_combo.currentIndex()][0]

    def __set_staged_browser(self, browser: Browser) -> None:
        """Select ``browser``'s entry in the combo box."""
        index = next(position for position, (candidate, _label) in enumerate(BROWSER_LABELS) if candidate is browser)
        self.__ui.browser_combo.setCurrentIndex(index)
        self.__update_persona_path_link()

    def __update_persona_path_link(self) -> None:
        """Show the staged browser's own persona folder, so **Reset persona…** never surprises."""
        self.__set_path_link(self.__ui.persona_path_link, persona_folder(self.__staged_browser()))

    @staticmethod
    def __set_path_link(label: ElidedLabel, folder: object) -> None:
        """Show ``folder`` elided, as a link that reveals it in the OS file browser (#278).

        :param label: the `~borco_pyside.widgets.ElidedLabel` to fill.
        :param folder: the path to show -- a `pathlib.Path` or anything `str`-able the same way.
        """
        text = str(folder)
        label.set_text(text, href=QUrl.fromLocalFile(text).toString(), hint=REVEAL_HINT)

    def __on_path_link_activated(self, href: str) -> None:
        """Reveal a clicked path link's folder in the OS file browser -- not opened *into*, since
        neither the persona nor the scripts folder is meant to be browsed as a document (#278).

        :param href: the ``file://`` URL an `~borco_pyside.widgets.ElidedLabel` link carried.
        """
        reveal_in_file_browser(Path(QUrl(href).toLocalFile()))

    def __on_browse_clicked(self) -> None:
        """Pick the scripts folder with a file dialog, leaving a cancelled pick untouched."""
        folder = QFileDialog.getExistingDirectory(self, "Locate scraper scripts folder", self.__ui.folder_edit.text())
        if folder:
            self.__ui.folder_edit.setText(folder)

    def __on_reload_clicked(self) -> None:
        """Re-scan the saved folder and refresh the table."""
        shared_scraper_registry().reload()
        self.__refresh_table()

    def __on_open_browser_clicked(self) -> None:
        """Bring up the staged browser's persona, for the user to log in to any site by hand.

        Runs off the GUI thread (#278): starting a browser, especially on a brand-new persona Selenium
        Manager must still fetch a driver for, can take several seconds, and the settings dialog must
        not freeze for them.
        """
        browser = self.__staged_browser()
        self.__run_persona_action(lambda: shared_persona_browser().open_for_login(browser), self.__on_open_finished)

    def __on_open_finished(self, error: object) -> None:
        """Report Open the browser's outcome -- see :meth:`__run_persona_action`."""
        self.__set_persona_controls_enabled(True)
        if error is not None:
            QMessageBox.warning(self, "Open the browser", str(error))

    def __on_reset_persona_clicked(self) -> None:
        """Confirm, then delete the staged browser's persona folder -- logging out of every site.

        Also runs off the GUI thread: quitting a live session can itself hang, exactly when the browser
        process it is quitting has stopped responding -- the state a reset is often reached for.
        """
        browser = self.__staged_browser()
        label = next(name for candidate, name in BROWSER_LABELS if candidate is browser)
        answer = QMessageBox.question(self, "Reset persona", RESET_PERSONA_QUESTION.format(browser=label))
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.__run_persona_action(lambda: shared_persona_browser().reset(browser), self.__on_reset_finished)

    def __on_reset_finished(self, error: object) -> None:
        """Report Reset persona's outcome -- see :meth:`__run_persona_action`."""
        self.__set_persona_controls_enabled(True)
        if error is not None:
            QMessageBox.warning(self, "Reset persona", str(error))

    def __run_persona_action(self, action: Callable[[], None], finished: Callable[[object], None]) -> None:
        """Run ``action`` on `~rehuco_agent.scraping.browser_fetcher.PersonaAction`'s pool thread,
        disabling the controls it could race with meanwhile.

        The `PersonaAction` is deliberately not kept in an instance attribute -- the same reasoning
        `~rehuco_agent.fields.background_measurement.measure_in_background` gives for its own runner:
        the ``finished`` connection made here keeps it alive for as long as this page does, and the
        callable its `~.browser_fetcher.PersonaAction.start` hands the thread pool keeps it alive for
        as long as ``action`` takes.

        **``finished`` must be a bound method of this page, never a lambda.** `PersonaAction.finished`
        fires on the worker thread; Qt's automatic queued-connection only marshals that onto the GUI
        thread when it can see the receiver's own thread affinity, which it reads off a bound method's
        `QObject`. A lambda has none, and the call would instead run *on the worker thread*, touching
        these widgets from outside the GUI thread -- the same pitfall
        `~rehuco_agent.scraping.scrape_job.ScrapeJob.Marshaller` documents for its own relay.

        :param action: the persona call to make.
        :param finished: a bound method of this page to report the outcome to.
        """
        self.__set_persona_controls_enabled(False)
        job = PersonaAction()
        job.finished.connect(finished)
        job.start(action)

    def __set_persona_controls_enabled(self, enabled: bool) -> None:
        """Enable or disable every control an in-flight persona action could race with.

        :param enabled: whether the controls should accept input.
        """
        self.__ui.open_browser_button.setEnabled(enabled)
        self.__ui.reset_persona_button.setEnabled(enabled)
        self.__ui.browser_combo.setEnabled(enabled)
