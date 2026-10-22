"""Tests for the Documents dock's preview while the record it shows is read off the GUI thread (#564): a record's type
is known only once it arrives, so the preview takes that type's layout then.

Every read is held back (``held_reads``) and answered when the test says so; the files are served by the same mocked
filesystem ``test_documents_dock`` uses. How a model takes a read is its own tests' subject.
"""

from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.documents_dock import DocumentsDock

from rehuco_agent_tests.record_reads import HeldReads

from .test_documents_dock import (
    FAKE_KEY,
    OTHER_KEY,
    OTHER_PATH,
    REFERENCE_PACK,
    THIRD_KEY,
    load_documents,
    on_disk_shown,
    preview_of,
    show_on_disk,
)

pytestmark = mark.usefixtures("real_sub_docks")


def test_the_preview_takes_its_records_layout_once_the_record_arrives(
    mocker: MockerFixture, qtbot: QtBot, held_reads: HeldReads
) -> None:
    """A preview, new or moving on, lays itself out for the record it shows only once that record arrives -- the type
    whose preview layout it takes is not known before.

    **Test steps:**

    * show a tutorial in a new preview, let it arrive, and show its On Disk dock
    * show a reference pack and let it arrive: verify its On Disk dock is hidden, as built
    * show another tutorial: verify the preview still has the pack's layout while the read is out
    * let it arrive: verify the tutorial's preview layout, its On Disk dock shown
    """
    load_documents(mocker, {OTHER_PATH: REFERENCE_PACK})
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    widget = dock.show_in_preview(FAKE_KEY)
    held_reads.answer(0)
    show_on_disk(widget)
    dock.show_in_preview(OTHER_KEY)
    held_reads.answer(1)
    assert not on_disk_shown(widget)

    dock.show_in_preview(THIRD_KEY)

    assert not on_disk_shown(widget)

    held_reads.answer(2)

    assert on_disk_shown(widget)


def test_a_new_preview_takes_its_records_preview_layout_once_the_record_arrives(
    mocker: MockerFixture, qtbot: QtBot, held_reads: HeldReads
) -> None:
    """A preview built for a record still being read is laid out for that record's type once it arrives.

    **Test steps:**

    * show a tutorial in the preview, let it arrive, show its On Disk dock, and close the preview -- leaving that as
      the tutorial's preview layout
    * show another tutorial in a new preview
    * verify its On Disk dock is hidden while the read is out
    * let it arrive
    * verify its On Disk dock is shown, as the tutorial's preview layout says
    """
    load_documents(mocker, {})
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    first = dock.show_in_preview(FAKE_KEY)
    held_reads.answer(0)
    show_on_disk(first)
    preview_of(dock).requestCloseDockWidget()

    second = dock.show_in_preview(THIRD_KEY)

    assert not on_disk_shown(second)

    held_reads.answer(1)

    assert on_disk_shown(second)


def test_a_preview_promoted_before_its_record_arrives_is_not_laid_out_as_one(
    mocker: MockerFixture, qtbot: QtBot, held_reads: HeldReads
) -> None:
    """A preview opened for good while its record is still being read is an ordinary document by the time the record
    arrives: it does not take the preview's layout.

    **Test steps:**

    * show a tutorial in the preview, let it arrive, show its On Disk dock, and close the preview -- leaving that as
      the tutorial's preview layout
    * show another tutorial in a new preview, and open it for good before its read arrives
    * let it arrive
    * verify its On Disk dock is hidden, as built, not shown as the preview layout says
    """
    load_documents(mocker, {})
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    first = dock.show_in_preview(FAKE_KEY)
    held_reads.answer(0)
    show_on_disk(first)
    preview_of(dock).requestCloseDockWidget()
    opened = dock.show_in_preview(THIRD_KEY)
    dock.open_document(THIRD_KEY)

    held_reads.answer(1)

    assert dock.preview_document_widget() is None
    assert not on_disk_shown(opened)


def test_opening_what_the_preview_is_moving_on_to_promotes_the_preview(
    mocker: MockerFixture, qtbot: QtBot, held_reads: HeldReads
) -> None:
    """A record the preview is moving on to, opened before its file arrives, is the preview's: the preview is
    promoted, as it is once the file has arrived, and no second document of the record is made.

    **Test steps:**

    * show one record in the preview, let it arrive, and show another, its read held
    * open the second record
    * verify the preview's own widget came back, promoted, and one read of the record is out
    * let the read arrive
    * verify one document is open, showing the record
    """
    load_documents(mocker, {})
    dock = DocumentsDock()
    qtbot.addWidget(dock)
    preview = dock.show_in_preview(FAKE_KEY)
    held_reads.answer(0)
    dock.show_in_preview(OTHER_KEY)

    opened = dock.open_document(OTHER_KEY)

    assert opened is preview
    assert dock.preview_document_widget() is None
    assert held_reads.keys == [FAKE_KEY, OTHER_KEY]

    held_reads.answer(1)

    assert dock.open_document_widgets() == [opened]
    assert opened.model.path == OTHER_PATH
