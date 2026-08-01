"""The `size` leaf field: a measured size shown formatted GNU ``ls -sh`` style, with the row that
measures it ([[plugins#field-toolkit]], #223).
"""

from collections.abc import Callable
from typing import Final, override

from PySide6.QtWidgets import QLabel

from .background_measurement import measure_in_background
from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import FileSizeEdit


class FileSizeField(Field[int | None]):
    """A ``size`` field ([[plugins#field-toolkit]], [[field-schema#duration-size]]): stored as whole
    **bytes**, edited via :class:`~rehuco_agent.fields.widgets.FileSizeEdit` -- the stored spin box plus
    the compute/apply row over it. The viewer formats those bytes GNU ``ls -sh`` style (``1.4G``,
    ``300B``; ``None`` -- unmeasured -- renders empty, a genuine ``0`` renders honestly as ``0B``).
    Covers ``original_size`` / ``current_size``, both of which
    [[field-schema#duration-size]] defines as measured values.

    ``measure`` is what makes this field type worth having over an int: summing a resource's content
    reaches the filesystem and the user's excluded-files setting, neither of which the toolkit knows
    about, so the caller that composes the form
    (`~rehuco_agent.documents.document_fields.build_document_form`) supplies it -- the same inversion the
    content count and the images strip's scanner take.

    **The scan runs off the GUI thread** (:class:`~rehuco_agent.fields.background_measurement.BackgroundMeasurement`):
    it is a ``stat`` per file over a whole tree, on a resource that lives on an SMB mount, and the window
    must not freeze for it. The editor is busy for the duration, which is what keeps a second Compute --
    or an Apply of a half-finished answer -- from being pressed.

    **Measuring is explicit and never writes.** Compute fills the readout beside the stored value and
    stops there; only ``Apply`` writes, and only while the two differ. Nothing measures on open, because
    a stored size that disagrees with the disk is evidence -- content deleted as a tutorial was watched
    -- and overwriting it would destroy that evidence. It matters most on ``original_size``, the
    footprint when complete: a compute pressed on a partly-deleted resource replaces the denominator of
    *how much is left* with the remainder, which is why nothing here does it unasked.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param measure: sums the resource's content on disk, returning ``None`` when there is nothing to
        measure (a document with no path yet). **Called on a worker thread**, so it must touch no widget
        and no ``QObject``. Called on every ``Compute``, never on construction.
    :param viewer_tab: the surface this field's viewer belongs to.
    :param editor_tab: the surface this field's editor belongs to.
    """

    TYPE = "size"

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
        label = QLabel(FileSizeEdit.format(binding.value))
        self.bind_external(binding.changed, lambda value: label.setText(FileSizeEdit.format(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[int | None]) -> FieldEditorWidgets:
        editor = FileSizeEdit()
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        # the ignore is the same one bind_value_widget above needs, for the same reason: PySide types a
        # class-level ``Signal`` as ``Signal``, not as the ``SignalInstance`` an *instance* actually
        # exposes, so no widget declaring one ever satisfies a protocol naming it statically
        measure_in_background(editor, self.__measure)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
