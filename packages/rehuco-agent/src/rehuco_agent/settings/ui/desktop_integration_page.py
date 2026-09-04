"""Desktop Integration settings page: the Linux ``.rehu`` file association (#209)."""

from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QWidget

from ... import linux_registration
from .desktop_integration_page_ui import Ui_DesktopIntegrationPage
from .tray_block import TrayBlock

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


# The three-button wiring and the four settings-page protocol methods below are the same 25 lines
# as `RegistryPage`'s. Kept as a deliberate copy, not factored into a shared base: the two are
# per-OS twins whose `.ui` files (hence generated `Ui_` types), constructor arguments and status
# vocabularies already differ -- this page reports four states where the Windows one reports three
# -- and a base class over two platform-specific pages would have to be re-opened by whichever OS
# diverges next. Matches the same choice made in `tests/rehuco_agent_tests/conftest.py`'s `FakeSettings`.
# pylint: disable=duplicate-code
class DesktopIntegrationPage(QWidget):
    """Register/unregister the Linux ``.rehu`` desktop entry, MIME type and icon, and check
    whether they're currently in place (#209) -- a thin GUI wrapper over
    `rehuco_agent.linux_registration`, the same orchestration the CLI's ``--register``/
    ``--unregister`` use.

    Register/unregister take effect immediately when clicked, so nothing of theirs is ever staged.
    The tray block below them (`TrayBlock`, #205) holds this page's one staged control, and is what
    :meth:`is_dirty`/:meth:`save_changes`/:meth:`drop_changes` answer for. The same shape as the
    Windows `RegistryPage`, and constructed under the matching ``sys.platform == "linux"`` branch in
    `main_window.py`.

    Unlike that page, this one reports four states rather than three:
    "registered, but launching a different location" is the **ordinary** case here, not an edge
    one -- an AppImage is a file the user may move, rename or replace with a newer download, and
    each of those silently invalidates the recorded ``Exec``
    ([[packaging-deployment#linux-format]]). Registering again is the fix, which is why that status
    names the action rather than just the fact.

    Takes no ``archive_extensions``: the folder and archive shell verbs (#43) are Windows-only, and
    each Linux desktop environment has its own mechanism for them
    ([[packaging-deployment#app-identity]]).

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_DesktopIntegrationPage()
        self.__ui.setupUi(self)

        self.__exe_path: Final = linux_registration.executable_path()
        register_blocker = linux_registration.registration_blocker(self.__exe_path)
        # unregistering and checking status never depend on exe_path being launchable -- only
        # actually registering does (a broken Exec= would be written); sandboxed is the one
        # reason that blocks all three alike
        unregister_blocker = linux_registration.unregistration_blocker()

        self.__ui.status_label.setText(NOT_CHECKED_STATUS if register_blocker is None else register_blocker)
        self.__ui.register_button.setEnabled(register_blocker is None)
        self.__ui.unregister_button.setEnabled(unregister_blocker is None)
        self.__ui.check_button.setEnabled(unregister_blocker is None)

        self.__ui.register_button.clicked.connect(self.__register)
        self.__ui.unregister_button.clicked.connect(self.__unregister)
        self.__ui.check_button.clicked.connect(self.__check)

        self.__tray: Final = TrayBlock(self.__ui.enabled_check_box, self.__ui.unavailable_label)

    def is_dirty(self) -> bool:
        """Whether the staged tray checkbox differs from what's saved.

        The registration controls above it never contribute: they act immediately when clicked, so
        there is nothing of theirs to stage (#205 put the one staged control on this page)."""
        return self.__tray.is_dirty()

    def save_changes(self) -> None:
        """Persist the staged tray choice -- register/unregister already took effect when clicked."""
        self.__tray.save_changes()

    def drop_changes(self) -> None:
        """Discard the staged tray edit -- register/unregister already took effect when clicked."""
        self.__tray.drop_changes()

    def __register(self) -> None:
        """Write the desktop entry, MIME type and icon, then reflect the result."""
        linux_registration.register(self.__exe_path)
        self.__ui.status_label.setText(REGISTERED_STATUS)

    def __unregister(self) -> None:
        """Remove the desktop entry, MIME type and icon, then reflect the result."""
        linux_registration.unregister()
        self.__ui.status_label.setText(NOT_REGISTERED_STATUS)

    def __check(self) -> None:
        """Verify the expected files are present and show which of the four states holds."""
        self.__ui.status_label.setText(self.__status(self.__exe_path))

    @staticmethod
    def __status(exe_path: Path) -> str:
        """Which registration state currently holds, as the sentence to show.

        :param exe_path: the executable this page would register.
        :returns: one of the four status strings.
        """
        if linux_registration.is_registered(exe_path):
            return REGISTERED_STATUS
        command = linux_registration.registered_command()
        if command is None:
            return NOT_REGISTERED_STATUS
        if command != linux_registration.launch_command(exe_path):
            return REGISTERED_ELSEWHERE_STATUS.format(command=command)
        return STALE_STATUS
