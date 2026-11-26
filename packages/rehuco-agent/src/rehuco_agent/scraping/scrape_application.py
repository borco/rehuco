"""What a scrape result writes onto a record, in one place ([[acquisition-tooling#scrape-job]],
[[acquisition-tooling#library-scan-job]]).

A URL dropped on an open document fills it (`~rehuco_agent.documents.scrape_actions.ScrapeActions`) and a library
scan fills a record it is creating (`~.library_scan_job.LibraryScanJob`); both write a `~.results.ScrapeResult` by
these rules, so an item filed by a drop and the same item filed by a scan read alike. The open document is its
model, written as an ordinary dirty edit on the GUI thread; the new record is a bare `~rehuco_core.RehuDocument`, on
the worker -- so what is written is reached through :class:`ScrapeTarget`, which both satisfy, the second through
`~.document_scrape_target.DocumentScrapeTarget`.
"""

import logging
from collections.abc import Callable, Collection
from typing import Any, Final, Protocol, cast

from rehuco_core import SITE_ID_KEY, AssetLicense

from .markdown_images import substitute_image_stem
from .results import ScrapedImage, ScrapeResult

LOG: Final = logging.getLogger(__name__)

SOURCE_FIELD_NAMES: Final = frozenset({"description", "url", SITE_ID_KEY})
"""The scraped fields that are not written as a field: ``url`` and ``site_id`` land on a source, and ``description``
is written with the scrape's own Markdown (:meth:`ScrapeApplication.apply`)."""

FIELD_READERS: Final[dict[str, Callable[[Any], object]]] = {"licenses": AssetLicense.read_list}
"""How a scraped field whose value the targets hold as objects is read from its JSON before it is written: an asset's
``licenses`` arrive as ``{license, url?}`` objects and are written as `~rehuco_core.AssetLicense` entries (#705)."""


class ScrapeTarget(Protocol):
    """What a scrape result's sources are written onto: the primary source's three fields, and the source list.

    The model satisfies it through its `~borco_pyside.core.SimpleProperty` attributes, which pyright reads by their
    class-access overload as ``SimpleProperty | str`` and so will not match to a property: the model is cast at its
    two call sites, which is the whole of the gap.
    """

    @property
    def title(self) -> str:  # pyright: ignore[reportReturnType]
        """The primary source's title, which a source added below it repeats."""

    @property
    def publisher(self) -> str:  # pyright: ignore[reportReturnType]
        """The primary source's publisher."""

    @publisher.setter
    def publisher(self, value: str) -> None: ...

    @property
    def url(self) -> str:  # pyright: ignore[reportReturnType]
        """The primary source's URL."""

    @url.setter
    def url(self, value: str) -> None: ...

    @property
    def sources(self) -> list[Any]:  # pyright: ignore[reportReturnType]
        """The ``sources`` list ([[field-schema#sources]]), replaced whole when set."""

    @sources.setter
    def sources(self, value: list[Any]) -> None: ...


