"""watchdog's ReadDirectoryChangesW emitter, made to say when it lost events, and to close its handle once (#511).

Windows-only, like everything under ``platforms/windows/``: imported only inside
:class:`~rehuco_core.notify.NativeWatch`'s ``if sys.platform == "win32":`` branches.

**watchdog drops an overflow silently.** When the 64 KB notification buffer overflows, ``ReadDirectoryChangesW``
succeeds and returns zero bytes -- "the entire contents of the buffer are discarded" -- and watchdog parses that as no
events at all. #502 measured exactly that on a share: ~830 creates and 2000 deletes lost with nothing to show for it. A
successful read always carries at least one entry, and the only other empty read is the one a stop aborts, so an empty
read while the emitter is meant to keep running *is* the overflow.

**watchdog closes the directory handle on every stop, and keeps its value.** A second stop -- the watch closing its
handle at once, then the observer's own teardown stopping every emitter again -- closes the same value twice, and by
then Windows may have handed it to something else: a thread's handle ("detach_thread: failed detaching thread"), or a
semaphore another thread is about to signal, which ends the process ("ReleaseSemaphore failed (error: 6)"). Measured
with a counting probe on a plain stop, and seen as that crash at quit. Here the handle is taken out under a lock
before it is closed, so whichever stop comes second finds nothing to close; a read takes its own copy, so a stop
between the check and the read cannot hand it ``None``.
"""

import threading
from collections.abc import Callable
from typing import Final, override

from watchdog.observers.read_directory_changes import WindowsApiEmitter
from watchdog.observers.winapi import WinAPINativeEvent, close_directory_handle, read_events

HANDLE_LOCK: Final = threading.Lock()
"""Guards taking an emitter's handle out to close it; shared by every emitter, since a stop is rare and brief."""


class OverflowReportingEmitter(WindowsApiEmitter):
    """A :class:`~watchdog.observers.read_directory_changes.WindowsApiEmitter` that calls :attr:`on_overflow` when the
    operating system discarded a buffer of events, and closes its handle exactly once.

    watchdog builds its emitters itself, so the callback is set on the instance once the watch is scheduled and before
    the observer starts it.
    """

    on_overflow: Callable[[], None] | None = None
    """Called on the emitter's thread when events were lost; ``None`` until set."""

    @override
    def on_thread_stop(self) -> None:
        with HANDLE_LOCK:
            handle, self._whandle = self._whandle, None
        if handle:
            close_directory_handle(handle)

    @override
    def _read_events(self) -> list[WinAPINativeEvent]:
        handle = self._whandle
        if not handle:
            return []
        try:
            events = read_events(handle, self.watch.path, recursive=self.watch.is_recursive)
        except OSError:
            if not self.should_keep_running():  # the handle was closed under the read by a stop: nothing was lost
                return []
            raise
        on_overflow = self.on_overflow
        if not events and self.should_keep_running() and on_overflow is not None:
            # pylint: disable-next=not-callable  # inferred from the class default, past the guard above
            on_overflow()
        return events
