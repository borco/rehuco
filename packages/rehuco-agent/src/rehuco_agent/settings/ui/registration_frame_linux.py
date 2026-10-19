"""The Linux ``.rehu`` file association frame of the System Integration page (#209, #508)."""

from pathlib import Path
from typing import Final

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFrame

from ... import registration_linux
from .registration_frame_linux_ui import Ui_RegistrationFrameLinux

NOT_CHECKED_STATUS: Final = "Not checked yet."
REGISTERED_STATUS: Final = "Registered."
NOT_REGISTERED_STATUS: Final = "Not registered."
REGISTERED_ELSEWHERE_STATUS: Final = (
    "Registered, but launching a different location ({command}) -- click Register to point it here."
)
STALE_STATUS: Final = (
    "Registered from here, but its desktop entry, MIME type or icon differs from this version's "
    "-- click Register to refresh it."
)


class RegistrationFrameLinux(QObject):
    """Register/unregister the Linux ``.rehu`` desktop entry, MIME type and icon, and check
    whether they're currently in place (#209) -- a thin GUI wrapper over
    `rehuco_agent.registration_linux`, the same orchestration the CLI's ``--register``/
    ``--unregister`` use.

    **Not a widget**, for the reason `TrayBlock` gives: `SettingsFrameFilter` counts only an exact ``QFrame``
    that is a direct child of the page as a block, so the frame is a plain ``QFrame`` built from this
    frame's ``.ui`` and handed to `SystemIntegrationPage` through :attr:`frame`. This object is parented to
    that frame, so it lives as long as the page does.

    Register/unregister take effect immediately when clicked, so nothing of this frame is ever staged.

    Reports four states rather than the three of its Windows counterpart: "registered, but launching a
    different location" is the **ordinary** case here, not an edge one -- an AppImage is a file the user may
    move, rename or replace with a newer download, and each of those silently invalidates the recorded
    ``Exec`` ([[packaging-deployment#linux-format]]). Registering again is the fix, which is why that status
    names the action rather than just the fact.

    Takes no ``archive_extensions``: the folder and archive shell verbs (#43) are Windows-only, and
    each Linux desktop environment has its own mechanism for them
    ([[packaging-deployment#app-identity]]).
    """

    def __init__(self) -> None:
        frame = QFrame()
        super().__init__(frame)
        self.__frame: Final = frame
        self.__ui: Final = Ui_RegistrationFrameLinux()
        self.__ui.setupUi(frame)

        self.__exe_path: Final = registration_linux.executable_path()
        register_blocker = registration_linux.registration_blocker(self.__exe_path)
        # unregistering and checking status never depend on exe_path being launchable -- only
        # actually registering does (a broken Exec= would be written); sandboxed is the one
        # reason that blocks all three alike
        unregister_blocker = registration_linux.unregistration_blocker()

        self.__ui.status_label.setText(NOT_CHECKED_STATUS if register_blocker is None else register_blocker)
        self.__ui.register_button.setEnabled(register_blocker is None)
        self.__ui.unregister_button.setEnabled(unregister_blocker is None)
        self.__ui.check_button.setEnabled(unregister_blocker is None)

        self.__ui.register_button.clicked.connect(self.__register)
        self.__ui.unregister_button.clicked.connect(self.__unregister)
        self.__ui.check_button.clicked.connect(self.__check)

    @property
    def frame(self) -> QFrame:
        """The block, for the page to insert."""
        return self.__frame

    def __register(self) -> None:
        """Write the desktop entry, MIME type and icon, then reflect the result."""
        registration_linux.register(self.__exe_path)
        self.__ui.status_label.setText(REGISTERED_STATUS)

    def __unregister(self) -> None:
        """Remove the desktop entry, MIME type and icon, then reflect the result."""
        registration_linux.unregister()
        self.__ui.status_label.setText(NOT_REGISTERED_STATUS)

    def __check(self) -> None:
        """Verify the expected files are present and show which of the four states holds."""
        self.__ui.status_label.setText(self.__status(self.__exe_path))

    @staticmethod
    def __status(exe_path: Path) -> str:
        """Which registration state currently holds, as the sentence to show.

        :param exe_path: the executable this frame would register.
        :returns: one of the four status strings.
        """
        if registration_linux.is_registered(exe_path):
            return REGISTERED_STATUS
        command = registration_linux.registered_command()
        if command is None:
            return NOT_REGISTERED_STATUS
        if command != registration_linux.launch_command(exe_path):
            return REGISTERED_ELSEWHERE_STATUS.format(command=command)
        return STALE_STATUS
