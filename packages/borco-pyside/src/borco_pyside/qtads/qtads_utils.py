"""Small helpers over `pyside6-qtads` (QtAds) widgets, for use with any `CDockWidget`."""

import PySide6QtAds as QtAds


def tab_label(dock: QtAds.CDockWidget) -> QtAds.CElidingLabel:
    """``dock``'s own tab label widget, e.g. for direct double-click detection.

    :param dock: the dock whose tab label to find.
    :returns: the label widget.
    """
    label = dock.tabWidget().findChild(QtAds.CElidingLabel, "dockWidgetTabLabel")
    if label is None:  # pragma: no cover  (verified empirically: QtAds always names it this way)
        raise RuntimeError("QtAds always names a CDockWidgetTab's own label 'dockWidgetTabLabel'")
    return label
