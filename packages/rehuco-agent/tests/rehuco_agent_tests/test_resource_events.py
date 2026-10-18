"""Tests for the Qt adapter of the change feed: what changed under the resources the app reaches (#376, #414, #511)."""

import logging
from pathlib import Path
from threading import Thread
from typing import Final, cast
from uuid import uuid4

from PySide6.QtCore import QThread
from pytest import LogCaptureFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.resource_events import ResourceEvents
from rehuco_core import Relocation
from rehuco_core.access import (
    Changed,
    ChangeEvent,
    ChangeFeed,
    FolderChanged,
    KeyRelocation,
    Moved,
    ResourceKey,
    RootReachable,
    RootStale,
)

FOLDER: Final = Path.cwd() / "fake" / "library" / "pack"
RELOCATION: Final = Relocation(((FOLDER, FOLDER.with_name("kit")),))
MOVED_KEYS: Final = KeyRelocation.from_local(RELOCATION)
RECORD: Final = ResourceKey(FOLDER / "info.rehu")
OTHER_RECORD: Final = ResourceKey(FOLDER.with_name("other") / "info.rehu")
TIMEOUT: Final = 5000


def test_an_announcement_on_the_gui_thread_is_emitted_at_once(qtbot: QtBot) -> None:
    """A rename on the GUI thread is heard before the announcing call returns, so every holder has followed it
    by the time the renaming code goes on.

    **Test steps:**

    * announce a move and an access on the GUI thread, with no event loop turn
    * verify each was emitted synchronously with what was announced, the rename as keys
    """
    del qtbot
    events = ResourceEvents()
    heard: list[object] = []
    events.moved.connect(heard.append)
    events.accessed.connect(heard.append)

    events.announce_moved(RELOCATION)
    events.announce_accessed((RECORD,))

    assert heard == [MOVED_KEYS, (RECORD,)]


def test_every_feed_event_reaches_its_signal(qtbot: QtBot) -> None:
    """Whoever publishes on the feed -- not only the ``announce_*`` methods -- is heard on the matching signal (#414).

    **Test steps:**

    * publish one event of each kind straight onto the feed the events adapt
    * verify each signal carried its event's payload, in order
    """
    del qtbot
    feed = ChangeFeed()
    events = ResourceEvents(feed)
    root_id = uuid4()
    heard: list[tuple[str, object]] = []
    events.moved.connect(lambda value: heard.append(("moved", value)))
    events.changed.connect(lambda value: heard.append(("changed", value)))
    events.folder_changed.connect(lambda value: heard.append(("folder_changed", value)))
    events.root_stale.connect(lambda value: heard.append(("root_stale", value)))
    events.root_reachable.connect(lambda value, reachable: heard.append(("root_reachable", (value, reachable))))

    feed.publish(Moved(MOVED_KEYS))
    feed.publish(Changed((RECORD, OTHER_RECORD)))
    feed.publish(FolderChanged(OTHER_RECORD.parent))
    feed.publish(RootStale(root_id))
    feed.publish(RootReachable(root_id, False))
    feed.publish(RootReachable(root_id, True))

    assert heard == [
        ("moved", MOVED_KEYS),
        ("changed", (RECORD, OTHER_RECORD)),
        ("folder_changed", OTHER_RECORD.parent),
        ("root_stale", root_id),
        ("root_reachable", (root_id, False)),
        ("root_reachable", (root_id, True)),
    ]


def test_a_move_is_published_on_the_feed_and_nothing_else_the_app_does_is(qtbot: QtBot) -> None:
    """A rename this machine ran goes through the feed, so another listener on it hears it (#414); the app announces
    no write of its own any more -- the notifiers report what the disk says (#511).

    **Test steps:**

    * listen on the feed the events were given
    * announce a move and an access
    * verify the feed carried the move alone, as keys
    """
    del qtbot
    feed = ChangeFeed()
    events = ResourceEvents(feed)
    published: list[ChangeEvent] = []
    events.changes.add_listener(published.append)

    events.announce_moved(RELOCATION)
    events.announce_accessed([RECORD])

    assert events.changes is feed
    assert published == [Moved(MOVED_KEYS)]


def test_the_default_feed_is_a_private_one(qtbot: QtBot) -> None:
    """Events built with no feed adapt one of their own, which no other events share.

    **Test steps:**

    * build two events with no feed
    * verify each has a feed, and not the same one
    * verify a change published on one's feed is not heard on the other
    """
    del qtbot
    first = ResourceEvents()
    second = ResourceEvents()
    heard: list[object] = []
    second.changed.connect(heard.append)

    first.changes.publish(Changed((RECORD,)))

    assert isinstance(first.changes, ChangeFeed)
    assert first.changes is not second.changes
    assert not heard


