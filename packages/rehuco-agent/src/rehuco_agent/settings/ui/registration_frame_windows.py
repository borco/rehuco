"""The Windows ``.rehu`` file association and context-menu frame of the System Integration page (#47, #508)."""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFrame

from ... import registration_windows
from .registration_frame_windows_ui import Ui_RegistrationFrameWindows

NOT_RUNNING_FROM_EXE_STATUS: Final = (
    "Cannot register/unregister -- not running from a real .exe (started via `python -m rehuco_agent`)."
)
NOT_CHECKED_STATUS: Final = "Not checked yet."
REGISTERED_STATUS: Final = "Registered."
NOT_REGISTERED_STATUS: Final = "Not registered (or registered from a different location)."


class RegistrationFrameWindows(QObject):
    """Register/unregister the Windows ``.rehu`` file association and the folder/archive context menus, and
    check whether they're currently in place (#47) -- a thin GUI wrapper over
    `rehuco_agent.registration_windows`.

    **Not a widget**, for the reason `TrayBlock` gives: `SettingsFrameFilter` counts only an exact ``QFrame``
    that is a direct child of the page as a block, so the frame is a plain ``QFrame`` built from this
    frame's ``.ui`` and handed to `SystemIntegrationPage` through :attr:`frame`. This object is parented to
    that frame, so it lives as long as the page does.

    Register/unregister take effect immediately when clicked, so nothing of this frame is ever staged.

    Windows-only, like `rehuco_agent.registration_windows` itself -- only ever constructed inside
    an ``if sys.platform == "win32":`` branch (`main_window.py`).

    Takes ``archive_extensions`` as a constructor parameter, not by importing
    ``rehuco_agent.main_window.ARCHIVE_EXTENSIONS`` directly -- ``main_window.py`` already imports
    this module (lazily, to construct the frame), so a module-level import back the other way would
    be a cyclic import.

    :param archive_extensions: archive file extensions (each including the leading dot) that get
        the "Create or Open Rehuco Info" shell verb -- ``rehuco_agent.main_window.ARCHIVE_EXTENSIONS``.
    """

    def __init__(self, archive_extensions: Sequence[str]) -> None:
        frame = QFrame()
        super().__init__(frame)
        self.__frame: Final = frame
        self.__ui: Final = Ui_RegistrationFrameWindows()
        self.__ui.setupUi(frame)
        self.__archive_extensions: Final = archive_extensions

        self.__exe_path: Final = Path(sys.argv[0]).resolve()
        can_register = registration_windows.is_running_from_exe(self.__exe_path)

        self.__ui.status_label.setText(NOT_CHECKED_STATUS if can_register else NOT_RUNNING_FROM_EXE_STATUS)
        self.__ui.register_button.setEnabled(can_register)
        self.__ui.unregister_button.setEnabled(can_register)
        self.__ui.check_button.setEnabled(can_register)

        self.__ui.register_button.clicked.connect(self.__register)
        self.__ui.unregister_button.clicked.connect(self.__unregister)
        self.__ui.check_button.clicked.connect(self.__check)

    @property
    def frame(self) -> QFrame:
        """The block, for the page to insert."""
        return self.__frame

    def __register(self) -> None:
        """Register the file association and context menus, then reflect the result."""
        registration_windows.register(self.__exe_path, self.__archive_extensions)
        self.__ui.status_label.setText(REGISTERED_STATUS)

    def __unregister(self) -> None:
        """Remove the file association and context menus, then reflect the result."""
        registration_windows.unregister(self.__archive_extensions)
        self.__ui.status_label.setText(NOT_REGISTERED_STATUS)

    def __check(self) -> None:
        """Verify the expected registry entries are present and show the result."""
        registered = registration_windows.is_registered(self.__exe_path, self.__archive_extensions)
        self.__ui.status_label.setText(REGISTERED_STATUS if registered else NOT_REGISTERED_STATUS)
