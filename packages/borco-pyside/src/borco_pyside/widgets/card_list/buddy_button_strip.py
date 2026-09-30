"""Buttons outside a card's frame, each centred on a row of the content inside it."""

from typing import Final, override

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton, QWidget


class BuddyButtonStrip(QObject):
    """A column of square tool buttons right of ``frame``, placed by hand on ``host``.

    No Qt layout aligns a widget with a row of *another* layout, so each button is positioned directly:
    beside the frame's right edge, vertically centred on its **buddy** -- a widget inside the frame. A button
    keeps its natural height and is as wide as it is tall; it never takes its buddy's height. Positions are
    recomputed whenever the host is shown or resized, a buddy moves or resizes, or the content asks for a new
    layout. Buttons never take focus: the keyboard reaches their actions through their shortcuts.

    :param host: the widget the buttons are children of, whose layout reserves :meth:`reserved_width` right of
        the frame.
    :param frame: the widget the buttons sit beside.
    """

    size_changed = Signal()
    """Fires when :meth:`reserved_width` changed -- an action gained an icon, so its button grew or shrank."""

    SPACING: Final = 4
    """The gap between the frame and the buttons, in pixels."""

    UNBOUNDED: Final = 16777215
    """Qt's ``QWIDGETSIZE_MAX``, which PySide does not export -- the size that lifts a fixed size again."""

    def __init__(self, host: QWidget, frame: QWidget) -> None:
        super().__init__(host)
        self.__host: Final = host
        self.__frame: Final = frame
        self.__buttons: list[tuple[QToolButton, QWidget]] = []
        self.__revealed = False
        host.installEventFilter(self)
        frame.installEventFilter(self)

    @property
    def buttons(self) -> tuple[QToolButton, ...]:
        """The buttons, in the order they were added."""
        return tuple(button for button, _ in self.__buttons)

    def add_button(self, action: QAction, buddy: QWidget) -> QToolButton:
        """Add a button for ``action``, centred on ``buddy``.

        :param action: what the button triggers, and where its icon, text and tooltip come from.
        :param buddy: the widget inside the frame the button is centred on.
        :returns: the new button.
        """
        button = QToolButton(self.__host)
        button.setDefaultAction(action)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setAutoRaise(True)
        button.setVisible(self.__revealed)
        self.__square(button)
        buddy.installEventFilter(self)
        self.__buttons.append((button, buddy))
        # an icon arriving after the button was built (an app dresses the actions once the card exists)
        # changes its natural size
        action.changed.connect(self.__refit)
        self.reposition()
        return button

    def __square(self, button: QToolButton) -> None:
        """Make ``button`` a square of its own natural height.

        :param button: the button.
        """
        button.setMinimumSize(0, 0)
        button.setMaximumSize(self.UNBOUNDED, self.UNBOUNDED)
        side = button.sizeHint().height()
        button.setFixedSize(QSize(side, side))

    def __refit(self) -> None:
        """Re-square every button after an action changed, telling the host when the strip's width did."""
        before = self.reserved_width()
        for button, _ in self.__buttons:
            self.__square(button)
        if self.reserved_width() != before:
            self.size_changed.emit()
        self.reposition()

    def reserved_width(self) -> int:
        """The room the host's layout keeps free right of the frame, so a revealed strip never moves it.

        :returns: the width, in pixels.
        """
        widest = max((button.width() for button, _ in self.__buttons), default=0)
        return self.SPACING + widest

    def set_revealed(self, revealed: bool) -> None:
        """Show or hide every button, without moving anything.

        :param revealed: whether the buttons show.
        """
        self.__revealed = revealed
        for button, _ in self.__buttons:
            button.setVisible(revealed)

    def reposition(self) -> None:
        """Place every button beside the frame, centred on its buddy."""
        left = self.__frame.geometry().right() + 1 + self.SPACING
        for button, buddy in self.__buttons:
            centre = buddy.mapTo(self.__host, QPoint(0, buddy.height() // 2)).y()
            button.move(left, centre - button.height() // 2)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802  (Qt override)
        match event.type():
            case QEvent.Type.Show | QEvent.Type.Resize | QEvent.Type.Move:
                self.reposition()
            case QEvent.Type.LayoutRequest:
                # the layout has not applied its geometry yet; read it once it has
                QTimer.singleShot(0, self, self.reposition)
            case _:
                pass
        return super().eventFilter(watched, event)
