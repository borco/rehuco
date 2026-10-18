"""What changed on disk, as the disk says it: one notifier per watched folder, publishing on the change feed (#511,
[[mounts-and-storage#out-of-band]]).

- :mod:`~rehuco_core.notify.file_notifier` -- :class:`FileNotifier`, choosing a backend by storage kind and falling
  back to polling; :mod:`~rehuco_core.notify.watched_folder` -- :class:`WatchedFolder`, what it watches.
- :mod:`~rehuco_core.notify.root_notifiers` -- :class:`RootNotifiers`, one notifier per root of the open ``.rehuco``.
- :mod:`~rehuco_core.notify.change_coalescer` -- :class:`ChangeCoalescer`, from observations to the feed's events.
- The backends: :class:`NativeWatch`, :class:`SmbWatch`, :class:`PollingWatch`, all a :class:`Watch`, each reporting
  :class:`RawChange` observations.

Nothing here imports Qt.
"""

from .change_coalescer import ChangeCoalescer
from .file_notifier import FileNotifier
from .native_watch import NativeWatch
from .polling_watch import PollingWatch
from .raw_change import RawChange, RawChangeKind
from .root_notifiers import RootNotifiers
from .smb_watch import SmbLocation, SmbWatch
from .watch import Watch
from .watched_folder import WatchedFolder

__all__ = [
    "ChangeCoalescer",
    "FileNotifier",
    "NativeWatch",
    "PollingWatch",
    "RawChange",
    "RawChangeKind",
    "RootNotifiers",
    "SmbLocation",
    "SmbWatch",
    "Watch",
    "WatchedFolder",
]