class ScrapeApplication:
    """The rules a scrape result is written by: which fields, what becomes a source, and what the description is."""

    @staticmethod
    def apply(  # pylint: disable=too-many-arguments  # what to write, onto what, and how each target takes a field
        target: ScrapeTarget,
        result: ScrapeResult,
        *,
        publisher: str,
        page_url: str,
        image_stem: str,
        declared: Collection[str],
        write_field: Callable[[str, object], None],
    ) -> tuple[ScrapedImage, ...]:
        """Write ``result`` onto ``target``, and hand back the images it names for the caller to fetch.

        A field the target's type does not declare is left unset and logged. A scraped ``url`` is a source rather
        than a field: a scraper that recognizes a canonical URL for the page it read (ArtStation's store host, #366)
        hands it over, and it goes through :meth:`add_source` ahead of the page itself -- so it fills an empty
        primary, or is kept beside the sources already there, never overwriting one; a scraped ``site_id`` goes with
        it onto that source, else onto the page's ([[assets#site-id]]).

        :param target: what to write onto.
        :param result: a validated result.
        :param publisher: the scraper's publisher, which the added sources carry.
        :param page_url: the page the result was read from, added as a source.
        :param image_stem: the stem the record's screenshots are numbered under -- its file's stem, ``info`` for a
            directory-scoped record -- which an embedded image placeholder becomes, so the Markdown names the files
            the images are written as (:func:`~.markdown_images.substitute_image_stem`).
        :param declared: the field names the target's type declares.
        :param write_field: writes one declared field onto the target, the description included.
        :returns: the result's images, in slot order.
        """
        for name, value in result.fields.items():
            if name in SOURCE_FIELD_NAMES:
                continue
            if name not in declared:
                LOG.info("%s is not a field of this document's type; left unset.", name)
                continue
            reader = FIELD_READERS.get(name)
            write_field(name, value if reader is None else reader(value))
        canonical_url = result.fields.get("url")
        site_id = cast("str | None", result.fields.get(SITE_ID_KEY))
        if isinstance(canonical_url, str) and canonical_url:
            ScrapeApplication.add_source(target, publisher, canonical_url, site_id)
            site_id = None
        description = result.description
        if description is None:
            raw = result.fields.get("description")
            description = raw if isinstance(raw, str) else None
        else:
            description = substitute_image_stem(description, image_stem)
        if description is not None and "description" in declared:
            write_field("description", description)
        ScrapeApplication.add_source(target, publisher, page_url, site_id)
        return result.images

    @staticmethod
    def add_source(target: ScrapeTarget, publisher: str, url: str, site_id: str | None = None) -> None:
        """Add a scraped page as a source ([[field-schema#sources]], #272), never a duplicate of one already there by
        ``url``.

        Three cases, decided by ``url`` alone (#366, #386), with URLs compared after trimming: a source with this
        ``url`` **already exists** -- its ``publisher`` is filled in if empty and it is otherwise left as it is, so a
        re-scrape never duplicates it and never relabels a publisher the document already names; the top source (the
        primary) **has no url** -- it takes this one, with or without a publisher, and takes the scraper's publisher
        only if it names none; or the ``url`` is **new** -- appended below whatever the document already has, never
        overwriting a source from an earlier drop or a `.tc` migration. The primary is filled through
        :attr:`ScrapeTarget.url` and :attr:`ScrapeTarget.publisher`, so a model's dirty tracking sees an edit through
        those fields; the other writes go through :attr:`ScrapeTarget.sources`. A ``site_id`` follows the
        publisher's rule: it fills the source this ``url`` lands on only when that source names none
        ([[assets#site-id]]).

        :param target: what to add the source to.
        :param publisher: the scraper's publisher -- fills the matching or primary source's own empty ``publisher``,
            and seeds a new entry's.
        :param url: the scraped page's URL.
        :param site_id: the store's own id for the item, when the scraper reported one.
        """
        url = url.strip()
        sources = target.sources
        match = next(
            (
                row
                for row, source in enumerate(sources)
                if isinstance(source, dict) and str(source.get("url") or "").strip() == url
            ),
            None,
        )
        if match is None and target.url.strip():
            added = {"title": target.title, "publisher": publisher, "url": url}
            target.sources = [*sources, {**added, SITE_ID_KEY: site_id} if site_id else added]
            return
        if match is None:
            target.url = url
            match = 0
        if match == 0:
            if not target.publisher:
                target.publisher = publisher
        elif not sources[match].get("publisher"):
            target.sources = [*sources[:match], {**sources[match], "publisher": publisher}, *sources[match + 1 :]]
        sources = target.sources
        if site_id and not sources[match].get(SITE_ID_KEY):
            target.sources = [*sources[:match], {**sources[match], SITE_ID_KEY: site_id}, *sources[match + 1 :]]
