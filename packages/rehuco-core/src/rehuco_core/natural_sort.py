"""Natural sort keys -- ``file-2`` before ``file-10`` -- for names and for ``/``-separated paths.

One home for the rule every listing in the project orders by: the legacy screenshot scanner and the
un-converted row (`rehuco_core.tc_screenshots`), the Files sub-dock's name column, and the content-image
browse ([[reference-images#image-identity]], which asks for "natural, not lexical").
"""

import re
from typing import Final

NaturalRun = tuple[int, int, int, str]
"""One digit or non-digit run of a name, as :func:`natural_sort_key` compares it."""

DIGIT_RUNS: Final = re.compile(r"(\d+)")


def natural_sort_key(filename: str) -> tuple[NaturalRun, ...]:
    """``filename`` as a natural-sort key, so ``file-2`` sorts before ``file-10``.

    Per digit/non-digit run: digit runs compare as numbers, non-digit runs case-insensitively. A numeric
    tie (``9`` against ``009``) falls to the run's **length**, fewer leading zeros first -- so
    ``image8 < image9 < image009 < image10``, the order Explorer and Finder show. Deliberately not the
    raw string, which would put ``009`` before ``9`` (``"0" < "9"``) and contradict that example.

    :param filename: the candidate filename.
    :returns: one entry per digit/non-digit run.
    """
    return tuple(
        (0, int(part), len(part), "") if part.isdigit() else (1, 0, 0, part.lower())
        for part in DIGIT_RUNS.split(filename)
        if part
    )


def natural_path_sort_key(path: str) -> tuple[tuple[NaturalRun, ...], ...]:
    """A ``/``-separated path as a natural-sort key, compared **component by component**.

    A zip member's path as the archive stores it (``/`` on every platform). Comparing the components as a
    tuple, each by :func:`natural_sort_key`, is what puts a folder before a same-prefix name
    (``a/x.jpg`` before ``a.jpg``: ``a`` is shorter than ``a.jpg``) rather than wherever the separator's
    code point happens to fall.

    :param path: the ``/``-separated path.
    :returns: one :func:`natural_sort_key` per component.
    """
    return tuple(natural_sort_key(component) for component in path.split("/"))
