"""The `count_claim` leaf field: a whole number that may be open-ended (``500+``), stored as text
([[plugins#field-toolkit]], #198).
"""

from typing import Final, override

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator

from .optional_text_field import OptionalTextField
from .widgets import LineEdit

COUNT_CLAIM_PATTERN: Final = r"\d*\+?"
"""What a claimed count may be typed as: digits, optionally followed by a single ``+`` (``500``, ``500+``,
or empty). ``5+0`` and ``+500`` are refused as they are typed, since neither is a claim anyone makes."""


class CountClaimField(OptionalTextField):
    """A **claimed** count ([[plugins#field-toolkit]], [[field-schema#field-types]]): a whole number the
    resource says of itself, kept as the text it was published as so an open-ended ``500+`` stays weaker
    than a bare ``500``. A label viewer + a validated `LineEdit` editor. Covers ``advertised_count``.

    Stored as a string rather than an integer precisely because of that ``+``: a listing claiming "500+
    images" claims *at least* 500, and storing ``500`` would silently strengthen it into an exact count
    nobody made. Nothing measures a claim, so this field has no compute row -- its measured counterpart is
    :class:`~rehuco_agent.fields.content_count_field.ContentCountField`.

    Empty is **absent**, not ``""`` ([[field-schema#deferred-items]]), as in
    :class:`~rehuco_agent.fields.optional_text_field.OptionalTextField`.
    """

    TYPE = "count_claim"

    @override
    def configure_editor(self, editor: LineEdit) -> None:
        editor.setValidator(QRegularExpressionValidator(QRegularExpression(COUNT_CLAIM_PATTERN), editor))
