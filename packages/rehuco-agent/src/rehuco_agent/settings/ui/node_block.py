"""The Local node block's wiring, for the System Integration page (#506)."""

from typing import Final

from PySide6.QtWidgets import QCheckBox, QLabel

from ...node_host import NodeHost, NodeState
from ..node_settings import NodeSettings, shared_node_settings
from ..persistent_settings import persistent_settings

STATUS_TEXTS: Final = {
    NodeState.DISABLED: "The local node is off.",
    NodeState.STOPPED: "The local node is not running.",
    NodeState.STARTING: "The local node is starting…",
    NodeState.RUNNING: "The local node is running (pid {pid}).",
    NodeState.FAILED: "The local node could not run; the Log has the reason.",
}
"""What the status line says in each `NodeState`."""

NO_HOST_STATUS: Final = "The local node is managed by the main window."
"""Shown when the page was built without a `NodeHost` to ask -- a test, or a page shown on its own."""


class NodeBlock:
    """Binds the System Integration page's node checkbox and status line to the shared `NodeSettings` and the
    `NodeHost` the main window owns (#506).

    **Not a widget**, for the reason `TrayBlock` gives: the block itself is a plain ``QFrame`` declared in the
    page's ``.ui``, and what lives here is the behaviour -- the half that reads and writes storage.

    Staged in the checkbox until :meth:`save_changes` pushes it into the shared `NodeSettings`, whose
    ``enabled_changed`` the host follows to start or stop the node at once.

    :param enabled_check_box: the block's checkbox.
    :param status_label: the line saying whether the node runs.
    :param host: the node host to read the state from; ``None`` leaves the line static.
    """

    def __init__(self, enabled_check_box: QCheckBox, status_label: QLabel, host: NodeHost | None) -> None:
        self.__enabled_check_box: Final = enabled_check_box
        self.__status_label: Final = status_label
        self.__host: Final = host
        if host is None:
            status_label.setText(NO_HOST_STATUS)
        else:
            host.state_changed.connect(self.__show_state)
            self.__show_state(host.state)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether the staged checkbox differs from the shared settings' current value."""
        return self.__enabled_check_box.isChecked() != shared_node_settings().enabled

    def save_changes(self) -> None:
        """Push the staged choice into the shared settings object (starting or stopping the node) and persist it."""
        settings = shared_node_settings()
        settings.enabled = self.__enabled_check_box.isChecked()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, reverting the checkbox to the shared settings' current value."""
        self.__enabled_check_box.setChecked(shared_node_settings().enabled)

    def seed_defaults(self) -> None:
        """Stage the factory value: what an unloaded `NodeSettings` holds (#342)."""
        self.__enabled_check_box.setChecked(NodeSettings().enabled)

    def __show_state(self, state: NodeState) -> None:
        """Say where the node is.

        :param state: the host's state.
        """
        pid = self.__host.pid if self.__host is not None else 0
        self.__status_label.setText(STATUS_TEXTS[state].format(pid=pid))
