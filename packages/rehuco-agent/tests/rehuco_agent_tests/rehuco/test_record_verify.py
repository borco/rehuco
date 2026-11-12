"""Tests for a Roots listing brought into the cache by :class:`RecordVerify` (#645): the records the cache holds
beneath the folder that the listing no longer accounts for are verified, and a folder that appeared is walked for
records on the pool.

The catalog is a ``Mock(spec=Catalog)`` and the walk's :class:`~rehuco_core.CatalogScanner` is patched: planning, the
cache's lookups and the walk are each core's and tested there. What is left is the routing between them.
"""

import logging
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Final
from unittest.mock import MagicMock, Mock

from PySide6.QtCore import QObject, QThreadPool, Signal
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.pool_relay import PoolRelay
from rehuco_agent.rehuco.record_verify import RecordVerify
from rehuco_agent.rehuco.roots_listing import ListedFolder
from rehuco_core import CatalogDirectory, CatalogScanner, RecordsChecked, RenameCoordinator
from rehuco_core.access import Catalog, ResourceKey

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

WAIT_TIMEOUT_MS: Final = 10_000

FOLDER: Final = Path("C:/root/folder").absolute()
RECORD: Final = FOLDER / "info.rehu"
KEPT: Final = FOLDER / "kept" / "info.rehu"
BENEATH_GONE: Final = FOLDER / "gone" / "info.rehu"
APPEARED: Final = FOLDER / "new"
IN_APPEARED: Final = APPEARED / "deep" / "x.rehu"


class Owner(QObject):
    """What owns a :class:`RecordVerify`: a parent and the signal it emits changed rows on."""

    rows_changed = Signal(object)


@fixture(name="catalog")
def fixture_catalog() -> Mock:
    """A catalog with a cache attached, holding nothing beneath :data:`FOLDER`, that plans nothing."""
    catalog = Mock(spec=Catalog)
    catalog.cache_path = Path("cache.rehudb")
    catalog.records_beneath.return_value = []
    catalog.plan_verify.return_value = []
    return catalog


@fixture(name="verify")
def fixture_verify(catalog: Mock, delete_at_teardown: DeleteAtTeardown) -> Iterator[RecordVerify]:
    """A verifier over :func:`fixture_catalog`; the pool is drained before it goes."""
    owner = delete_at_teardown(Owner())
    yield RecordVerify(catalog, Mock(spec=RenameCoordinator), None, owner.rows_changed, owner)
    QThreadPool.globalInstance().waitForDone()


def walked(*records: Path) -> MagicMock:
    """A scanner whose walk finds ``records``, in one directory.

    :param records: the records.
    :returns: the scanner.
    """
    scanner = MagicMock(spec=CatalogScanner)
    scanner.walk.return_value = [Mock(spec=CatalogDirectory, records=records)]
    return scanner


def planned(catalog: Mock) -> list[ResourceKey]:
    """Every record the catalog was asked to plan a check for, in order."""
    return [key for call in catalog.plan_verify.call_args_list for key in call.args[0]]


def test_the_cached_records_a_listing_no_longer_accounts_for_are_verified_with_its_own(
    verify: RecordVerify, catalog: Mock
) -> None:
    """A listing asks the cache what it holds beneath the folder, and verifies with the listing's own records each one
    the listing shows no way to any more -- deleted or moved away, the app running or not (#645).

    **Test steps:**

    * a cache holding a record under a folder still listed and one under a folder no longer there
    * list the folder, holding a record and the folder still there
    * verify the cache was asked about the listed folder, and the listing's record and the gone one were planned
    """
    catalog.records_beneath.return_value = [KEPT, BENEATH_GONE]

    verify.on_listed(ListedFolder(FOLDER, (RECORD,), ("kept",), ("info.rehu",)))

    catalog.records_beneath.assert_called_once_with(ResourceKey(FOLDER))
    assert planned(catalog) == [ResourceKey(RECORD), ResourceKey(BENEATH_GONE)]


def test_a_listing_with_no_cache_attached_asks_and_walks_nothing(
    verify: RecordVerify, catalog: Mock, mocker: MockerFixture
) -> None:
    """With no cache there is nothing to bring in line: a listing reads nothing and walks no folder (#645).

    **Test steps:**

    * detach the cache, and list a folder holding a record with a folder that appeared
    * verify the cache was asked nothing and no walk was started
    """
    scanner_class = mocker.patch("rehuco_agent.rehuco.record_verify.CatalogScanner")
    catalog.cache_path = None

    verify.on_listed(ListedFolder(FOLDER, (RECORD,), appeared=(APPEARED,)))
    QThreadPool.globalInstance().waitForDone()

    catalog.records_beneath.assert_not_called()
    catalog.plan_verify.assert_not_called()
    scanner_class.assert_not_called()


