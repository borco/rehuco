"""A `QLabel` that middle-elides its text to fit its width, optionally keeping a hyperlink target."""

import html
from typing import override

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QPalette, QResizeEvent
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
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__full = ""
        self.__href = ""
        self.__hint = ""
        policy = self.sizePolicy()
        policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.setSizePolicy(policy)

    def set_text(self, text: str, href: str = "", hint: str = "") -> None:
        """Set the full text (and optional hyperlink target), then render it elided to the current width.

        :param text: the full, un-elided text.
        :param href: the hyperlink target the elided text links to; empty for plain text.
        :param hint: what the link does, shown in the tooltip alongside (or instead of) the full text --
            e.g. an action a click performs that "open this link" wouldn't otherwise suggest. Ignored
            without a ``href``.
        """
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
            link_color = self.palette().color(QPalette.ColorRole.Link).name()
            self.setText(f'<a href="{html.escape(self.__href)}" style="color:{link_color};">{html.escape(elided)}</a>')
        else:
            self.setTextFormat(Qt.TextFormat.PlainText)
            self.setText(elided)
        tooltip = self.__full if elided != self.__full else ""
        if self.__href and self.__hint:
            tooltip = f"{tooltip}\n{self.__hint}" if tooltip else self.__hint
        self.setToolTip(tooltip)
