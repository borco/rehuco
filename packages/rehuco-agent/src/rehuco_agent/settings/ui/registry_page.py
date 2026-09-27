"""Registry settings page: file association + folder/archive context-menu registration (#47), and
Windows crash-dump retention (#363)."""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, override

from borco_pyside.file_browser import reveal_in_file_browser
from humanize import naturalsize
from PySide6.QtCore import QUrl
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from ... import crash_dumps, windows_registration
from ...fields.path_field import REVEAL_HINT
from .registry_page_ui import Ui_RegistryPage
from .tray_block import TrayBlock

NOT_RUNNING_FROM_EXE_STATUS: Final = (
    "Cannot register/unregister -- not running from a real .exe (started via `python -m rehuco_agent`)."
)
NOT_CHECKED_STATUS: Final = "Not checked yet."
REGISTERED_STATUS: Final = "Registered."
NOT_REGISTERED_STATUS: Final = "Not registered (or registered from a different location)."

NOT_RUNNING_FROM_EXE_DUMPS_STATUS: Final = (
    "Cannot enable/disable/check crash dumps -- not running from a real .exe (started via `python -m rehuco_agent`)."
)
NOT_CHECKED_DUMPS_STATUS: Final = "Not checked yet."
ENABLED_DUMPS_STATUS: Final = "Crash dumps are kept."
DISABLED_DUMPS_STATUS: Final = "Crash dumps are not kept."
ENABLED_ELSEWHERE_DUMPS_STATUS: Final = "Crash dumps are kept, but in a different folder than expected: {folder}"

NO_DUMPS_YET: Final = "No dumps yet"


class RegistryPage(QWidget):
    """Register/unregister the Windows ``.rehu`` file association and context menus, enable/disable
    kept Windows crash dumps for the running exe (#363), and check whether either is currently in
    place -- a thin GUI wrapper over `rehuco_agent.windows_registration` and `rehuco_agent.crash_dumps`.

    Register/unregister and Enable/Disable crash dumps all take effect immediately when clicked, so
    nothing of theirs is ever staged. The tray block below them (`TrayBlock`, #205) holds this page's
    one staged control, and is what :meth:`is_dirty`/:meth:`save_changes`/:meth:`drop_changes` answer
    for -- the Linux `DesktopIntegrationPage` and the macOS `SystemIntegrationPage` carry the same
    block under the same page title, so the tray setting is reachable on every platform.

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

        self.__ui.crash_dumps_status_label.setText(
            NOT_CHECKED_DUMPS_STATUS if can_register else NOT_RUNNING_FROM_EXE_DUMPS_STATUS
        )
        self.__ui.enable_dumps_button.setEnabled(can_register)
        self.__ui.disable_dumps_button.setEnabled(can_register)
        self.__ui.check_dumps_button.setEnabled(can_register)

        self.__ui.enable_dumps_button.clicked.connect(self.__enable_dumps)
        self.__ui.disable_dumps_button.clicked.connect(self.__disable_dumps)
        self.__ui.check_dumps_button.clicked.connect(self.__check_dumps)
        self.__ui.crash_dumps_path_link.linkActivated.connect(self.__on_dumps_path_link_activated)
        self.__ui.clear_dumps_button.clicked.connect(self.__clear_dumps)

        self.__shown_dumps_folder: Path = crash_dumps.dumps_folder()
        self.__show_dumps_folder()
        self.__refresh_dumps_usage()

        self.__tray: Final = TrayBlock(self.__ui.enabled_check_box, self.__ui.unavailable_label)

    @override
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  (Qt override)
        """Re-read the crash dumps' folder and usage: the first dump creates the folder and every later one
        grows it, while the page sits unopened in the dialog."""
        super().showEvent(event)
        self.__show_dumps_folder()
        self.__refresh_dumps_usage()

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

    def seed_defaults(self) -> None:
        """Stage the tray block's factory value -- registration is not a setting (#342)."""
        self.__tray.seed_defaults()

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

    def __enable_dumps(self) -> None:
        """Turn on kept crash dumps for the running exe, through an elevated PowerShell, then reflect it."""
        crash_dumps.enable(self.__exe_path.name)
        self.__check_dumps()

    def __disable_dumps(self) -> None:
        """Turn off kept crash dumps for the running exe, through an elevated PowerShell, then reflect it."""
        crash_dumps.disable(self.__exe_path.name)
        self.__check_dumps()

    def __check_dumps(self) -> None:
        """Read the ``LocalDumps`` key back and show whether crash dumps are kept, and where.

        The status comes from this read-back, never from Enable/Disable's subprocess exit code, so a
        cancelled UAC prompt reads as "not kept" rather than lying about what happened.
        """
        enabled, folder = crash_dumps.is_enabled(self.__exe_path.name)
        expected = crash_dumps.dumps_folder()
        if not enabled or folder is None:
            self.__ui.crash_dumps_status_label.setText(DISABLED_DUMPS_STATUS)
            self.__shown_dumps_folder = expected
        elif folder == expected:
            self.__ui.crash_dumps_status_label.setText(ENABLED_DUMPS_STATUS)
            self.__shown_dumps_folder = expected
        else:
            self.__ui.crash_dumps_status_label.setText(ENABLED_ELSEWHERE_DUMPS_STATUS.format(folder=folder))
            self.__shown_dumps_folder = folder
        self.__show_dumps_folder()
        self.__refresh_dumps_usage()

    def __show_dumps_folder(self) -> None:
        """Show the shown crash-dumps folder as a link once it exists, plain text before Windows
        creates it with the first dump."""
        text = str(self.__shown_dumps_folder)
        if self.__shown_dumps_folder.exists():
            self.__ui.crash_dumps_path_link.set_text(text, href=QUrl.fromLocalFile(text).toString(), hint=REVEAL_HINT)
        else:
            self.__ui.crash_dumps_path_link.set_text(text)

    def __refresh_dumps_usage(self) -> None:
        """Show how much space the ``*.dmp`` files in the shown folder use, and enable Clear only
        while there is something to clear."""
        files = crash_dumps.dump_files(self.__shown_dumps_folder)
        if not files:
            self.__ui.crash_dumps_usage_label.setText(NO_DUMPS_YET)
            self.__ui.clear_dumps_button.setEnabled(False)
            return
        total = sum(file.stat().st_size for file in files)
        count = "1 dump" if len(files) == 1 else f"{len(files)} dumps"
        self.__ui.crash_dumps_usage_label.setText(f"{naturalsize(total)} in {count}")
        self.__ui.clear_dumps_button.setEnabled(True)

    def __on_dumps_path_link_activated(self, href: str) -> None:
        """Reveal the crash-dumps folder in the OS file browser.

        :param href: the ``file://`` URL the link carried.
        """
        reveal_in_file_browser(Path(QUrl(href).toLocalFile()))

    def __clear_dumps(self) -> None:
        """Delete the crash dumps in the shown folder, then show what is left."""
        crash_dumps.clear_dumps(self.__shown_dumps_folder)
        self.__refresh_dumps_usage()
