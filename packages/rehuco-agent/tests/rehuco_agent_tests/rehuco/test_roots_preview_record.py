"""Tests for what the Roots view's details pane shows of a record: its URL and its description (#458)."""

import logging
from pathlib import Path
from typing import Final

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import QModelIndex, QUrl
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import QFrame
from pytest import LogCaptureFixture, fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.record_images import RecordImages
from rehuco_agent.rehuco.roots_preview import MINIMUM_WIDTH
from rehuco_agent.rehuco.scrolling_markdown_view import ScrollingMarkdownView
from rehuco_agent.settings.image_viewer_settings import shared_image_viewer_settings
from rehuco_agent.settings.markdown_rendering_settings import shared_markdown_rendering_settings
from rehuco_core import RehuDocument

from .test_roots_preview import WAIT_TIMEOUT_MS, Shown

URL: Final = "https://example.com/tutorials/jet-ski"
LONG_DESCRIPTION: Final = "\n\n".join(f"Paragraph {number} of a very long description." for number in range(60))


def write_record(path: Path, *, url: str = "", description: str = "") -> None:
    """Write a ``.rehu`` that says some things about its resource.

    :param path: where the record goes.
    :param url: the primary source's URL; empty for none.
    :param description: the description; empty for none.
    """
    path.touch()  # the suite's default ``Path.stat`` answers a missing file with a mock the atomic write cannot use
    document = RehuDocument.new(path)
    if url:
        document.url = url
    if description:
        document.description = description
    document.save()


def record_of_folder(library: Path, index: QModelIndex) -> Path | None:
    """What the owner would answer for a folder row: its ``info.rehu``, when it has one.

    :param library: the library's folder.
    :param index: the row.
    :returns: the record's path, or ``None``.
    """
    record = library / str(index.data()) / "info.rehu"
    return record if record.is_file() else None


@fixture(name="shown")
def fixture_shown(qtbot: QtBot, tmp_path: Path) -> Shown:
    """A preview over a library with a record of each shape, a ``.tc``, a broken record and a video.

    :param qtbot: pytest-qt fixture.
    :param tmp_path: pytest's temporary directory.
    :returns: the preview and its model.
    """
    library = tmp_path / "lib"
    library.mkdir()
    QImage(40, 30, QImage.Format.Format_RGB32).save(str(library / "pic.png"))
    write_record(library / "both.rehu", url=URL, description="Some **bold** words.\n\n![pic](pic.png)")
    write_record(library / "url_only.rehu", url=URL)
    write_record(library / "text_only.rehu", description="Just words.")
    write_record(library / "neither.rehu")
    write_record(library / "long.rehu", url=URL, description=LONG_DESCRIPTION)
    (library / "legacy.tc").write_text("url: https://example.com/old\ndescription: Old words.\n", encoding="utf-8")
    (library / "broken.rehu").write_text("{not json", encoding="utf-8")
    (library / "clip.mp4").write_bytes(b"x" * 64)
    (library / "pack").mkdir()
    write_record(library / "pack" / "info.rehu", url=URL, description="The pack says this.")
    (library / "plain").mkdir()
    return Shown(qtbot, library, record_for=lambda index: record_of_folder(library, index))


def show_record(qtbot: QtBot, shown: Shown, name: str) -> None:
    """Show a row and wait until the pane has answered for it.

    :param qtbot: pytest-qt fixture.
    :param shown: the preview and its model.
    :param name: the row's name.
    """
    shown.preview.show_index(shown.row(name))
    qtbot.waitUntil(lambda: shown.preview.record_texts is not None, timeout=WAIT_TIMEOUT_MS)


def url_label(shown: Shown) -> ElidedLabel:
    """The label the URL is shown in.

    :param shown: the preview and its model.
    :returns: the label.
    """
    label = shown.preview.findChild(ElidedLabel, "url_value")
    assert label is not None
    return label


def test_a_record_with_a_url_and_a_description_shows_both_under_a_line(
    qtbot: QtBot, mocker: MockerFixture, shown: Shown
) -> None:
    """The description is the description dock's own view, so a picture in it is found beside the record.

    **Test steps:**

    * show a record with a URL and a description with bold text and an image in the record's folder
    * verify both are shown, the description without its markup, the image resolved, and a line above them
    """
    resolved = mocker.spy(RecordImages, "get_markdown_viewer_image")

    show_record(qtbot, shown, "both.rehu")

    url, description = shown.preview.record_texts or ("", "")
    assert url == URL
    assert description.startswith("Some bold words.")
    view = shown.preview.findChild(ScrollingMarkdownView, "description_view")
    assert view is not None
    qtbot.waitUntil(lambda: resolved.spy_return is not None, timeout=WAIT_TIMEOUT_MS)
    assert "pic.png" in view.toHtml()
    line = shown.preview.findChild(QFrame, "record_line")
    assert line is not None
    assert line.isVisibleTo(shown.preview)


