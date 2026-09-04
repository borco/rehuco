"""Registry settings page: file association + folder/archive context-menu registration (#47)."""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from PySide6.QtWidgets import QWidget

from ... import windows_registration
from .registry_page_ui import Ui_RegistryPage
from .tray_block import TrayBlock

NOT_RUNNING_FROM_EXE_STATUS: Final = (
    "Cannot register/unregister -- not running from a real .exe (started via `python -m rehuco_agent`)."
)
NOT_CHECKED_STATUS: Final = "Not checked yet."
REGISTERED_STATUS: Final = "Registered."
NOT_REGISTERED_STATUS: Final = "Not registered (or registered from a different location)."


class RegistryPage(QWidget):
    """Register/unregister the Windows ``.rehu`` file association and context menus, and check
    whether they're currently in place (#47) -- a thin GUI wrapper over
    `rehuco_agent.windows_registration`, the same orchestration the CLI's ``--register``/
    ``--unregister`` use.

    Register/unregister take effect immediately when clicked, so nothing of theirs is ever staged.
    The tray block below them (`TrayBlock`, #205) holds this page's one staged control, and is what
    :meth:`is_dirty`/:meth:`save_changes`/:meth:`drop_changes` answer for -- the Linux
    `DesktopIntegrationPage` and the macOS `SystemIntegrationPage` carry the same block under the
    same page title, so the tray setting is reachable on every platform.

    Windows-only, like `rehuco_agent.windows_registration` itself -- only ever constructed inside
    an ``if sys.platform == "win32":`` branch (`main_window.py`).

    Takes ``archive_extensions`` as a constructor parameter, not by importing
    ``rehuco_agent.main_window.ARCHIVE_EXTENSIONS`` directly -- ``main_window.py`` already imports
    this module (lazily, to construct the page), so a module-level import back the other way would
    be a cyclic import.

    :param archive_extensions: archive file extensions (each including the leading dot) that get
        the "Create or Open Rehuco Info" shell verb -- ``rehuco_agent.main_window.ARCHIVE_EXTENSIONS``.
    :param parent: optional Qt parent.
    """

    def __init__(self, archive_extensions: Sequence[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RegistryPage()
        self.__ui.setupUi(self)
        self.__archive_extensions: Final = archive_extensions

        self.__exe_path: Final = Path(sys.argv[0]).resolve()
        can_register = windows_registration.is_running_from_exe(self.__exe_path)

        self.__ui.status_label.setText(NOT_CHECKED_STATUS if can_register else NOT_RUNNING_FROM_EXE_STATUS)
        self.__ui.register_button.setEnabled(can_register)
        self.__ui.unregister_button.setEnabled(can_register)
        self.__ui.check_button.setEnabled(can_register)

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
        """Register the file association and context menus, then reflect the result."""
        windows_registration.register(self.__exe_path, self.__archive_extensions)
        self.__ui.status_label.setText(REGISTERED_STATUS)

    def __unregister(self) -> None:
        """Remove the file association and context menus, then reflect the result."""
        windows_registration.unregister(self.__archive_extensions)
        self.__ui.status_label.setText(NOT_REGISTERED_STATUS)

    def __check(self) -> None:
        """Verify the expected registry entries are present and show the result."""
        registered = windows_registration.is_registered(self.__exe_path, self.__archive_extensions)
        self.__ui.status_label.setText(REGISTERED_STATUS if registered else NOT_REGISTERED_STATUS)
