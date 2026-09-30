"""How a card paints its states: which fill and border a state name stands for, resolved at paint time."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import ClassVar, Final

from PySide6.QtGui import QColor, QPalette

type CardColor = QColor | QPalette.ColorRole | Callable[[QPalette], QColor]
"""A colour as a style names it: a fixed `QColor`, a palette role, or a function of the palette -- the last
two follow a theme switch, since they are only turned into a `QColor` when the card paints."""


@dataclass(frozen=True)
class CardStateStyle:
    """The look of one card state: what fills the whole card, and what outlines it.

    :param fill: the colour painted over the whole card (grip, frame and buttons), or ``None`` for none.
    :param border: the card's outline colour, or ``None`` for none.
    """

    fill: CardColor | None = None
    border: CardColor | None = None

    @staticmethod
    def resolve(color: CardColor | None, palette: QPalette) -> QColor | None:
        """Turn ``color`` into a `QColor` against ``palette`` -- called at paint time, never cached.

        :param color: the colour as a style names it, or ``None``.
        :param palette: the palette of the widget being painted.
        :returns: the colour to paint with, or ``None`` when there is none.
        """
        if color is None or isinstance(color, QColor):
            return color
        if isinstance(color, QPalette.ColorRole):
            return palette.color(color)
        return color(palette)


class CardStyle:
    """Maps a card state's name to its :class:`CardStateStyle` ([[plugins#field-toolkit]]).

    Ships only :attr:`CURRENT`, the card holding focus, in the palette's selection colour. Every other state
    -- a ``flagged`` card, say -- is the app's to :meth:`register`, since this package carries no app
    colours. A card that is both current and in a registered state keeps the current fill and takes the
    state's border, so the flag stays visible on the card being edited.

    :param states: per-instance styles, taking precedence over the class-wide :attr:`STATES`.
    """

    CURRENT: Final = "current"
    """The state of the card holding focus."""

    STATES: ClassVar[dict[str, CardStateStyle]] = {
        CURRENT: CardStateStyle(fill=QPalette.ColorRole.Highlight, border=QPalette.ColorRole.Highlight),
    }
    """Class-wide styles, shared by every card list that names no style of its own for a state."""

    def __init__(self, states: Mapping[str, CardStateStyle] | None = None) -> None:
        self.__states: dict[str, CardStateStyle] = dict(states or {})

    def register(self, state: str, style: CardStateStyle) -> None:
        """Style ``state`` for this card list; a state registered earlier wins over a later one.

        :param state: the state name a :class:`~.card_list_model.CardListModel`'s ``card_states`` hook reports.
        :param style: how a card in that state paints.
        """
        self.__states[state] = style  # pylint: disable=unsupported-assignment-operation

    def style(self, state: str) -> CardStateStyle | None:
        """The style of ``state``: this instance's, else the class-wide one, else ``None``.

        :param state: the state name.
        :returns: its style, or ``None`` for a state nobody styled.
        """
        return self.__states.get(state, self.STATES.get(state))

    def style_for(self, current: bool, states: Mapping[str, str]) -> CardStateStyle:
        """The look of a card that is ``current`` or not, and in ``states``.

        :param current: whether the card holds focus.
        :param states: the card's states (name to reason); only styled ones count, the first one styled
            in registration order winning.
        :returns: the style to paint; an empty one for a plain card.
        """
        flagged = next(
            (
                style
                for name in (*self.__states, *self.STATES)
                if name != self.CURRENT and name in states and (style := self.style(name))
            ),
            None,
        )
        current_style = self.style(self.CURRENT) if current else None
        if current_style is None:
            return flagged or CardStateStyle()
        if flagged is None:
            return current_style
        return CardStateStyle(fill=current_style.fill, border=flagged.border or current_style.border)
