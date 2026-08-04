"""Tasks settings page: what a restart does with the saved queue (#202)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ..persistent_settings import persistent_settings
from ..tasks_settings import TasksSettings
from .tasks_page_ui import Ui_TasksPage


class TasksPage(QWidget):
    """Configure the three restart-time choices over the saved task queue
    ([[appendices.task-queue#lifetime]]).

    Three checkboxes, staged in the widgets until :meth:`save_changes` writes them -- the same shape
    as every other settings page here, and unlike `LogsPage` there is nothing already open to re-notify
    on save: these are read once, at the next startup.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_TasksPage()
        self.__ui.setupUi(self)
        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Tasks"

    def is_dirty(self) -> bool:
        """Whether any staged checkbox differs from what's saved."""
        saved = TasksSettings()
        saved.load(persistent_settings())
        return (
            self.__ui.clear_done_check_box.isChecked() != saved.clear_done_on_restart
            or self.__ui.clear_failed_check_box.isChecked() != saved.clear_failed_on_restart
            or self.__ui.resume_check_box.isChecked() != saved.resume_on_restart
        )

    def save_changes(self) -> None:
        """Persist the staged choices."""
        settings = TasksSettings(
            clear_done_on_restart=self.__ui.clear_done_check_box.isChecked(),
            clear_failed_on_restart=self.__ui.clear_failed_check_box.isChecked(),
            resume_on_restart=self.__ui.resume_check_box.isChecked(),
        )
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding every checkbox from persistent storage."""
        saved = TasksSettings()
        saved.load(persistent_settings())
        self.__ui.clear_done_check_box.setChecked(saved.clear_done_on_restart)
        self.__ui.clear_failed_check_box.setChecked(saved.clear_failed_on_restart)
        self.__ui.resume_check_box.setChecked(saved.resume_on_restart)
