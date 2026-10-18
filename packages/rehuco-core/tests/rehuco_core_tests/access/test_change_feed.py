"""Tests for the Qt-free change feed (#413, #511)."""

import logging
from pathlib import Path
from typing import Final
from uuid import UUID

from pytest import LogCaptureFixture
from rehuco_core import (
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

FOLDER: Final = ResourceKey(Path("/fake/library").absolute())
EVENTS: Final[tuple[ChangeEvent, ...]] = (
    Moved(KeyRelocation()),
    Changed((FOLDER.joinpath("info.rehu"),)),
    FolderChanged(FOLDER),
    RootStale(UUID("00000000-0000-0000-0000-000000000001")),
    RootReachable(UUID("00000000-0000-0000-0000-000000000001"), False),
)


def test_every_listener_hears_every_event_in_order() -> None:
    """Each listener gets each kind of event, in publishing order.

    **Test steps:**

    * add two listeners
    * publish one event of each kind
    """
    feed = ChangeFeed()
    first: list[ChangeEvent] = []
    second: list[ChangeEvent] = []
    feed.add_listener(first.append)
    feed.add_listener(second.append)

    for event in EVENTS:
        feed.publish(event)

    assert first == list(EVENTS)
    assert second == list(EVENTS)


def test_a_removed_listener_hears_nothing_more() -> None:
    """Removal takes effect from the next event; removing one never added is ignored.

    **Test steps:**

    * publish, remove the listener, publish again
    * remove a listener that was never added
    """
    feed = ChangeFeed()
    heard: list[ChangeEvent] = []
    feed.add_listener(heard.append)

    feed.publish(EVENTS[0])
    feed.remove_listener(heard.append)
    feed.publish(EVENTS[1])
    feed.remove_listener(print)

    assert heard == [EVENTS[0]]


def test_a_failing_listener_is_logged_and_the_rest_still_hear(caplog: LogCaptureFixture) -> None:
    """The change already happened, so a listener's exception never reaches the publisher.

    **Test steps:**

    * add a raising listener, then a recording one
    * publish an event
    * check the publish returned, the second listener heard it and the failure was logged
    """
    feed = ChangeFeed()
    heard: list[ChangeEvent] = []

    def fail(_event: ChangeEvent) -> None:
        """Raise, as a broken listener would.

        :param _event: ignored.
        :raises RuntimeError: always.
        """
        raise RuntimeError("broken listener")

    feed.add_listener(fail)
    feed.add_listener(heard.append)

    with caplog.at_level(logging.ERROR):
        feed.publish(EVENTS[2])

    assert heard == [EVENTS[2]]
    assert "change listener failed" in caplog.text


def test_a_listener_may_remove_itself_while_it_runs() -> None:
    """The event being delivered still reaches every listener; the removal counts from the next one.

    **Test steps:**

    * add a listener that removes itself, then a recording one
    * publish twice
    """
    feed = ChangeFeed()
    once: list[ChangeEvent] = []
    heard: list[ChangeEvent] = []

    def hear_once(event: ChangeEvent) -> None:
        """Record ``event`` and stop listening.

        :param event: the event.
        """
        once.append(event)
        feed.remove_listener(hear_once)

    feed.add_listener(hear_once)
    feed.add_listener(heard.append)

    feed.publish(EVENTS[0])
    feed.publish(EVENTS[1])

    assert once == [EVENTS[0]]
    assert heard == [EVENTS[0], EVENTS[1]]
