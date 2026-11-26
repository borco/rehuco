"""Opens what a log link names: a store's page in the user's browser, a library item's record in the documents dock
(#700, [[appendices.logging#surfaces]])."""

import logging
from collections.abc import Callable
from functools import partial
from typing import Final

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from rehuco_core import Catalog, CatalogRow

from ..documents.latest_runner import LatestRunner
from ..scraping.library_record_link import LibraryRecordLink
from .catalog_table_model import RowKey
from .web_pages import is_web_page

LOG: Final = logging.getLogger(__name__)

RECORD_NOT_FOUND: Final = "No record of this item is in the open catalog."
"""Why a title link opens nothing: the record was deleted or its root is no longer in the open catalog."""

RECORD_TAG: Final = "record"
"""What the runner is told its work is about; the one kind of lookup this opener makes."""


class LogLinkOpener(QObject):
    """Opens a clicked log link by what its target is.

    **A web address** goes to the system's browser, once :func:`~rehuco_agent.rehuco.web_pages.is_web_page` says it is
    one: a record's text is outside input, and only ``http`` and ``https`` are handed to the system.

    **A library item's record** is looked up by its store id in the open catalog **off the GUI thread**, and the row
    found is opened as a double-click on it in a browser would (``open_row``), so an unreachable root is refused with
    its reason the same way. The answer of a click a later one outdated is dropped
    (:class:`~rehuco_agent.documents.latest_runner.LatestRunner`).

    Anything else is logged and left alone.

    :param catalog: the catalog the record is looked up in.
    :param open_row: opens the record of a catalog row; reports a root it cannot open into by itself.
    :param parent: optional Qt parent.
    """

    refused = Signal(str)
    """Emitted with why a link opened nothing, for the status bar."""

    def __init__(self, catalog: Catalog, open_row: Callable[[RowKey], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__catalog: Final = catalog
        self.__open_row: Final = open_row
        self.__runner: Final = LatestRunner(self)
        self.__runner.read.connect(self.__on_found)

    def open(self, target: object) -> None:
        """Open a link's target.

        :param target: what the record's :class:`~borco_core.logging.LogLink` carried.
        """
        if isinstance(target, str) and is_web_page(target):
            QDesktopServices.openUrl(QUrl(target))
        elif isinstance(target, LibraryRecordLink):
            self.__runner.start(
                RECORD_TAG, partial(self.__catalog.find_by_site_id, target.site, target.site_id, target.root_id)
            )
        else:
            LOG.warning("A log link to %r is not one this app opens; left alone.", target)

    def __on_found(self, tag: str, result: object) -> None:
        """Open the record a lookup found, or say why nothing opened (GUI thread).

        :param tag: what the lookup was about.
        :param result: the row, ``None`` for no record, or the exception the lookup raised.
        """
        del tag
        if isinstance(result, CatalogRow):
            self.__open_row((result.root_id, result.record.path))
        elif isinstance(result, Exception):
            LOG.warning("A log link's record could not be looked up: %s", result)
            self.refused.emit(f"The record could not be looked up: {result}")
        else:
            self.refused.emit(RECORD_NOT_FOUND)
