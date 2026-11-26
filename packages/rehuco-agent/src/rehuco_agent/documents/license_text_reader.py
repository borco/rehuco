"""Reads the text of a license picked from the License dock's presets, off the GUI thread ([[assets#licenses]],
#705)."""

import logging
import threading
from typing import Final

from PySide6.QtCore import QObject, Signal

from ..scraping.library_site import StoreOfflineError
from ..scraping.protocols import FetchError
from ..scraping.sites.fab_license_texts import FabLicenseTexts, fetch_public_json

LOG: Final = logging.getLogger(__name__)


class LicenseTextReader(QObject):
    """Reads a license's text from the address its preset states, over plain HTTP as *Refresh License* does, each read
    on a daemon thread of its own so a store that does not answer never holds up the window or quitting.

    **A text that cannot be read is logged, never shown**: the license keeps no text, which a later *Refresh License*
    fills in. A text read after the reader is gone -- its document closed meanwhile -- is dropped.

    :param parent: optional Qt parent.
    """

    text_read = Signal(str, str, object)
    """A text was read: the license's id, the address it was read from, and its
    :class:`~rehuco_core.LicenseTerms`. Emitted from the reading thread, so a receiver on the GUI thread gets it
    queued."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.__gone: Final = threading.Event()
        # a reader torn down must not be emitted into from a read's thread after its C++ object is gone: ``set`` is a
        # plain Python bound method, safe to run from here
        self.destroyed.connect(self.__gone.set)

    def read(self, license_id: str, url: str) -> None:
        """Start reading a license's text.

        :param license_id: the license's id, handed back with the text.
        :param url: where its terms are stated.
        """
        threading.Thread(target=self.__read, args=(license_id, url), name="license-text-reader", daemon=True).start()

    def __read(self, license_id: str, url: str) -> None:
        """Read one text and hand it over; on the reading thread.

        :param license_id: the license's id.
        :param url: where its terms are stated.
        """
        try:
            terms = FabLicenseTexts(fetch_public_json).read_url(url)
        except (StoreOfflineError, FetchError) as error:
            LOG.warning("The text of the license %s could not be read from %s: %s", license_id, url, error)
            return
        if terms is None:
            LOG.info("No text is known for the license %s at %s.", license_id, url)
            return
        if self.__gone.is_set():
            return
        try:
            self.text_read.emit(license_id, url, terms)
        except RuntimeError:  # the read outlived its reader between the test and the emit
            pass
