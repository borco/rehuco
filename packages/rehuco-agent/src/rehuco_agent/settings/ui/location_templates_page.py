"""Locations settings page: one resource type's rename-suggestion name patterns, with a Try-it preview
(#322).
"""

from typing import Final

from PySide6.QtWidgets import QWidget

from ...fields.widgets.path_editor import PathEditor
from ..location_templates_settings import (
    NAME_SUGGESTION_PATTERNS,
    location_pattern_problem,
    normalize_location_templates,
    render_location_pattern,
    shared_location_templates_settings,
)
from ..persistent_settings import persistent_settings
from .location_templates_page_ui import Ui_LocationTemplatesPage

DEFAULT_SAMPLE: Final[tuple[str, ...]] = ("Sample Title", "Sample Publisher", "Jane Doe, John Roe", "2025")
"""What the Try-it sample record starts out as -- ``title`` / ``publisher`` / ``authors`` / ``year`` in
that order -- so a fresh page shows the patterns naming something rather than an empty preview."""


class LocationTemplatesPage(QWidget):
    """Edit one resource type's rename-suggestion name patterns (#322): one instance per type, registered
    under the ``Locations`` group (see ``MainWindow.__register_settings_pages``), each reading and
    writing only its own type's entry in the shared `LocationTemplatesSettings`.

    Two frames. **Location name patterns** is the editable list, a
    :class:`~rehuco_agent.settings.ui.location_template_patterns_editor.LocationTemplatePatternsEditor` of
    one column each: a format string interpolating ``{title}`` / ``{publisher}`` / ``{authors}`` /
    ``{year}``, with ``{{ ... }}`` groups that drop out when a field is missing. **Try it** is a sample
    record (title / publisher / authors / year, editable) beside a read-only preview of what each staged
    pattern would name it -- sanitized the same way a `PathField` would show it
    (:meth:`~rehuco_agent.fields.widgets.path_editor.PathEditor.sanitize`), refreshed on every edit to
    either the patterns or the sample. One line per pattern, so every row is accounted for: a line whose
    name an earlier line already produced says so (the `PathField` offers it once), an invalid row says
    why, and a pattern whose groups all dropped says it named nothing.

    **The sample record is scratch space, not a setting.** It previews the patterns and changes nothing
    the app does, so it is seeded from :data:`DEFAULT_SAMPLE`, never saved, never part of
    :meth:`is_dirty`, and untouched by :meth:`save_changes` and :meth:`drop_changes`; its frame carries
    `SettingsFrameFilter.SCRATCH_PROPERTY` so the dialog's dirty highlight leaves it alone too. Only a
    value that has an effect on the app earns Apply.

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
        self.__ui: Final = Ui_LocationTemplatesPage()
        self.__ui.setupUi(self)
        self.__ui.patterns_editor.defaults = NAME_SUGGESTION_PATTERNS
        self.__sample_edits: Final = (
            self.__ui.sample_title_edit,
            self.__ui.sample_publisher_edit,
            self.__ui.sample_authors_edit,
            self.__ui.sample_year_edit,
        )
        """The sample record's fields, in :data:`DEFAULT_SAMPLE`'s ``(title, publisher, authors, year)``
        order."""
        for edit, value in zip(self.__sample_edits, DEFAULT_SAMPLE, strict=True):
            edit.setText(value)

        self.__ui.patterns_editor.values_changed.connect(self.__refresh_try_it)
        for edit in self.__sample_edits:
            edit.textChanged.connect(self.__refresh_try_it)

        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether applying would change this type's stored patterns.

        The staged patterns are normalized before the comparison, so a row that saving would drop
        anyway -- blank, or an exact repeat -- is not yet a change; an invalid row *is* one, since saving
        keeps it. The sample record is not consulted: it is not a setting.
        """
        staged = normalize_location_templates(self.__ui.patterns_editor.values, NAME_SUGGESTION_PATTERNS)
        return staged != shared_location_templates_settings().stored_for(self.__resource_type)

    def save_changes(self) -> None:
        """Push this type's staged patterns into the shared settings object, persist them, and show the
        result.

        The list is reloaded from the stored set afterwards rather than left as typed: normalization can
        change it, and a page still showing what was typed would disagree with what the next Apply
        would keep.
        """
        settings = shared_location_templates_settings()
        staged = normalize_location_templates(self.__ui.patterns_editor.values, NAME_SUGGESTION_PATTERNS)
        settings.patterns = {**settings.patterns, self.__resource_type: staged}
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged pattern edits, refilling the editor from this type's stored set -- invalid
        rows included, flagged; the sample record stays as typed."""
        self.__ui.patterns_editor.values = shared_location_templates_settings().stored_for(self.__resource_type)
        self.__refresh_try_it()

    def __refresh_try_it(self) -> None:
        """Recompute the Try-it preview from the staged (not yet saved) patterns and the sample record.

        One line per pattern. A name an earlier line already produced is reported as such rather than
        repeated, since the `PathField` offers it once; the comparison is on the sanitized name, so what
        merges here is exactly what merges there.
        """
        sample = (edit.text() for edit in self.__sample_edits)
        values: dict[str, str] = dict(zip(("title", "publisher", "authors", "year"), sample, strict=True))
        lines: list[str] = []
        first_line_by_name: dict[str, int] = {}
        for pattern in self.__ui.patterns_editor.values:
            problem = location_pattern_problem(pattern)
            name = None if problem else PathEditor.sanitize(render_location_pattern(pattern, values))
            if problem:
                result = f"(invalid: {problem})"
            elif name is None:
                result = "(empty)"
            elif name in first_line_by_name:
                result = f"(same as line {first_line_by_name[name]})"
            else:
                first_line_by_name[name] = len(lines) + 1
                result = name
            lines.append(f"{pattern} → {result}")
        self.__ui.try_it_result_label.setText("\n".join(lines))