def test_the_previews_toggle_turns_the_description_images_into_placeholders(qtbot: QtBot, shown: Shown) -> None:
    """The pane follows the app-wide previews toggle like the description dock.

    **Test steps:**

    * show a record with an image, then turn previews off
    * verify the image stands in as a placeholder; turn them back on
    """
    settings = shared_image_viewer_settings()
    show_record(qtbot, shown, "both.rehu")
    try:
        settings.previews_visible = False
        assert "[image: pic]" in (shown.preview.record_texts or ("", ""))[1]
    finally:
        settings.previews_visible = True


def test_the_rendering_settings_reach_the_description(qtbot: QtBot, shown: Shown) -> None:
    """A change to the Markdown settings renders the description again, as in the description dock.

    **Test steps:**

    * show a record, then say the settings changed
    * verify the description is still shown
    """
    show_record(qtbot, shown, "both.rehu")

    shared_markdown_rendering_settings().description_rendering_changed.emit()

    assert (shown.preview.record_texts or ("", ""))[1].startswith("Some bold words.")


def test_a_record_with_only_one_of_them_shows_that_one(qtbot: QtBot, shown: Shown) -> None:
    """A field the record lacks is left out.

    **Test steps:**

    * show a record with only a URL, then one with only a description
    * verify the first shows the URL and no description, the second the reverse
    """
    show_record(qtbot, shown, "url_only.rehu")
    description = shown.preview.findChild(ScrollingMarkdownView, "description_view")
    assert description is not None
    assert shown.preview.record_texts == (URL, "")
    assert description.isHidden()

    shown.preview.show_index(shown.row("text_only.rehu"))
    qtbot.waitUntil(lambda: (shown.preview.record_texts or ("", ""))[1] != "", timeout=WAIT_TIMEOUT_MS)

    assert shown.preview.record_texts == ("", "Just words.")
    assert url_label(shown).isHidden()


def test_a_record_with_neither_shows_no_line_and_no_gap(qtbot: QtBot, shown: Shown) -> None:
    """A record that says nothing adds nothing to the pane.

    **Test steps:**

    * show a record with neither field and wait for the read to have ended
    * verify the section is hidden
    """
    shown.preview.show_index(shown.row("neither.rehu"))
    qtbot.wait(300)

    assert shown.preview.record_texts is None


def test_only_the_description_scrolls_and_it_takes_the_height_left_below_the_buttons(
    qtbot: QtBot, shown: Shown
) -> None:
    """A long description scrolls inside its own view, so the details and buttons above it stay where they are, and
    the pane never grows or gets a scrollbar of its own.

    **Test steps:**

    * show the pane, then a record with a short description and one with a long one
    * scroll the long one to its end
    * verify it scrolls and fills the pane down to its bottom edge, the details above it do not move, and the pane's
      minimum width is the same for both
    """
    shown.preview.resize(320, 500)
    shown.preview.show()
    qtbot.waitExposed(shown.preview)
    view = shown.preview.findChild(ScrollingMarkdownView, "description_view")
    path_value = shown.preview.findChild(ElidedLabel, "path_value")
    assert view is not None
    assert path_value is not None
    layout = shown.preview.layout()
    assert layout is not None

    show_record(qtbot, shown, "text_only.rehu")
    qtbot.wait(50)
    short_width = layout.minimumSize().width()
    assert view.verticalScrollBar().maximum() == 0

    shown.preview.show_index(shown.row("long.rehu"))
    qtbot.waitUntil(lambda: view.verticalScrollBar().maximum() > 0, timeout=WAIT_TIMEOUT_MS)
    qtbot.wait(50)
    details_top = path_value.mapTo(shown.preview, path_value.rect().topLeft()).y()

    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())

    assert view.mapTo(shown.preview, view.rect().bottomLeft()).y() > shown.preview.height() - 40
    assert path_value.mapTo(shown.preview, path_value.rect().topLeft()).y() == details_top
    assert layout.minimumSize().width() == short_width <= MINIMUM_WIDTH


def test_the_link_opens_through_the_desktop_services_and_a_long_url_is_elided(
    qtbot: QtBot, mocker: MockerFixture, shown: Shown
) -> None:
    """A click hands the whole address to the system; the pane shows only what fits and keeps the rest in a tooltip.

    **Test steps:**

    * show a record with a very long URL in a narrow pane
    * verify the label is elided with the whole address in its tooltip and the pane's minimum width is unchanged
    * activate the link and verify the system was asked to open the address
    """
    long_url = "https://example.com/" + "segment/" * 40
    path = shown.model.path_of(shown.row("url_only.rehu"))
    assert path is not None
    write_record(path, url=long_url)
    opened = mocker.patch.object(QDesktopServices, "openUrl")
    shown.preview.resize(MINIMUM_WIDTH, 500)
    shown.preview.show()
    qtbot.waitExposed(shown.preview)

    show_record(qtbot, shown, "url_only.rehu")

    label = url_label(shown)
    assert label.toolTip() == long_url
    assert "…" in label.text()  # the anchor keeps the whole address; the text it wraps is elided
    layout = shown.preview.layout()
    assert layout is not None
    assert layout.minimumSize().width() <= MINIMUM_WIDTH

    label.linkActivated.emit(long_url)

    opened.assert_called_once_with(QUrl(long_url))


