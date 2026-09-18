"""A small colored type badge for the document viewer ([[plugins#plugin-blocks]], #83)."""

from collections.abc import Callable
from typing import Final, override

from PySide6.QtCore import QEvent
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget


class TypeBadge(QLabel):
    """A small, colored chip naming the document's resource type ([[plugins#plugin-blocks]], #83).

    The Qt-widget counterpart of the predecessor's top-right viewer badge: a filled rectangle with a
    smaller font, leading the document's own toolbar (#309) so the type reads whichever docks are
    open, or with the Main View closed altogether. Its colors are whatever the resource's
    **plugin declares** (:attr:`~rehuco_core.PluginSpec.color` / ``text_color``, resolved through
    ``colors_for``): a declared color is fixed, and an **undeclared** one falls back to the theme's
    selection colors -- the palette ``Highlight`` background and ``HighlightedText`` text, the
    predecessor's palette-driven badge. So a plugin that declares nothing (or a type whose plugin isn't
    installed here) still gets a sensible, theme-consistent badge, while a plugin that declares a color
    pins it. Re-styles on a palette (theme) change, so any color left to the palette tracks a live theme
    toggle.

    :meth:`on_type` is the reactive **slot**: bound to it, the model's ``resource_type_changed`` updates
    the chip -- the model rather than a field binding, since the toolbar is built once and outlives every
    form rebuild a type switch causes, which would destroy a field-bound badge along with its row. Being
    a bound method of this widget, Qt drops the connection with the badge when its document closes.

    :param colors_for: resolves a type key to its badge ``(background, text)`` colors, each a hex string
        or ``None`` to fall back to the theme's selection color.
    :param label_for: resolves a type key to its display label.
    :param parent: optional Qt parent.
    """

    FONT_SCALE: Final = 0.8
    """The badge font's size relative to the inherited one -- a *smaller* font, the predecessor's badge trait."""

    STYLE_TEMPLATE: Final = "background-color: {background}; color: {foreground}; padding: 4px 10px;"
    """The chip's stylesheet: a filled rectangle with comfortable padding; the resolved
    background/foreground (plugin-declared or palette-selected) are filled in."""

    def __init__(
        self,
        colors_for: Callable[[str], tuple[str | None, str | None]],
        label_for: Callable[[str], str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__colors_for: Final = colors_for
        self.__label_for: Final = label_for
        self.__background: str | None = None
        self.__foreground: str | None = None
        self.__applying = False
        """Recursion guard: :meth:`setStyleSheet` recomputes the widget's effective palette and so emits
        its own synchronous ``PaletteChange``; without this, :meth:`changeEvent` would call
        :meth:`__apply_style` again and recurse without end. Set only while this widget writes its own
        style, so a *genuine* theme change (with the flag clear) still re-styles once."""
        font = self.font()
        font.setPointSizeF(font.pointSizeF() * self.FONT_SCALE)
        self.setFont(font)
        # a fixed vertical size, not the toolbar's stretched full height (a QToolBar otherwise grows
        # any widget it hosts to its own extent): a chip that hugs its own text, vertically centered by
        # the toolbar layout like the icon buttons beside it
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def on_type(self, value: str) -> None:
        """Show ``value``'s badge, or blank the chip when the type is empty ([[plugins#plugin-blocks]]).

        The reactive slot bound to ``binding.changed``. An empty type (a brand-new, type-less document,
        or a session-restore placeholder before its file has loaded, #66) shows an empty, unstyled chip
        that takes up no visible room; any real type shows its label on a chip colored by the plugin's
        declared colors, each falling back to the theme's selection color.

        Deliberately never calls :meth:`~QWidget.setVisible`: a QToolBar-hosted widget explicitly hidden
        and later shown again *before its top-level window has ever been shown* -- exactly a session
        restore's own sequence, since every pending dock's document loads while the window is still
        hidden (``DocumentsDock.restore_session``) -- stays invisible forever afterwards even once the
        window does show, a confirmed Qt/``QToolBarLayout`` quirk. Never touching visibility at all
        sidesteps it: an untouched widget simply follows its parent's own shown state once parented,
        which is also what keeps a still-parentless badge (the very first call, before
        ``toolbar.addWidget``) from flashing as a momentary top-level window.

        :param value: the resource type key.
        """
        if not value:
            self.setText("")
            self.setStyleSheet("")
            return
        self.__background, self.__foreground = self.__colors_for(value)
        self.setText(self.__label_for(value))
        self.__apply_style()

    @override
    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 (Qt override)
        """Re-style on a palette change, so a palette-fallback color follows a live theme toggle.

        :param event: the Qt change event; only a palette change triggers a re-style.
        """
        if event.type() == QEvent.Type.PaletteChange and not self.__applying:
            self.__apply_style()
        super().changeEvent(event)

    def __apply_style(self) -> None:
        """Apply the chip stylesheet, resolving each undeclared color against the live palette's
        selection roles.

        Guarded by :attr:`__applying`: :meth:`setStyleSheet` re-emits ``PaletteChange`` synchronously, so
        the flag keeps :meth:`changeEvent` from calling back into here and recursing.
        """
        palette = self.palette()
        background = self.__background or palette.color(QPalette.ColorRole.Highlight).name()
        foreground = self.__foreground or palette.color(QPalette.ColorRole.HighlightedText).name()
        self.__applying = True
        try:
            self.setStyleSheet(self.STYLE_TEMPLATE.format(background=background, foreground=foreground))
        finally:
            self.__applying = False
