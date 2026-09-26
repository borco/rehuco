"""Logs settings page: how much of the log each surface keeps (#200), and the run log file (#362)."""

import logging
from pathlib import Path
from typing import Final, override

from borco_pyside.file_browser import reveal_in_file_browser
from humanize import naturalsize
from PySide6.QtCore import QUrl
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from ...fields.path_field import REVEAL_HINT
from ...run_log import shared_run_log
from ..logs_settings import LogsSettings, shared_logs_settings
from ..persistent_settings import persistent_settings
from .logs_page_ui import Ui_LogsPage

LOG: Final = logging.getLogger(__name__)

CLAMP_NOTE: Final = (
    "The other log docks are held to {limit} records — the main log dock's limit, which is as far back as anything"
    " is kept."
)
"""Shown while the resource limit is set above the app one, naming the number that actually applies.

Said rather than silently corrected: the typed value is kept, so raising the app limit later gives the
resource logs the number they were already asked for -- but a page that showed a limit nothing honours
would be lying about what its own Save did."""

NO_LOG_FILES: Final = "Nothing written yet"
"""The usage line when neither the log file nor any backup exists -- a cleared log, until the next record."""


class LogsPage(QWidget):
    """Configure how many records the app-wide log and each resource's log keep
    ([[appendices.logging#configured-limits]]).

    Two spin boxes over `LogsSettings`. The app-wide limit is deliberately *also* the bridge's replay
    cache, so raising it is what makes a newly opened log dock show more of what already happened. The
    per-resource one goes down to zero, meaning *keep everything*, which the spin box shows in words
    rather than as a bare ``0`` a reader would take for *keep none*; the app-wide one does not, and
    :data:`~rehuco_agent.settings.logs_settings.MINIMUM_RESOURCE_LIMIT` says why the difference is what
    lets zero mean that at all.

    Edits are staged in the widgets until :meth:`save_changes` pushes them into the shared settings,
    which re-caps every log surface already open -- the reason this page's settings object is reactive
    rather than a value read at construction.

    The **Log file** frame does the same for the run log file ([[appendices.logging#run-log-file]]): its
    size and backup count reach the running handler on Save. Its location and the space it uses are
    facts about the disk rather than settings, so they are read again whenever the page is shown and
    after a clear, and nothing about them is staged.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_LogsPage()
        self.__ui.setupUi(self)

        self.__ui.app_limit_spin_box.valueChanged.connect(self.__show_clamp_note)
        self.__ui.resource_limit_spin_box.valueChanged.connect(self.__show_clamp_note)
        self.__ui.log_file_path_link.linkActivated.connect(self.__on_path_link_activated)
        self.__ui.clear_log_files_button.clicked.connect(self.__on_clear_clicked)

        self.drop_changes()
        self.__show_log_file()

    @override
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802  (Qt override)
        """Re-read the log file's usage: it grows while the page sits unopened in the dialog."""
        super().showEvent(event)
        self.__show_log_file()

    def is_dirty(self) -> bool:
        """Whether any staged value differs from what the shared settings currently hold."""
        settings = shared_logs_settings()
        return (
            self.__ui.app_limit_spin_box.value() != settings.app_limit
            or self.__ui.resource_limit_spin_box.value() != settings.resource_limit
            or self.__ui.log_file_size_spin_box.value() != settings.file_size_mb
            or self.__ui.log_file_backups_spin_box.value() != settings.file_backups
        )

    def save_changes(self) -> None:
        """Push the staged values into the shared settings and persist them.

        Every open surface re-caps itself off the settings object's own change signals, so nothing here
        reaches for a dock: this page does not know how many are open, and should not have to. The run
        log's handler follows the same signals for the file size and backup count.
        """
        settings = shared_logs_settings()
        settings.app_limit = self.__ui.app_limit_spin_box.value()
        settings.resource_limit = self.__ui.resource_limit_spin_box.value()
        settings.file_size_mb = self.__ui.log_file_size_spin_box.value()
        settings.file_backups = self.__ui.log_file_backups_spin_box.value()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding both spin boxes from the shared settings."""
        self.__show(shared_logs_settings())

    def seed_defaults(self) -> None:
        """Stage the factory values: what an unloaded `LogsSettings` holds (#342)."""
        self.__show(LogsSettings())

    def __show(self, settings: LogsSettings) -> None:
        """Fill both spin boxes from ``settings``.

        :param settings: the values to show -- the shared object's saved ones, or a fresh one's defaults.
        """
        self.__ui.app_limit_spin_box.setValue(settings.app_limit)
        self.__ui.resource_limit_spin_box.setValue(settings.resource_limit)
        self.__ui.log_file_size_spin_box.setValue(settings.file_size_mb)
        self.__ui.log_file_backups_spin_box.setValue(settings.file_backups)
        self.__show_clamp_note()

    def __show_log_file(self) -> None:
        """Show where the run log file is and how much space it and its backups take right now."""
        handler = shared_run_log().handler
        path = handler.baseFilename
        self.__ui.log_file_path_link.set_text(path, href=QUrl.fromLocalFile(path).toString(), hint=REVEAL_HINT)
        existing = [file for file in handler.log_files() if file.exists()]
        if not existing:
            self.__ui.log_file_usage_label.setText(NO_LOG_FILES)
            return
        files = "1 file" if len(existing) == 1 else f"{len(existing)} files"
        self.__ui.log_file_usage_label.setText(f"{naturalsize(handler.used_bytes())} in {files}")

    def __on_path_link_activated(self, href: str) -> None:
        """Reveal the log file in the OS file browser, selected in its folder.

        :param href: the ``file://`` URL the link carried.
        """
        reveal_in_file_browser(Path(QUrl(href).toLocalFile()))

    def __on_clear_clicked(self) -> None:
        """Empty the log file and delete its backups, then show what is left.

        A failure is logged rather than shown in a dialog: the usage line is re-read either way and says
        what is still there. A successful clear is logged too, which makes that record the first line of
        the emptied file -- so a reader later can tell an empty log from one cleared on purpose.
        """
        try:
            shared_run_log().handler.clear()
        except OSError:
            LOG.warning("Could not clear the log files", exc_info=True)
        else:
            LOG.info("Log files cleared")
        self.__show_log_file()

    def __show_clamp_note(self) -> None:
        """Say when the staged resource limit is above the app one, and so cannot be honoured.

        Zero needs no case of its own, and gets none: *keep everything* is never *above* a limit, so the
        comparison is false and the note stays quiet -- which is the whole of what the page owes it. What
        no cap does and does not cover is [[appendices.logging#configured-limits]]'s to say, not a
        paragraph a reader has to read past every time this page is opened (#236).

        Checked against the *staged* values, not the saved ones: what a reader wants to know while typing
        a number is whether the number they are typing will apply.
        """
        app_limit = self.__ui.app_limit_spin_box.value()
        clamped = self.__ui.resource_limit_spin_box.value() > app_limit
        self.__ui.clamp_note_label.setText(CLAMP_NOTE.format(limit=app_limit) if clamped else "")
        self.__ui.clamp_note_label.setVisible(clamped)
