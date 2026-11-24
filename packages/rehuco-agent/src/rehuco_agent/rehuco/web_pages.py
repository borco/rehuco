"""Which of a record's URLs is a web page (#679): the one rule behind the Roots preview's link and a browser's *Open in
Web Browser*."""

from collections.abc import Sequence
from typing import Final

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

OPENABLE_SCHEMES: Final = frozenset({"http", "https"})
"""The schemes a record's URL is a link for, when it names a host. A ``.rehu`` is outside input, so what it says is
shown, and only a web address is handed to the system to open."""

PAGES_WITHOUT_ASKING: Final = 10
"""How many pages are opened without asking: one more and it asks first, since each is a tab."""


def is_web_page(url: str) -> bool:
    """Whether ``url`` is a web address, the only kind handed to the system to open.

    :param url: a record's URL, as it is stored.
    :returns: ``True`` for an ``http`` or ``https`` address that names a host, whatever the case of its scheme.
    """
    parsed = QUrl(url)
    return parsed.scheme().lower() in OPENABLE_SCHEMES and bool(parsed.host())


def confirm_open_pages(parent: QWidget, count: int) -> bool:
    """Ask whether to open that many pages at once. The one modal behind *Open in Web Browser*, so a test replaces it.

    :param parent: the widget the question is for.
    :param count: how many pages would open.
    :returns: whether to go ahead; Cancel is the default.
    """
    answer = QMessageBox.question(
        parent,
        "Open in Web Browser",
        f"Open {count:,} pages in the web browser?",
        QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return answer == QMessageBox.StandardButton.Open


def open_web_pages(parent: QWidget, pages: Sequence[str]) -> None:
    """Open ``pages`` in the system's browser, once confirmed if there are more than :data:`PAGES_WITHOUT_ASKING`.

    :param parent: the widget the question is for.
    :param pages: the addresses, in the order they open.
    """
    if len(pages) > PAGES_WITHOUT_ASKING and not confirm_open_pages(parent, len(pages)):
        return
    for page in pages:
        QDesktopServices.openUrl(QUrl(page))