def test_a_folder_that_appeared_is_walked_on_the_pool_and_its_records_verified(
    qtbot: QtBot, verify: RecordVerify, catalog: Mock, mocker: MockerFixture
) -> None:
    """A folder new to a listing is walked for records off the GUI thread, legacy ones included, and they are verified
    with the listing's own (#645).

    **Test steps:**

    * a listing holding a record, with a folder that appeared, whose walk finds a record deep in it
    * verify the walk ran on a pool thread over that folder, and both records were planned
    """
    threads: list[threading.Thread] = []
    scanner = walked(IN_APPEARED)

    def made(*_args: object, **_kwargs: object) -> MagicMock:
        threads.append(threading.current_thread())
        return scanner

    scanner_class = mocker.patch("rehuco_agent.rehuco.record_verify.CatalogScanner", side_effect=made)

    verify.on_listed(ListedFolder(FOLDER, (RECORD,), appeared=(APPEARED,)))

    qtbot.waitUntil(lambda: catalog.plan_verify.called, timeout=WAIT_TIMEOUT_MS)
    assert planned(catalog) == [ResourceKey(RECORD), ResourceKey(IN_APPEARED)]
    assert scanner_class.call_args.args == (APPEARED,)
    assert scanner_class.call_args.kwargs["include_legacy"]
    assert threads and threads[0] is not threading.main_thread()


def test_a_newer_listing_of_the_folder_drops_a_walk_still_out(
    qtbot: QtBot, verify: RecordVerify, catalog: Mock, mocker: MockerFixture
) -> None:
    """The folder listed again while a walk of its last listing is out: the newer listing is verified, and the walk's
    answer is dropped when it lands (#645).

    **Test steps:**

    * a listing with a folder that appeared, whose walk is held until released; every plan has a check to run
    * list the folder again, with nothing appeared, once the walk has started
    * release the walk and let its answer land
    * verify only the newer listing was planned
    """
    catalog.plan_verify.return_value = [MagicMock()]
    mocker.patch("rehuco_agent.rehuco.record_verify.check_records", return_value=RecordsChecked([], {}))
    started, release = threading.Event(), threading.Event()

    def walk() -> list[CatalogDirectory]:
        started.set()
        release.wait(WAIT_TIMEOUT_MS / 1000)
        return [Mock(spec=CatalogDirectory, records=(IN_APPEARED,))]

    scanner = MagicMock(spec=CatalogScanner)
    scanner.walk.side_effect = walk
    mocker.patch("rehuco_agent.rehuco.record_verify.CatalogScanner", return_value=scanner)
    verify.on_listed(ListedFolder(FOLDER, (), appeared=(APPEARED,)))
    assert started.wait(WAIT_TIMEOUT_MS / 1000)

    verify.on_listed(ListedFolder(FOLDER, (RECORD,)))
    release.set()
    QThreadPool.globalInstance().waitForDone()
    qtbot.wait(20)

    assert planned(catalog) == [ResourceKey(RECORD)]


def test_a_walk_that_fails_is_logged_and_the_rest_still_verified(
    qtbot: QtBot, verify: RecordVerify, catalog: Mock, mocker: MockerFixture, caplog: LogCaptureFixture
) -> None:
    """The pool swallows what escapes a job: a walk that fails is logged, and what the other walks found is verified
    with the listing's own records (#645).

    **Test steps:**

    * a listing with two folders that appeared: the walk of the first fails, the second finds a record
    * verify the failure is logged, and the listing's record and the one found were planned
    """
    other = FOLDER / "other"
    mocker.patch("rehuco_agent.rehuco.record_verify.CatalogScanner", side_effect=[OSError("gone"), walked(IN_APPEARED)])

    with caplog.at_level(logging.ERROR):
        verify.on_listed(ListedFolder(FOLDER, (RECORD,), appeared=(other, APPEARED)))
        qtbot.waitUntil(lambda: catalog.plan_verify.called, timeout=WAIT_TIMEOUT_MS)

    assert f"Could not walk {other} for records." in caplog.text
    assert planned(catalog) == [ResourceKey(RECORD), ResourceKey(IN_APPEARED)]


def test_a_walk_superseded_before_it_starts_does_nothing(verify: RecordVerify, mocker: MockerFixture) -> None:
    """A newer listing of the folder leaves an older walk that has not started to walk nothing and answer nothing;
    the hop cannot be provoked through the public surface, so the walk is run by hand (#645).

    **Test steps:**

    * note a newer call for a folder, then run an older walk of it
    * verify nothing was walked and nothing posted
    """
    scanner_class = mocker.patch("rehuco_agent.rehuco.record_verify.CatalogScanner")
    getattr(verify, "_RecordVerify__latest_verify")[FOLDER] = 2
    relay = Mock(spec=PoolRelay)

    getattr(verify, "_RecordVerify__run_walk")(relay, 1, FOLDER, (RECORD,), (APPEARED,))

    scanner_class.assert_not_called()
    relay.post.assert_not_called()
