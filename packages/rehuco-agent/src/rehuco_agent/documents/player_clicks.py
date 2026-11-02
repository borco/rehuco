"""What a click on the player's picture means: a press, a click or a double-click ([[plugins#player-maximized]], #573,
#574)."""

from collections.abc import Iterable
from enum import Enum, auto
from typing import Final, cast, override

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget


class Count(Enum):
    """Where a run of presses stands."""

    NONE = auto()
    """No press within the interval."""

    ONE = auto()
    """One press, waiting the interval for a second."""

    TWO = auto()
    """A double-click, told; a third press within the interval is part of the same run and counts for nothing."""


class PlayerClicks(QObject):
    """Counts the clicks on the picture's surfaces itself, rather than taking Qt's double-clicks.

    **Two presses within the interval are a double-click**, whatever Qt calls the second one. A press with no second
    one after it within the interval is a click, told when the interval has passed, so a double-click never also
    clicks; a third press within the interval of the second is part of the same run, so a triple-click never also
    clicks either. A click that brings the focus to the player counts like any other (owner, #574): the picture has
    nothing a stray click could harm, and players toggle on the first click.

    :param surfaces: the picture's widgets whose left presses are counted.
    :param interval_ms: how long a second press may wait to make a double-click; the system's when ``None``.
    :param parent: the Qt parent, which owns this.
    """

    pressed = Signal()
    """A left press landed on the picture: each press of a run, once."""

    clicked = Signal()
    """A press on the picture with no second press after it."""

    double_clicked = Signal(Qt.KeyboardModifier)
    """Two presses on the picture within the interval: the keys held at the second."""

    def __init__(self, surfaces: Iterable[QWidget], interval_ms: int | None, parent: QObject) -> None:
        super().__init__(parent)
        self.__surfaces: Final = tuple(surfaces)
        self.__count = Count.NONE
        self.__timer: Final = QTimer(self)
        self.__timer.setSingleShot(True)
        self.__timer.setInterval(interval_ms if interval_ms is not None else QApplication.doubleClickInterval())
        self.__timer.timeout.connect(self.__on_interval_passed)
        for surface in self.__surfaces:
            surface.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt API name)
        """Count a left press on a surface, the one Qt calls a double-click among them.

        :param watched: a surface.
        :param event: what happened to it.
        :returns: whether the event is consumed -- never: the surfaces keep their own behaviour.
        """
        kind = event.type()
        if (
            kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick)
            and cast(QMouseEvent, event).button() == Qt.MouseButton.LeftButton
        ):
            self.__on_press(cast(QMouseEvent, event).modifiers())
        return super().eventFilter(watched, event)

    def __on_press(self, modifiers: Qt.KeyboardModifier) -> None:
        """Count a left press on the picture.

        :param modifiers: the keys held at it.
        """
        self.pressed.emit()
        match self.__count:
            case Count.NONE:
                self.__count = Count.ONE
                self.__timer.start()
            case Count.ONE:
                self.__count = Count.TWO
                self.__timer.start()
                self.double_clicked.emit(modifiers)
            case _:
                self.__timer.start()

    def __on_interval_passed(self) -> None:
        """End the run: one press was a click, two were told already."""
        count, self.__count = self.__count, Count.NONE
        if count is Count.ONE:
            self.clicked.emit()
