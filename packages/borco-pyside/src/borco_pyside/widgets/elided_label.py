"""A `QLabel` that middle-elides its text to fit its width, optionally keeping a hyperlink target."""

import html
from typing import override

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QColor, QPalette, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class ElidedLabel(QLabel):
    """A `QLabel` that middle-elides its text to whatever width it is given, re-eliding on resize, so
    a long value never forces the label (or its layout neighbors) wider than the space available.

    Its horizontal size policy is ``Ignored`` -- the label takes the width the layout hands it and
    shortens the text to fit, rather than dictating width from its content. Set the content with
    :meth:`set_text`, not ``setText``. When a ``href`` is given, the visible (elided) text is wrapped
    in a hyperlink to the **full** target, so the link stays clickable while only the display is
    shortened (pair with ``setOpenExternalLinks(True)`` or a ``linkActivated`` connection). While the
    text is actually elided, the full text is shown in a tooltip (cleared once it fits again).

    :param parent: optional Qt parent.
    :param rich: (keyword) draw plain text as escaped rich text too, so the label is as tall with a link as
        without one -- a rich-text label is a little taller than a plain one, which would make a label that
        turns into a link and back change height.
    """

    def __init__(self, parent: QWidget | None = None, *, rich: bool = False) -> None:
        super().__init__(parent)
        self.__rich = rich
        self.__full = ""
        self.__href = ""
        self.__hint = ""
        self.__tooltip = ""
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)

    def set_text(self, text: str, href: str = "", hint: str = "", tooltip: str = "") -> None:
        """Set the full text (and optional hyperlink target), then render it elided to the current width.

        :param text: the full, un-elided text.
        :param href: the hyperlink target the elided text links to; empty for plain text.
        :param hint: what the link does, shown in the tooltip alongside (or instead of) the full text --
            e.g. an action a click performs that "open this link" wouldn't otherwise suggest. Ignored
            without a ``href``.
        :param tooltip: rich text shown as the tooltip in place of the full text and the hint.
        """
        self.__tooltip = tooltip
        self.__full = text
        self.__href = href
        self.__hint = hint
        self.__render()

    @override
    def minimumSizeHint(self) -> QSize:  # noqa: N802  (Qt API name)
        # zero-width minimum so a long value can never force this label (or its layout) wider -- the
        # text elides to fit instead; the default QLabel minimum is its longest unbreakable word.
        return QSize(0, super().minimumSizeHint().height())

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802  (Qt API name)
        super().resizeEvent(event)
        self.__render()

    def link_color(self) -> QColor:
        """The color a link is drawn in: the palette's ``Link`` role. A subclass drawing its link in another
        color overrides this rather than pinning a palette or a stylesheet on the widget: either stops a theme
        change from reaching it (a stylesheet for good -- Qt keeps ``WA_StyleSheet`` set once one was set).

        :returns: the current link color.
        """
        return self.palette().color(QPalette.ColorRole.Link)

    def text_color(self) -> QColor | None:
        """The color a ``rich`` label's plain text is drawn in, in place of the palette's; ``None`` leaves it
        to the palette. A subclass overrides this for the same reason as :meth:`link_color`. Ignored by a
        label that is not ``rich``, whose plain text the palette alone colors.

        :returns: the color, or ``None`` for the palette's.
        """
        return None

    @override
    def changeEvent(self, event: QEvent) -> None:  # noqa: N802  (Qt API name)
        """Re-render on a palette change, so a link's color follows a live theme toggle rather than
        staying whatever it was drawn in at the previous one.

        :param event: the Qt change event; only a palette change triggers a re-render.
        """
        if event.type() == QEvent.Type.PaletteChange and self.__href:
            self.__render()
        super().changeEvent(event)

    def __render(self) -> None:
        """Re-render the label with the full text middle-elided to the current width, showing the
        full text in a tooltip only while it is actually elided."""
        if not self.__full:
            self.setText("")
            self.setToolTip("")
            return
        elided = self.fontMetrics().elidedText(self.__full, Qt.TextElideMode.ElideMiddle, self.width())
        # the format is set explicitly per branch: under the default ``AutoText`` a plain name is
        # parsed as markup only when it happens to contain a ``<``, so escaping it would show ``&amp;``
        # literally while not escaping would mangle a ``<`` -- plain text is plain, a link is rich.
        if self.__href:
            self.setTextFormat(Qt.TextFormat.RichText)
            # Qt's rich-text anchor defaults to a hardcoded blue, not the palette's own Link role --
            # illegible against a dark theme's background, since nothing here ever asked for that color
            href, color = html.escape(self.__href), self.link_color().name()
            self.setText(f'<a href="{href}" style="color:{color};">{html.escape(elided)}</a>')
        elif self.__rich:
            self.setTextFormat(Qt.TextFormat.RichText)
            color = self.text_color()  # pylint: disable=assignment-from-none
            text = html.escape(elided)
            self.setText(f'<span style="color:{color.name()};">{text}</span>' if color is not None else text)
        else:
            self.setTextFormat(Qt.TextFormat.PlainText)
            self.setText(elided)
        tooltip = self.__full if elided != self.__full else ""
        if self.__href and self.__hint:
            tooltip = f"{tooltip}\n{self.__hint}" if tooltip else self.__hint
        self.setToolTip(self.__tooltip or tooltip)
