"""Trying again a filesystem call Windows refuses while another process briefly holds the file (#512, #546).

Windows refuses a delete or a replace of a file any process has open -- a scanner, an indexer, a reader of a record
for the milliseconds of its read -- as a ``PermissionError``, whatever share mode that process opened it with. The
refusal is over as soon as the handle closes, so the one answer is to try again a few times, a bounded number of them,
and then let the refusal stand. POSIX refuses neither, so there a ``PermissionError`` is a real permission problem,
raised once the same delays are spent.
"""

import time
from collections.abc import Callable, Sequence


def retry_refused(attempt: Callable[[], None], delays: Sequence[float]) -> None:
    """Run ``attempt``, trying it again after each refusal for as many delays as ``delays`` holds.

    :param attempt: the call; its own exceptions other than ``PermissionError`` pass straight through.
    :param delays: how long to wait before each retry, in seconds -- one retry per delay.
    :raises PermissionError: the call was still refused after the last delay.
    """
    for delay in delays:
        try:
            attempt()
        except PermissionError:
            time.sleep(delay)
        else:
            return
    attempt()
