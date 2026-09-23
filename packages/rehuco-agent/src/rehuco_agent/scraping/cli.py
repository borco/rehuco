"""The scraping half of the `rehuco_agent.__main__` CLI: ``--scrape URL`` and ``--scrape-schema PATH``
([[acquisition-tooling#scraper-registry]]).

A separate module rather than inline in ``__main__`` so that flag stays free of `ScrapeJob`/registry
imports until one of these two flags is actually used -- the same reason ``__main__`` imports
`rehuco_agent.app` lazily.
"""

import json
import sys
from pathlib import Path

from .registry import ScraperRegistry
from .results import SCRAPE_RESULT_SCHEMA_TEXT
from .scrape_job import ScrapeError, ScrapeJob


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


def scrape_url_to_json(url: str, *, scrapers_folder: Path | None, output: Path | None) -> int:
    """Scrape ``url`` and write the result as JSON, for developing and testing a script without opening
    the GUI ([[acquisition-tooling#scraper-registry]]).

    :param url: the page to scrape.
    :param scrapers_folder: build the registry over this folder for this call only, leaving the saved
        Scrapers setting untouched; `None` reads that setting instead, the shape every other caller wants.
    :param output: write the JSON here instead of stdout.
    :returns: ``0`` on success, ``1`` when no scraper matched, the fetch failed, or the result failed the
        scrape-result schema -- the reason is printed to stderr.
    """
    registry = ScraperRegistry(folder=scrapers_folder) if scrapers_folder is not None else ScraperRegistry()
    try:
        result = ScrapeJob(url, registry).scrape()
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
