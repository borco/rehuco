"""The `size_pair` field: the original and current sizes on disk as one editor over **one** scan
([[plugins#field-toolkit]], [[field-schema#duration-size]], #232).
"""

from collections.abc import Callable, Sequence
from typing import Final, override

from borco_pyside.widgets import equal_height_column
from PySide6.QtWidgets import QLabel, QWidget

from .background_measurement import measure_in_background
from .field import Field, FieldBinding, FieldEditorWidgets, FieldsTab, FieldViewerWidgets
from .widgets import SizeMeasurementEdit


# the two single-binding hooks are deliberately left unimplemented: this field overrides the row-level
# ``make_viewer_rows``/``make_editor_row`` instead, which is the pair of hooks `FieldsForm` calls, and a
# forwarding `make_viewer` would have to invent which of the two names it meant
# pylint: disable-next=abstract-method
class SizePairField(Field[int | None]):
    """The two measured sizes as one field ([[field-schema#duration-size]]): ``original_size`` and
    ``current_size``, stored as whole **bytes**, sharing one measurement and one readout, each accepted
    by its own copy button.

    **Why they merged.** Both sizes are the same walk of the same tree over the same exclusion list
    (#223/#226) -- *when* you press one is the whole difference. As two independent rows, populating a
    freshly imported record meant two Compute presses running two identical scans for one identical
    answer. One press now fills one readout that both rows accept from, and accepting stays two separate,
    explicit clicks: ``original_size`` is the denominator for *how much is left*, so a copy into
    ``current_size`` must leave it exactly where it was.

    **One field, two bindings.** :attr:`names` carries both, `FieldsForm` resolves a binding for each,
    and the editor's rows are bound one apiece -- which is why this is a `Field` over two model names
    rather than two fields sharing a widget. The **viewer** is untouched by the merge: one formatted
    GNU ``ls -sh`` row per size, labeled separately, exactly as before (``None`` -- unmeasured -- renders
    empty, a genuine ``0`` renders honestly as ``0B``).

    **A pair is not a requirement.** A type declaring only one of the two names composes a coherent
    single row rather than raising: the composition filter narrows the spec to whichever name is declared
    (`~rehuco_agent.documents.document_fields.composed_field_specs`) and the widget is built from the
    labels it is given. Today both are common-core, so both are always declared; the rule exists so that
    stops being a load-bearing accident.

    ``measure`` is what makes this worth having over two ints: summing a resource's content reaches the
    filesystem and the user's excluded-files setting, neither of which the toolkit knows about, so the
    caller that composes the form
    (`~rehuco_agent.documents.document_fields.build_document_form`) supplies it -- the same inversion the
    content count and the images strip's scanner take. It is handed in **once**, not once per name, which
    is the merge stated in the constructor.

    **The scan runs off the GUI thread** (:class:`~rehuco_agent.fields.background_measurement.BackgroundMeasurement`):
    it is a ``stat`` per file over a whole tree, on a resource that lives on an SMB mount, and the window
    must not freeze for it. Every row is busy for the duration, which is what keeps a second Compute --
    or a copy of a half-finished answer -- from being pressed.

    **Measuring is explicit and never writes.** Compute fills the readout beside the stored values and
    stops there; only a copy writes, and only while that row differs from it. Nothing measures on open,
    because a stored size that disagrees with the disk is evidence -- content deleted as a tutorial was
    watched -- and overwriting it would destroy that evidence.

    :param name: the first bound size's identifier on its model.
    :param label: display label for that first size; derived from ``name`` when omitted.
    :param partner_name: the second bound size's identifier, or ``None`` for a lone row.
    :param measure: sums the resource's content on disk, returning ``None`` when there is nothing to
        measure (a document with no path yet). **Called on a worker thread**, so it must touch no widget
        and no ``QObject``. Called once per ``Compute``, never on construction.
    :param viewer_tab: the surface this field's viewers belong to.
    :param editor_tab: the surface this field's editor belongs to.
    """

    TYPE = "size_pair"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        *,
        partner_name: str | None = None,
        measure: Callable[[], int | None],
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab)
        self.__partner_name: Final = partner_name
        self.__measure: Final = measure

    @property
    @override
    def names(self) -> tuple[str, ...]:
        return (self.name,) if self.__partner_name is None else (self.name, self.__partner_name)

    @property
    def labels(self) -> tuple[str, ...]:
        """One display label per :attr:`names` entry, in the same order -- the first is this field's own
        :attr:`~Field.label`, the rest derived from their names the way any field's is."""
        return (self.label, *(Field.derive_label(name) for name in self.names[1:]))

    @override
    def make_viewer_rows(self, bindings: Sequence[FieldBinding[int | None]]) -> Sequence[FieldViewerWidgets]:
        return tuple(
            self.__make_viewer_row(label, binding) for label, binding in zip(self.labels, bindings, strict=True)
        )

    @override
    def make_editor_row(self, bindings: Sequence[FieldBinding[int | None]]) -> FieldEditorWidgets:
        labels = self.labels
        editor = SizeMeasurementEdit(labels)
        for row, binding in zip(editor.rows, bindings, strict=True):
            self.bind_value_widget(row, binding)  # type: ignore[arg-type]  # set_value is a synthesized slot
        # the ignore is the same one bind_value_widget above needs, for the same reason: PySide types a
        # class-level ``Signal`` as ``Signal``, not as the ``SignalInstance`` an *instance* actually
        # exposes, so no widget declaring one ever satisfies a protocol naming it statically
        measure_in_background(editor, self.__measure)  # type: ignore[arg-type]
        return FieldEditorWidgets(self.editor_tab, self.__make_stacked_label(labels), editor)

    def __make_viewer_row(self, label: str, binding: FieldBinding[int | None]) -> FieldViewerWidgets:
        """Build one size's viewer row: its own name label and its own formatted value.

        :param label: the bound size's display label.
        :param binding: that size's binding.
        :returns: the row bundle, live on the binding.
        """
        viewer = QLabel(SizeMeasurementEdit.format(binding.value))
        self.bind_external(binding.changed, lambda value: viewer.setText(SizeMeasurementEdit.format(value)))
        return FieldViewerWidgets(self.viewer_tab, QLabel(label), viewer)

    @staticmethod
    def __make_stacked_label(labels: Sequence[str]) -> QWidget:
        """Build the editor row's label cell: one name per editor row, stacked.

        Laid out with `~borco_pyside.widgets.equal_height_column`, the vertical twin of the editor grid's
        equal row stretches: both containers are handed the same cell height and both split it into the
        same equal bands, so name *i* sits against row *i* with no pixel math on either side.

        :param labels: the bound sizes' labels, top to bottom.
        :returns: the label cell.
        """
        cell = QWidget()
        equal_height_column(cell, *(QLabel(label, cell) for label in labels))
        return cell
