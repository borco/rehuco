"""Tests for the relay every pool job posts its answer through: :class:`~rehuco_agent.pool_relay.PoolRelay`."""

import threading
from typing import Final

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool
from pytest import raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.pool_relay import PoolRelay

from rehuco_agent_tests.delete_at_teardown import DeleteAtTeardown

WAIT_MS: Final = 2000


def test_the_application_has_one_relay_as_its_child(qtbot: QtBot) -> None:
    """**Test steps:**

    * ask for the relay twice
    * verify it is the same object, the application's child
    """
    del qtbot
    relay = PoolRelay.instance()

    assert PoolRelay.instance() is relay
    assert relay.parent() is QCoreApplication.instance()


def test_there_is_no_relay_without_an_application(mocker: MockerFixture) -> None:
    """**Test steps:**

    * ask for the relay with no application
    * verify it is refused
    """
    mocker.patch("rehuco_agent.pool_relay.QCoreApplication").instance.return_value = None

    with raises(RuntimeError, match="needs an application"):
        PoolRelay.instance()


def test_the_relay_is_refused_off_the_applications_thread(qtbot: QtBot) -> None:
    """A relay built on another thread would live there, and its calls would never be made on the GUI thread.

    **Test steps:**

    * ask for the relay on another thread
    * verify it is refused there
    """
    del qtbot
    refused: list[str] = []

    def ask() -> None:
        try:
            PoolRelay.instance()
        except RuntimeError as error:
            refused.append(str(error))

    thread = threading.Thread(target=ask)
    thread.start()
    thread.join(WAIT_MS / 1000)

    assert len(refused) == 1
    assert "application's thread" in refused[0]


def test_a_call_posted_on_a_pool_thread_is_made_on_the_gui_thread_in_order(
    delete_at_teardown: DeleteAtTeardown,
) -> None:
    """**Test steps:**

    * post two calls from a pool thread
    * let the pool settle and the calls be delivered
    * verify both were made on this thread, in the order posted, with their arguments
    """
    relay = PoolRelay.instance()
    calls: list[tuple[int, str, int]] = []

    def deliver(tag: str, value: int) -> None:
        calls.append((threading.get_ident(), tag, value))

    owner = delete_at_teardown(QObject())

    def work() -> None:
        relay.post(owner, deliver, "first", 1)
        relay.post(owner, deliver, "second", 2)

    QThreadPool.globalInstance().start(work)
    assert QThreadPool.globalInstance().waitForDone(WAIT_MS)
    QCoreApplication.sendPostedEvents()

    here = threading.get_ident()
    assert calls == [(here, "first", 1), (here, "second", 2)]


def test_a_call_for_an_owner_deleted_meanwhile_is_not_made(qtbot: QtBot) -> None:
    """The owner is deleted on the GUI thread, the thread the call is made on, so a gone owner is seen gone.

    **Test steps:**

    * post a call for an owner from a pool thread, and delete the owner before the call is delivered
    * let the call be delivered
    * verify it was not made
    """
    del qtbot
    relay = PoolRelay.instance()
    owner = QObject()
    calls: list[str] = []

    QThreadPool.globalInstance().start(lambda: relay.post(owner, calls.append, "late"))
    assert QThreadPool.globalInstance().waitForDone(WAIT_MS)
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QCoreApplication.sendPostedEvents()

    assert not calls
