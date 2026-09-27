"""Taking a dock out of a QtAds `CDockManager` under the name it was registered by."""

import PySide6QtAds as QtAds


def remove_dock_widget(dock_manager: QtAds.CDockManager, dock: QtAds.CDockWidget) -> None:
    """``dock_manager.removeDockWidget(dock)``, made correct for a dock renamed since it was added.

    QtAds keys its dock registry -- ``dockWidgetsMap()``, which ``findDockWidget`` and ``restoreState``
    read -- by the ``objectName()`` a dock had when it was **added**, and never re-keys it, while
    ``removeDockWidget`` drops the entry under the name the dock has **now**. A dock renamed in between is
    taken off screen but stays registered, and once it is deleted that entry is a dangling pointer: the next
    read of the registry crashes natively (#364, [[appendices.qt-ads#dock-registry-keys]]). So the dock
    carries the name it was registered by for the removal, and gets its current one back after it.

    The dock comes out parentless; delete it with ``deleteLater()``, as for ``removeDockWidget``. Freed on
    the spot instead, ahead of the events the removal posted, it was measured to crash or hang the next
    ``processEvents``.

    :param dock_manager: the manager ``dock`` was added to.
    :param dock: the dock to remove.
    """
    name = dock.objectName()
    registered = next((key for key, entry in dock_manager.dockWidgetsMap().items() if entry is dock), name)
    dock.setObjectName(registered)
    try:
        dock_manager.removeDockWidget(dock)
    finally:
        dock.setObjectName(name)