def test_an_announcement_off_the_gui_thread_arrives_on_it(qtbot: QtBot) -> None:
    """A rename asked for on another thread still reaches the listeners on the GUI thread.

    **Test steps:**

    * announce a move from a plain worker thread
    * verify the signal arrives, on the GUI thread
    """
    events = ResourceEvents()
    threads: list[QThread] = []
    events.moved.connect(lambda _relocation: threads.append(QThread.currentThread()))

    with qtbot.waitSignal(events.moved, timeout=TIMEOUT) as moved:
        worker = Thread(target=events.announce_moved, args=(RELOCATION,))
        worker.start()
        worker.join()

    assert moved.args == [MOVED_KEYS]
    assert threads == [events.thread()]


def test_a_feed_event_published_off_the_gui_thread_arrives_on_it(qtbot: QtBot) -> None:
    """An event published on the feed from another thread -- as the file notifier will (#511) -- is queued onto
    the GUI thread (#414).

    **Test steps:**

    * publish a stale root on the feed from a plain worker thread
    * verify the signal arrives, on the GUI thread
    """
    feed = ChangeFeed()
    events = ResourceEvents(feed)
    root_id = uuid4()
    threads: list[QThread] = []
    events.root_stale.connect(lambda _root_id: threads.append(QThread.currentThread()))

    with qtbot.waitSignal(events.root_stale, timeout=TIMEOUT) as stale:
        worker = Thread(target=feed.publish, args=(RootStale(root_id),))
        worker.start()
        worker.join()

    assert stale.args == [root_id]
    assert threads == [events.thread()]


def test_a_reachability_published_off_the_gui_thread_arrives_on_it(qtbot: QtBot) -> None:
    """A root gone out of reach, as its notifier publishes it from its own thread (#511), is queued onto the GUI thread
    with the root and the flag.

    **Test steps:**

    * publish an unreachable root on the feed from a plain worker thread
    * verify the signal arrives, on the GUI thread, with the root and ``False``
    """
    feed = ChangeFeed()
    events = ResourceEvents(feed)
    root_id = uuid4()
    threads: list[QThread] = []
    events.root_reachable.connect(lambda _root_id, _reachable: threads.append(QThread.currentThread()))

    with qtbot.waitSignal(events.root_reachable, timeout=TIMEOUT) as reachable:
        worker = Thread(target=feed.publish, args=(RootReachable(root_id, False),))
        worker.start()
        worker.join()

    assert reachable.args == [root_id, False]
    assert threads == [events.thread()]


def test_an_access_is_announced_with_the_records_opened(qtbot: QtBot) -> None:
    """Opening a record is announced, for the catalog to verify it (#487): nothing was written, so the feed hears
    nothing.

    **Test steps:**

    * announce two records as accessed
    * verify one announcement carries both
    * verify nothing was published on the feed
    """
    del qtbot
    events = ResourceEvents()
    heard: list[object] = []
    published: list[ChangeEvent] = []
    events.accessed.connect(heard.append)
    events.changes.add_listener(published.append)

    events.announce_accessed([RECORD, OTHER_RECORD])

    assert heard == [(RECORD, OTHER_RECORD)]
    assert not published


def test_an_event_of_no_known_kind_is_refused_loudly(qtbot: QtBot, caplog: LogCaptureFixture) -> None:
    """Something on the feed that is no change event is a programming error: it fails in the adapter, which the
    feed logs, and no signal is emitted.

    **Test steps:**

    * publish an object that is no change event on the feed
    * verify the failure was logged and nothing was heard
    """
    del qtbot
    feed = ChangeFeed()
    events = ResourceEvents(feed)
    heard: list[object] = []
    for signal in (events.moved, events.changed, events.folder_changed, events.root_stale):
        signal.connect(heard.append)
    events.root_reachable.connect(lambda root_id, reachable: heard.append((root_id, reachable)))

    with caplog.at_level(logging.ERROR):
        feed.publish(cast(ChangeEvent, object()))

    assert "A change listener failed" in caplog.text
    assert not heard


def test_detached_events_hear_the_feed_no_more(qtbot: QtBot) -> None:
    """Once detached, events stop adapting the feed, which outlives them (#414).

    **Test steps:**

    * detach events from their feed
    * publish a change on the feed
    * verify no signal was emitted
    """
    del qtbot
    feed = ChangeFeed()
    events = ResourceEvents(feed)
    heard: list[object] = []
    events.changed.connect(heard.append)

    events.detach()
    feed.publish(Changed((RECORD,)))

    assert not heard
