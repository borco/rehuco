"""The `content_count` leaf field: a measured count, with the row that measures it
([[plugins#field-toolkit]], #198).
"""

from collections.abc import Callable
from typing import Final, override

from PySide6.QtWidgets import QLabel

from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import ContentCountEdit


class ContentCountField(Field[int | None]):
    """A count whose value can be **measured** ([[plugins#field-toolkit]]): the plain-integer viewer
    :class:`~rehuco_agent.fields.int_field.IntField` gives, and an editor that is the stored spin box plus
    the compute/apply row over it (:class:`~rehuco_agent.fields.widgets.ContentCountEdit`). Covers
    ``current_count``, the number of images inside a reference-images resource's archives
    ([[data-model#resource-scoping]]).

    ``measure`` is what makes this field type worth having over ``int``: counting reaches the filesystem
    and the user's recognized-extension setting, neither of which the toolkit knows about, so the caller
    that composes the form (`~rehuco_agent.documents.document_fields.build_document_form`) supplies it --
    the same inversion the images strip's scanner takes.

    **Measuring is explicit and never writes.** Compute fills the label beside the stored value and stops
    there; only ``Apply`` writes, and only while the two differ. Nothing measures on open, because a stored
    count that disagrees with the archive is evidence of a refreshed zip and overwriting it would destroy
    that evidence ([[data-model#image-meanings]]).

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param measure: counts the resource's content images afresh, returning ``None`` when there is nothing
        to measure (a document with no path yet). Called on every ``Compute``, never on construction.
    :param viewer_tab: the surface this field's viewer belongs to.
    :param editor_tab: the surface this field's editor belongs to.
    """

    TYPE = "content_count"

    def __init__(
        self,
        name: str,
        label: str | None = None,
        *,
        measure: Callable[[], int | None],
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__measure: Final = measure

    @override
    def make_viewer(self, binding: FieldBinding[int | None]) -> FieldViewerWidgets:
        label = QLabel(self.__label_text(binding.value))
        self.bind_external(binding.changed, lambda value: label.setText(self.__label_text(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @staticmethod
    def __label_text(value: int | None) -> str:
        """The viewer label's text for ``value``: the plain number, or ``""`` when unset -- a genuine ``0``
        reads as ``0``, absent as nothing ([[field-schema#deferred-items]]).

        :param value: the field's current value.
        :returns: the display text.
        """
        return str(value) if value is not None else ""

    @override
    def make_editor(self, binding: FieldBinding[int | None]) -> FieldEditorWidgets:
        editor = ContentCountEdit()
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        editor.compute_requested.connect(lambda: editor.set_computed(self.__measure()))  # type: ignore[attr-defined]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
