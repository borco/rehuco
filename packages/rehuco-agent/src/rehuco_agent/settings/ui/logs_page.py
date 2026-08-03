"""Logs settings page: how much of the log each surface keeps (#200)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ..logs_settings import shared_logs_settings
from ..persistent_settings import persistent_settings
from .logs_page_ui import Ui_LogsPage

CLAMP_NOTE: Final = (
    "A resource log is held to {limit} records — the app log's limit, which is as far back as anything is kept."
)
"""Shown while the resource limit is set above the app one, naming the number that actually applies.

Said rather than silently corrected: the typed value is kept, so raising the app limit later gives the
resource logs the number they were already asked for -- but a page that showed a limit nothing honours
would be lying about what its own Save did."""


class LogsPage(QWidget):
    """Configure how many records the app-wide log and each resource's log keep
    ([[appendices.logging#configured-limits]]).

    Two spin boxes over `LogsSettings`. The app-wide limit is deliberately *also* the bridge's replay
    cache, so raising it is what makes a newly opened log dock show more of what already happened.

    Edits are staged in the widgets until :meth:`save_changes` pushes them into the shared settings,
    which re-caps every log surface already open -- the reason this page's settings object is reactive
    rather than a value read at construction.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_LogsPage()
        self.__ui.setupUi(self)

        self.__ui.app_limit_spin_box.valueChanged.connect(self.__show_clamp_note)
        self.__ui.resource_limit_spin_box.valueChanged.connect(self.__show_clamp_note)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Logs"

    def is_dirty(self) -> bool:
        """Whether either staged limit differs from what the shared settings currently hold."""
        settings = shared_logs_settings()
        return (
            self.__ui.app_limit_spin_box.value() != settings.app_limit
            or self.__ui.resource_limit_spin_box.value() != settings.resource_limit
        )

    def save_changes(self) -> None:
        """Push the staged limits into the shared settings and persist them.

        Every open surface re-caps itself off the settings object's own change signals, so nothing here
        reaches for a dock: this page does not know how many are open, and should not have to.
        """
        settings = shared_logs_settings()
        settings.app_limit = self.__ui.app_limit_spin_box.value()
        settings.resource_limit = self.__ui.resource_limit_spin_box.value()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding both spin boxes from the shared settings."""
        settings = shared_logs_settings()
        self.__ui.app_limit_spin_box.setValue(settings.app_limit)
        self.__ui.resource_limit_spin_box.setValue(settings.resource_limit)
        self.__show_clamp_note()

    def __show_clamp_note(self) -> None:
        """Say when the staged resource limit is above the app one, and so cannot be honoured.

        Checked against the *staged* values, not the saved ones: what a reader wants to know while typing
        a number is whether the number they are typing will apply.
        """
        app_limit = self.__ui.app_limit_spin_box.value()
        clamped = self.__ui.resource_limit_spin_box.value() > app_limit
        self.__ui.clamp_note_label.setText(CLAMP_NOTE.format(limit=app_limit) if clamped else "")
        self.__ui.clamp_note_label.setVisible(clamped)
