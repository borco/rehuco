"""Windows-only: paint a just-shown top-level window now, rather than when the message queue drains.

On Windows a top-level's first paint is not part of its ``show()``. Qt exposes a window -- and so
paints it for the first time -- only from the ``WM_PAINT`` it receives, and ``WM_PAINT`` is the
lowest-priority message there is: the system generates it only once the thread's queue holds
nothing else. A window shown during startup, or during any burst of work that posts events, therefore
sits on screen as an empty surface until that burst is over, with whatever is behind it showing
through, and only then gets its content. ``QWidget.repaint()`` cannot help: Qt drops a repaint on a
window it has not yet exposed. Measured on the real ``windows`` plugin: an owning main window painted
synchronously inside its own ``show()``, the floating dock it owns not until the event loop's first
pass.

``UpdateWindow`` is the system's own way around that: it sends ``WM_PAINT`` synchronously when the
window's update region is not empty -- which a freshly shown window's always is -- so the first paint
lands inside the caller's frame rather than after everything else queued ahead of it.
"""

import ctypes

from PySide6.QtWidgets import QWidget


def paint_now(window: QWidget) -> None:
    """Deliver ``window``'s pending first paint synchronously.

    :param window: the already-shown top-level window to paint; a no-op when nothing in it needs
        painting, which is the system's own rule for ``UpdateWindow``.
    """
    ctypes.windll.user32.UpdateWindow(int(window.winId()))
