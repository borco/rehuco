"""The `optional_url` leaf field: a link a record may leave out ([[plugins#field-toolkit]], #678)."""

from typing import override

from borco_pyside.widgets import ElidedLabel

from .field import FieldBinding, FieldViewerWidgets
from .optional_text_field import OptionalTextField


class OptionalUrlField(OptionalTextField):
    """A link a record may leave out: the viewer is an external hyperlink in an
    :class:`~borco_pyside.widgets.ElidedLabel`, as :class:`~rehuco_agent.fields.url_field.UrlField`'s is, and the
    editor is :class:`~rehuco_agent.fields.optional_text_field.OptionalTextField`'s, so clearing it removes the key.
    Covers an asset's ``license_url``, which is no source's: it says where the store states the terms.
    """

    TYPE = "optional_url"

    @override
    def make_viewer(self, binding: FieldBinding[str | None]) -> FieldViewerWidgets:
        link = ElidedLabel()
        link.setOpenExternalLinks(True)
        link.set_text(binding.value or "", href=binding.value or "")
        self.bind_external(binding.changed, lambda value: link.set_text(value or "", href=value or ""))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), link)
