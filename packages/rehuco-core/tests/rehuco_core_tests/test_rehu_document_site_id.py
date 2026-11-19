"""Tests for a source's ``site_id``, the store's own id for the item (#675, [[assets#site-id]]).

Optional, read off the primary source like its title, publisher and URL; a present value that is not a string locks
the document, so an edit never saves the coerced ``None`` over it ([[data-model#write-integrity]]).
"""

import json
from typing import Any

from pytest import mark, param
from pytest_mock import MockerFixture
from rehuco_core import CORE_FIELD_NAMES, SITE_ID_KEY, LockReasonKind, RehuDocument

from rehuco_core_tests.test_rehu_document import FAKE_PATH, mock_writes


def sourced(*sources: Any) -> RehuDocument:
    """A tutorial whose ``sources`` are ``sources``, bound to a path for the tests that save.

    :param sources: the entries, as stored.
    :returns: the document.
    """
    return RehuDocument({"format_version": 2, "core": {"type": "tutorial", "sources": list(sources)}}, FAKE_PATH)


def test_site_id_is_a_core_field() -> None:
    """Every type declares it, as it declares the primary source's title, publisher and URL.

    **Test steps:**

    * verify ``site_id`` is among the core field names
    """
    assert SITE_ID_KEY in CORE_FIELD_NAMES


def test_the_primary_sources_site_id_is_read() -> None:
    """The flagged primary's id is the document's, whatever another source carries.

    **Test steps:**

    * build a document whose second source is the flagged primary, each with an id
    * verify the primary's is read
    """
    doc = sourced(
        {"url": "https://a", SITE_ID_KEY: "other"}, {"url": "https://b", SITE_ID_KEY: "mine", "primary": True}
    )

    assert doc.site_id == "mine"


@mark.parametrize(
    "sources",
    [param((), id="no-source"), param(({"url": "https://a"},), id="no-id")],
)
def test_a_missing_site_id_reads_none(sources: tuple[Any, ...]) -> None:
    """No source, or a primary with no id, reads as not known and does not lock.

    **Test steps:**

    * build the document
    * verify the id reads ``None`` and nothing locks

    :param sources: the stored entries.
    """
    doc = sourced(*sources)

    assert doc.site_id is None
    assert not doc.lock_reasons


def test_the_setter_writes_the_primary_creating_it_when_absent() -> None:
    """Setting an id on a source-less document creates a flagged primary holding it.

    **Test steps:**

    * assign an id on a document with no sources
    * verify one flagged primary holds it
    """
    doc = sourced()

    doc.site_id = "f-1"

    assert doc.sources == [{SITE_ID_KEY: "f-1", "primary": True}]


def test_setting_none_removes_the_key_and_leaves_the_rest() -> None:
    """``None`` is never written: it removes the key from the primary, and is a no-op with no source at all.

    **Test steps:**

    * set ``None`` on a document with no source and verify it still has none
    * set ``None`` on a primary with an id and verify the key is gone, its other keys and the second source kept
    """
    empty = sourced()
    empty.site_id = None
    assert not empty.sources

    doc = sourced({"url": "https://a", SITE_ID_KEY: "f-1"}, {"url": "https://b", SITE_ID_KEY: "u-9"})
    doc.site_id = None

    assert doc.sources == [{"url": "https://a"}, {"url": "https://b", SITE_ID_KEY: "u-9"}]


def test_a_primary_site_id_that_is_not_a_string_reads_none_and_locks() -> None:
    """A malformed id on the primary is read past and locks, naming the key.

    **Test steps:**

    * build a document whose primary's id is a number
    * verify it reads ``None`` and one invalid-field reason names ``site_id``
    """
    doc = sourced({"url": "https://a", SITE_ID_KEY: 42})

    assert doc.site_id is None
    assert [(reason.kind, reason.message.split(" (")[0]) for reason in doc.lock_reasons] == [
        (LockReasonKind.INVALID_FIELD, "site_id: present but not a string")
    ]


def test_a_malformed_site_id_on_another_source_does_not_lock() -> None:
    """Only the primary is read, so only its id is judged; another source's is carried as it is.

    **Test steps:**

    * build a document whose second source's id is a number
    * verify nothing locks
    """
    doc = sourced({"url": "https://a"}, {"url": "https://b", SITE_ID_KEY: 42})

    assert not doc.lock_reasons


def test_a_null_site_id_normalizes_away_on_save(mocker: MockerFixture) -> None:
    """A JSON ``null`` on the primary reads ``None``, does not lock, and saves as no key at all.

    **Test steps:**

    * build a document whose primary's id is ``null``
    * save with the writers mocked
    * verify it did not lock and the saved primary has no such key
    """
    doc = sourced({"url": "https://a", SITE_ID_KEY: None})
    write, _ = mock_writes(mocker)

    assert not doc.lock_reasons
    doc.save()

    assert json.loads(write.call_args[0][1])["core"]["sources"] == [{"url": "https://a"}]
