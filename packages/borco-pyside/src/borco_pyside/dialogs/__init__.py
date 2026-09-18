"""A modeless, dockable dialog framework: dialogs hosted as `CDockWidget`s with restore-on-start
persistence.

Offered to callers of this library, and used by none of the applications in this repository: rehuco's
Settings surface was the last one, and #307 made it an ordinary dock whose visibility rides on its
`CDockManager`'s own ``saveState()``. The restore-on-start checkbox this adds is for a dialog the user
should be able to leave open *now* without it reopening next launch -- a distinction a dock does not
draw, and the reason that app stopped wanting it."""

from .dockable_dialog import DockableDialog
from .dockable_dialog_frame import DockableDialogFrame
from .dockable_dialog_manager import DockableDialogManager
from .dockable_dialog_settings import DockableDialogSettings

__all__ = [
    "DockableDialog",
    "DockableDialogFrame",
    "DockableDialogManager",
    "DockableDialogSettings",
]
