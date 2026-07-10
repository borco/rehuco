"""The path editor widget: the resource's current name over a collapsible list of clickable
rename-suggestion labels ([[plugins#field-toolkit]]).

The expand/collapse control is deliberately *not* part of this widget -- the form places one in its
own "misc" grid column (see `FieldsForm`/`PathField`); this widget only exposes :attr:`expanded`.
"""

from collections.abc import Sequence
from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import ElidedLabel
from pathvalidate import is_valid_filename, sanitize_filename
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from unidecode import unidecode

from rehuco_agent.fields.colors import WARNING_COLOR

WARNING_STYLESHEET: Final = f"QLabel {{ color: {WARNING_COLOR}; }}"
"""Applied to the current-name label when the name matches none of the suggestions ([[plugins#field-toolkit]])."""


class PathEditor(QWidget):
    """Edits a resource's name by picking a rename suggestion ([[plugins#field-toolkit]],
    [[field-schema#field-mapping]]). No free-text entry: the current name over a collapsible vertical
    list of clickable suggestion labels.

    :attr:`expanded` shows/hides the suggestions panel; the expand control itself lives in the form's
    misc column, not here. :meth:`set_current_name` and :meth:`set_suggestions` are slots so the owner
    can keep them live as the underlying fields change (e.g. editing ``authors`` re-renders the
    suggestions). Each suggestion is transliterated to ASCII (Unidecode) and sanitized into a valid
    filesystem name (``pathvalidate``); one that reduces to nothing is dropped, one equal to the
    current name renders disabled (a rename to it is a no-op). When the current name matches **none**
    of the suggestions it is drawn in the warning color, since it isn't one of the canonical names.
    Clicking a live suggestion emits :attr:`suggestion_selected` with its sanitized name -- this
    widget never touches the filesystem itself.

    :param parent: optional Qt parent.
    """

    suggestion_selected = Signal(str)
    expanded_changed = Signal(bool)
    expanded = SimpleProperty(False)
    """Whether the suggestions panel is open; ``set_expanded`` is the slot-usable setter (the owner
    restores it per ``.rehu`` from persisted session state, and the misc-column toggle drives it)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__current_name = ""
        self.__suggestions: list[str] = []
        self.__suggestion_labels: dict[str, ElidedLabel] = {}

        self.__name_label: Final = ElidedLabel()

        self.__suggestions_widget: Final = QWidget()
        self.__suggestions_layout: Final = QVBoxLayout(self.__suggestions_widget)
        self.__suggestions_layout.setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__name_label)
        layout.addWidget(self.__suggestions_widget)

        self.expanded_changed.connect(self.__on_expanded_changed)
        self.__on_expanded_changed(self.expanded)

    def set_current_name(self, name: str) -> None:
        """Set the resource's current name and re-render.

        :param name: the current file/folder name.
        """
        self.__current_name = name
        self.__render()

    def set_suggestions(self, raw_suggestions: Sequence[str]) -> None:
        """Set the raw candidate names, sanitizing them and rebuilding the list when they change.

        :param raw_suggestions: the caller-formatted candidate strings (unsanitized).
        """
        sanitized = self.__sanitize_all(raw_suggestions)
        if sanitized != self.__suggestions:
            self.__suggestions = sanitized
            self.__rebuild()
        self.__render()

    def __on_expanded_changed(self, value: bool) -> None:
        """Show or hide the suggestions panel to match :attr:`expanded`.

        :param value: the new expand state.
        """
        self.__suggestions_widget.setVisible(value)

    def __rebuild(self) -> None:
        """Recreate one clickable label per current sanitized suggestion, replacing the old set."""
        for label in self.__suggestion_labels.values():
            self.__suggestions_layout.removeWidget(label)
            label.deleteLater()
        self.__suggestion_labels.clear()
        for name in self.__suggestions:
            label = ElidedLabel()
            label.linkActivated.connect(lambda _href, name=name: self.suggestion_selected.emit(name))
            self.__suggestions_layout.addWidget(label)
            self.__suggestion_labels[name] = label  # pylint: disable=unsupported-assignment-operation

    def __render(self) -> None:
        """Refresh the current-name label (warning-colored when unmatched) and each suggestion's state."""
        self.__name_label.set_text(self.__current_name)
        unmatched = bool(self.__current_name) and self.__current_name not in self.__suggestions
        self.__name_label.setStyleSheet(WARNING_STYLESHEET if unmatched else "")
        for name, label in self.__suggestion_labels.items():
            is_current = name == self.__current_name
            label.setEnabled(not is_current)
            label.set_text(name, href="" if is_current else "#")

    @staticmethod
    def __sanitize_all(raw_suggestions: Sequence[str]) -> list[str]:
        """Transliterate and filesystem-sanitize every candidate, dropping duplicates and empties.

        :param raw_suggestions: the caller-formatted candidate strings.
        :returns: the sanitized, deduplicated, order-preserved names.
        """
        sanitized = (PathEditor.__sanitize(raw) for raw in raw_suggestions)
        return list(dict.fromkeys(name for name in sanitized if name is not None))

    @staticmethod
    def __sanitize(raw: str) -> str | None:
        """Transliterate ``raw`` to ASCII and sanitize it into a valid filesystem name.

        :param raw: a caller-formatted suggestion string (may hold unicode/invalid characters).
        :returns: the sanitized name, or ``None`` if nothing valid survives.
        """
        name = sanitize_filename(unidecode(raw)).strip()
        return name if name and is_valid_filename(name) else None
