"""Which install of one external tool to use: a list of the ones found, and a custom path, as one settings value
(#521)."""

import sys
from collections.abc import Sequence
from typing import Final

from borco_pyside.widgets import ElidedRadioButton
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QFileDialog, QWidget
from rehuco_core import ToolCandidate, ToolStatus, best_candidate, version_text

from ...fields.colors import WARNING_COLOR
from .tool_path_control_ui import Ui_ToolPathControl

EXECUTABLE_FILTER: Final = "Executables (*.exe);;All files (*)" if sys.platform == "win32" else "All files (*)"
"""What the Browse dialog offers. Windows names the extension because a path without ``.exe`` is the
realistic mistake there; everywhere else an executable carries no extension at all."""

LOOKING_TEXT: Final = "Looking…"
NOT_FOUND_TEXT: Final = "not found"
WARNING_PROPERTY: Final = "warning"
WARNING_STYLESHEET: Final = f'QLineEdit[{WARNING_PROPERTY}="true"] {{ color: {WARNING_COLOR}; }}'
"""Paints the custom path in the warning colour while nothing usable is at it -- the field toolkit's idiom."""


def summarize(candidate: ToolCandidate) -> str:
    """Say what a candidate is, in the parenthesis beside its row.

    :param candidate: the copy to summarize.
    :returns: ``version, status`` and, for a copy that cannot be used, the reason; *not found* for a path holding
        nothing.
    """
    if candidate.status is ToolStatus.MISSING:
        return NOT_FOUND_TEXT
    if candidate.status is ToolStatus.NOT_RUNNABLE:
        return f"{candidate.status}: {candidate.reason}"
    summary = f"{version_text(candidate.version)}, {candidate.status}"
    return f"{summary}: {candidate.reason}" if not candidate.is_usable else summary


