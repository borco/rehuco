"""Shared fixtures for the field toolkit tests."""

from pytest import fixture
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_core import RehuDocument


@fixture
def model() -> RehuDocumentModel:
    """A view-model seeded with a primary source, for widgets to bind to."""
    return RehuDocumentModel(
        RehuDocument(
            {
                "type": "Tutorial",
                "sources": [
                    {"title": "Foo", "publisher": "Bar", "url": "https://example.com", "primary": True},
                ],
            }
        )
    )
