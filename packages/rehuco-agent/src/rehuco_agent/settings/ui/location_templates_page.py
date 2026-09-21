"""Locations settings page: one resource type's rename-suggestion name patterns, with a Try-it preview
(#322).
"""

from typing import Final

from PySide6.QtWidgets import QWidget

from ...fields.widgets.path_editor import PathEditor
from ..location_templates_settings import (
    NAME_SUGGESTION_PATTERNS,
    normalize_location_templates,
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
    ``{year}``. **Try it** is a sample record (title / publisher / authors / year, editable) beside a
    read-only preview of what each staged pattern would name it -- sanitized the same way a `PathField`
    would show it (:meth:`~rehuco_agent.fields.widgets.path_editor.PathEditor.sanitize`), refreshed on
    every edit to either the patterns or the sample.

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

    Saving normalizes: blank patterns and ones naming an unknown placeholder are dropped, duplicates go,
    and an emptied list resolves to the shipped defaults rather than to *offer nothing*. That rule lives
    in `LocationTemplatesSettings`, not in the editor, which holds whatever was typed; the page reloads
    itself from the saved result afterwards, so what it shows is always what a suggestion would actually
    use.

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
        """Whether applying would change the patterns this type's shared settings resolve to.

        The staged patterns are normalized before the comparison, so a row that saving would drop
        anyway -- blank, half-typed, or naming an unknown placeholder -- is not yet a change. The sample
        record is not consulted: it is not a setting.
        """
        staged = normalize_location_templates(self.__ui.patterns_editor.values, NAME_SUGGESTION_PATTERNS)
        return staged != shared_location_templates_settings().patterns_for(self.__resource_type)

    def save_changes(self) -> None:
        """Push this type's staged patterns into the shared settings object, persist them, and show the
        result.

        The list is reloaded from the saved set afterwards rather than left as typed: normalization can
        change it, and a page still showing what was typed would disagree with what the next suggestion
        actually offers.
        """
        settings = shared_location_templates_settings()
        staged = normalize_location_templates(self.__ui.patterns_editor.values, NAME_SUGGESTION_PATTERNS)
        settings.patterns = {**settings.patterns, self.__resource_type: staged}
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged pattern edits, refilling the editor from this type's effective set; the
        sample record stays as typed."""
        self.__ui.patterns_editor.values = shared_location_templates_settings().patterns_for(self.__resource_type)
        self.__refresh_try_it()

    def __refresh_try_it(self) -> None:
        """Recompute the Try-it preview from the staged (not yet saved) patterns and the sample record."""
        sample = (edit.text() for edit in self.__sample_edits)
        values: dict[str, str] = dict(zip(("title", "publisher", "authors", "year"), sample, strict=True))
        lines = [f"{pattern} → {self.__try_it_result(pattern, values)}" for pattern in self.__ui.patterns_editor.values]
        self.__ui.try_it_result_label.setText("\n".join(lines))

    @staticmethod
    def __try_it_result(pattern: str, values: dict[str, str]) -> str:
        """What ``pattern`` would name the sample record, sanitized the way a `PathField` would show it.

        :param pattern: one staged pattern, possibly still half-typed or invalid.
        :param values: the sample record's ``title`` / ``publisher`` / ``authors`` / ``year``.
        :returns: the sanitized name, or a short explanation when the pattern cannot be formatted.
        """
        try:
            raw = pattern.format(**values)
        except KeyError, IndexError, ValueError:
            return "(invalid pattern)"
        sanitized = PathEditor.sanitize(raw)
        return sanitized if sanitized is not None else "(empty after sanitizing)"
