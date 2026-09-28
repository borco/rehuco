"""A themed strip of inline, non-dismissible notices -- one row per still-active condition, replacing
a modal dialog for state that persists exactly as long as its cause does.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Final, cast

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget


class MessageBannerSeverity(StrEnum):
    """A row's severity, selecting its look (see :attr:`MessageBanner.SEVERITY_STYLES`).

    None of these ship a built-in per-severity style -- a consuming app registers its own
    :class:`MessageBannerSeverityStyle` for whichever severities it actually uses; one it hasn't
    renders with :class:`MessageBanner`'s generic fallback look instead of crashing. A genuinely new
    severity (beyond these three) plugs in the same way: a new member plus a matching style, not a
    parallel notice mechanism.
    """

    WARNING = "warning"
    """A condition blocking normal use until its remedy is taken (e.g. a locked document)."""

    INFO = "info"
    """A purely informational notice -- nothing blocking, nothing wrong."""

    ERROR = "error"
    """A condition that has already gone wrong (contrast :attr:`WARNING`'s "acting would go wrong")."""


@dataclass(frozen=True)
class MessageBannerSeverityStyle:
    """How one severity's rows render: their marker and left-border accent color.

    :param margin_color: the row's left-border accent color.
    :param icon: the row's marker -- built however the caller likes (a font glyph via
        :func:`~borco_pyside.theming.glyph_icon`, an SVG resource via `QIcon`, ...); this widget has
        no opinion on which. ``None`` falls back to a plain Unicode warning glyph in ``margin_color``.
    """

    margin_color: str
    icon: QIcon | None = None


@dataclass(frozen=True)
class MessageBannerRow:
    """One notice: its severity, word-wrapping message, and optionally one remedy.

    :param severity: the row's severity, selecting its marker and accent color
        (:attr:`MessageBanner.SEVERITY_STYLES`).
    :param text: the notice's message; word-wraps rather than widening the strip.
    :param action: a remedy for the condition, shown as a button after the message -- `None` for a
        message-only row. The caller owns it, and keeps passing the **same** action for as long as the row
        stands: that identity is what lets :meth:`MessageBanner.set_rows` update the row in place.
    """

    severity: MessageBannerSeverity
    text: str
    action: QAction | None = None


class MessageBanner(QWidget):
    """A vertical strip of :class:`MessageBannerRow` notices, one row per still-active condition.

    Rebuilt wholesale on a :meth:`set_rows` call that changes the strip's shape -- a row's condition is
    recomputed by the caller on every relevant change, so there is nothing to diff. The one exception is
    a call that only rewords the rows it already shows (same count, severities and actions): those are
    updated in place, so a row re-said every second, such as a countdown, never rebuilds its action
    button under a press and loses the click. Carries **no** dismiss button: a row is state, not a
    one-shot notification, and clears itself the next time :meth:`set_rows` is called with its condition
    gone. A row's own :attr:`~MessageBannerRow.action` is a remedy for the condition, not a dismiss.
    Shows nothing, and takes no layout space, while empty.

    :param parent: optional Qt parent.
    :param styles: per-instance severity styles, taking precedence over the class-wide
        :attr:`SEVERITY_STYLES` for whichever severities it names. A severity absent from it falls
        back to :attr:`SEVERITY_STYLES`, then to :attr:`__DEFAULT_STYLE` -- so two windows (or two
        libraries) in one process can style their banners differently without fighting over the shared
        class table, while the class table stays the default when this is ``None``.
    """

    __ICON_SIZE: Final = 20
    __DEFAULT_GLYPH: Final = "⚠"
    """Fallback marker for a severity whose style carries no ``icon`` -- a plain Unicode symbol, so a
    severity that never bothered customizing its look still shows *something*, not a blank cell."""

    __DEFAULT_STYLE: Final = MessageBannerSeverityStyle(margin_color="palette(highlight)")
    """The look any severity renders with until a consuming app registers its own entry for it in
    :attr:`SEVERITY_STYLES` -- so a row never hard-crashes just because its style isn't registered."""

    SEVERITY_STYLES: ClassVar[dict[MessageBannerSeverity, MessageBannerSeverityStyle]] = {}
    """The class-wide default for each severity's look, keyed by :class:`MessageBannerSeverity`. Empty
    by default -- every severity renders with :attr:`__DEFAULT_STYLE` until a consuming app registers
    its own entry (e.g. with its own brand color and icon) for whichever severities it actually uses,
    before building any `MessageBanner` that uses them. A severity missing from this table at render
    time falls back to :attr:`__DEFAULT_STYLE` rather than crashing, so this being empty is never
    itself a problem.

    This is a shared, process-global table: convenient when one app styles every banner alike, but two
    windows or libraries in one process cannot use it to style banners differently. For that, pass a
    per-instance ``styles`` to the constructor instead -- it takes precedence over this table for
    whichever severities it names, and this stays the fallback."""

    def __init__(
        self,
        parent: QWidget | None = None,
        styles: Mapping[MessageBannerSeverity, MessageBannerSeverityStyle] | None = None,
    ) -> None:
        super().__init__(parent)
        self.__styles: Final = styles
        self.__layout: Final = QVBoxLayout(self)
        self.__layout.setContentsMargins(0, 0, 0, 0)
        self.__shown: list[tuple[MessageBannerRow, QLabel]] = []
        """The rows currently shown, each beside the label carrying its text."""
        self.setVisible(False)

    def set_rows(self, rows: Sequence[MessageBannerRow]) -> None:
        """Replace the strip's rows, hiding the whole strip when ``rows`` is empty -- rewording the shown
        rows in place when only their texts changed, rebuilding them otherwise.

        :param rows: the notices to show, one row each, in order.
        """
        if self.__rewords_shown_rows(rows):
            for (_, label), row in zip(self.__shown, rows, strict=True):
                label.setText(row.text)
            self.__shown = [(row, label) for (_, label), row in zip(self.__shown, rows, strict=True)]
            return
        while (item := self.__layout.takeAt(0)) is not None:
            # __layout only ever holds widgets added via addWidget below, never a spacer or nested
            # layout, so item.widget() is never None here
            widget = cast(QWidget, item.widget())
            # hide explicitly first: addWidget queued a `_q_showIfNotHidden` for a row added while
            # the strip was visible, and a row removed before that call runs would otherwise be
            # shown by it as a bare top-level window -- setParent(None) clears the implicit hidden
            # state, an explicit hide() survives it
            widget.hide()
            # unparent immediately -- deleteLater() alone only schedules the actual destruction,
            # leaving the row widget (and its children) discoverable via findChildren() until the
            # next event loop turn, which would leak a stale row into whatever set_rows builds next
            widget.setParent(None)
            widget.deleteLater()
        self.__shown = []
        for row in rows:
            container, label = self.__build_row(row)
            self.__layout.addWidget(container)
            self.__shown.append((row, label))
        self.setVisible(bool(rows))

    def __rewords_shown_rows(self, rows: Sequence[MessageBannerRow]) -> bool:
        """Whether ``rows`` differ from the shown ones in their texts at most -- same count, and each
        with the same severity and the very same action.

        :param rows: the rows :meth:`set_rows` was just given.
        :returns: whether they can be applied by rewording the shown rows in place.
        """
        return len(rows) == len(self.__shown) and all(
            row.severity == shown.severity and row.action is shown.action
            for row, (shown, _) in zip(rows, self.__shown, strict=True)
        )

    def __resolve_style(self, severity: MessageBannerSeverity) -> MessageBannerSeverityStyle:
        """Pick a severity's style: this instance's own ``styles`` first (for whichever severities it
        names), then the class-wide :attr:`SEVERITY_STYLES`, then :attr:`__DEFAULT_STYLE` -- so a row
        never hard-crashes just because its style isn't registered anywhere.

        :param severity: the severity whose style to resolve.
        :returns: the resolved style.
        """
        if self.__styles is not None and severity in self.__styles:
            return self.__styles[severity]
        return self.SEVERITY_STYLES.get(severity, self.__DEFAULT_STYLE)

    def __build_row(self, row: MessageBannerRow) -> tuple[QWidget, QLabel]:
        """Build one row: an accent-bordered container holding the severity's marker, the word-wrapping
        message (the only child stretched -- the same discipline as
        :class:`~borco_pyside.widgets.WrappingCheckBox`, so a long message grows the row taller, never
        the strip wider), and the row's action as a button, if it has one.

        :param row: the notice to render.
        :returns: the built row widget, ready to add to the strip, and its message label.
        """
        style = self.__resolve_style(row.severity)
        container = QWidget()
        # scoped by the severity attribute, not a bare `QWidget { ... }` rule -- Qt style sheets match
        # a type selector against every matching descendant too, which would paint the same border
        # around the icon/text children; the icon/text labels below have no widget children of their
        # own, so they can style themselves directly with no such risk.
        container.setProperty("severity", row.severity.value)
        container.setStyleSheet(
            f'QWidget[severity="{row.severity.value}"] {{ border-left: 3px solid {style.margin_color}; }}'
        )
        layout = QHBoxLayout(container)

        icon = QLabel(container)
        if style.icon is not None:
            icon.setPixmap(style.icon.pixmap(self.__ICON_SIZE, self.__ICON_SIZE))
        else:
            icon.setText(self.__DEFAULT_GLYPH)
            icon.setStyleSheet(f"color: {style.margin_color};")
        layout.addWidget(icon, 0)

        text = QLabel(row.text, container)
        text.setWordWrap(True)
        layout.addWidget(text, 1)

        if row.action is not None:
            button = QToolButton(container)
            button.setDefaultAction(row.action)
            layout.addWidget(button, 0)

        return container, text
