"""The Tray block's wiring, shared by whichever System Integration page a platform builds (#205)."""

from typing import Final

from PySide6.QtWidgets import QCheckBox, QLabel, QSystemTrayIcon

from ..persistent_settings import persistent_settings
from ..tray_settings import shared_tray_settings


class TrayBlock:
    """Binds one System Integration page's tray checkbox to the shared `TraySettings` (#205).

    **Not a widget.** The block itself is a plain ``QFrame`` declared in each page's own ``.ui``,
    because that is the only thing `SettingsFrameFilter` counts as a settings block: it takes the
    exact-``QFrame`` direct children of the page, deliberately excluding subclasses so a decorative
    rule is never mistaken for a group. A ``TrayBlock(QFrame)`` widget would therefore be invisible
    to the filter, the group column and the dirty highlight alike -- so what is shared here is the
    behaviour, while the markup is declared per page.

    That markup is duplicated across the three pages that host it, the same deliberate copy
    `DesktopIntegrationPage` already keeps of `RegistryPage`'s chrome. The **behaviour** is not:
    it reads and writes persistent storage, which is where three copies would drift into a real
    defect rather than a cosmetic one.

    Staged in the checkbox until :meth:`save_changes` pushes it into the shared `TraySettings`
    instance -- firing its ``enabled_changed`` signal, which `MainWindow` follows to create or tear
    down the tray icon immediately rather than only on the next launch.

    :param enabled_check_box: the block's tray-mode checkbox.
    :param unavailable_label: the note shown only where no system tray exists.
    """

    def __init__(self, enabled_check_box: QCheckBox, unavailable_label: QLabel) -> None:
        self.__enabled_check_box: Final = enabled_check_box
        # a desktop's tray availability does not change over the app's lifetime, so this is read once
        # rather than re-checked on every poll -- the checkbox itself is left enabled either way, since
        # a preference set with no tray today is still worth saving: it engages on the next launch
        # under a desktop that has one
        unavailable_label.setVisible(not QSystemTrayIcon.isSystemTrayAvailable())
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether the staged checkbox differs from the shared settings' current value."""
        return self.__enabled_check_box.isChecked() != shared_tray_settings().enabled

    def save_changes(self) -> None:
        """Push the staged choice into the shared settings object (live-updating the tray icon) and
        persist it."""
        settings = shared_tray_settings()
        settings.enabled = self.__enabled_check_box.isChecked()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, reverting the checkbox to the shared settings' current value."""
        self.__enabled_check_box.setChecked(shared_tray_settings().enabled)
