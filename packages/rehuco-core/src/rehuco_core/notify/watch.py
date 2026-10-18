"""What every backend of the file notifier is to it (#511)."""

from typing import Protocol


class Watch(Protocol):
    """One backend watching one folder, reporting each :class:`~rehuco_core.notify.RawChange` to the sink it was given.

    **It never blocks quitting**: whatever it waits on runs on daemon threads, and :meth:`stop` returns at once.
    """

    def start(self) -> None:
        """Begin watching.

        :raises OSError: when the folder cannot be watched this way -- the caller falls back to another backend.
        """

    def stop(self) -> None:
        """Stop watching and report nothing more. Returns at once; a call blocked in the operating system is left to
        end on its own daemon thread."""

    @property
    def failed(self) -> bool:  # pyright: ignore[reportReturnType]
        """Whether it stopped watching without being told to -- the folder went away, the server dropped the session."""
