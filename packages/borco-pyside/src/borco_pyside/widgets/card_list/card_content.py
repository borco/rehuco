"""What an app's widget inside a card must offer, so a card list can build, fill and read it."""

from typing import Any, Protocol, runtime_checkable

from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import QWidget


@runtime_checkable
class CardContent(Protocol):
    """The app-supplied content of one card -- its labels, edits and checkboxes, and nothing else.

    A content widget may also define ``set_primary(primary: bool)``, told whether its card is the top one,
    and ``set_reasons(reasons: Sequence[str])``, told why its card is in the states it is in; each is
    called only when present.
    """

    value_changed: SignalInstance
    """Fires whenever the user edits the content."""

    def set_item(self, item: Any) -> None:
        """Show ``item`` without emitting :attr:`value_changed`.

        :param item: the card's item.
        """

    def item_values(self) -> Any:  # pyright: ignore[reportReturnType]
        """The item as the content now reads.

        :returns: the item built from the content's widgets.
        """

    def buddies(self) -> tuple[QWidget, QWidget]:  # pyright: ignore[reportReturnType]
        """The rows the card's buttons sit beside, each button centred on its buddy.

        :returns: the delete button's buddy, then the insert button's.
        """
