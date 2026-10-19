"""The Windows crash-dump retention frame of the System Integration page (#363, #508)."""

import sys
from pathlib import Path
from typing import Final, override

from borco_pyside.file_browser import reveal_in_file_browser
from humanize import naturalsize
from PySide6.QtCore import QEvent, QObject, QUrl
from PySide6.QtWidgets import QFrame

from ... import crash_dumps, registration_windows
from ...fields.path_field import REVEAL_HINT
from .crash_dumps_frame_windows_ui import Ui_CrashDumpsFrameWindows

NOT_RUNNING_FROM_EXE_DUMPS_STATUS: Final = (
    "Cannot enable/disable/check crash dumps -- not running from a real .exe (started via `python -m rehuco_agent`)."
)
NOT_CHECKED_DUMPS_STATUS: Final = "Not checked yet."
ENABLED_DUMPS_STATUS: Final = "Crash dumps are kept."
DISABLED_DUMPS_STATUS: Final = "Crash dumps are not kept."
ENABLED_ELSEWHERE_DUMPS_STATUS: Final = "Crash dumps are kept, but in a different folder than expected: {folder}"

NO_DUMPS_YET: Final = "No dumps yet"


class CrashDumpsFrameWindows(QObject):
    """Enable/disable kept Windows crash dumps for the running exe (#363), check whether they are kept, and
    show and clear what they use -- a thin GUI wrapper over `rehuco_agent.crash_dumps`.

    **Not a widget**, for the reason `TrayBlock` gives: `SettingsFrameFilter` counts only an exact ``QFrame``
    that is a direct child of the page as a block, so the frame is a plain ``QFrame`` built from this
    frame's ``.ui`` and handed to `SystemIntegrationPage` through :attr:`frame`. This object is parented to
    that frame, so it lives as long as the page does.

    Enable/Disable and Clear take effect immediately when clicked, so nothing of this frame is ever staged.

    Re-reads the dumps' folder and usage whenever the frame is shown: the first dump creates the folder and
    every later one grows it, while the page sits unopened in the dialog.

    Windows-only, like `rehuco_agent.crash_dumps` itself -- only ever constructed inside an
    ``if sys.platform == "win32":`` branch (`main_window.py`).
    """

    def __init__(self) -> None:
        frame = QFrame()
        super().__init__(frame)
        self.__frame: Final = frame
        self.__ui: Final = Ui_CrashDumpsFrameWindows()
        self.__ui.setupUi(frame)

        self.__exe_path: Final = Path(sys.argv[0]).resolve()
        can_enable = registration_windows.is_running_from_exe(self.__exe_path)

        self.__ui.status_label.setText(NOT_CHECKED_DUMPS_STATUS if can_enable else NOT_RUNNING_FROM_EXE_DUMPS_STATUS)
        self.__ui.enable_button.setEnabled(can_enable)
        self.__ui.disable_button.setEnabled(can_enable)
        self.__ui.check_button.setEnabled(can_enable)

        self.__ui.enable_button.clicked.connect(self.__enable)
        self.__ui.disable_button.clicked.connect(self.__disable)
        self.__ui.check_button.clicked.connect(self.__check)
        self.__ui.path_link.linkActivated.connect(self.__on_path_link_activated)
        self.__ui.clear_button.clicked.connect(self.__clear)

        self.__shown_folder: Path = crash_dumps.dumps_folder()
        self.__show_folder()
        self.__refresh_usage()
        frame.installEventFilter(self)

    @property
    def frame(self) -> QFrame:
        """The block, for the page to insert."""
        return self.__frame

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt override)
        """Re-read the dumps' folder and usage each time the frame is shown.

        :param watched: the object the event was sent to.
        :param event: the event.
        :returns: ``False`` -- the event is never consumed.
        """
        if watched is self.__frame and event.type() == QEvent.Type.Show:
            self.__show_folder()
            self.__refresh_usage()
        return super().eventFilter(watched, event)

    def __enable(self) -> None:
        """Turn on kept crash dumps for the running exe, through an elevated PowerShell, then reflect it."""
        crash_dumps.enable(self.__exe_path.name)
        self.__check()

    def __disable(self) -> None:
        """Turn off kept crash dumps for the running exe, through an elevated PowerShell, then reflect it."""
        crash_dumps.disable(self.__exe_path.name)
        self.__check()

    def __check(self) -> None:
        """Read the ``LocalDumps`` key back and show whether crash dumps are kept, and where.

        The status comes from this read-back, never from Enable/Disable's subprocess exit code, so a
        cancelled UAC prompt reads as "not kept" rather than lying about what happened.
        """
        enabled, folder = crash_dumps.is_enabled(self.__exe_path.name)
        expected = crash_dumps.dumps_folder()
        if not enabled or folder is None:
            self.__ui.status_label.setText(DISABLED_DUMPS_STATUS)
            self.__shown_folder = expected
        elif folder == expected:
            self.__ui.status_label.setText(ENABLED_DUMPS_STATUS)
            self.__shown_folder = expected
        else:
            self.__ui.status_label.setText(ENABLED_ELSEWHERE_DUMPS_STATUS.format(folder=folder))
            self.__shown_folder = folder
        self.__show_folder()
        self.__refresh_usage()

    def __show_folder(self) -> None:
        """Show the shown crash-dumps folder as a link once it exists, plain text before Windows
        creates it with the first dump."""
        text = str(self.__shown_folder)
        if self.__shown_folder.exists():
            self.__ui.path_link.set_text(text, href=QUrl.fromLocalFile(text).toString(), hint=REVEAL_HINT)
        else:
            self.__ui.path_link.set_text(text)

    def __refresh_usage(self) -> None:
        """Show how much space the ``*.dmp`` files in the shown folder use, and enable Clear only
        while there is something to clear."""
        files = crash_dumps.dump_files(self.__shown_folder)
        if not files:
            self.__ui.usage_label.setText(NO_DUMPS_YET)
            self.__ui.clear_button.setEnabled(False)
            return
        total = sum(file.stat().st_size for file in files)
        count = "1 dump" if len(files) == 1 else f"{len(files)} dumps"
        self.__ui.usage_label.setText(f"{naturalsize(total)} in {count}")
        self.__ui.clear_button.setEnabled(True)

    def __on_path_link_activated(self, href: str) -> None:
        """Reveal the crash-dumps folder in the OS file browser.

        :param href: the ``file://`` URL the link carried.
        """
        reveal_in_file_browser(Path(QUrl(href).toLocalFile()))

    def __clear(self) -> None:
        """Delete the crash dumps in the shown folder, then show what is left."""
        crash_dumps.clear_dumps(self.__shown_folder)
        self.__refresh_usage()
