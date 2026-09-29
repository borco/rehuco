"""The document toolbar's Search the Web action: the location's words, searched for in the default browser
(#388).

The query is :func:`~rehuco_agent.documents.web_search_query.web_search_query` of the document's location
on disk -- the parent folder's name for an ``info.rehu``, the file's stem for a ``foo.rehu``
(:attr:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.current_name`) -- put into the
chosen engine's URL template
(:mod:`rehuco_agent.settings.web_search_settings`). The action only reads, so a locked document keeps it
enabled; it is disabled while the query is empty (a document with no path yet), and its tooltip names the
query it would search for.
"""

from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices

from ..settings.web_search_settings import WebSearchSettings, search_url, shared_web_search_settings
from .rehu_document_model import RehuDocumentModel
from .web_search_query import web_search_query

ICON_RESOURCE: Final = ":/icons/web_search.svg"
TOOLTIP: Final = "Search the web for: {query}"
EMPTY_TOOLTIP: Final = "Search the web for the location (the document has no location words to search for)"


class WebSearchAction(QObject):
    """Owns the toolbar's Search the Web `QAction` and keeps it in step with the location and the engine.

    :param model: the document whose location is searched for.
    :param settings: the engine settings; the shared ones unless a caller says otherwise.
    :param parent: optional Qt parent.
    """

    def __init__(
        self,
        model: RehuDocumentModel,
        settings: WebSearchSettings | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__settings: Final = settings or shared_web_search_settings()
        self.__action: Final = QAction("Search the Web", self)
        ActionIconThemeHandler(self.__action, ICON_RESOURCE)
        self.__action.triggered.connect(self.search)
        model.path_changed.connect(self.__update)  # type: ignore[attr-defined]
        self.__update()

    @property
    def action(self) -> QAction:
        """The toolbar action."""
        return self.__action

    @property
    def query(self) -> str:
        """What a click searches for: the document's location name, reduced to its words."""
        return web_search_query(self.__model.current_name)

    def search(self) -> None:
        """Open the chosen engine's results for :attr:`query` in the default browser; nothing when the
        query is empty."""
        query = self.query
        if query:
            QDesktopServices.openUrl(QUrl(search_url(self.__settings.selected.url, query)))

    def __update(self, *_args: object) -> None:
        """Re-derive the enabled state and the tooltip from the location and the engine."""
        query = self.query
        self.__action.setEnabled(bool(query))
        self.__action.setToolTip(TOOLTIP.format(query=query) if query else EMPTY_TOOLTIP)
