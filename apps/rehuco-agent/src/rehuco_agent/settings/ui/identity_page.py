"""Identity settings page: the username per-user state is filed under (#99, [[field-schema#per-user-shared]])."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ..identity_settings import default_username, shared_identity_settings
from ..persistent_settings import persistent_settings
from .identity_page_ui import Ui_IdentityPage


class IdentityPage(QWidget):
    """Edit the configured username -- the identity the editor's per-user writes and the ``.tc``
    importer file their state under ([[field-schema#per-user-shared]]).

    The edit is staged in the line edit until :meth:`save_changes` pushes it into the shared
    `IdentitySettings` instance and persists it; from then on it is what every *subsequent*
    document open/conversion reads (`DocumentsDock`) -- already-open documents keep the username
    they were constructed with (see `rehuco_agent.settings.identity_settings`). A staged value
    that is blank (nothing but whitespace) stands for "no name" and resolves to
    :func:`~rehuco_agent.settings.identity_settings.default_username` instead, the same fallback
    ``IdentitySettings.load`` applies -- an identity is never saved empty.

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
        """Whether the staged username differs from the shared settings' current value."""
        return self.__staged_username() != shared_identity_settings().username

    def save_changes(self) -> None:
        """Push the staged username into the shared settings object and persist it."""
        settings = shared_identity_settings()
        settings.username = self.__staged_username()
        settings.save(persistent_settings())

    def drop_changes(self) -> None:
        """Discard the staged edit, reverting the field back to the shared settings' current value."""
        self.__ui.username_edit.setText(shared_identity_settings().username)

    def __staged_username(self) -> str:
        """The line edit's text, stripped, with a blank result resolving to the OS-login default."""
        return self.__ui.username_edit.text().strip() or default_username()
