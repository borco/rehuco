"""The `measured_duration` leaf field: a duration the app can measure, with the row that measures it
([[plugins#field-toolkit]], #224).
"""

from collections.abc import Callable
from typing import Final, override

from PySide6.QtWidgets import QLabel

from .background_measurement import measure_in_background
from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import DurationEdit, MeasuredDurationEdit


class MeasuredDurationField(Field[int | None]):
    """A duration whose value can be **measured** ([[plugins#field-toolkit]]): the formatted viewer
    :class:`~rehuco_agent.fields.duration_field.DurationField` gives, and an editor that is the same
    seconds editor plus the compute/apply row over it
    (:class:`~rehuco_agent.fields.widgets.MeasuredDurationEdit`). Covers ``original_duration`` and
    ``current_duration``, the two [[field-schema#duration-size]] defines as measured.

    **Not ``advertised_duration``**, which stays a plain
    :class:`~rehuco_agent.fields.duration_field.DurationField`: it is the coarse web claim, kept
    precisely so ``original_duration`` can be checked against it ([[field-schema#duration-size]]'s *"did
    I get everything"*). A measure row on it would erase the comparison by inviting the two to be made
    equal. That split -- one type for the claim, another for the measurement -- is the one
    ``count_claim``/``content_count`` already draws on the reference-images count pair (#198).

    ``measure`` is what makes this field type worth having over a duration: summing a tutorial's videos
    reaches the filesystem, a probe backend and the user's video-extension list, none of which the
    toolkit knows about, so the caller that composes the form
    (`~rehuco_agent.documents.document_fields.build_document_form`) supplies it -- the same inversion the
    size and count rows take.

    **The scan runs off the GUI thread** (:class:`~rehuco_agent.fields.background_measurement.BackgroundMeasurement`):
    it reads a container header per video -- hundreds of them, on a resource that lives on an SMB mount,
    or a subprocess per file with the external backend -- and the window must not freeze for it. The
    editor is busy for the duration, which is what keeps a second Compute -- or an Apply of a
    half-finished answer -- from being pressed.

    **Measuring is explicit and never writes.** Compute fills the readout beside the stored value and
    stops there; only ``Apply`` writes, and only while the two differ. Nothing measures on open, because
    a stored duration that disagrees with the disk is evidence -- videos deleted as they were watched,
    which is the tracking method the ``current_*`` axis exists for -- and overwriting it would destroy
    that evidence. It matters most on ``original_duration``, the length when complete: a compute pressed
    on a partly-watched resource replaces the denominator of *how much is left* with the remainder.

    :param name: the field's identifier on its model.
    :param label: display label; derived from ``name`` when omitted.
    :param measure: sums how long the resource's videos run, returning ``None`` when there is nothing to
        measure -- a document with no path yet, or a probe backend that cannot run here at all.
        **Called on a worker thread**, so it must touch no widget and no ``QObject``. Called on every
        ``Compute``, never on construction.
    :param viewer_tab: the surface this field's viewer belongs to.
    :param editor_tab: the surface this field's editor belongs to.
    """

    TYPE = "measured_duration"

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
        label = QLabel(DurationEdit.format(binding.value))
        self.bind_external(binding.changed, lambda value: label.setText(DurationEdit.format(value)))
        return FieldViewerWidgets(self.viewer_tab, self.make_label(), label)

    @override
    def make_editor(self, binding: FieldBinding[int | None]) -> FieldEditorWidgets:
        editor = MeasuredDurationEdit()
        self.bind_value_widget(editor, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        # the ignore is the same one bind_value_widget above needs, for the same reason: PySide types a
        # class-level ``Signal`` as ``Signal``, not as the ``SignalInstance`` an *instance* actually
        # exposes, so no widget declaring one ever satisfies a protocol naming it statically
        measure_in_background(editor, self.__measure)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.make_label(), editor)
