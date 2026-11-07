"""The global table of text replacements applied to a rendered location name (#350): the rules themselves, and how
they apply, are :mod:`rehuco_core.replacement_rule` (#577); this keeps the user's table.

One ordered, global table (not per resource type, unlike
`~rehuco_agent.settings.location_templates_settings.LocationTemplatesSettings` -- a separator convention is a
preference about names in general, not about one resource type's fields), applied in table order to a rendered
pattern's output. A regex row is what lets one rule collapse ``" | "``'s own surrounding spaces (``r" *\\| *"``)
while a neighboring row stays a literal match.

**A rule with no text, or an unparsable regex, is kept but never applied**, the same "flagged, not dropped" rule
`LocationPattern` follows for a broken pattern; the settings page marks it invalid in place.

**Unlike a type's pattern list, an empty rule table is a real, permanent choice** -- "no replacements" is
as valid an answer as any two rules, where an empty *pattern* list is not (a document always needs a
name). So :meth:`LocationReplacementsSettings.load` cannot fall back to :data:`DEFAULT_RULES` just
because the stored table is empty the way `normalize_location_templates` does: that would make it
impossible to ever save "delete both shipped rules". :data:`CONFIGURED_KEY` records that a save has
happened at all, so only a table that was *never* saved reads back as the shipped seed.
"""

from functools import lru_cache
from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtCore import QObject, QSettings, Signal
from rehuco_core import ReplacementRule

from .persistent_settings import persistent_settings

GROUP: Final = "location_replacements"
CONFIGURED_KEY: Final = "configured"
RULES_KEY: Final = "rules"
TEXT_KEY: Final = "text"
REPLACEMENT_KEY: Final = "replacement"
IS_REGEX_KEY: Final = "is_regex"


DEFAULT_RULES: Final = (ReplacementRule(": ", " - "), ReplacementRule(r" *\| *", " - ", is_regex=True))
"""The shipped seed (#350): a colon-space and a pipe -- with whatever spacing surrounds it -- both read
as a separator, so both become the same plain one a filesystem name can keep. The pipe rule is a regex
specifically so ``" | "`` collapses to one `` - ``, not the two spaces a literal ``"|"`` rule would leave
either side of the replacement."""


class LocationReplacementsSettings(QObject):
    """The global replacement-rule table (#350): one stored field, the ordered rule list, raw as the
    page left it -- an invalid (empty-text) row is kept and flagged, the same discipline
    `~rehuco_agent.settings.location_templates_settings.LocationTemplatesSettings` uses for a broken
    pattern.

    A reactive ``QObject`` (`SimpleProperty`), so a caller that renders a location name can follow
    :attr:`rules_changed` the way
    `~rehuco_agent.documents.name_suggestion_model.NameSuggestionModel` already follows
    `~rehuco_agent.settings.location_templates_settings.LocationTemplatesSettings.patterns_changed`.

    :param parent: optional Qt parent.
    """

    rules_changed = Signal(object)
    """Fires whenever :attr:`rules` changes -- a tuple value, so an explicit ``Signal(object)`` rather
    than the auto-synthesized one, per `SimpleProperty`'s own convention."""

    rules = SimpleProperty[tuple[ReplacementRule, ...]](default_factory=lambda: DEFAULT_RULES)
    """Every rule, in table order, raw as stored -- an empty-text row included. What a fresh, unloaded
    instance holds is :data:`DEFAULT_RULES`, which is both the shipped seed and what
    :meth:`seed_defaults` on the settings page puts back."""

    def load(self, settings: QSettings) -> None:
        """Replace :attr:`rules` with what's in persistent storage.

        A table that was never saved (:data:`CONFIGURED_KEY` absent) reads back as :data:`DEFAULT_RULES`
        -- the shipped seed a fresh install shows. One that *was* saved, even empty, is read exactly as
        stored: an empty table is a real choice here, unlike a type's pattern list.

        :param settings: the ``QSettings`` to read from.
        """
        settings.beginGroup(GROUP)
        try:
            if not settings.value(CONFIGURED_KEY, False, type=bool):
                self.rules = DEFAULT_RULES
                return
            rules: list[ReplacementRule] = []
            for index in range(settings.beginReadArray(RULES_KEY)):
                settings.setArrayIndex(index)
                rules.append(
                    ReplacementRule(
                        text=str(settings.value(TEXT_KEY, "")),
                        replacement=str(settings.value(REPLACEMENT_KEY, "")),
                        is_regex=bool(settings.value(IS_REGEX_KEY, False, type=bool)),
                    )
                )
            settings.endArray()
            self.rules = tuple(rules)
        finally:
            settings.endGroup()

    def save(self, settings: QSettings) -> None:
        """Save :attr:`rules` to persistent storage, and mark the table as configured.

        :param settings: the ``QSettings`` to write to.
        """
        settings.beginGroup(GROUP)
        try:
            settings.setValue(CONFIGURED_KEY, True)
            # QSettings' array writer sets the size and writes the entries it is given, but never deletes
            # the indexed keys a longer array left behind -- so a table that shrank would keep its dead
            # rows in the file, under a size that no longer counts them
            settings.remove(RULES_KEY)
            settings.beginWriteArray(RULES_KEY)
            for index, rule in enumerate(self.rules):
                settings.setArrayIndex(index)
                settings.setValue(TEXT_KEY, rule.text)
                settings.setValue(REPLACEMENT_KEY, rule.replacement)
                settings.setValue(IS_REGEX_KEY, rule.is_regex)
            settings.endArray()
        finally:
            settings.endGroup()


@lru_cache(maxsize=1)
def shared_location_replacements_settings() -> LocationReplacementsSettings:
    """The single, process-wide `LocationReplacementsSettings` instance, loaded from persistent storage
    on first call -- the same shape as
    `~rehuco_agent.settings.location_templates_settings.shared_location_templates_settings`.

    :returns: the shared instance.
    """
    settings = LocationReplacementsSettings()
    settings.load(persistent_settings())
    return settings
