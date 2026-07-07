"""Accessors for widgets within a `pyside6-qtads` (QtAds) dock hierarchy."""

import PySide6QtAds as QtAds
from PySide6.QtWidgets import QAbstractButton


def tab_label(dock: QtAds.CDockWidget) -> QtAds.CElidingLabel:
    """``dock``'s own tab label widget, e.g. for direct double-click detection.

    :param dock: the dock whose tab label to find.
    :returns: the label widget.
    """
    label = dock.tabWidget().findChild(QtAds.CElidingLabel, "dockWidgetTabLabel")
    if label is None:  # pragma: no cover  (verified empirically: QtAds always names it this way)
        raise RuntimeError("QtAds always names a CDockWidgetTab's own label 'dockWidgetTabLabel'")
    return label


def tab_close_button(dock: QtAds.CDockWidget) -> QAbstractButton | None:
    """``dock``'s tab close button (the ``[x]``), or ``None`` if its tab shows none.

    The button only exists when a close-button config flag is set (``AllTabsHaveCloseButton`` or
    ``ActiveTabHasCloseButton``); with neither there is nothing to find, hence the ``None``. QtAds
    always names it ``tabCloseButton`` and makes it a ``QPushButton`` (or a ``QToolButton`` under
    ``TabCloseButtonIsToolButton``), both ``QAbstractButton``s.

    :param dock: the dock whose tab close button to find.
    :returns: the close button, or ``None`` if its tab shows none.
    """
    return dock.tabWidget().findChild(QAbstractButton, "tabCloseButton")
