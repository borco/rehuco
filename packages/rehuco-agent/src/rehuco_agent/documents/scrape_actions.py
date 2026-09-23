"""A URL dropped on the Main Editor dock, queued and applied as a reviewable field edit
([[acquisition-tooling#drag-drop-aids]], #272).

**Not the app-wide task queue.** A scrape runs on `~rehuco_agent.scraping.scraper_executor.ScraperExecutor`'s
own pool, submitted under this document's log scope so its fetch and parse are readable alongside the
app-wide log ([[acquisition-tooling#scrape-job]]).

**A result is applied only on the GUI thread, and only if the document is still open at the same path**
([[acquisition-tooling#scrape-job]]): a document closed or renamed while its page was being fetched simply
discards the result, logged under the scope it was submitted in.
"""

import logging
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlsplit

from borco_core.logging import LogScope
from borco_pyside.widgets import MessageBannerRow, MessageBannerSeverity
from PySide6.QtCore import QObject, Signal

from ..scraping.markdown_images import substitute_image_stem
from ..scraping.protocols import PageFetcher
from ..scraping.registry import ScraperRegistry, shared_scraper_registry
from ..scraping.results import Page, ScrapeResult
from ..scraping.scrape_job import NoScraperError, ScrapeError, ScrapeJob
from ..scraping.scraper_executor import ScraperExecutor, shared_scraper_executor
from ..scraping.url_drop import UrlDrop
from .document_fields import declared_field_names
from .rehu_document_model import RehuDocumentModel

LOG: Final = logging.getLogger(__name__)

BUSY_MESSAGE: Final = "Scraping {host}…"
"""What the banner says while a drop's scrape is in flight."""


