"""The `count_claim` leaf field: a whole number that may be open-ended (``500+``), stored as text
([[plugins#field-toolkit]], #198).
"""

from typing import Final, override

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldViewerWidgets
from .widgets import LineEdit

COUNT_CLAIM_PATTERN: Final = r"\d*\+?"
"""What a claimed count may be typed as: digits, optionally followed by a single ``+`` (``500``, ``500+``,
or empty). ``5+0`` and ``+500`` are refused as they are typed, since neither is a claim anyone makes."""


class CountClaimField(Field[str | None]):
    """A **claimed** count ([[plugins#field-toolkit]], [[field-schema#field-types]]): a whole number the
    resource says of itself, kept as the text it was published as so an open-ended ``500+`` stays weaker
    than a bare ``500``. A label viewer + a validated `LineEdit` editor. Covers ``advertised_count``.

    Stored as a string rather than an integer precisely because of that ``+``: a listing claiming "500+
    images" claims *at least* 500, and storing ``500`` would silently strengthen it into an exact count
    nobody made. Nothing measures a claim, so this field has no compute row -- its measured counterpart is
    :class:`~rehuco_agent.fields.content_count_field.ContentCountField`.

    Empty is **absent**, not ``""`` ([[field-schema#deferred-items]]): clearing the editor removes the key,
    and an absent value edits as an empty line rather than a placeholder the user has to delete.
    """

    TYPE = "count_claim"

    @override
    def make_viewer(self, binding: FieldBinding[str | None]) -> FieldViewerWidgets:
        label = QLabel(binding.value or "")
        self.bind_external(binding.changed, lambda value: label.setText(value or ""))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[str | None]) -> FieldEditorWidgets:
        editor = LineEdit()
        editor.setValidator(QRegularExpressionValidator(QRegularExpression(COUNT_CLAIM_PATTERN), editor))
        # the ""-is-absent mapping is this field's, not the widget's: `LineEdit` is the plain text
        # value widget every other string field binds to, and a text editor has no notion of a key
        # that stops existing when it is emptied
        editor.set_value(binding.value or "")
        editor.value_changed.connect(lambda text: binding.set_value(text or None))
        self.bind_external(binding.changed, lambda value: editor.set_value(value or ""))
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
