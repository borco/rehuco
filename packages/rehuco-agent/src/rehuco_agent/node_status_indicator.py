"""The status bar's word on the local node: running, or not (#506)."""

from typing import Final

from PySide6.QtWidgets import QLabel, QWidget

from .node_host import NodeHost, NodeState

RUNNING_TEXT: Final = "Local Node: Running"
STOPPED_TEXT: Final = "Local Node: Stopped"

DETAIL_TEXTS: Final = {
    NodeState.DISABLED: "The local node is turned off (Settings > System Integration).",
    NodeState.STOPPED: "The local node is not running.",
    NodeState.STARTING: "The local node is starting.",
    NodeState.RUNNING: "The local node is running (pid {pid}).",
    NodeState.FAILED: "The local node could not run; the Log has the reason.",
}
"""The tooltip, per `NodeState`."""


class NodeStatusIndicator(QLabel):
    """A permanent status bar label: *Local Node: Running*, or *Local Node: Stopped* greyed out.

    Two words only, since the bar is read at a glance; the tooltip carries the state in full, the pid
    included. Greyed through ``setEnabled(False)``, so the palette's own disabled text colour does it in
    both themes rather than a colour of this widget's own.

    :param host: the node host whose state this follows.
    :param parent: optional Qt parent.
    """

    def __init__(self, host: NodeHost, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__host: Final = host
        host.state_changed.connect(self.__show_state)
        self.__show_state(host.state)

    def __show_state(self, state: NodeState) -> None:
        """Re-word and re-tint for ``state``.

        :param state: the host's state.
        """
        running = state == NodeState.RUNNING
        self.setText(RUNNING_TEXT if running else STOPPED_TEXT)
        self.setEnabled(running)
        self.setToolTip(DETAIL_TEXTS[state].format(pid=self.__host.pid))