class ScrapeActions(QObject):  # pylint: disable=too-many-instance-attributes
    """One document's scrape-on-drop: submits a `ScrapeJob` for a dropped `UrlDrop`, and applies its
    result as an ordinary dirty edit once it lands ([[acquisition-tooling#drag-drop-aids]]).

    **Applying a result never re-checks a value.** `ScrapeJob.scrape` already validated the whole result
    against the scrape-result schema before `result_ready` fired ([[acquisition-tooling#scraper-protocols]]),
    so this class only decides *which* fields this document's active type declares -- a field the result
    carries that the type does not is skipped, logged, never written.

    **Images are not downloaded here.** The image pipeline that does (#73) is a separate, later piece of
    work; a result carrying ``images`` is applied for its fields and description, and the image count is
    only logged.

    :param model: the document these actions are about.
    :param registry: where to look up a matching scraper; `None` uses the shared, process-wide instance.
    :param executor: what runs the scrape; `None` uses the shared, process-wide instance.
    :param fetcher: what fetches a URL drop's page when it carries no fragment; `None` uses
        `~.scrape_job.ScrapeJob`'s own default (`~.http_fetcher.HttpPageFetcher`) -- a real network
        fetch. Overridable for tests, the same reason `ScrapeJob` itself takes one.
    :param parent: optional Qt parent.
    """

    changed = Signal()
    """Fires when :attr:`notice` may have changed -- what the document's banner rebuilds on."""

    def __init__(
        self,
        model: RehuDocumentModel,
        registry: ScraperRegistry | None = None,
        executor: ScraperExecutor | None = None,
        fetcher: PageFetcher | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.__registry: Final = registry if registry is not None else shared_scraper_registry()
        self.__executor: Final = executor if executor is not None else shared_scraper_executor()
        self.__fetcher: Final = fetcher
        self.__pending: Final[dict[ScrapeJob, str]] = {}
        """Jobs submitted but not yet resolved, keyed to the path captured at submission -- kept alive
        because `ScraperExecutor.submit` requires it (the runnable is auto-deleted before the queued
        signal is delivered), and read back to decide whether the document is still the one that asked."""

        self.__last_failure = ""
        self.__last_error: ScrapeError | None = None
        self.__detached = False
        """Set by :meth:`detach`. Checked explicitly, rather than relying on dropping this object's own
        reference to a pending job: a job is kept alive by the very signal connection its result would
        arrive through (a closure over ``job`` connected to ``job``'s own signal), a reference cycle
        Python's cyclic collector does not promise to break before that queued signal is delivered."""

    # region What the document shows

    @property
    def notice(self) -> list[MessageBannerRow]:
        """The document's inline strip rows for the scrape currently in flight, if any, followed by the
        last failure, if one stands and nothing is running -- replaced by the next drop's own outcome."""
        rows: list[MessageBannerRow] = []
        for host in self.__pending.values():
            rows.append(MessageBannerRow(MessageBannerSeverity.INFO, BUSY_MESSAGE.format(host=host)))
        if not self.__pending and self.__last_failure:
            severity = (
                MessageBannerSeverity.INFO
                if isinstance(self.__last_error, NoScraperError)
                else MessageBannerSeverity.WARNING
            )
            rows.append(MessageBannerRow(severity, self.__last_failure))
        return rows

    def detach(self) -> None:
        """Stop reacting to this document's own scrapes, for a document that is being closed.

        The jobs themselves keep running -- there is nothing to cancel a fetch-and-parse for -- but
        their results are no longer applied once they land, the same discard a path change already
        gets.
        """
        self.__detached = True
        self.__pending.clear()

    # endregion

    # region Submitting

    def submit(self, drop: UrlDrop) -> None:
        """Queue a scrape for a dropped URL, under this document's log scope.

        :param drop: the parsed drop (`UrlDrop.parse`).
        """
        path = self.__model.path
        if path is None:
            return
        page = Page(url=drop.url, final_url=drop.url, html=drop.fragment) if drop.fragment is not None else None
        job = ScrapeJob(drop.url, self.__registry, page=page, fetcher=self.__fetcher)
        host = urlsplit(drop.url).hostname or drop.url
        self.__pending[job] = host  # pylint: disable=unsupported-assignment-operation
        self.__last_failure = ""
        job.result_ready.connect(lambda result: self.__on_result(job, path, result))
        job.failed.connect(lambda error: self.__on_failed(job, error))
        self.changed.emit()
        with LogScope.open(path):
            LOG.info("Scraping %s…", drop.url)
            self.__executor.submit(job)

    # endregion

    def __on_result(self, job: ScrapeJob, submitted_path: Path, result: object) -> None:
        """Apply a finished scrape's result, or discard it, on the GUI thread.

        :param job: the job that just resolved, dropped from :attr:`__pending` either way.
        :param submitted_path: the document's path when ``job`` was submitted.
        :param result: the `ScrapeResult`.
        """
        self.__pending.pop(job, None)
        if self.__detached:
            return
        self.changed.emit()
        # the scope the scrape was submitted under, re-opened by hand: this runs on the GUI thread off a
        # queued signal, which inherits nothing from the worker the job's own records were made on, so
        # what is said about applying (or discarding) the result would otherwise reach the app-wide log
        # alone and never the document's ([[appendices.logging#scopes]])
        with LogScope.open(submitted_path):
            if self.__model.path != submitted_path:
                LOG.info("Discarding a scrape result: the document is no longer at %s.", submitted_path)
                return
            if self.__model.locked:
                LOG.info("Discarding a scrape result: the document is locked.")
                return
            # not a runtime check: result_ready's payload is always a ScrapeResult, by ScrapeJob's own
            # contract -- Signal(object) is what PySide6 requires for a payload's exact type to survive
            # the C++ boundary at all (Qt's meta-object system has no template signals), so this cast is
            # purely for pyright, the same reason ScrapeJob.result_ready's own docstring states it.
            self.__apply(job, cast(ScrapeResult, result))

    def __on_failed(self, job: ScrapeJob, error: object) -> None:
        """Record a scrape's refusal for the banner, on the GUI thread.

        :param job: the job that just failed, dropped from :attr:`__pending` either way.
        :param error: the `ScrapeError`.
        """
        self.__pending.pop(job, None)
        if self.__detached:
            return
        # not a runtime check -- see __on_result's matching cast
        self.__last_error = cast(ScrapeError, error)
        self.__last_failure = str(error)
        self.changed.emit()

    def __apply(self, job: ScrapeJob, result: ScrapeResult) -> None:
        """Write a validated result's fields, description and source onto the model, as an ordinary
        dirty edit.

        :param job: the job the result came from -- its :attr:`~.scrape_job.ScrapeJob.publisher` and
            :attr:`~.scrape_job.ScrapeJob.page_url` become the added source.
        :param result: the result to apply.
        """
        declared = declared_field_names(self.__model)
        for name, value in result.fields.items():
            if name == "description":
                continue
            if name not in declared:
                LOG.info("%s is not a field of this document's type; left unset.", name)
                continue
            setattr(self.__model, name, value)
        description = result.description
        if description is None:
            raw = result.fields.get("description")
            description = raw if isinstance(raw, str) else None
        else:
            description = substitute_image_stem(description, self.__model.current_name)
        if description is not None and "description" in declared:
            self.__model.description = description
        # not a runtime check: both are set together, unconditionally, by the time scrape() returns the
        # result __apply is only ever called with -- see ScrapeJob.publisher/page_url's own docstrings
        self.__model.add_source(cast(str, job.publisher), cast(str, job.page_url))
        if result.images:
            LOG.info(
                "%d image(s) found; downloading them is not implemented yet (#73).",
                len(result.images),
            )
