"""Tests for the status-icon lookup: which glyph a row wears, and the recolored icon cache (#248)."""

from typing import Any

from PySide6.QtGui import QColor
from pytest import fixture, mark
from pytest_mock import MockerFixture
from rehuco_agent.tasks import task_status_icons
from rehuco_agent.tasks.task_status_icons import PENDING_STOP_ICONS, STATE_ICONS, StatusIconCache, status_icon
from rehuco_core import JobState, JobStatus, StopRequest


def status(state: JobState, stop: StopRequest | None = None) -> JobStatus:
    """A job in ``state``, having been asked for ``stop``.

    :param state: the state the job is in.
    :param stop: what it was last asked to do about stopping.
    :returns: the status to look up.
    """
    return JobStatus(serial=1, label="job", state=state, stop_requested=stop)


# region which glyph


@mark.parametrize("state", list(JobState))
def test_every_state_has_its_own_glyph(state: JobState) -> None:
    """An icon-only column cannot have a state it draws nothing for.

    **Test steps:**

    * look up each of the six states in turn
    * verify each answers a distinct icon
    """
    assert status_icon(status(state)) == STATE_ICONS[state]
    assert len(set(STATE_ICONS.values())) == len(JobState)


@mark.parametrize("stop", list(StopRequest))
def test_a_pending_stop_wins_over_the_state_it_is_still_in(stop: StopRequest) -> None:
    """A running job asked to stop is still honestly running, and the glyph says *asked* -- the same
    precedence :func:`~.task_queue_model.state_text` reads the two fields in.

    **Test steps:**

    * look up a running job that has been asked to pause, and one asked to cancel
    * verify each answers its own pending glyph rather than the running one
    """
    drawn = status_icon(status(JobState.RUNNING, stop))

    assert drawn == PENDING_STOP_ICONS[stop]
    assert drawn != STATE_ICONS[JobState.RUNNING]


def test_a_pending_stop_reads_the_same_whatever_state_it_was_asked_in() -> None:
    """A *queued* job can be asked to cancel too, and reads as cancelling like a running one.

    **Test steps:**

    * look up a queued job asked to cancel
    * verify it answers the cancelling glyph, not the queued one
    """
    assert status_icon(status(JobState.QUEUED, StopRequest.CANCEL)) == PENDING_STOP_ICONS[StopRequest.CANCEL]


def test_the_pending_glyphs_are_not_reused_from_the_states() -> None:
    """*Pausing* must not be drawn as *paused*, or the distinction the column exists to keep is lost.

    **Test steps:**

    * compare the two pending glyphs against every state glyph
    * verify all eight are distinct
    """
    assert len(set(STATE_ICONS.values()) | set(PENDING_STOP_ICONS.values())) == len(JobState) + len(StopRequest)


# endregion


# region the cache


@fixture
def cache(qapp: object) -> StatusIconCache:
    """A fresh cache; takes ``qapp`` because building an icon needs a `QGuiApplication`."""
    del qapp
    return StatusIconCache()


def test_the_same_glyph_and_color_is_built_once(cache: StatusIconCache, mocker: MockerFixture) -> None:
    """Recoloring rewrites an SVG and builds an icon engine, which must not happen per repaint.

    **Test steps:**

    * ask twice for the same glyph in the same color
    * verify the icon was built once and the same object came back
    """
    built = mocker.spy(task_status_icons, "recolored_svg_icon")
    path = STATE_ICONS[JobState.DONE]

    first = cache.icon(path, QColor("red"))
    second = cache.icon(path, QColor("red"))

    assert first is second
    built.assert_called_once()


def test_a_second_color_is_a_second_icon(cache: StatusIconCache) -> None:
    """A theme switch asks for colors not seen before rather than needing the cache told anything.

    **Test steps:**

    * ask for one glyph in two colors
    * verify the two are distinct icons
    """
    path = STATE_ICONS[JobState.DONE]

    assert cache.icon(path, QColor("red")) is not cache.icon(path, QColor("blue"))


def test_the_icon_renders_in_the_color_it_was_asked_for(cache: StatusIconCache) -> None:
    """The recoloring is real, not just a cache key.

    **Test steps:**

    * build a glyph in red and render it
    * verify red pixels came out
    """
    pixmap = cache.icon(STATE_ICONS[JobState.DONE], QColor("red")).pixmap(32, 32)
    image = pixmap.toImage()
    colors: set[Any] = {image.pixelColor(x, y).name() for y in range(image.height()) for x in range(image.width())}

    assert "#ff0000" in colors


# endregion
