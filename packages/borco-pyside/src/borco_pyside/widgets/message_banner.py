"""A themed strip of inline, non-dismissible notices -- one row per still-active condition, replacing
a modal dialog for state that persists exactly as long as its cause does.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget


class MessageBannerSeverity(StrEnum):
    """A row's severity, selecting its accent color.

    The only severity built so far is :attr:`WARNING`; a future severity (e.g. a purely informational
    notice) plugs in as a new member plus a matching color, not a parallel notice mechanism.
    """

    WARNING = "warning"
    """A condition blocking normal use until its remedy is taken (e.g. a locked document)."""


@dataclass(frozen=True)
class MessageBannerRow:
    """One notice: an icon glyph and its word-wrapping message.

    :param severity: the row's severity; selects its accent color.
    :param glyph: the character drawn beside the message -- a plain Unicode symbol or an icon-font
        codepoint (paired with ``family``); this widget has no opinion on which, only that it is one
        drawn character, not a `QIcon`.
    :param text: the notice's message; word-wraps rather than widening the strip.
    :param family: the font family ``glyph`` resolves in; empty keeps the inherited UI font (right for
        a plain Unicode symbol). Must already be loaded application-wide when given.
    """

    severity: MessageBannerSeverity
    glyph: str
    text: str
    family: str = ""


class MessageBanner(QWidget):
    """A vertical strip of :class:`MessageBannerRow` notices, one row per still-active condition.

    Rebuilt wholesale on every :meth:`set_rows` call rather than diffed -- a row's condition is
    recomputed by the caller on every relevant change, so there is no partial-update case to optimize
    for. Carries **no** dismiss button: a row is state, not a one-shot notification, and clears itself
    the next time :meth:`set_rows` is called with its condition gone. Shows nothing, and takes no
    layout space, while empty.

    :param parent: optional Qt parent.
    """

    __SEVERITY_COLORS: Final[dict[MessageBannerSeverity, str]] = {
        MessageBannerSeverity.WARNING: "#F4511E",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__layout: Final = QVBoxLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        self.setVisible(False)

    def set_rows(self, rows: Sequence[MessageBannerRow]) -> None:
        """Replace the strip's rows wholesale, hiding the whole strip when ``rows`` is empty.

        :param rows: the notices to show, one row each, in order.
        """
        while (item := self.__layout.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                # unparent immediately -- deleteLater() alone only schedules the actual destruction,
                # leaving the row widget (and its children) discoverable via findChildren() until the
                # next event loop turn, which would leak a stale row into whatever set_rows builds next
                widget.setParent(None)
                widget.deleteLater()
        for row in rows:
            self.__layout.addWidget(self.__build_row(row))
        self.setVisible(bool(rows))

    @classmethod
    def __build_row(cls, row: MessageBannerRow) -> QWidget:
        """Build one row: an accent-bordered container holding the icon glyph and the word-wrapping
        message (the only child stretched -- the same discipline as
        :class:`~borco_pyside.widgets.WrappingCheckBox`, so a long message grows the row taller, never
        the strip wider).

        :param row: the notice to render.
        :returns: the built row widget, ready to add to the strip.
        """
        color = cls.__SEVERITY_COLORS[row.severity]
        container = QWidget()
        # scoped by the severity attribute, not a bare `QWidget { ... }` rule -- Qt style sheets match
        # a type selector against every matching descendant too, which would paint the same border
        # around the icon/text children; the icon/text labels below have no widget children of their
        # own, so they can style themselves directly with no such risk.
        container.setProperty("severity", row.severity.value)
        container.setStyleSheet(f'QWidget[severity="{row.severity.value}"] {{ border-left: 3px solid {color}; }}')
        layout = QHBoxLayout(container)

        icon = QLabel(row.glyph, container)
        family_rule = f'font-family: "{row.family}"; ' if row.family else ""
        icon.setStyleSheet(f"color: {color}; {family_rule}")
        layout.addWidget(icon, 0)

        text = QLabel(row.text, container)
        text.setWordWrap(True)
        layout.addWidget(text, 1)

        return container
