"""Checksums settings page: the one place the checksum defaults live ([[data-model#checksums]], #242)."""

from typing import Final

from PySide6.QtWidgets import QButtonGroup, QRadioButton, QWidget
from rehuco_core import CHECKSUM_ALGORITHMS

from ..checksum_settings import ChecksumSettings, shared_checksum_settings
from ..persistent_settings import persistent_settings
from .checksums_page_ui import Ui_ChecksumsPage


class ChecksumsPage(QWidget):
    """Configure what a checksum run is run with: the algorithm, the two verify choices and the window.

    Staged in the widgets until :meth:`save_changes`, the same shape as every other settings page here.
    Unlike most of them, Save writes onto the **shared** `ChecksumSettings` instance as well as to
    storage: that object is what the next enqueued run reads, and it also carries the last swept folder,
    which no control on this page edits and neither Save may drop.

    **The algorithm radios are built here rather than declared in the ``.ui``.**
    :data:`~rehuco_core.CHECKSUM_ALGORITHMS` is a closed set that changes by editing one core file
    (#203), and eight hand-written radio buttons would drift from it silently -- one added to core would
    simply be unofferable. They are built in :meth:`__init__`, which matters: the settings dialog reads a
    page's searchable text once, when the page is registered, so a control created later would be
    invisible to the filter.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ChecksumsPage()
        self.__ui.setupUi(self)
        self.__algorithms: Final = QButtonGroup(self)
        for index, algorithm in enumerate(CHECKSUM_ALGORITHMS.values()):
            button = QRadioButton(algorithm.label, self.__ui.algorithm_buttons)
            self.__ui.algorithm_buttons_layout.addWidget(button)
            self.__algorithms.addButton(button, index)
        self.__algorithms.idToggled.connect(self.__resync_migrate_label)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether any staged control differs from what's saved."""
        saved = ChecksumSettings()
        saved.load(persistent_settings())
        return (
            self.__selected_algorithm() != saved.algorithm
            or self.__ui.migrate_check_box.isChecked() != saved.migrate_on_verify
            or self.__ui.create_missing_check_box.isChecked() != saved.create_missing_on_verify
            or self.__ui.stale_days_spin_box.value() != saved.stale_days
        )

    def save_changes(self) -> None:
        """Persist the staged choices, onto the shared instance the next run will read.

        The shared object is mutated rather than replaced so that ``last_sweep_root`` -- written by the
        sweep, edited by nothing here -- survives this Save, and so that a run enqueued afterwards sees
        the new values without reloading anything.
        """
        settings = shared_checksum_settings()
        settings.algorithm = self.__selected_algorithm()
        settings.migrate_on_verify = self.__ui.migrate_check_box.isChecked()
        settings.create_missing_on_verify = self.__ui.create_missing_check_box.isChecked()
        settings.stale_days = self.__ui.stale_days_spin_box.value()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edits, re-seeding every control from persistent storage."""
        saved = ChecksumSettings()
        saved.load(persistent_settings())
        names = list(CHECKSUM_ALGORITHMS)
        button = self.__algorithms.button(names.index(saved.algorithm))
        button.setChecked(True)
        self.__ui.migrate_check_box.setChecked(saved.migrate_on_verify)
        self.__ui.create_missing_check_box.setChecked(saved.create_missing_on_verify)
        self.__ui.stale_days_spin_box.setValue(saved.stale_days)
        self.__resync_migrate_label()

    def __selected_algorithm(self) -> str:
        """Which algorithm the radios currently name.

        :returns: the staged algorithm's name, a key of :data:`~rehuco_core.CHECKSUM_ALGORITHMS`.
        """
        return list(CHECKSUM_ALGORITHMS)[self.__algorithms.checkedId()]

    def __resync_migrate_label(self) -> None:
        """Rebuild the migration checkbox's text so it always names the algorithm it would migrate to.

        A checkbox reading *update checksums on verify* would leave the reader to go and look at which
        one is selected, and a label naming the wrong algorithm after a radio change would be worse than
        a vague one.
        """
        label = CHECKSUM_ALGORITHMS[self.__selected_algorithm()].label
        self.__ui.migrate_check_box.setText(f"Update checksums to {label} on verify")
