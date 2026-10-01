"""One command's keys as a row of key buttons, each removable, plus one that adds a key (#344)."""

from collections.abc import Sequence
from typing import Final

from borco_pyside.theming import ActionIconThemeHandler
from borco_pyside.widgets import FlowLayout, KeySequenceRecorder
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QHBoxLayout, QToolButton, QWidget

NEW_KEY: Final = -1
"""The index :attr:`KeyListEditor.key_recorded` reports for a key recorded by the add button."""

ADD_ICON_RESOURCE: Final = ":/icons/shortcuts_add.svg"
"""The add button's glyph."""

DELETE_ICON_RESOURCE: Final = ":/icons/shortcuts_delete.svg"
"""A key's remove button's glyph."""


class KeyListEditor(QWidget):
    """Shows a command's keys as key buttons -- click one to record a replacement, click its delete button to
    remove it -- and a last button that records an extra key.

    The add and delete buttons are icon-only tool buttons that show a border only under the mouse, like a
    settings frame's Apply / Reset / Defaults. Add opens a fresh key button already recording, in the place the
    new key will take; cancelling it (clicking elsewhere) takes it away again.

    It **reports** edits and never applies them: :meth:`set_keys` is the only thing that changes what it
    shows, so its owner can ask about a conflict first and show the outcome (or nothing) afterwards.

    :param parent: optional Qt parent.
    """

    key_recorded = Signal(int, QKeySequence)
    """A key was recorded: the index of the key it replaces, or :data:`NEW_KEY` for an added one."""

    key_removed = Signal(int)
    """The delete button of the key at this index was clicked."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__layout: Final = FlowLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        self.__keys: tuple[QKeySequence, ...] = ()
        self.__key_buttons: list[KeySequenceRecorder] = []
        self.__remove_buttons: list[QToolButton] = []
        self.__pending: KeySequenceRecorder | None = None
        """The key button add opened, while it records."""
        add_action = QAction("Add key", self)
        add_action.setToolTip("Record another key")
        ActionIconThemeHandler(add_action, ADD_ICON_RESOURCE)
        add_action.triggered.connect(self.__on_add)
        self.__add_button: Final = self.__tool_button(add_action, "add_key_button")
        self.__layout.addWidget(self.__add_button)

    @property
    def keys(self) -> tuple[QKeySequence, ...]:
        """The keys shown, in order."""
        return self.__keys

    @property
    def add_button(self) -> QToolButton:
        """The button that records an extra key."""
        return self.__add_button

    @property
    def pending_button(self) -> KeySequenceRecorder | None:
        """The key button the add button opened, while it is recording; ``None`` otherwise."""
        return self.__pending

    def key_buttons(self) -> list[KeySequenceRecorder]:
        """Each shown key's button, in order."""
        return list(self.__key_buttons)

    def remove_buttons(self) -> list[QToolButton]:
        """Each shown key's delete button, in order."""
        return list(self.__remove_buttons)

    def set_keys(self, keys: Sequence[QKeySequence]) -> None:
        """Show ``keys``, one key button and delete button each, before the add button.

        :param keys: the keys, in order.
        """
        self.__pending = None
        while (item := self.__layout.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None and widget is not self.__add_button:
                widget.setParent(None)  # gone at once, not when the event loop frees it
                widget.deleteLater()
        self.__keys = tuple(keys)
        self.__key_buttons.clear()
        self.__remove_buttons.clear()
        for index, sequence in enumerate(self.__keys):
            self.__layout.addWidget(self.__key_cell(index, sequence))
        self.__layout.addWidget(self.__add_button)  # always last
        self.__layout.invalidate()

    def __on_add(self) -> None:
        """Open a key button for a new key, before the add button, already recording."""
        if self.__pending is not None:
            return
        pending = KeySequenceRecorder(self)
        pending.setObjectName("pending_key_button")
        pending.recorded.connect(lambda sequence: self.key_recorded.emit(NEW_KEY, sequence))
        pending.recorded.connect(lambda _sequence: self.__drop_pending())
        pending.cancelled.connect(self.__drop_pending)
        self.__layout.takeAt(self.__layout.count() - 1)  # the add button, re-added after
        self.__layout.addWidget(pending)
        self.__layout.addWidget(self.__add_button)
        self.__pending = pending
        pending.show()
        pending.start()

    def __drop_pending(self) -> None:
        """Take away the key button add opened, once it is done -- the owner's :meth:`set_keys` shows a key
        it kept."""
        pending = self.__pending
        if pending is None:
            return
        self.__pending = None
        self.__layout.removeWidget(pending)
        pending.setParent(None)
        pending.deleteLater()

    def __key_cell(self, index: int, sequence: QKeySequence) -> QWidget:
        """One key's button and its delete button, side by side.

        :param index: the key's position.
        :param sequence: the key.
        :returns: the pair, as one widget.
        """
        cell = QWidget(self)
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        button = KeySequenceRecorder(cell)
        button.setObjectName(f"key_button_{index}")
        button.sequence = sequence
        button.setToolTip("Click, then press the replacement key")
        button.recorded.connect(lambda recorded, at=index: self.key_recorded.emit(at, recorded))
        remove_action = QAction("Remove key", cell)
        remove_action.setToolTip("Remove this key")
        ActionIconThemeHandler(remove_action, DELETE_ICON_RESOURCE)
        remove_action.triggered.connect(lambda _checked=False, at=index: self.key_removed.emit(at))
        remove = self.__tool_button(remove_action, f"remove_key_button_{index}", cell)
        layout.addWidget(button)
        layout.addWidget(remove)
        self.__key_buttons.append(button)
        self.__remove_buttons.append(remove)
        return cell

    def __tool_button(self, action: QAction, name: str, parent: QWidget | None = None) -> QToolButton:
        """An icon-only tool button driven by ``action``, bordered only under the mouse.

        :param action: the action it shows and triggers.
        :param name: its object name.
        :param parent: its parent; this editor when omitted.
        :returns: the button.
        """
        button = QToolButton(parent if parent is not None else self)
        button.setObjectName(name)
        button.setDefaultAction(action)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return button
