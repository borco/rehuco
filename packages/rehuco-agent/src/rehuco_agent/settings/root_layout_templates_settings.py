"""The library of root path templates the root editor's drop-down offers, and the Try-it sample that page shows (#637).

A root path template is the Locations grammar plus ``/`` as the level separator
([[mounts-and-storage#rehuroot]]). **The library holds text only**: a root keeps the template it was given, so editing
the library later changes no root.

**What is stored is not what is offered.** The stored list keeps every row the user typed, an invalid one included, so a
typo is fixed in place; the root editor offers a template only when it is valid for the row's type.

A reactive ``QObject`` (``SimpleProperty`` fields), like
:class:`~rehuco_agent.settings.location_templates_settings.LocationTemplatesSettings`: an open root editor follows
:attr:`RootLayoutTemplatesSettings.templates_changed` and offers the saved list without a reopen.
"""

from functools import lru_cache
from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal
from rehuco_core import KEEP_NAME

from .location_templates_settings import DEFAULT_SAMPLE, SAMPLE_FIELDS
from .persistent_settings import persistent_settings, read_stored_strings

TEMPLATES_GROUP: Final = "root_layout_templates"
TEMPLATES_KEY: Final = "templates"
SAMPLE_GROUP: Final = "root_layout_try_it"

DEFAULT_ROOT_LAYOUT_TEMPLATES: Final[tuple[str, ...]] = ()
"""The shipped library: empty. The root editor always offers ``*``, so a root works with no template at all."""

REFUSED_TEMPLATES: Final = {KEEP_NAME: "The root editor always offers *: this row is ignored."}
"""Rows the library flags and never offers, though the grammar reads them as plain text: each with why."""


def normalize_root_layout_templates(templates: object) -> tuple[str, ...]:
    """Coerce a stored or edited list into its **stored** shape.

    Each entry is trimmed; blank ones and repeats go. An invalid template is **kept**, ``*`` included
    (:data:`REFUSED_TEMPLATES`): the page flags it in place.

    :param templates: the stored templates, or the templates as edited.
    :returns: the templates in the order first seen.
    """
    normalized: list[str] = []
    for entry in read_stored_strings(templates):
        template = entry.strip()
        if not template or template in normalized:
            continue
        normalized.append(template)
    return tuple(normalized)


class RootLayoutTemplatesSettings(QObject):
    """The root path template library, and the Try-it sample record of its page.

    :param parent: optional Qt parent.
    """

    templates_changed = Signal(object)
    sample_changed = Signal(object)

    templates = SimpleProperty[tuple[str, ...]](default_factory=lambda: DEFAULT_ROOT_LAYOUT_TEMPLATES)
    """The templates as stored, in the order the root editor offers them."""

    sample = SimpleProperty[tuple[str, ...]](default_factory=lambda: DEFAULT_SAMPLE)
    """The Try-it sample record, in :data:`~rehuco_agent.settings.location_templates_settings.SAMPLE_FIELDS` order."""

    def load(self, settings: QSettings) -> None:
        """Replace the library and the sample with what is in persistent storage.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(TEMPLATES_GROUP)
        self.templates = normalize_root_layout_templates(settings.value(TEMPLATES_KEY))
        settings.endGroup()
        settings.beginGroup(SAMPLE_GROUP)
        self.sample = tuple(
            str(settings.value(field, default)) for field, default in zip(SAMPLE_FIELDS, DEFAULT_SAMPLE, strict=True)
        )
        settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save the library as a list, and the sample one key per field (a field is free text, and ``authors`` holds
        a comma the ini list encoding would split).

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(TEMPLATES_GROUP)
        settings.setValue(TEMPLATES_KEY, list(self.templates))
        settings.endGroup()
        settings.beginGroup(SAMPLE_GROUP)
        for field, value in zip(SAMPLE_FIELDS, self.sample, strict=True):
            settings.setValue(field, value)
        settings.endGroup()


@lru_cache(maxsize=1)
def shared_root_layout_templates_settings() -> RootLayoutTemplatesSettings:
    """The single, process-wide `RootLayoutTemplatesSettings`, loaded from persistent storage on first call.

    :returns: the shared instance.
    """
    settings = RootLayoutTemplatesSettings()
    settings.load(persistent_settings())
    return settings
