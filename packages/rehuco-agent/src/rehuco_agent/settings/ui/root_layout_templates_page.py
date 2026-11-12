"""Locations › Root Layout Templates settings page: the library of path templates a root's Path template drop-down
offers, with a Try-it preview (#637)."""

from typing import Final

from PySide6.QtWidgets import QWidget
from rehuco_core import PLACEHOLDERS, LocationPattern, render_layout

from ..location_replacements_settings import shared_location_replacements_settings
from ..location_templates_settings import DEFAULT_SAMPLE, SAMPLE_FIELDS
from ..persistent_settings import persistent_settings
from ..root_layout_templates_settings import (
    DEFAULT_ROOT_LAYOUT_TEMPLATES,
    REFUSED_TEMPLATES,
    normalize_root_layout_templates,
    shared_root_layout_templates_settings,
)
from .root_layout_templates_page_ui import Ui_RootLayoutTemplatesPage

ALL_PLACEHOLDERS: Final = frozenset(PLACEHOLDERS)
"""What a library row may name: a row is checked against a type's own set only where the root editor offers it."""

NO_TEMPLATES: Final = "No templates yet: the root editor offers * only."


class RootLayoutTemplatesPage(QWidget):
    """Edit the library of root path templates, one list for every record type, with a Try-it sample record.

    A row is the Locations grammar plus ``/`` between folder levels. **An invalid row is kept and flagged**, as on the
    per-type Locations pages, and so is a ``*`` row: the root editor always offers ``*``, so it is no template of
    the library. **Try it** shows, for each valid
    row, the path it gives the sample record -- through the saved Location Replacements and the name sanitising, as a
    root's destination does -- or why the root would offer no place. The preview follows the staged rows and sample,
    applied or not.

    Edits are staged until :meth:`save_changes`; the sample is a setting like the rows, so it dirties the page and is
    put back by :meth:`drop_changes` and :meth:`seed_defaults`.

    :param parent: optional Qt parent.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RootLayoutTemplatesPage()
        self.__ui.setupUi(self)
        self.__ui.templates_editor.known_placeholders = ALL_PLACEHOLDERS
        self.__ui.templates_editor.refused = REFUSED_TEMPLATES
        self.__ui.templates_editor.defaults = DEFAULT_ROOT_LAYOUT_TEMPLATES
        self.__sample_edits: Final = (
            self.__ui.sample_title_edit,
            self.__ui.sample_publisher_edit,
            self.__ui.sample_authors_edit,
            self.__ui.sample_year_edit,
            self.__ui.sample_count_edit,
        )
        """The sample record's fields, in :data:`SAMPLE_FIELDS` order."""
        self.__ui.templates_editor.values_changed.connect(self.__refresh_try_it)
        for edit in self.__sample_edits:
            edit.textChanged.connect(self.__refresh_try_it)
        shared_location_replacements_settings().rules_changed.connect(self.__refresh_try_it)
        self.drop_changes()

    def is_dirty(self) -> bool:
        """Whether applying would change the stored templates or sample record."""
        settings = shared_root_layout_templates_settings()
        staged = normalize_root_layout_templates(self.__ui.templates_editor.values)
        return staged != settings.templates or self.__sample() != settings.sample

    def save_changes(self) -> None:
        """Push the staged templates and sample into the shared settings, persist them, and show the result."""
        settings = shared_root_layout_templates_settings()
        settings.templates = normalize_root_layout_templates(self.__ui.templates_editor.values)
        settings.sample = self.__sample()
        settings.save(persistent_settings())
        self.drop_changes()

    def drop_changes(self) -> None:
        """Discard the staged edits, showing the stored templates -- invalid rows flagged -- and sample."""
        settings = shared_root_layout_templates_settings()
        self.__ui.templates_editor.values = settings.templates
        self.__show_sample(settings.sample)
        self.__refresh_try_it()

    def seed_defaults(self) -> None:
        """Stage the factory state: no templates, and the shipped sample."""
        self.__ui.templates_editor.values = DEFAULT_ROOT_LAYOUT_TEMPLATES
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
        """Recompute the preview from the staged templates, the sample as typed and the saved replacements."""
        values: dict[str, str] = dict(zip(SAMPLE_FIELDS, self.__sample(), strict=True))
        rules = shared_location_replacements_settings().rules
        lines: list[str] = []
        for template in normalize_root_layout_templates(self.__ui.templates_editor.values):
            pattern = LocationPattern(template, ALL_PLACEHOLDERS)
            if pattern.problem or template in REFUSED_TEMPLATES:
                continue
            missing = pattern.missing(values)
            if missing:
                verb = "is" if len(missing) == 1 else "are"
                lines.append(f"{template}: {', '.join(missing)} {verb} empty")
                continue
            path = render_layout(pattern, values, {}, rules)
            lines.append(f"{template} → {path}" if path else f"{template}: a folder level renders to nothing")
        self.__ui.try_it_result_label.setText("\n".join(lines) or NO_TEMPLATES)
