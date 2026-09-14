"""Remembers which sidebar a QtAds dock was last pinned to, across pins and across restarts."""

from typing import Final, cast

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject, QSettings

PIN_SIDE_KEY: Final = "pin_side"
"""Key each handler writes its dock's side under, within the group it was given."""

DEFAULT_PIN_SIDE: Final = QtAds.SideBarLeft
"""Where a dock nobody has pinned yet sends its first pin.

**The authority for every such dock, for as long as it is this constant** -- which is why a dock that
has never been pinned stores nothing at all (see :meth:`QtAdsPinSideHandler.save`). Changing this moves
those docks on the next start, rather than being overruled by a side an earlier build wrote on their
behalf."""

PIN_SIDE_NAMES: Final[dict[QtAds.SideBarLocation, str]] = {
    QtAds.SideBarLeft: "left",
    QtAds.SideBarRight: "right",
    QtAds.SideBarTop: "top",
    QtAds.SideBarBottom: "bottom",
}
"""Each pinnable sidebar's stored word. Persisted as the word rather than QtAds' own enum value, so the
``.ini`` stays readable and is not bound to a third-party enum's numbering under a file already on disk.

``SideBarNone`` is deliberately absent: it is what a dock that is *not* pinned reports, never a side
anything was pinned to (and it is the enum's **last** member, 4, not 0 --
[[appendices.qt-ads#auto-hide-preferred-side]])."""


class QtAdsPinSideHandler(QObject):
    """Keeps one dock pinning back to wherever it was last pinned, and remembers that across restarts.

    **The problem.** `CDockWidget.setPreferredAutoHideSideBarLocation` is what the dock area's pin
    button reads, and **nothing QtAds does updates it**: dropping a dock on a border calls
    ``CDockManager.addAutoHideDockWidget(location, dock)``, which sets where the dock *is* and leaves
    the preference alone, and so does a ``restoreState`` that brings a pinned dock back. So a dock
    dragged to the right sidebar, unpinned and pinned again with the button lands back on the left --
    it never learned where the user actually put it ([[appendices.qt-ads#auto-hide-preferred-side]]).

    **The fix.** ``CDockManager.autoHideWidgetCreated`` fires with the slide-out container on *every*
    pin -- a drop, the pin button, ``setAutoHide(True, location)``, a drag of an already-pinned dock
    from one sidebar to another, and a layout restore -- and the container names both its dock and the
    side it landed on. Writing that side back as the preference is the whole of it.

    A ``QObject``, parented to ``dock`` -- ``QtAdsPinSideHandler(dock, group)`` alone is enough, with
    nothing to hold onto beyond whatever the caller needs for :meth:`save`: Qt destroys it along with
    the dock. Several handlers share one manager's signal and each ignores the other docks' containers.

    :param dock: the dock whose pin side to follow. Must already be associated with a `CDockManager`
        (the two-argument ``CDockWidget`` constructor, or after ``addDockWidget``).
    :param group: the settings group :meth:`load`/:meth:`save` read and write under -- normally one
        per dock, e.g. ``f"dock_pin_sides/{dock.objectName()}"``. Taken here rather than at each call
        so a caller holding several handlers passes only the ``QSettings``.
    :param default: where to send a pin before anything has been remembered. Defaults to
        :data:`DEFAULT_PIN_SIDE`.
    :param parent: optional Qt parent; defaults to ``dock`` itself.
    """

    def __init__(
        self,
        dock: QtAds.CDockWidget,
        group: str,
        default: QtAds.SideBarLocation = DEFAULT_PIN_SIDE,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent if parent is not None else dock)
        self.__dock: Final = dock
        self.__group: Final = group
        self.__pinned = False
        """Whether this dock has ever been pinned -- by the user this session, or in an earlier one
        whose answer :meth:`load` read back. What :meth:`save` writes a key at all for."""

        dock.setPreferredAutoHideSideBarLocation(default)
        # unguarded: dockManager() is None only for a dock built by the one-argument constructor and
        # never added to a manager, which this class's contract excludes
        dock.dockManager().autoHideWidgetCreated.connect(self.__on_auto_hide_widget_created)

    @property
    def pinned(self) -> bool:
        """Whether this dock has ever been pinned, here or in an earlier session.

        ``False`` means :attr:`side` is only :data:`DEFAULT_PIN_SIDE` standing in, and that
        :meth:`save` will write nothing.
        """
        return self.__pinned

    @property
    def side(self) -> QtAds.SideBarLocation:
        """The sidebar this dock's next pin will land in.

        Read straight off the dock rather than mirrored here: the dock's own
        ``preferredAutoHideSideBarLocation`` *is* this handler's memory once
        :meth:`__on_auto_hide_widget_created` keeps it current, and a second copy could only fall out
        of step with it.
        """
        return self.__dock.preferredAutoHideSideBarLocation()

    def load(self, settings: QSettings) -> None:
        """Apply the side persisted for this dock, or leave it on the default.

        An unrecognized word -- an ``.ini`` written by a newer build offering a fifth sidebar, or one
        edited by hand -- is treated exactly as a missing one: the dock keeps the default, and is
        still considered never pinned. An unreadable preference must not decide that this dock's next
        pin goes nowhere in particular.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(self.__group)
        stored = cast(str, settings.value(PIN_SIDE_KEY, "", type=str))
        settings.endGroup()
        for side, name in PIN_SIDE_NAMES.items():
            if name == stored:
                self.__pinned = True
                self.__dock.setPreferredAutoHideSideBarLocation(side)
                return

    def save(self, settings: QSettings) -> None:
        """Persist this dock's side, or remove the key if it has never been pinned.

        **Removed, not written as the default.** Storing the default for a dock nobody has pinned
        would freeze today's :data:`DEFAULT_PIN_SIDE` into the file as though the user had chosen it,
        so a later change to that constant would reach fresh installs only.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(self.__group)
        if self.__pinned:
            settings.setValue(PIN_SIDE_KEY, PIN_SIDE_NAMES[self.side])
        else:
            settings.remove(PIN_SIDE_KEY)
        settings.endGroup()

    def __on_auto_hide_widget_created(self, container: QtAds.CAutoHideDockContainer) -> None:
        """Remember the side ``container``'s dock was just pinned to, if that dock is this one.

        Every handler on the same manager sees every pin, so the dock check is what makes one handler
        per dock work off one shared signal.

        :param container: the slide-out container QtAds has just built for some pinned dock.
        """
        if container.dockWidget() is self.__dock:
            self.__pinned = True
            self.__dock.setPreferredAutoHideSideBarLocation(container.sideBarLocation())
