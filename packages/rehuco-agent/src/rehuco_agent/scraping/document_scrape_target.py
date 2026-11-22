"""A bare record as a scrape result's target (#682): what a library scan writes a new record through, off the GUI
thread, by the rules a drop fills an open document by (:class:`~.scrape_application.ScrapeApplication`).
"""

from typing import Any, Final

from rehuco_core import CORE_FIELD_NAMES, RehuDocument

from .results import ScrapedImage, ScrapeResult
from .scrape_application import ScrapeApplication


class DocumentScrapeTarget:
    """A `~rehuco_core.RehuDocument` seen as a :class:`~.scrape_application.ScrapeTarget`: its sources primary first,
    as the editor holds them.

    :param document: the record to write onto; its type and its path are set already, so its fields are declared and
        its screenshots' stem is known.
    """

    def __init__(self, document: RehuDocument) -> None:
        self.__document: Final = document

    @property
    def title(self) -> str:
        """The primary source's title.

        :returns: the title.
        """
        return self.__document.title

    @property
    def publisher(self) -> str:
        """The primary source's publisher.

        :returns: the publisher.
        """
        return self.__document.publisher

    @publisher.setter
    def publisher(self, value: str) -> None:
        self.__document.publisher = value

    @property
    def url(self) -> str:
        """The primary source's URL.

        :returns: the URL.
        """
        return self.__document.url

    @url.setter
    def url(self, value: str) -> None:
        self.__document.url = value

    @property
    def sources(self) -> list[Any]:
        """The sources, primary first and unflagged, as an editor holds them
        (`~rehuco_core.RehuDocument.source_records`).

        :returns: a copy of the entries.
        """
        return self.__document.source_records

    @sources.setter
    def sources(self, value: list[Any]) -> None:
        self.__document.set_source_records(value)

    def apply(self, result: ScrapeResult, *, publisher: str, page_url: str) -> tuple[ScrapedImage, ...]:
        """Write ``result`` onto the record (:meth:`~.scrape_application.ScrapeApplication.apply`).

        :param result: a validated result.
        :param publisher: the scraper's publisher.
        :param page_url: the page the result was read from.
        :returns: the result's images, for the caller to fetch.
        :raises ValueError: the document has no path, so its screenshots have no stem.
        """
        document = self.__document
        if document.path is None:
            raise ValueError("A scraped record needs its path to name its screenshots")
        return ScrapeApplication.apply(
            self,
            result,
            publisher=publisher,
            page_url=page_url,
            image_stem=document.path.stem,
            declared=frozenset(CORE_FIELD_NAMES) | frozenset(document.plugins.field_names(document.type)),
            write_field=self.__write_field,
        )

    def __write_field(self, name: str, value: object) -> None:
        """Write one declared field: through the document's own property where it has one, so the value is stored as
        that property stores it, else into the type's block.

        :param name: the field.
        :param value: its scraped value.
        """
        accessor = getattr(type(self.__document), name, None)
        if isinstance(accessor, property) and accessor.fset is not None:
            setattr(self.__document, name, value)
        else:
            self.__document.set_active_field(name, value)
