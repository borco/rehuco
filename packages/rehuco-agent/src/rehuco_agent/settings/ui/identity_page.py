"""Identity settings page: the current + unknown usernames per-user state is filed under (#109).

See [[field-schema#per-user-shared]].
"""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import DEFAULT_UNKNOWN_USERNAME

from ..identity_settings import default_username, shared_identity_settings
from ..persistent_settings import persistent_settings
from .identity_page_ui import Ui_IdentityPage


class IdentityPage(QWidget):
    """Edit the two configured usernames -- the **current** user this install's own per-user writes are
    filed under, and the **unknown** user the ``.tc`` importer files its imported state under
    ([[field-schema#per-user-shared]], #109). Setting both to the same value is allowed -- collapsing them
    into one identity is a supported configuration.

    Each edit is staged in its line edit until :meth:`save_changes` pushes both into the shared
    `IdentitySettings` instance and persists them; from then on they are what every *subsequent* document
    open/conversion reads (`DocumentsDock`) -- already-open documents keep the username they were
    constructed with (see `rehuco_agent.settings.identity_settings`). A staged value that is blank (nothing
    but whitespace) stands for "no name" and resolves to its own default instead (current ->
    :func:`~rehuco_agent.settings.identity_settings.default_username`, unknown ->
    :data:`~rehuco_core.DEFAULT_UNKNOWN_USERNAME`), the same fallback ``IdentitySettings.load`` applies --
    an identity is never saved empty.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_IdentityPage()
        self.__ui.setupUi(self)

        self.drop_changes()

    @property
    def title(self) -> str:
        """This page's category-tree label."""
        return "Identity"

    def is_dirty(self) -> bool:
        """Whether either staged username differs from the shared settings' current value."""
        settings = shared_identity_settings()
        return (
            self.__staged_current_username() != settings.current_username
            or self.__staged_unknown_username() != settings.unknown_username
        )

    def save_changes(self) -> None:
        """Push both staged usernames into the shared settings object and persist them."""
        settings = shared_identity_settings()
        settings.current_username = self.__staged_current_username()
        settings.unknown_username = self.__staged_unknown_username()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edits, reverting both fields back to the shared settings' current values."""
        settings = shared_identity_settings()
        self.__ui.current_username_edit.setText(settings.current_username)
        self.__ui.unknown_username_edit.setText(settings.unknown_username)

    def __staged_current_username(self) -> str:
        """The current-user field's text, stripped, with a blank result resolving to the OS-login default."""
        return self.__ui.current_username_edit.text().strip() or default_username()

    def __staged_unknown_username(self) -> str:
        """The unknown-user field's text, stripped, with a blank result resolving to the unknown default."""
        return self.__ui.unknown_username_edit.text().strip() or DEFAULT_UNKNOWN_USERNAME
