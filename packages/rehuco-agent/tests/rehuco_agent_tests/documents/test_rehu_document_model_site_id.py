"""Tests for the store id a scrape hands `RehuDocumentModel.add_source` (#675, [[assets#site-id]]): it fills the source
the URL lands on, only when that source names none, in each of the method's three cases."""

from typing import Any

from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RehuDocument


def model_over(*sources: dict[str, Any]) -> tuple[RehuDocumentModel, RehuDocument]:
    """A model over a tutorial whose ``sources`` are ``sources``, the first flagged primary.

    :param sources: the entries, as stored.
    :returns: the model and its document.
    """
    stored = [{**source, "primary": True} if row == 0 else source for row, source in enumerate(sources)]
    document = RehuDocument({"type": "tutorial", "sources": stored} if stored else {"type": "tutorial"})
    return RehuDocumentModel(document), document


def test_an_empty_primary_takes_the_url_and_the_id() -> None:
    """A source-less document's new primary holds the scraped URL, the publisher and the id.

    **Test steps:**

    * add a source with an id to a source-less document
    * verify the primary holds all three and the model is dirty
    """
    model, document = model_over()

    model.add_source("Fab", "https://fab.example/1", "f-1")

    assert (document.url, document.publisher, document.site_id) == ("https://fab.example/1", "Fab", "f-1")
    assert model.dirty is True


def test_a_new_url_is_appended_with_its_id() -> None:
    """A URL no source has is appended carrying the id; the primary is left alone.

    **Test steps:**

    * add a new URL with an id beside a primary that has a URL
    * verify the appended entry holds the id and the primary none
    """
    model, document = model_over({"title": "T", "url": "https://a.example"})

    model.add_source("Fab", "https://fab.example/1", "f-1")

    assert document.sources[-1] == {"title": "T", "publisher": "Fab", "url": "https://fab.example/1", "site_id": "f-1"}
    assert document.site_id is None


def test_a_matching_source_with_a_publisher_still_takes_a_missing_id() -> None:
    """A source found by its URL, whatever its publisher, is given the id it lacks; its publisher is kept.

    **Test steps:**

    * add the second source's URL again under another publisher, with an id
    * verify that source took the id and kept its publisher, and the model is dirty
    """
    model, document = model_over({"url": "https://a.example"}, {"url": "https://fab.example/1", "publisher": "Fab"})

    model.add_source("Other", "https://fab.example/1", "f-1")

    assert document.sources[1] == {"url": "https://fab.example/1", "publisher": "Fab", "site_id": "f-1"}
    assert model.dirty is True


def test_a_matching_primary_takes_a_missing_id() -> None:
    """The primary found by its URL is given the id it lacks.

    **Test steps:**

    * add the primary's own URL again with an id
    * verify the primary holds it
    """
    model, document = model_over({"url": "https://fab.example/1", "publisher": "Fab"})

    model.add_source("Fab", "https://fab.example/1", "f-1")

    assert document.site_id == "f-1"


def test_an_id_already_there_is_never_replaced() -> None:
    """A source naming an id keeps it, so a scrape adding the same URL again changes nothing.

    **Test steps:**

    * add a source's URL again with another id
    * verify its id is unchanged and the model is clean
    """
    model, document = model_over({"url": "https://fab.example/1", "publisher": "Fab", "site_id": "f-1"})

    model.add_source("Fab", "https://fab.example/1", "f-2")

    assert document.site_id == "f-1"
    assert model.dirty is False
