"""Which icon a task row wears, and the recolored :class:`QIcon` that draws it (#248).

The State column is **icons, no words**: ten glyphs covering every reading the column ever had,
including a done job that left something to act on (#712) and the two that are not states at all --
a job that has been asked to stop and has not reached its checkpoint yet
([[appendices.task-queue#pause-concept]]). :func:`status_icon` therefore reads the same two fields in
the same order :func:`~.task_queue_model.state_text` does, so the icon and the sentence that column's
tooltip still carries can never disagree.

Icons are named here rather than passed in, unlike the row tints: a color is a palette decision #251
deliberately keeps out of a widget, but an icon set is this app's own -- the same arrangement
:mod:`~rehuco_agent.item_action_icons` makes for a list editor's actions.
"""

from collections.abc import Mapping
from typing import Final

from rehuco_core import JobState, JobStatus, StopRequest

from .task_row_delegate import UNCLEAN_DONE, status_key

STATE_ICONS: Final[Mapping[JobState, str]] = {
    JobState.QUEUED: ":/icons/task_scheduled.svg",
    JobState.RUNNING: ":/icons/task_running.svg",
    JobState.PAUSED: ":/icons/task_paused.svg",
    JobState.WAITING: ":/icons/task_waiting.svg",
    JobState.DONE: ":/icons/task_done.svg",
    JobState.FAILED: ":/icons/task_failed.svg",
    JobState.CANCELED: ":/icons/task_canceled.svg",
}
"""One glyph per state, and all seven are present.

Distinct from the toolbar's ``task_run``/``task_pause``/``task_cancel``, which are *verbs* on a button
-- what pressing it would do. These are the states themselves, so a row reading ``task_paused`` and a
button offering ``task_pause`` are not the same drawing doing two jobs.

``WAITING`` is a raised hand rather than a second hourglass (#497): queued waits for its turn, waiting for
something outside the app, and the two must not read as one at a glance."""

UNCLEAN_DONE_ICON: Final = ":/icons/task_done_unclean.svg"
"""What a done row wears when its outcome is not clean (#712): the warning triangle, not the check of a job that
finished well, and not the failed row's barred disc -- it did finish."""

PENDING_STOP_ICONS: Final[Mapping[StopRequest, str]] = {
    StopRequest.PAUSE: ":/icons/task_pausing.svg",
    StopRequest.CANCEL: ":/icons/task_canceling.svg",
}
"""The two readings that are **not** states: asked to stop, not yet stopped.

A running job that has been told to pause is still honestly running
([[appendices.task-queue#pause-concept]]), which is why this cannot be folded into
:data:`STATE_ICONS` -- and why an icon-only column needs its own glyph for each rather than losing the
distinction the *Pausing…* / *Canceling…* text used to carry."""


def status_icon(status: JobStatus) -> str:
    """Which icon this row wears -- the pending stop if there is one, else the state.

    The same field order :func:`~.task_queue_model.state_text` reads them in, so the glyph and the
    sentence always describe the same thing.

    A done job that is not clean wears :data:`UNCLEAN_DONE_ICON` (#712).

    :param status: the job to describe.
    :returns: the icon's resource path.
    """
    pending = PENDING_STOP_ICONS.get(status.stop_requested) if status.stop_requested is not None else None
    if pending is not None:
        return pending
    return UNCLEAN_DONE_ICON if status_key(status) == UNCLEAN_DONE else STATE_ICONS[status.state]
