"""Docks settings page: which border a pinned dock collapses into (#279)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ..docks_settings import SIDE_LABELS, DockPinSide, shared_docks_settings
from ..persistent_settings import persistent_settings
from .docks_page_ui import Ui_DocksPage


class DocksPage(QWidget):
    """Choose which of the window's four borders a pinned main dock lands on
    ([[appendices.qt-ads#auto-hide-flags]], #279).

    One combo box over `DocksSettings`, populated from
    :data:`~rehuco_agent.settings.docks_settings.SIDE_LABELS` rather than from the ``.ui``: a side
    listed here that :data:`~rehuco_agent.settings.docks_settings.SIDE_BAR_LOCATIONS` had no entry
    for would be a choice with nothing behind it, and the two lists are keyed by the same enum so
    that cannot happen.

    Edits are staged in the combo box until :meth:`save_changes` pushes them into the shared
    settings, which re-sets the preferred side on every main dock already open -- the reason this
    page's settings object is reactive rather than a value read at construction.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_DocksPage()
        self.__ui.setupUi(self)

        for side, label in SIDE_LABELS.items():
            self.__ui.pin_side_combo_box.addItem(label, side)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether the staged side differs from what the shared settings currently hold."""
        return self.__staged_side() != shared_docks_settings().pin_side

    def save_changes(self) -> None:
        """Push the staged side into the shared settings and persist it.

        Every open dock re-reads the side off the settings object's own change signal, so nothing
        here reaches for a dock: this page does not know which ones the window built.
        """
        settings = shared_docks_settings()
        settings.pin_side = self.__staged_side()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, re-seeding the combo box from the shared settings."""
        side = shared_docks_settings().pin_side
        index = self.__ui.pin_side_combo_box.findData(side)
        self.__ui.pin_side_combo_box.setCurrentIndex(index)

    def __staged_side(self) -> DockPinSide:
        """The side the combo box currently shows.

        Rebuilt from the stored word rather than read back as the enum member that was put in: Qt
        marshals a `StrEnum` through ``QVariant`` as a plain ``str``, so ``currentData()`` hands back
        ``"left"`` and not `DockPinSide.LEFT` -- which compares equal to the member (a `StrEnum` does)
        and so passes every equality check while failing every ``isinstance`` one.

        Unguarded, because the combo box cannot be empty: ``__init__`` fills it from
        :data:`~rehuco_agent.settings.docks_settings.SIDE_LABELS`, whose completeness against
        `DockPinSide` is itself asserted. A fallback here would be a branch nothing can take, and one
        that would answer a future empty combo box with a plausible-looking wrong side instead of
        saying so.
        """
        return DockPinSide(self.__ui.pin_side_combo_box.currentData())
