"""Live, reactive settings for where a record's URL is shown (#620): the Main View, the Description View, or both."""

from functools import lru_cache
from typing import Final, cast

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings

from .persistent_settings import persistent_settings

GROUP: Final = "record_url"
SHOW_ON_MAIN_VIEW_KEY: Final = "show_on_main_view"
SHOW_ON_DESCRIPTION_VIEW_KEY: Final = "show_on_description_view"

SHOW_ON_MAIN_VIEW_DEFAULT: Final = True
SHOW_ON_DESCRIPTION_VIEW_DEFAULT: Final = True


class RecordUrlSettings(QObject):
    """App-wide choice of where a record's URL line is drawn (#620): on the Main View, on the
    Description View (between the image strip and the description), or both. Both default on.

    A reactive ``QObject`` like its sibling
    :class:`~rehuco_agent.settings.description_editor_settings.DescriptionEditorSettings`: every open
    document's `~rehuco_agent.fields.url_field.UrlField` follows the ``*_changed`` signals, so a change
    on the settings page shows or hides the line in already-open documents with no reopen.
    :func:`shared_record_url_settings` is the single, process-wide instance every consumer reads and
    writes.

    :param parent: optional Qt parent.
    """

    show_on_main_view = SimpleProperty(SHOW_ON_MAIN_VIEW_DEFAULT)
    """Whether the Main View shows the record's URL."""

    show_on_description_view = SimpleProperty(SHOW_ON_DESCRIPTION_VIEW_DEFAULT)
    """Whether the Description View shows the record's URL."""

    def load(self, settings: QSettings) -> None:
        """Replace the current values with what's in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        self.show_on_main_view = cast(bool, settings.value(SHOW_ON_MAIN_VIEW_KEY, SHOW_ON_MAIN_VIEW_DEFAULT, type=bool))
        self.show_on_description_view = cast(
            bool, settings.value(SHOW_ON_DESCRIPTION_VIEW_KEY, SHOW_ON_DESCRIPTION_VIEW_DEFAULT, type=bool)
        )
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the current values to persistent storage.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        settings.setValue(SHOW_ON_MAIN_VIEW_KEY, self.show_on_main_view)
        settings.setValue(SHOW_ON_DESCRIPTION_VIEW_KEY, self.show_on_description_view)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_record_url_settings() -> RecordUrlSettings:
    """The single, process-wide `RecordUrlSettings` instance, loaded from persistent storage on first call.

    :returns: the shared instance.
    """
    settings = RecordUrlSettings()
    settings.load(persistent_settings())
    return settings
