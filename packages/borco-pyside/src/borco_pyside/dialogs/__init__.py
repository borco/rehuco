"""A modeless, dockable dialog framework: dialogs hosted as `CDockWidget`s with restore-on-start
persistence (#47)."""

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
