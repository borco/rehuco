"""Give an action a themed icon, and keep an optional menu companion mirroring it."""

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from .themed_icons import themed_svg_icon


class ActionIconThemeHandler(QObject):
    """Gives an action an icon that colors itself from the current app theme.

    ``icon`` (an SVG resource/file path) is the source glyph; the handler assigns the shared
    :func:`~borco_pyside.theming.themed_svg_icon` built from it. That icon carries every corner of the
    checked/enabled space and reads the palette **as it paints** each one, so Qt picks the right corner
    from the action's own checked/enabled state and the right color from the palette of the moment.
    Nothing is swapped on ``toggled``/``enabledChanged``, and nothing is rebuilt on a palette change --
    there is no stored color to rebuild.

    That last point is the whole design. This class used to hold a ``QIcon`` it recolored whenever the
    shared :class:`~borco_pyside.theming.ApplicationPaletteChangeNotifier` reported a palette change,
    which made a glyph's correctness depend on a signal arriving at every one of the many handlers an
    app creates. #304 was what that costs: with several documents restored from the session, a theme
    switch recolored only the document that happened to be focused, and the rest kept the previous
    theme's glyphs for the remainder of the run.

    A ``QObject``, parented to ``action`` by default -- ``ActionIconThemeHandler(action, icon)`` alone
    is enough, with nothing to hold onto. It is needed at all only for ``companion``; an action with no
    companion can equally well be given :func:`~borco_pyside.theming.themed_svg_icon` directly.

    :param action: the action to give a themed icon.
    :param icon: path (Qt resource or filesystem) to the source SVG. Must be genuinely monochrome, in
        the narrow sense :func:`~borco_pyside.theming.recolor_svg` actually requires -- a multi-color
        source loses its color distinctions rather than being preserved. A glyph that is deliberately
        colored does not belong here at all: give the action
        :func:`~borco_pyside.theming.as_drawn_icon` instead.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    :param flat: ``action`` itself lives in a context that paints no filled chrome behind its icon the
        way a toolbar's checked button does -- e.g. a ``View`` menu's theme entries, same reasoning as
        the ``companion`` parameter below. Skips the checked-state color, relying on the row's native
        checkmark to communicate checked-ness instead.
    :param companion: an optional second action standing in for ``action`` in a context where the
        checked-state color would be unreadable -- e.g. a menu row, which paints no filled chrome
        behind its icon the way a toolbar's checked button does. Given the same source SVG's ``flat``
        icon, with no separate checked color -- the row's own native checkmark communicates
        checked-ness there instead. Also kept mirroring ``action``'s checked state (initially, and via
        ``toggled`` from then on) and forwards its own ``triggered`` to ``action.trigger()``, so a
        plain menu placement needs no extra wiring by the caller.

        That ``toggled``-based mirroring is **best-effort only**: some ways ``action``'s checked state
        can change (e.g. a `QtAds` dock closed via its tab's ``[x]``, or ``DockableDialog.toggleView()``,
        as called by its ``restore_all``/``enforce_restore_on_start`` -- confirmed empirically) update
        ``isChecked()`` without emitting ``toggled`` at all, silently leaving the companion stale. A
        companion placed in a menu (unlike a persistently-visible toolbar button) is never actually
        *seen* except right as its menu opens, though -- call :meth:`resync_companion_checked_state`
        from that menu's own ``aboutToShow`` to force it correct right before it matters, the same
        "rebuild fresh before showing" idiom already used for this app's other on-demand menus.
    """

    def __init__(
        self,
        action: QAction,
        icon: str,
        parent: QObject | None = None,
        *,
        companion: QAction | None = None,
        flat: bool = False,
    ) -> None:
        super().__init__(parent if parent is not None else action)
        self.__action = action
        self.__companion_action = companion
        self.__flat = flat

        if self.__companion_action is not None:
            self.__companion_action.triggered.connect(action.trigger)
            action.toggled.connect(self.__companion_action.setChecked)
        self.resync_companion_checked_state()

        self.__assign_icon(icon)

    def resync_companion_checked_state(self) -> None:
        """Force ``companion``'s checked state to match ``action``'s right now.

        A no-op if no companion action was given. Use this to correct for the ``toggled``-based
        mirroring's known gap (see the ``companion`` parameter's docstring) -- best called from
        wherever the companion is about to become visible, e.g. its containing menu's ``aboutToShow``.
        """
        if self.__companion_action is not None:
            self.__companion_action.setChecked(self.__action.isChecked())

    def set_icon(self, icon: str) -> None:
        """Switch the source SVG, assigning the shared themed icon built from it.

        For an action whose glyph itself changes (e.g. a mode-cycling action swapping between
        sun/moon/auto), rather than just its color -- the new source is themed exactly like the
        original one.

        :param icon: path (Qt resource or filesystem) to the new source SVG.
        """
        self.__assign_icon(icon)

    def __assign_icon(self, icon: str) -> None:
        self.__action.setIcon(themed_svg_icon(icon, flat=self.__flat))
        if self.__companion_action is not None:
            # flat, with no checked color -- see the companion parameter's docstring
            self.__companion_action.setIcon(themed_svg_icon(icon, flat=True))
