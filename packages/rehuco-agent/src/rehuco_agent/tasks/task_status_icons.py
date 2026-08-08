"""Which icon a task row wears, and the recolored :class:`QIcon` that draws it (#248).

The State column is **icons, no words**: eight glyphs covering every reading the column ever had,
including the two that are not states at all -- a job that has been asked to stop and has not reached
its checkpoint yet ([[appendices.task-queue#pause-concept]]). :func:`status_icon` therefore reads the
same two fields in the same order :func:`~.task_queue_model.state_text` does, so the icon and the
sentence that column's tooltip still carries can never disagree.

Icons are named here rather than passed in, unlike the row tints: a color is a palette decision #251
deliberately keeps out of a widget, but an icon set is this app's own -- the same arrangement
:mod:`~rehuco_agent.item_action_icons` makes for a list editor's actions.
"""

from collections.abc import Mapping
from typing import Final

from borco_pyside.theming import recolored_svg_icon
from borco_pyside.theming.utils import read_resource_bytes
from PySide6.QtGui import QColor, QIcon
from rehuco_core import JobState, JobStatus, StopRequest

STATE_ICONS: Final[Mapping[JobState, str]] = {
    JobState.QUEUED: ":/icons/task_scheduled.svg",
    JobState.RUNNING: ":/icons/task_running.svg",
    JobState.PAUSED: ":/icons/task_paused.svg",
    JobState.DONE: ":/icons/task_done.svg",
    JobState.FAILED: ":/icons/task_failed.svg",
    JobState.CANCELLED: ":/icons/task_canceled.svg",
}
"""One glyph per state, and all six are present.

Distinct from the toolbar's ``task_run``/``task_pause``/``task_cancel``, which are *verbs* on a button
-- what pressing it would do. These are the states themselves, so a row reading ``task_paused`` and a
button offering ``task_pause`` are not the same drawing doing two jobs."""

PENDING_STOP_ICONS: Final[Mapping[StopRequest, str]] = {
    StopRequest.PAUSE: ":/icons/task_pausing.svg",
    StopRequest.CANCEL: ":/icons/task_canceling.svg",
}
"""The two readings that are **not** states: asked to stop, not yet stopped.

A running job that has been told to pause is still honestly running
([[appendices.task-queue#pause-concept]]), which is why this cannot be folded into
:data:`STATE_ICONS` -- and why an icon-only column needs its own glyph for each rather than losing the
distinction the *Pausing…* / *Cancelling…* text used to carry."""


def status_icon(status: JobStatus) -> str:
    """Which icon this row wears -- the pending stop if there is one, else the state.

    The same field order :func:`~.task_queue_model.state_text` reads them in, so the glyph and the
    sentence always describe the same thing.

    :param status: the job to describe.
    :returns: the icon's resource path.
    """
    pending = PENDING_STOP_ICONS.get(status.stop_requested) if status.stop_requested is not None else None
    return pending if pending is not None else STATE_ICONS[status.state]


# one method is the whole of it: a cache that also decided *which* icon, or what color, would be two
# things -- those are :func:`status_icon`'s and the delegate's
# pylint: disable-next=too-few-public-methods
class StatusIconCache:
    """Recolored :class:`QIcon`s for the status glyphs, built once per (icon, color) pair.

    Recoloring rewrites the SVG and builds an icon engine, which is far too much to do on every
    repaint of every row. The pairs are few and bounded -- eight glyphs against the handful of colors a theme puts
    on a row -- so holding them all costs nothing, and a theme switch simply asks for colors not seen
    yet rather than needing to be told anything.
    """

    def __init__(self) -> None:
        self.__icons: dict[tuple[str, int], QIcon] = {}

    def icon(self, path: str, color: QColor) -> QIcon:
        """The glyph at ``path``, recolored to ``color``.

        :param path: the icon's resource path.
        :param color: the color to draw it in.
        :returns: the icon, built on first ask and kept.
        """
        key = (path, color.rgba())
        held = self.__icons.get(key)
        if held is None:
            held = recolored_svg_icon(read_resource_bytes(path), color)
            self.__icons[key] = held  # pylint: disable=unsupported-assignment-operation
        return held
