"""The text of a Fab license ([[assets#licenses]], [[acquisition-tooling#library-scan-job]], #684, #688): one reader for
what the library scan saves with a new record and what *Refresh License* compares a record's saved text with.

Fab has two kinds of text: the Standard License, public JSON whose ``body`` is HTML, and Creative Commons BY's plain
legal code, a page of its own. The Marketplace license has none. **Neither needs the account**, so a refresh reads them
over plain HTTP; the scan hands in its own way of fetching Fab's JSON, the persona's.

A text is read with its line endings as LF, whatever the server sent: a saved text is compared with a fresh one, and
the same terms must not differ for the way a page ends its lines.
"""

import datetime
import json
import logging
from collections.abc import Callable
from typing import Any, Final

import requests
from rehuco_core import LicenseTerms

from ..html_markdown import HtmlMarkdown
from ..http_fetcher import HttpPageFetcher
from ..library_site import StoreOfflineError
from ..protocols import FetchError, LoginRequiredError
from .fab import EULA_URL, LICENSES, SITE_URL

LOG: Final = logging.getLogger(__name__)

EULA_JSON_URL: Final = SITE_URL + "/i/eula/fab_eula"
"""The Standard License's text, public JSON whose ``body`` is HTML."""

EULA_TITLE: Final = "Standard License"
"""What the Standard License's sidecar is titled: Fab's own name for the group."""

CC_TEXTS: Final = {
    "license/cc/cc-by": (
        "Creative Commons Attribution 4.0 International (CC BY 4.0)",
        "https://creativecommons.org/licenses/by/4.0/legalcode.txt",
    ),
}
"""The licenses whose text is a page of its own, by Fab's path: the title the sidecar takes and where the plain text is
read. Fab's *Creative Commons* tiers all arrive as ``license/cc/cc-by``, the generic index its group links to being no
text."""

STANDARD_PATH_PREFIX: Final = "license/standard/"
"""What the path of each Standard License tier starts with: one text covers them all."""

LICENSE_URL_PATHS: Final = {
    EULA_URL.casefold(): STANDARD_PATH_PREFIX,
    LICENSES[("cc", "cc-by")][1].rstrip("/").casefold(): "license/cc/cc-by",
}
"""The ``license_url`` a record states, as :meth:`FabLicenseTexts.path_of_url` spells it, to a path
:meth:`FabLicenseTexts.read` reads: the two texts Fab's listings point at. The URL of a record is the license's own
page, which is not always where its text is read from -- the Creative Commons page is HTML and its legal code is a file
beside it."""


class FabLicenseTexts:
    """Reads the text of a Fab license, by its Fab path or by the address a record states for it.

    :param get_json: how Fab's JSON is fetched: given an address, the object it answers. The persona's in a library
        scan, :func:`fetch_public_json` over plain HTTP anywhere else.
    """

    def __init__(self, get_json: Callable[[str], dict[str, Any]]) -> None:
        self.__get_json: Final = get_json

    @staticmethod
    def path_of_url(url: str) -> str | None:
        """The path a record's ``license_url`` is read through, if there is a text for it.

        :param url: the address a record states, any case, with or without its closing slash.
        :returns: a path :meth:`read` accepts; ``None`` for an address no reader here knows.
        """
        return LICENSE_URL_PATHS.get(url.strip().rstrip("/").casefold())

    def read(self, path: str) -> LicenseTerms | None:
        """Read a license's text.

        :param path: Fab's stable id for the license (``license/cc/cc-by``).
        :returns: the terms, read today; ``None`` for a license Fab states no text for, the Marketplace's.
        :raises StorePausedError: the persona's fetch was stopped by a challenge page or an expired login.
        :raises StoreOfflineError: Fab, or the page holding a Creative Commons text, does not answer.
        :raises FetchError: Fab's text is not the JSON it should be.
        """
        today = datetime.date.today()
        if path.startswith(STANDARD_PATH_PREFIX):
            body = self.__get_json(EULA_JSON_URL).get("body")
            if not isinstance(body, str) or not body:
                raise FetchError(f"Fab answered no text for its Standard License: {EULA_JSON_URL}")
            return LicenseTerms(EULA_TITLE, EULA_URL, today, FabLicenseTexts.__lf(HtmlMarkdown.convert(body)))
        if path in CC_TEXTS:
            title, url = CC_TEXTS[path]
            try:
                page = HttpPageFetcher().fetch(url)
            except (requests.RequestException, LoginRequiredError) as error:
                raise StoreOfflineError(f"The license text could not be read: {url}: {error}") from error
            # a refusal that passes comes back as a page: its body is never a license's text
            if page.status != 200 or not page.html.strip():
                raise StoreOfflineError(f"The license text could not be read: {url} answered {page.status}")
            return LicenseTerms(title, url, today, FabLicenseTexts.__lf(page.html.strip()))
        LOG.info("Fab states no text for the license %s.", path)
        return None

    def read_url(self, url: str) -> LicenseTerms | None:
        """Read the text of the license a record's ``license_url`` names.

        :param url: the address the record states.
        :returns: the terms, read today; ``None`` for an address no reader here knows.
        :raises StoreOfflineError: Fab, or the page holding a Creative Commons text, does not answer.
        :raises FetchError: Fab's text is not the JSON it should be.
        """
        path = FabLicenseTexts.path_of_url(url)
        return None if path is None else self.read(path)

    @staticmethod
    def __lf(text: str) -> str:
        """A text with its line endings as LF.

        :param text: the text as a server sent it.
        :returns: the text.
        """
        return text.replace("\r\n", "\n").replace("\r", "\n")


def fetch_public_json(url: str) -> dict[str, Any]:
    """One public JSON object of Fab's, over plain HTTP: no persona, no login.

    :param url: the address.
    :returns: the object.
    :raises StoreOfflineError: the request failed, or Fab answered something that is not a text -- a refusal that
        passes, a login wall.
    :raises FetchError: the answer is not a JSON object.
    """
    try:
        page = HttpPageFetcher().fetch(url)
    except (requests.RequestException, LoginRequiredError) as error:
        raise StoreOfflineError(f"The license text could not be read: {url}: {error}") from error
    if page.status != 200:
        raise StoreOfflineError(f"The license text could not be read: {url} answered {page.status}")
    try:
        data = json.loads(page.html)
    except ValueError as error:
        raise FetchError(f"Fab answered something that is not JSON: {url}") from error
    if not isinstance(data, dict):
        raise FetchError(f"Fab answered something that is not a JSON object: {url}")
    return data
