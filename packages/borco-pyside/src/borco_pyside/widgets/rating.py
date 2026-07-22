"""A generic star-style rating display: repeated glyphs, styled separately by sign."""

from dataclasses import dataclass
from typing import Final

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..core import SimpleProperty


class Rating(QWidget):
    """Displays an integer rating as ``|value|`` repeated characters, styled by sign.

    A positive value repeats ``positive_text``, styled with the ``positive_style`` stylesheet; a
    negative value repeats ``negative_text`` with ``negative_style``; zero or ``None`` (unrated) shows
    nothing -- a zero-magnitude rating and an absent one render identically, since "no stars" is the
    honest render of both. An empty style, or a style that leaves
    a given property unset, leaves that aspect fully inherited (tracks the ambient font/palette,
    including a live theme change) rather than freezing a snapshot -- clearing a widget's stylesheet is
    how Qt itself un-sets a local override, so this needs no separate font/color bookkeeping the way
    holding raw ``QFont``/``QColor`` objects would.

    Wraps a private ``QLabel`` rather than subclassing it, so the only public surface is ``value`` --
    a caller cannot reach in and call ``setText``/``setPixmap``/etc. and desync the display from
    ``value``.

    :param value: the starting rating; ``None`` for unrated.
    :param positive_style: Qt stylesheet declarations for a positive value's characters (e.g.
        ``'color: green; font-family: "Foo";'``); empty keeps everything inherited.
    :param positive_text: character repeated ``value`` times for a positive value.
    :param negative_style: Qt stylesheet declarations for a negative value's characters; empty keeps
        everything inherited.
    :param negative_text: character repeated ``|value|`` times for a negative value.
    :param parent: optional Qt parent.
    """

    value = SimpleProperty[int | None](None)
    """The current rating, or ``None`` for unrated; ``set_value`` is the slot-usable setter (for
    binding to signals)."""

    @dataclass
    class __Style:  # pylint: disable=invalid-name
        """One sign's rendering: the stylesheet to apply (empty keeps everything inherited) and its text."""

        stylesheet: str
        text: str

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        value: int | None = None,
        positive_style: str = "",
        positive_text: str = "★",
        negative_style: str = "",
        negative_text: str = "☆",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__positive: Final = self.__Style(positive_style, positive_text)
        self.__negative: Final = self.__Style(negative_style, negative_text)

        self.__label: Final = QLabel(self)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__label)

        self.value_changed.connect(self.__render)  # type: ignore[attr-defined]
        self.value = value

    def __render(self, value: int | None) -> None:
        """Re-render the label for a new rating value.

        :param value: the new rating, or ``None`` for unrated.
        """
        if not value:
            self.__label.clear()
            return
        style = self.__positive if value > 0 else self.__negative
        self.__label.setStyleSheet(style.stylesheet)
        self.__label.setText(style.text * abs(value))
