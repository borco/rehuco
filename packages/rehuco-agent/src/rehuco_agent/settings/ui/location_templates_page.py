"""Locations settings page: one resource type's rename-suggestion name patterns, with a Try-it preview
(#322).
"""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import DEFAULT_PLUGIN_REGISTRY

from ...fields.widgets.path_editor import PathEditor
from ..location_replacements_settings import apply_location_replacements, shared_location_replacements_settings
from ..location_templates_settings import (
    DEFAULT_SAMPLE,
    NAME_SUGGESTION_PATTERNS,
    SAMPLE_FIELDS,
    LocationTemplatesSettings,
    effective_location_templates,
    known_placeholders_for,
    normalize_location_templates,
    render_location_pattern,
    shared_location_templates_settings,
)
from ..persistent_settings import persistent_settings
from .location_templates_page_ui import Ui_LocationTemplatesPage


class LocationTemplatesPage(QWidget):
    """Edit one resource type's rename-suggestion name patterns (#322): one instance per type, registered
    under the ``Locations`` group (see ``MainWindow.__register_settings_pages``), each reading and
    writing only its own type's entry in the shared `LocationTemplatesSettings`.

    Two frames. **Location name patterns** is the editable list, a
    :class:`~rehuco_agent.settings.ui.location_template_patterns_editor.LocationTemplatePatternsEditor` of
    one column each: a format string interpolating ``{title}`` / ``{publisher}`` / ``{authors}`` /
    ``{year}``, plus ``{count}`` on a type whose plugin declares ``advertised_count`` (ReferenceImages,
    #349), with ``{{ ... }}`` groups that drop out when a field is missing. **Try it** is a sample record
    (title / publisher / authors / year, plus count on such a type, editable) beside a read-only preview
    of the names the staged patterns would offer it -- exactly the list a `PathField` would show on a
    document with these fields: sanitized (:meth:`~rehuco_agent.fields.widgets.path_editor.PathEditor.sanitize`),
    merged, an invalid or all-dropped pattern contributing nothing -- refreshed on every edit to either
    the patterns or the sample. The names alone, not the pattern each came from: the row above is where a
    pattern is read and flagged, and the preview's job is to show the outcome the way the document will.

    :attr:`__known_placeholders` is fixed at construction from ``resource_type``'s plugin declaration
    (`~rehuco_agent.settings.location_templates_settings.known_placeholders_for`) and never changes
    afterwards, which is what lets it also gate the Try-it sample record's Count row: one instance, one
    type, one placeholder set for its lifetime.

    **The sample record is a setting like the patterns**: staged in its fields, part of :meth:`is_dirty`,
    saved by :meth:`save_changes`, put back by :meth:`drop_changes` and :meth:`seed_defaults` -- so its
    frame dirties, and takes Apply, Reset, Defaults and "Apply changes as they're made", the way every
    other frame does. The preview, though, never waits for any of that: it expands the patterns with the
    record as typed, applied or not.

    **The ordering column stays visible**, unlike a list whose order is presentation: patterns are
    offered top to bottom, so moving one changes which suggestion a resource sees first.

    Edits are staged in the editor until :meth:`save_changes` pushes them into the shared
    `LocationTemplatesSettings` and persists them; from then on that list is what
    `~rehuco_agent.documents.name_suggestion_model.NameSuggestionModel` offers for this type, on every
    open document, without a reopen.

    Saving normalizes: blank patterns and exact duplicates go, and an emptied list resolves to the shipped
    defaults rather than to *offer nothing* -- but an **invalid row is kept**, flagged, so a typo is fixed
    in place rather than retyped: only the effective list a document reads skips it. That rule lives in
    `LocationTemplatesSettings`, not in the editor, which holds whatever was typed; the page reloads
    itself from the stored result afterwards, so what it shows is always what the next Apply would keep.

    :param resource_type: the plugin main key this page edits (e.g. ``"tutorial"``).
    :param parent: optional Qt parent.
    """

    def __init__(self, resource_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__resource_type: Final = resource_type
        self.__known_placeholders: Final = known_placeholders_for(DEFAULT_PLUGIN_REGISTRY.field_names(resource_type))
        """This type's full placeholder set (#349): the base four plus ``count`` when its plugin
        declares ``advertised_count``."""
        self.__ui: Final = Ui_LocationTemplatesPage()
        self.__ui.setupUi(self)
        self.__ui.patterns_editor.defaults = NAME_SUGGESTION_PATTERNS
        self.__ui.patterns_editor.known_placeholders = self.__known_placeholders
        has_count = "count" in self.__known_placeholders
        self.__ui.sample_count_label.setVisible(has_count)
        self.__ui.sample_count_edit.setVisible(has_count)
        if has_count:
            self.__ui.patterns_editor.setToolTip(
                self.__ui.patterns_editor.toolTip() + " This type also accepts {count}, its advertised count."
            )
            self.__ui.placeholders_label.setText(
                self.__ui.placeholders_label.text()
                + " This type also accepts a fifth: {count}, the pack's advertised image count."
            )
        self.__sample_edits: Final = (
            self.__ui.sample_title_edit,
            self.__ui.sample_publisher_edit,
            self.__ui.sample_authors_edit,
            self.__ui.sample_year_edit,
            self.__ui.sample_count_edit,
        )
        """The sample record's fields, in :data:`SAMPLE_FIELDS` order -- ``sample_count_edit`` stays in
        this tuple even when hidden, since it is simply never named by a pattern this type's patterns
        editor would accept."""

        self.__ui.patterns_editor.values_changed.connect(self.__refresh_try_it)
        for edit in self.__sample_edits:
            edit.textChanged.connect(self.__refresh_try_it)
        shared_location_replacements_settings().rules_changed.connect(self.__refresh_try_it)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether applying would change this type's stored patterns or sample record.

        The staged patterns are normalized before the comparison, so a row that saving would drop
        anyway -- blank, or an exact repeat -- is not yet a change; an invalid row *is* one, since saving
        keeps it. The sample record is compared as typed.
        """
        settings = shared_location_templates_settings()
        staged = normalize_location_templates(self.__ui.patterns_editor.values, NAME_SUGGESTION_PATTERNS)
        return staged != settings.stored_for(self.__resource_type) or self.__sample() != settings.sample_for(
            self.__resource_type
        )

    def save_changes(self) -> None:
        """Push this type's staged patterns and sample record into the shared settings object, persist
        them, and show the result.

        The list is reloaded from the stored set afterwards rather than left as typed: normalization can
        change it, and a page still showing what was typed would disagree with what the next Apply
        would keep.
        """
        settings = shared_location_templates_settings()
        staged = normalize_location_templates(self.__ui.patterns_editor.values, NAME_SUGGESTION_PATTERNS)
        settings.patterns = {**settings.patterns, self.__resource_type: staged}
        settings.samples = {**settings.samples, self.__resource_type: self.__sample()}
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, refilling the patterns editor from this type's stored set -- invalid
        rows included, flagged -- and the sample record from the stored one."""
        settings = shared_location_templates_settings()
        self.__ui.patterns_editor.values = settings.stored_for(self.__resource_type)
        self.__show_sample(settings.sample_for(self.__resource_type))
        self.__refresh_try_it()

    def seed_defaults(self) -> None:
        """Stage the factory state: the patterns an unloaded `LocationTemplatesSettings` resolves to
        for this type -- the shipped `NAME_SUGGESTION_PATTERNS`, the same for every type -- and the
        shipped sample record (#342)."""
        self.__ui.patterns_editor.values = LocationTemplatesSettings().stored_for(self.__resource_type)
        self.__show_sample(DEFAULT_SAMPLE)
        self.__refresh_try_it()

    def __sample(self) -> tuple[str, ...]:
        """The sample record as typed, in :data:`SAMPLE_FIELDS` order."""
        return tuple(edit.text() for edit in self.__sample_edits)

    def __show_sample(self, sample: tuple[str, ...]) -> None:
        """Show ``sample`` in the record's fields.

        :param sample: the record to show, in :data:`SAMPLE_FIELDS` order.
        """
        for edit, value in zip(self.__sample_edits, sample, strict=True):
            edit.setText(value)

    def __refresh_try_it(self) -> None:
        """Recompute the Try-it preview from the staged patterns and the sample record as typed -- both
        read off the widgets, never off the settings object, so an edit shows here before any Apply.

        The same pipeline a document's suggestions go through -- the effective list
        (:func:`~rehuco_agent.settings.location_templates_settings.effective_location_templates`, so a
        list with no valid row previews the shipped set a document would fall back to), rendered, run
        through the saved location-replacement rules (#350), sanitized, what reduced to nothing
        dropped, exact repeats merged in first-seen order -- so what shows here is exactly what a
        `PathField` would offer. An invalid pattern contributes nothing; its row is flagged above. The
        replacement rules are the *saved* ones, not staged: they belong to the separate Location
        Replacements page, and this preview follows a save there live via ``rules_changed``.
        """
        values: dict[str, str] = dict(zip(SAMPLE_FIELDS, self.__sample(), strict=True))
        usable = effective_location_templates(self.__ui.patterns_editor.values, self.__known_placeholders)
        rules = shared_location_replacements_settings().rules
        sanitized = (
            PathEditor.sanitize(
                apply_location_replacements(render_location_pattern(pattern, values, self.__known_placeholders), rules)
            )
            for pattern in usable
        )
        names = dict.fromkeys(name for name in sanitized if name is not None)
        self.__ui.try_it_result_label.setText("\n".join(names))
