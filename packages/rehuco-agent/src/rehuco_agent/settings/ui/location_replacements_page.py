"""Location replacements settings page: one global text -> replacement rule table (#350)."""

from typing import Final

from PySide6.QtWidgets import QWidget

from ..location_replacements_settings import (
    DEFAULT_RULES,
    LocationReplacementsSettings,
    shared_location_replacements_settings,
)
from ..persistent_settings import persistent_settings
from .location_replacements_page_ui import Ui_LocationReplacementsPage


class LocationReplacementsPage(QWidget):
    """Edit the global location-replacement rule table (#350), registered under its own top-level title
    (see ``MainWindow.__register_settings_pages``) -- unlike
    `~rehuco_agent.settings.ui.location_templates_page.LocationTemplatesPage`, there is one instance for
    the whole app: a separator convention is a preference about names in general, not about one
    resource type's fields.

    Saving pushes the staged table straight into the shared `LocationReplacementsSettings` and persists
    it -- no normalization beyond what the model already enforces (order, and the per-row text/
    replacement pair), since unlike a location pattern list an empty table is itself a valid saved
    state (see the module docstring). An empty-text row is **kept**, flagged, the same "fix it in place"
    rule `~rehuco_agent.settings.ui.location_templates_page.LocationTemplatesPage` follows for a broken
    pattern: only what `~rehuco_agent.settings.location_replacements_settings.apply_location_replacements`
    actually applies skips it.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_LocationReplacementsPage()
        self.__ui.setupUi(self)
        self.__ui.rules_editor.defaults = DEFAULT_RULES
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether applying would change the stored rule table."""
        return self.__ui.rules_editor.values != shared_location_replacements_settings().rules

    def save_changes(self) -> None:
        """Push the staged rule table into the shared settings object and persist it."""
        settings = shared_location_replacements_settings()
        settings.rules = self.__ui.rules_editor.values
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, refilling the editor from the stored table -- invalid rows
        included, flagged."""
        self.__ui.rules_editor.values = shared_location_replacements_settings().rules

    def seed_defaults(self) -> None:
        """Stage the factory state: the rules an unloaded `LocationReplacementsSettings` resolves to,
        :data:`~rehuco_agent.settings.location_replacements_settings.DEFAULT_RULES`."""
        self.__ui.rules_editor.values = LocationReplacementsSettings().rules
