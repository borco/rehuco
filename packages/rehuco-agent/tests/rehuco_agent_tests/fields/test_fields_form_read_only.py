"""Tests for the part-lock of a fields form (#568): the editors of the named fields go read-only while the rest of the
form, labels included, stays as it is."""

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QGridLayout, QWidget
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel
from rehuco_agent.fields.fields_form import CONTENT_COLUMN, LABEL_COLUMN, FieldsForm

from rehuco_agent_tests.fields.field_testers import TextFieldTester as TextField

from .test_fields_form import grid_of, sole_grid_widget, widget_at


def enabled_at(grid: QGridLayout, row: int, column: int) -> bool:
    """Whether the widget in a grid cell is enabled.

    :param grid: the grid.
    :param row: the cell's row.
    :param column: the cell's column.
    :returns: its enabled state.
    """
    widget = widget_at(grid, row, column)
    assert widget is not None
    return widget.isEnabled()


def editor_at(grid: QGridLayout, row: int) -> QWidget:
    """The editor in a grid row's content cell.

    :param grid: the grid.
    :param row: the row.
    :returns: the editor.
    """
    widget = widget_at(grid, row, CONTENT_COLUMN)
    assert widget is not None
    return widget


def test_set_read_only_fields_disables_only_the_editors_of_the_named_fields(
    qtbot: QtBot, model: RehuDocumentModel
) -> None:
    """A part-lock (#568): the named fields' editors go disabled, the others and every label stay enabled, and an
    empty set gives the editors back.

    **Test steps:**

    * build an editor form over the title and the URL fields
    * make ``url`` read-only
    * verify its editor is disabled, the title's editor and both labels enabled
    * make nothing read-only
    * verify both editors are enabled
    """
    form = FieldsForm([TextField("title"), TextField("url")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)

    form.set_read_only_fields(frozenset({"url"}))

    assert [enabled_at(grid, row, CONTENT_COLUMN) for row in (0, 1)] == [True, False]
    assert [enabled_at(grid, row, LABEL_COLUMN) for row in (0, 1)] == [True, True]
    form.set_read_only_fields(frozenset())
    assert [enabled_at(grid, row, CONTENT_COLUMN) for row in (0, 1)] == [True, True]


def test_set_read_only_fields_does_not_enable_what_it_did_not_disable(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """Enabling follows only what an earlier call disabled: an editor disabled by anything else stays so.

    **Test steps:**

    * build an editor form over two fields and disable the title's editor by hand
    * make the URL read-only, then nothing
    * verify the title's editor is still disabled
    """
    form = FieldsForm([TextField("title"), TextField("url")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    grid = grid_of(widget)
    editor_at(grid, 0).setEnabled(False)

    form.set_read_only_fields(frozenset({"url"}))
    form.set_read_only_fields(frozenset())

    assert not enabled_at(grid, 0, CONTENT_COLUMN)


def test_set_read_only_fields_skips_editors_that_are_gone(qtbot: QtBot, model: RehuDocumentModel) -> None:
    """The form keeps no hold on the widgets its grids own: once they are deleted -- a teardown -- a call finds nothing
    to touch and raises nothing, enabling or disabling.

    **Test steps:**

    * build an editor form, make ``url`` read-only, and delete the grid
    * make ``url`` read-only again, then nothing
    * verify neither call raised
    """
    form = FieldsForm([TextField("title"), TextField("url")])
    widget = sole_grid_widget(form.make_editor(model))
    qtbot.addWidget(widget)
    form.set_read_only_fields(frozenset({"url"}))
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    form.set_read_only_fields(frozenset({"url"}))
    form.set_read_only_fields(frozenset())
