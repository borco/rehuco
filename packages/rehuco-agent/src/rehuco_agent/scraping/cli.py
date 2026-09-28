"""The scraping half of the `rehuco_agent.__main__` CLI: ``--scrape URL`` and ``--scrape-schema PATH``
([[acquisition-tooling#scraper-registry]]).

A separate module rather than inline in ``__main__`` so that flag stays free of `ScrapeJob`/registry
imports until one of these two flags is actually used -- the same reason ``__main__`` imports
`rehuco_agent.app` lazily.
"""

import json
import random
import sys
import time
from pathlib import Path
from typing import cast

from .protocols import RefetchRequestedError
from .registry import ScraperRegistry
from .results import SCRAPE_RESULT_SCHEMA_TEXT, ScrapeResult
from .scrape_job import (
    MAX_REFETCHES,
    REFETCH_COUNTDOWN_MESSAGE,
    REFETCH_GAVE_UP_MESSAGE,
    ScrapeError,
    ScrapeJob,
)


def write_scrape_schema(path: Path) -> int:
    """Write the bundled scrape-result schema to ``path``, as checked in, for a script author's editor to
    validate against -- the same file every scrape, this build's own scrapers included, is checked against.

    A file rather than stdout: the packaged Windows build prints nowhere, not even into a pipe or a
    redirect ([[appendices.release-runbook#windows-console]]). LF line endings on every platform, so the
    output does not depend on which OS the app happened to run on.

    :param path: where to write the schema.
    :returns: ``0``.
    """
    path.write_text(SCRAPE_RESULT_SCHEMA_TEXT, encoding="utf-8", newline="\n")
    return 0


def scrape_with_refetches(url: str, registry: ScraperRegistry) -> ScrapeResult:
    """Run one scrape's attempts synchronously: the first at once, and each re-fetch the scraper asks for
    (`~.protocols.RefetchRequestedError`) after sleeping a delay drawn from its range, up to
    `~.scrape_job.MAX_REFETCHES` of them ([[acquisition-tooling#scrape-job]]).

    The CLI's counterpart of `rehuco_agent.documents.scrape_actions.ScrapeActions`' timer-driven loop: a
    console call has no event loop to wait on and no pool slot to spare, so sleeping here is the plain
    answer. Each wait is announced on stderr, which stays free of the JSON stdout carries.

    :param url: the page to scrape first.
    :param registry: where to look up a matching scraper.
    :returns: the result of the first attempt that produced one.
    :raises ScrapeError: an attempt failed, or the re-fetches ran out.
    """
    attempt = 1
    while True:
        try:
            return ScrapeJob(url, registry).scrape()
        except RefetchRequestedError as request:
            if attempt > MAX_REFETCHES:
                raise ScrapeError(
                    REFETCH_GAVE_UP_MESSAGE.format(message=request.message, count=MAX_REFETCHES)
                ) from request
            # not runtime checks: ScrapeJob.scrape fills both before raising (its own :raises: says so)
            url = cast(str, request.url)
            low, high = cast(tuple[float, float], request.delay)
            # a jitter between polite retries, not anything security-sensitive
            delay = random.uniform(low, high)  # nosec B311
            attempt += 1
            countdown = REFETCH_COUNTDOWN_MESSAGE.format(
                message=request.message, url=url, seconds=round(delay), attempt=attempt, attempts=MAX_REFETCHES + 1
            )
            print(countdown, file=sys.stderr)
            time.sleep(delay)


def scrape_url_to_json(url: str, *, scrapers_folder: Path | None, output: Path | None) -> int:
    """Scrape ``url`` and write the result as JSON, for developing and testing a script without opening
    the GUI ([[acquisition-tooling#scraper-registry]]).

    :param url: the page to scrape.
    :param scrapers_folder: build the registry over this folder for this call only, leaving the saved
        Scrapers setting untouched; `None` reads that setting instead, the shape every other caller wants.
    :param output: write the JSON here instead of stdout.
    :returns: ``0`` on success, ``1`` when no scraper matched, the fetch failed, the result failed the
        scrape-result schema, or the scraper was still asking for a re-fetch after
        `~.scrape_job.MAX_REFETCHES` of them -- the reason is printed to stderr.
    """
    registry = ScraperRegistry(folder=scrapers_folder) if scrapers_folder is not None else ScraperRegistry()
    try:
        result = scrape_with_refetches(url, registry)
    except ScrapeError as error:
        print(str(error), file=sys.stderr)
        return 1
    text = json.dumps(result.to_json(), indent=2, ensure_ascii=False)
    if output is not None:
        output.write_text(text, encoding="utf-8")
    else:
        # UTF-8 bytes rather than `print`: a redirected stdout on Windows encodes as the ANSI code page
        # (cp1252 here), and a title in a script outside it would end the scrape in a
        # `UnicodeEncodeError` -- exactly on the `--scrape URL > out.json` call this exists for. A real
        # console decodes these bytes as UTF-8 too, so the two paths agree with `--output`.
        sys.stdout.flush()
        sys.stdout.buffer.write(f"{text}\n".encode())
        sys.stdout.buffer.flush()
    return 0
