"""The two bucket limits (#680), edited alike on the Files page and in the balance dialog (#681)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import MAX_SPLIT_LIMIT, MIN_SPLIT_LIMIT, max_join_limit

from ...fields.colors import WARNING_COLOR
from .bucket_limits_editor_ui import Ui_BucketLimitsEditor


class BucketLimitsEditor(QWidget):
    """How many entries a folder of buckets holds before it splits, and how few before a balance joins it back.

    Neither box changes the other: a join limit above half the split limit stays as entered, and a warning under the
    boxes names the one used instead. So a number on the way to another -- 50, typing 500 -- loses nothing.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_BucketLimitsEditor()
        self.__ui.setupUi(self)
        self.__ui.split_limit_spin_box.setRange(MIN_SPLIT_LIMIT, MAX_SPLIT_LIMIT)
        self.__ui.join_limit_spin_box.setRange(0, max_join_limit(MAX_SPLIT_LIMIT))
        self.__ui.warning_label.setStyleSheet(f"color: {WARNING_COLOR};")
        self.__ui.split_limit_spin_box.valueChanged.connect(self.__show_warning)
        self.__ui.join_limit_spin_box.valueChanged.connect(self.__show_warning)
        self.__show_warning()

    @property
    def limits(self) -> tuple[int, int]:
        """The split limit and the join limit, as entered."""
        return self.__ui.split_limit_spin_box.value(), self.__ui.join_limit_spin_box.value()

    @limits.setter
    def limits(self, limits: tuple[int, int]) -> None:
        """Show these limits.

        :param limits: the split limit and the join limit.
        """
        split, join = limits
        self.__ui.split_limit_spin_box.setValue(split)
        self.__ui.join_limit_spin_box.setValue(join)

    def __show_warning(self) -> None:
        """Say which join limit is used while the one entered is above half the split limit; nothing otherwise."""
        split, join = self.limits
        used = max_join_limit(split)
        self.__ui.warning_label.setText(f"{join} is more than half the split limit, so {used} is used.")
        self.__ui.warning_label.setVisible(join > used)