class ToolPathControl(QWidget):
    """One radio per install found, best first, and a last **Custom** row with a path and Browse.

    The control is one settings value for the frame snapshot ([[appendices.settings-pages#dirty-state-ui]]): empty
    while the best install is chosen -- so a fresh install needs no Apply, and a Detect that finds a newer build moves
    the choice with it without the page going dirty -- another install's folder when one is pinned, and the typed
    path under Custom. Its radios and its edit are inside it and so are not values of their own.

    An install found but unusable is listed, greyed, with the reason, so the user sees why it was not chosen. The
    Custom row carries the same parenthesis the found rows do, from inspecting its path, and the path is painted in
    the warning colour while nothing usable is at it: a stored install that has gone is shown here, marked, rather
    than silently dropped.

    :param parent: optional Qt parent.
    """

    choice_changed = Signal()
    """The staged choice or the typed path changed."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_ToolPathControl()
        self.__ui.setupUi(self)
        self.browse_title = "Locate the install"
        """The Browse dialog's title; the frame names its tool here."""
        self.__candidates: Sequence[ToolCandidate] = ()
        self.__rows: list[ElidedRadioButton] = []
        self.__staged = ""
        self.__group: Final = QButtonGroup(self)
        self.__group.addButton(self.__ui.custom_radio_button)
        self.__ui.path_edit.setStyleSheet(WARNING_STYLESHEET)

        self.__group.buttonToggled.connect(self.__on_toggled)
        self.__group.buttonClicked.connect(self.__on_clicked)
        self.__ui.path_edit.textChanged.connect(self.choice_changed)
        self.__ui.browse_button.clicked.connect(self.__on_browse_clicked)
        self.set_candidates(())

    @property
    def candidates(self) -> Sequence[ToolCandidate]:
        """The installs listed, best first."""
        return self.__candidates

    @property
    def rows(self) -> list[ElidedRadioButton]:
        """The radio of each install listed, in the order of :attr:`candidates`."""
        return list(self.__rows)

    def set_looking(self) -> None:
        """Say a search is going, leaving the choice alone: nothing is known yet to choose from."""
        self.__ui.looking_label.setVisible(True)

    def set_candidates(self, candidates: Sequence[ToolCandidate]) -> None:
        """List the installs found, keeping the choice: the best row for an empty value, the pinned folder's row
        where it is still listed, Custom otherwise.

        :param candidates: the installs, best first.
        """
        value = self.settings_value()
        for row in self.__rows:
            self.__group.removeButton(row)
            self.__ui.rows_layout.removeWidget(row)
            row.deleteLater()
        self.__candidates = tuple(candidates)
        self.__rows = []
        for candidate in self.__candidates:
            # the folder elides at its start: its tail is what tells scoop's `ffmpeg` from its `ffmpeg-shared`, both
            # under a `current\bin`; the parenthesis never elides
            row = ElidedRadioButton(self)
            row.set_text(str(candidate.folder), f" ({summarize(candidate)})", mode=Qt.TextElideMode.ElideLeft)
            row.setEnabled(candidate.is_usable)
            self.__group.addButton(row)
            self.__ui.rows_layout.addWidget(row)
            self.__rows.append(row)
        self.__ui.looking_label.setVisible(False)
        self.set_settings_value(value)

    def set_custom_status(self, candidate: ToolCandidate | None) -> None:
        """Mark the Custom row with what is at its path.

        :param candidate: the path inspected, or ``None`` while it is being looked at or there is no path.
        """
        edit = self.__ui.path_edit
        text = "" if candidate is None else f"({summarize(candidate)})"
        self.__ui.custom_status_label.setText(text)
        warning = candidate is not None and not candidate.is_usable
        if bool(edit.property(WARNING_PROPERTY)) != warning:
            edit.setProperty(WARNING_PROPERTY, warning)
            # re-polish so the property selector re-applies after the property flips
            edit.style().unpolish(edit)
            edit.style().polish(edit)

    def chosen_candidate(self) -> ToolCandidate | None:
        """The listed install whose row is checked.

        :returns: the candidate, or ``None`` under Custom.
        """
        for candidate, row in zip(self.__candidates, self.__rows, strict=True):
            if row.isChecked():
                return candidate
        return None

    def settings_value(self) -> object:
        """The staged choice -- the `ValueControl` half of the settings seam.

        :returns: empty for the best install found, a pinned install's folder, or the typed path under Custom.
        """
        chosen = self.chosen_candidate()
        if chosen is None:
            return self.__ui.path_edit.text().strip()
        # what was staged for this row is kept: an install pinned by its folder stays pinned when a later search
        # makes it the best, rather than reading as the best and dirtying the page by itself
        if self.__staged == str(chosen.folder) or (not self.__staged and chosen == best_candidate(self.__candidates)):
            return self.__staged
        return "" if chosen == best_candidate(self.__candidates) else str(chosen.folder)

    def set_settings_value(self, value: object) -> None:
        """Stage a choice, as :meth:`settings_value` returned it.

        :param value: empty for the best install, or a folder -- a listed install's, which checks its row, or any
            other, which is Custom.
        """
        path = str(value)
        best = best_candidate(self.__candidates)
        target = (
            best if not path else next((c for c in self.__candidates if str(c.folder) == path and c.is_usable), None)
        )
        if target is not None:
            self.__staged = path
            self.__rows[self.__candidates.index(target)].setChecked(True)
            return
        if path or self.__ui.path_edit.text():
            self.__ui.path_edit.setText(path)
        was_checked = self.__ui.custom_radio_button.isChecked()
        self.__ui.custom_radio_button.setChecked(True)
        if was_checked:
            self.choice_changed.emit()

    def __on_toggled(self, button: QAbstractButton, checked: bool) -> None:
        """Follow the radios: the path is editable only under Custom.

        :param button: the radio that toggled; unused, the checked state is read back.
        :param checked: whether it is now checked; only the one going on is followed, so a switch fires once.
        """
        del button
        if not checked:
            return
        custom = self.__ui.custom_radio_button.isChecked()
        self.__ui.path_edit.setEnabled(custom)
        self.__ui.browse_button.setEnabled(custom)
        self.choice_changed.emit()

    def __on_clicked(self, button: QAbstractButton) -> None:
        """Stage what a click means: the best row the empty value, any other row its folder -- so a row pinned by its
        folder and clicked again once it is the best is the best, not the pin.

        :param button: the radio clicked; unused, the checked state is read back.
        """
        del button
        chosen = self.chosen_candidate()
        if chosen is not None:
            self.__staged = "" if chosen == best_candidate(self.__candidates) else str(chosen.folder)

    def __on_browse_clicked(self) -> None:
        """Pick the executable with a file dialog, leaving a cancelled pick untouched."""
        path, _ = QFileDialog.getOpenFileName(self, self.browse_title, "", EXECUTABLE_FILTER)
        if path:
            self.__ui.path_edit.setText(path)
