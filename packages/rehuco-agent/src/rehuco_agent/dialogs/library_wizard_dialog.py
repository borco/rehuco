"""The one dialog that starts a store's library scan into a root of the open catalog
([[acquisition-tooling#library-wizard-protocol]], #685).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Final, override

from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPushButton, QWidget
from rehuco_core import ASSET_PLUGIN, MappedRoot, layout_templates

from ..scraping.browser_fetcher import PersonaAction, shared_persona_browser
from ..scraping.library_scan_job import LibraryScanTarget
from ..scraping.scraper_wizard import ScraperWizard
from ..settings.library_wizard_settings import LibraryWizardSettings
from ..settings.persistent_settings import persistent_settings
from ..settings.scrapers_settings import shared_scrapers_settings
from .library_root_delegate import LOCATION_ROLE, LibraryRootDelegate
from .library_wizard_dialog_ui import Ui_LibraryWizardDialog

START_TEXT: Final = "Start"
"""What the OK button says: it enqueues the scan."""


class LibraryWizardDialog(QDialog):
    """Asks which store to scan, into which root, and whether to read the whole library again; **Start** accepts.

    A root that takes no ``asset`` is listed disabled, the reason as its tooltip. **Login** opens the persona browser,
    unautomated, for the user to sign in to the store; Start is not held back while it is open, a scan that cannot
    take the profile pauses and says so. The root last started into is saved per wizard on Start, and preselected
    when that site is next chosen, a site with none keeping the root already chosen; the full-rescan box starts
    unticked every time.

    :param wizards: the scraper wizards the user picks the site from, in the order shown.
    :param roots: the roots of the open catalog this machine reaches.
    :param cache_path: the catalog's ``.rehudb``.
    :param settings: the roots last used, which Start updates.
    :param parent: optional Qt parent.
    """

    def __init__(
        self,
        wizards: Sequence[ScraperWizard],
        roots: Sequence[MappedRoot],
        cache_path: Path,
        settings: LibraryWizardSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_LibraryWizardDialog()
        self.__ui.setupUi(self)
        self.__wizards: Final = tuple(wizards)
        self.__roots: Final = tuple(roots)
        self.__cache_path: Final = cache_path
        self.__settings: Final = settings
        self.__action: Final = PersonaAction(self)
        self.ok_button.setText(START_TEXT)

        self.__model: Final = QStandardItemModel(self)
        for root in self.__roots:
            self.__model.appendRow(self.__item_of(root))
        self.__ui.root_combo.setModel(self.__model)
        self.__ui.root_combo.view().setItemDelegate(LibraryRootDelegate(self.__ui.root_combo))
        self.__ui.root_combo.setCurrentIndex(-1)
        self.__ui.site_combo.addItems([wizard.label for wizard in self.__wizards])

        self.__ui.site_combo.currentIndexChanged.connect(self.__on_site_changed)
        self.__ui.root_combo.currentIndexChanged.connect(self.__update_start)
        self.__ui.login_button.clicked.connect(self.__on_login_clicked)
        self.__action.finished.connect(self.__on_login_finished)
        self.__on_site_changed()

    @property
    def ok_button(self) -> QPushButton:
        """The Start button, for tests."""
        return self.__ui.button_box.button(QDialogButtonBox.StandardButton.Ok)

    @property
    def wizard(self) -> ScraperWizard | None:
        """The wizard whose site is chosen; ``None`` when the list is empty."""
        index = self.__ui.site_combo.currentIndex()
        return self.__wizards[index] if index >= 0 else None

    @property
    def target(self) -> LibraryScanTarget | None:
        """What to scan as the dialog stands; ``None`` until a site and a root are chosen."""
        wizard, root = self.wizard, self.__chosen_root()
        if wizard is None or root is None or root.file is None:
            return None
        return LibraryScanTarget(
            wizard.key,
            root.root_id,
            root.label or str(root.path),
            root.file,
            self.__cache_path,
            self.__ui.full_rescan_check.isChecked(),
        )

    @override
    def accept(self) -> None:
        """Remember the root for the site, then close accepted."""
        wizard, root = self.wizard, self.__chosen_root()
        if wizard is not None and root is not None:
            self.__settings.roots[wizard.key] = root.root_id  # pylint: disable=unsupported-assignment-operation
            self.__settings.save(persistent_settings())
        super().accept()

    def __item(self, index: int) -> QStandardItem:
        """A root's item in the list.

        :param index: its position.
        :returns: the item.
        """
        item = self.__model.item(index)
        assert item is not None  # nosec B101  # a position of a root the list was built from
        return item

    def __chosen_root(self) -> MappedRoot | None:
        """The root the list shows, when it is one that can be scanned into.

        :returns: the root; ``None`` when none is chosen or the chosen one is disabled.
        """
        index = self.__ui.root_combo.currentIndex()
        if index < 0 or not self.__item(index).isEnabled():
            return None
        return self.__roots[index]

    @staticmethod
    def __item_of(root: MappedRoot) -> QStandardItem:
        """A root's line in the list: its label, its location beneath, disabled with the reason when no scan can go in.

        :param root: the root.
        :returns: the item.
        """
        name = root.label or str(root.path)
        item = QStandardItem(name)
        item.setData(root.location, LOCATION_ROLE)
        item.setEditable(False)
        reason = LibraryWizardDialog.__refusal(root, name)
        if reason:
            item.setEnabled(False)
            item.setToolTip(reason)
        return item

    @staticmethod
    def __refusal(root: MappedRoot, name: str) -> str:
        """Why a root takes no scan, or ``""`` when it does.

        :param root: the root.
        :param name: how the root is named.
        :returns: the reason, as a sentence.
        """
        if root.file is None:
            return f"{name} was not read from a .rehuroot file, which places the records."
        if not layout_templates(root, ASSET_PLUGIN.key):
            return f"{name} does not take an asset: its layouts name no such type, and no '*'."
        return ""

    def __on_site_changed(self) -> None:
        """Choose the root this site was last started into, if it is still listed and can take the scan; a site with
        none keeps the root already chosen, since one root takes the items of several stores."""
        wizard = self.wizard
        saved = None if wizard is None else self.__settings.roots.get(wizard.key)
        row = next(
            (
                position
                for position, root in enumerate(self.__roots)
                if root.root_id == saved and self.__item(position).isEnabled()
            ),
            None,
        )
        if row is not None:
            self.__ui.root_combo.setCurrentIndex(row)
        self.__update_start()

    def __update_start(self) -> None:
        """Let Start through only while a site and a root that can take the scan are chosen."""
        self.ok_button.setEnabled(self.target is not None)

    def __on_login_clicked(self) -> None:
        """Open the persona browser at the site's page, off the GUI thread; a second click brings the window forward."""
        self.__ui.login_error_label.clear()
        self.__ui.login_error_label.hide()
        wizard = self.wizard
        url = getattr(wizard, "site_url", None)
        browser = shared_scrapers_settings().browser
        persona = shared_persona_browser()
        self.__action.start(lambda: persona.open_for_login(browser, url if isinstance(url, str) and url else None))

    def __on_login_finished(self, error: object) -> None:
        """Say in the dialog why the browser could not be opened.

        :param error: ``None`` when it opened, the failure's message otherwise.
        """
        if error is not None:
            self.__ui.login_error_label.setText(str(error))
            self.__ui.login_error_label.show()
