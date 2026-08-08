"""How each unit of progress reads in a task row -- one renderer per unit a job can declare (#248).

**Core declares, the agent renders.** A job says what its ``done``/``total`` count
(:attr:`~rehuco_core.TaskJob.progress_unit`) and nothing about how that looks; this is where the
looking is decided, because it is the layer that may depend on `humanize` and on what a table cell can
hold. `rehuco-core` gains neither.

Keyed by the unit rather than by the job -- and deliberately not by
:attr:`~rehuco_core.PersistableTaskJob.kind`, which is a promise written into the user's saved queue
file and therefore not something a display lookup may pin down. Two jobs counting bytes read the same
because they *are* the same question asked twice.
"""

from collections.abc import Callable, Mapping
from typing import Final

import humanize
from rehuco_core import PROGRESS_UNIT_BYTES, PROGRESS_UNIT_RESOURCES, JobStatus

type ProgressRenderer = Callable[[JobStatus], str]
"""What a unit's renderer is: a job's numbers in, one line of text out.

``""`` is a legitimate answer -- a cell holding nothing is better than one holding a figure that means
nothing -- and the caller decides what to do with the emptiness.

**Never asked about a job with nothing to say.** :func:`progress_text` answers the *counted nothing,
had nothing to count* case itself, so a renderer is only ever handed numbers worth writing out and none
of them has to repeat the check."""


def render_bytes(status: JobStatus) -> str:
    """A byte count, humanized GNU-style -- ``"3.0G / 8.2G"``, or ``"3.0G"`` with no total yet.

    The same spelling :class:`~rehuco_agent.fields.widgets.SizeMeasurementEdit` uses for a resource's
    size, so the two figures a reader compares are written the same way.

    :param status: the job to describe.
    :returns: the text for its cell.
    """
    done = humanize.naturalsize(status.done, gnu=True)
    if status.total is None or status.total <= 0:
        return done
    return f"{done} / {humanize.naturalsize(status.total, gnu=True)}"


def render_resources(status: JobStatus) -> str:
    """A resource count, named -- ``"12 / 40 resources"``, or ``"12 resources"`` with no total yet.

    The unit is spelled out because the numbers are small enough to be mistaken for anything: a bare
    ``12 / 40`` beside a row reading ``3.0G / 8.2G`` invites reading it as files, or as percent.

    :param status: the job to describe.
    :returns: the text for its cell.
    """
    if status.total is None or status.total <= 0:
        return f"{status.done} {plural_resources(status.done)}"
    return f"{status.done} / {status.total} {plural_resources(status.total)}"


def plural_resources(count: int) -> str:
    """``"resource"`` for one, ``"resources"`` for anything else.

    :param count: how many.
    :returns: the noun to use.
    """
    return "resource" if count == 1 else "resources"


def render_counts(status: JobStatus) -> str:
    """The bare numbers -- ``"3/4"``, or ``"3"`` with no total yet.

    What a unit nobody here recognizes falls back to: a job declaring one this build has never seen
    still has honest figures, and showing them unlabelled is better than showing nothing and better
    than inventing a name for them.

    :param status: the job to describe.
    :returns: the text for its cell.
    """
    if status.total is None or status.total <= 0:
        return str(status.done)
    return f"{status.done}/{status.total}"


PROGRESS_RENDERERS: Final[Mapping[str, ProgressRenderer]] = {
    PROGRESS_UNIT_BYTES: render_bytes,
    PROGRESS_UNIT_RESOURCES: render_resources,
}
"""Every unit this build knows how to write out.

A unit missing from here is not an error -- see :func:`render_counts` -- and a job declaring no unit at
all never reaches this map, because there is nothing to render rather than something unrecognized."""


def progress_text(status: JobStatus) -> str:
    """What ``status``'s progress reads as, in its own unit.

    Two ways a job has nothing to say, and both draw an empty cell rather than a zero:

    - **it declares no unit** -- its work is one indivisible step, so there was never a figure to show;
    - **it counted nothing and had nothing to count** -- a verify whose files were all checked
      recently has no bytes to read, and a sweep over a folder holding no resources has none to walk.
      Both report ``(0, 0)`` honestly, and ``0B`` is a worse answer than nothing: it reads as *this ran
      and moved zero bytes* where the truth is *there was nothing here to do*. What the run established
      is the log's to say ([[data-model#checksums]] -- ``"nothing to check"``), not a table cell's.

    A ``0`` against a **real** total is not this case and still draws: ``0 / 40 resources`` is a job
    with forty resources ahead of it, which is worth a reader's attention.

    :param status: the job to describe.
    :returns: the text for its cell; ``""`` in either case above, or when its renderer had nothing to
        say.
    """
    if not status.progress_unit:
        return ""
    if not status.done and (status.total is None or status.total <= 0):
        return ""
    renderer = PROGRESS_RENDERERS.get(status.progress_unit, render_counts)
    return renderer(status)
