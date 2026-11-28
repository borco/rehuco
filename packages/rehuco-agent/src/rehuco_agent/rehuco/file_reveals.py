"""Open a browser's selected records in the system's file browser (#720): the helper behind its *Open in Explorer*."""

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from borco_pyside.file_browser import FILE_BROWSER_NAME, reveal_in_file_browser
from PySide6.QtWidgets import QMessageBox, QWidget

from .web_pages import PAGES_WITHOUT_ASKING

LOG: Final = logging.getLogger(__name__)

OPEN_IN_FILE_BROWSER_TEXT: Final = f"Open in {FILE_BROWSER_NAME}"
"""The browser menu's entry that reveals the selected records: *Open in Explorer*, *Open in Finder* or *Open in file
manager*."""


def confirm_open_places(parent: QWidget, count: int) -> bool:
    """Ask whether to open that many places at once. The one modal behind *Open in Explorer*, so a test replaces it.

    :param parent: the widget the question is for.
    :param count: how many places would open.
    :returns: whether to go ahead; Cancel is the default.
    """
    answer = QMessageBox.question(
        parent,
        OPEN_IN_FILE_BROWSER_TEXT,
        f"Open {count:,} places in {FILE_BROWSER_NAME}?",
        QMessageBox.StandardButton.Open | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel,
    )
    return answer == QMessageBox.StandardButton.Open


def reveal_places(parent: QWidget, places: Sequence[Path]) -> None:
    """Reveal ``places`` in the system's file browser, once confirmed if there are more than
    :data:`~.web_pages.PAGES_WITHOUT_ASKING` -- each is a window or a tab.

    :param parent: the widget the question is for.
    :param places: a folder to open or a file to select, in the order they open; one that is gone, with its folder,
        opens nothing and is named in the log at INFO.
    """
    if len(places) > PAGES_WITHOUT_ASKING and not confirm_open_places(parent, len(places)):
        return
    for place in places:
        if not reveal_in_file_browser(place):
            LOG.info("%s is not opened in the file browser: neither it nor its folder was found", place)