def test_a_url_that_is_not_a_web_address_is_shown_and_is_not_a_link(qtbot: QtBot, shown: Shown) -> None:
    """A record is outside input: its text is shown, but only a web address is a link.

    **Test steps:**

    * show a record whose URL is a file address
    * verify the URL is shown as plain text, with no anchor
    """
    path = shown.model.path_of(shown.row("url_only.rehu"))
    assert path is not None
    write_record(path, url="file:///C:/Windows/system32/calc.exe")

    show_record(qtbot, shown, "url_only.rehu")

    assert "<a " not in url_label(shown).text()
    assert shown.preview.record_texts == ("file:///C:/Windows/system32/calc.exe", "")


def test_an_answer_for_a_row_no_longer_shown_is_dropped(qtbot: QtBot, shown: Shown) -> None:
    """The answer of a read is for the row that asked.

    **Test steps:**

    * show a record and at once a video, then wait for the read to have ended
    * verify nothing of the record is shown
    """
    shown.preview.show_index(shown.row("both.rehu"))
    shown.preview.show_index(shown.row("clip.mp4"))

    qtbot.wait(300)

    assert shown.preview.record_texts is None


def test_a_record_that_does_not_parse_leaves_the_pane_as_it_was_and_logs_why(
    qtbot: QtBot, caplog: LogCaptureFixture, shown: Shown
) -> None:
    """A broken record shows its details as before and no section; the reason goes to the log, not a dialog.

    **Test steps:**

    * show a record with a URL, then one that is not JSON
    * verify the section is gone, the type line is still the record's, and a warning names the file
    """
    show_record(qtbot, shown, "both.rehu")

    with caplog.at_level(logging.WARNING, logger="rehuco_agent.rehuco.roots_preview"):
        shown.preview.show_index(shown.row("broken.rehu"))
        qtbot.waitUntil(lambda: "broken.rehu" in caplog.text, timeout=WAIT_TIMEOUT_MS)

    assert shown.preview.record_texts is None
    assert shown.text("type_value")


def test_a_tc_record_shows_its_url_and_description_and_other_files_show_nothing(qtbot: QtBot, shown: Shown) -> None:
    """A legacy record has the same two fields; a file that is not a record has no section.

    **Test steps:**

    * show a ``.tc`` record, then a video and an empty selection
    * verify the ``.tc`` shows its URL and description and the others show no section
    """
    show_record(qtbot, shown, "legacy.tc")
    assert shown.preview.record_texts == ("https://example.com/old", "Old words.")

    shown.preview.show_index(shown.row("clip.mp4"))
    assert shown.preview.record_texts is None

    shown.preview.show_index(QModelIndex())
    assert shown.preview.record_texts is None


def test_a_record_read_that_ends_after_the_preview_was_deleted_is_dropped(mocker: MockerFixture, shown: Shown) -> None:
    """The worker's last step, telling the preview, does not raise once the preview is gone.

    **Test steps:**

    * make telling the preview raise, as a deleted C++ object does, and run the read of a record
    * verify nothing is raised
    """
    path = shown.model.path_of(shown.row("both.rehu"))
    assert path is not None
    mocker.patch.object(shown.preview, "record_ready").emit.side_effect = RuntimeError
    read_record = shown.preview._RootsPreview__read_record  # type: ignore[attr-defined]  # pylint: disable=protected-access

    read_record(1, path)


def test_a_folder_shows_the_url_and_description_of_its_own_rehu(qtbot: QtBot, shown: Shown) -> None:
    """A folder that is a resource says what its record says; a folder with no record shows nothing.

    **Test steps:**

    * show a folder holding an ``info.rehu``, then one holding none
    * verify the first shows its record's URL and description and the second no section
    """
    show_record(qtbot, shown, "pack")

    assert shown.preview.record_texts == (URL, "The pack says this.")

    shown.preview.show_index(shown.row("plain"))
    qtbot.wait(100)

    assert shown.preview.record_texts is None


def test_a_record_changed_on_disk_since_the_pane_read_it_is_read_again(
    qtbot: QtBot, shown: Shown, tmp_path: Path
) -> None:
    """The pane compares what the disk shows now with what it read, not with the cache (#487).

    **Test steps:**

    * show a record, then rewrite it outside the app
    * report the file as it was read: verify nothing is read again
    * report it as it is now: verify the pane shows the new description
    """
    path = tmp_path / "lib" / "text_only.rehu"
    show_record(qtbot, shown, "text_only.rehu")
    read_at = path.stat()
    write_record(path, description="Rewritten outside the app, at more length.")

    shown.preview.follow_files({path: (read_at.st_mtime_ns, read_at.st_size)})
    assert (shown.preview.record_texts or ("", ""))[1] == "Just words."

    now = path.stat()
    shown.preview.follow_files({path: (now.st_mtime_ns, now.st_size)})
    qtbot.waitUntil(
        lambda: (shown.preview.record_texts or ("", ""))[1] == "Rewritten outside the app, at more length.",
        timeout=WAIT_TIMEOUT_MS,
    )
