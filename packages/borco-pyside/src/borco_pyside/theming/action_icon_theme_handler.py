"""Keep a checkable action's icon recolored to match the current app theme."""

from PySide6.QtCore import QFile, QIODevice, QObject
from PySide6.QtGui import QAction, QPalette
from PySide6.QtWidgets import QApplication

from borco_pyside.theming.svg_recolor import recolored_svg_icon


class ActionIconThemeHandler(QObject):
    """Keeps a checkable action's icon recolored to match the current app theme.

    ``icon`` (an SVG resource/file path) is the source glyph; the handler sets **one** scalable
    ``QIcon`` (via :func:`~borco_pyside.theming.recolored_svg_icon` with an ``on_color``, a
    ``disabled_color``, and an ``on_disabled_color``) carrying all four corners of the checked/enabled
    space, each colored from the matching ``QPalette`` group/role -- ``ButtonText`` (enabled+off),
    ``HighlightedText`` (enabled+on), the ``Disabled`` group's ``ButtonText`` (disabled+off), and the
    ``Disabled`` group's ``HighlightedText`` (disabled+on, so a disabled checkable action -- e.g. one
    mirroring a model flag it doesn't let the user toggle directly -- still shows its state, not just a
    flat disabled look, #41) -- so **Qt** picks the right one from the action's own checked/enabled
    state; the handler never swaps icons on ``toggled``/``enabledChanged``. The whole icon is rebuilt
    whenever ``QApplication.paletteChanged`` fires -- that signal (not
    ``QStyleHints.colorSchemeChanged``, which can fire before the palette itself has actually been
    updated) is the authoritative point at which the new theme's colours are available to read.

    A ``QObject``, parented to ``action`` by default -- ``ActionIconThemeHandler(action, icon)``
    alone is enough, with nothing to hold onto: Qt destroys it along with ``action``, and its own
    signal connections keep it alive as long as ``action`` does regardless.

    :param action: the checkable action to keep recolored.
    :param icon: path (Qt resource or filesystem) to the source SVG, drawn for the light theme's
        unchecked (normal) state. Must be genuinely monochrome, in the narrow sense
        :func:`~borco_pyside.theming.recolor_svg` actually requires -- a multi-color source loses its
        color distinctions rather than being preserved.
    :param parent: optional Qt parent; defaults to ``action`` itself.
    :param flat: ``action`` itself lives in a context with no ``Highlight``-colored backdrop behind
        its icon the way a toolbar's checked button chrome has -- e.g. a menu row (#57's ``View``
        theme entries), same reasoning as the ``companion`` parameter below. Skips the
        checked-state color variant on ``action``'s own icon (plain ``ButtonText``/disabled colors
        only, same as a companion's), relying on the row's native checkmark to communicate
        checked-ness instead.
    :param companion: an optional second action standing in for ``action`` in a context where the
        checked-state recolor would be unreadable -- e.g. a menu row, which paints no
        ``Highlight``-colored background behind its icon the way a toolbar's checked button chrome
        does (#64). Kept themed alongside ``action``, from the same source SVG, but always in the
        plain ``ButtonText``/disabled colors with no separate checked variant -- the row's own native
        checkmark communicates checked-ness there instead. Also kept mirroring ``action``'s checked
        state (initially, and via ``toggled`` from then on) and forwards its own ``triggered`` to
        ``action.trigger()``, so a plain menu placement needs no extra wiring by the caller.

        That ``toggled``-based mirroring is **best-effort only** -- exactly the same gap
        :meth:`__apply_icon` above works around for ``action``'s own icon: some ways ``action``'s
        checked state can change (e.g. a `QtAds` dock closed via its tab's ``[x]``, or
        ``DockableDialog.toggleView()``, as called by its ``restore_all``/
        ``enforce_restore_on_start`` -- confirmed empirically, #64) update ``isChecked()`` without
        emitting ``toggled`` at all, silently leaving the companion stale. A companion placed in a
        menu (unlike a persistently-visible toolbar button) is never actually *seen* except right as
        its menu opens, though -- call :meth:`resync_companion_checked_state` from that menu's own
        ``aboutToShow`` to force it correct right before it matters, the same "rebuild fresh before
        showing" idiom already used for this app's other on-demand menus.
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
        self.__svg: bytes = self.__read_file(icon)

        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("ActionIconThemeHandler requires a running QApplication")
        app.paletteChanged.connect(self.__on_palette_changed)

        if self.__companion_action is not None:
            self.__companion_action.triggered.connect(action.trigger)
            action.toggled.connect(self.__companion_action.setChecked)
        self.resync_companion_checked_state()

        self.__apply_icon()

    def resync_companion_checked_state(self) -> None:
        """Force ``companion``'s checked state to match ``action``'s right now.

        A no-op if no companion action was given. Use this to correct for the ``toggled``-based
        mirroring's known gap (see the ``companion`` parameter's docstring) -- best called from
        wherever the companion is about to become visible, e.g. its containing menu's ``aboutToShow``.
        """
        if self.__companion_action is not None:
            self.__companion_action.setChecked(self.__action.isChecked())

    def set_icon(self, icon: str) -> None:
        """Switch the source SVG this handler recolors, rebuilding the icon immediately.

        For an action whose glyph itself changes (e.g. a mode-cycling action swapping between
        sun/moon/auto), rather than just its color -- the new source is still kept themed exactly
        like the original one.

        :param icon: path (Qt resource or filesystem) to the new source SVG, drawn for the light
            theme's unchecked (normal) state.
        """
        self.__svg = self.__read_file(icon)
        self.__apply_icon()

    def __on_palette_changed(self, *_args: object) -> None:
        # the app's palette only reflects a theme switch once this fires -- rebuilding eagerly on
        # colorSchemeChanged instead reads the still-stale pre-switch palette (confirmed: the save
        # icon then never picked up the real colors).
        self.__apply_icon()

    def __apply_icon(self) -> None:
        # One scalable QIcon carrying all four mode/state corners -- unchecked (ButtonText) as
        # State.Off, checked (HighlightedText) as State.On, and the same Off/On split again within
        # the Disabled color group for Mode.Disabled -- and let Qt pick per the action's
        # checked/enabled state. Nothing is swapped on `toggled`/`enabledChanged`, which would miss
        # state changes that don't emit them (a dock closed via its tab's [x], or
        # CDockManager.restoreState() flipping toggleViewAction()).
        palette = QApplication.palette()
        disabled = QPalette.ColorGroup.Disabled
        button_text = palette.color(QPalette.ColorRole.ButtonText)
        disabled_button_text = palette.color(disabled, QPalette.ColorRole.ButtonText)
        on_color = None if self.__flat else palette.color(QPalette.ColorRole.HighlightedText)
        on_disabled_color = None if self.__flat else palette.color(disabled, QPalette.ColorRole.HighlightedText)
        self.__action.setIcon(
            recolored_svg_icon(self.__svg, button_text, on_color, disabled_button_text, on_disabled_color)
        )
        if self.__companion_action is not None:
            # no on_color/on_disabled_color -- see the companion parameter's docstring
            self.__companion_action.setIcon(
                recolored_svg_icon(self.__svg, button_text, None, disabled_button_text, None)
            )

    def __read_file(self, path: str) -> bytes:
        """Read ``path`` (Qt resource or filesystem) fully into memory.

        :param path: the file to read, e.g. a ``:/...`` Qt resource path or a plain filesystem path.
        :returns: the file's full contents.
        :raises RuntimeError: if ``path`` cannot be opened for reading.
        """
        file = QFile(path)
        if not file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"cannot open {path!r} for reading")
        try:
            return bytes(file.readAll().data())
        finally:
            file.close()
