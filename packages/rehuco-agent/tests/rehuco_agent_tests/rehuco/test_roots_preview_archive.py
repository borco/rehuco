"""Tests for what the Roots preview says of a zip: what it is made of, and whether it is a reference pack (#456)."""

import zipfile
from pathlib import Path
from typing import Final

from PySide6.QtCore import QThreadPool
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QLabel
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.rehuco.roots_checksum import BAD_INK, OLD_BAD_INK
from rehuco_agent.rehuco.roots_management import PackInfo, PackState
from rehuco_agent.rehuco.roots_preview import (
    PACK_TEXTS,
    SLOW_METHOD_NOTE,
    UNREADABLE_ARCHIVE,
    UNREADABLE_METHOD_NOTE,
    format_size,
)
from rehuco_core import ArchiveFacts

from .test_roots_preview import WAIT_TIMEOUT_MS, Shown

PICTURE: Final = b"p" * 2000


def make_zip(path: Path, method: int, *, members: tuple[str, ...] = ("a.jpg", "b.png", "note.txt")) -> None:
    """Write a zip whose members are all in one compression method.

    :param path: where.
    :param method: the :mod:`zipfile` compression method.
    :param members: the member names; each holds :data:`PICTURE`.
    """
    with zipfile.ZipFile(path, "w", compression=method) as archive:
        for name in members:
            archive.writestr(name, PICTURE)


@fixture(name="library")
def fixture_library(tmp_path: Path) -> Path:
    """A folder holding a stored zip, a mixed one, a bzip2 one, something that is no zip, and a video.

    :param tmp_path: pytest's temporary directory.
    :returns: the folder.
    """
    library = tmp_path / "lib"
    library.mkdir()
    make_zip(library / "stored.zip", zipfile.ZIP_STORED)
    make_zip(library / "bzip.zip", zipfile.ZIP_BZIP2)
    with zipfile.ZipFile(library / "mixed.zip", "w") as archive:
        archive.writestr("a.jpg", PICTURE, compress_type=zipfile.ZIP_STORED)
        archive.writestr("b.jpg", PICTURE, compress_type=zipfile.ZIP_DEFLATED)
    (library / "broken.zip").write_bytes(b"not a zip")
    (library / "clip.mp4").write_bytes(b"x" * 2048)
    return library


def wait_for_archive(qtbot: QtBot, shown: Shown) -> dict[str, str]:
    """Wait until the archive rows say something, and read them.

    :param qtbot: pytest-qt fixture.
    :param shown: the preview.
    :returns: the rows.
    """
    qtbot.waitUntil(lambda: "contents" in shown.preview.archive_texts, timeout=WAIT_TIMEOUT_MS)
    return shown.preview.archive_texts


def ink(shown: Shown, name: str) -> QColor:
    """The colour a label of the preview is drawn in.

    :param shown: the preview.
    :param name: the label's object name.
    :returns: its window-text colour.
    """
    label = shown.preview.findChild(QLabel, name)
    assert label is not None
    return label.palette().color(QPalette.ColorRole.WindowText)


def test_a_stored_zip_says_what_it_holds_and_that_it_is_stored(qtbot: QtBot, library: Path) -> None:
    """The central directory gives the counts, both sizes and the method, with no member opened.

    **Test steps:**

    * show a zip of two pictures and a note, all stored
    * verify the file count with its images, the unpacked and packed sizes, and the compression
    """
    shown = Shown(qtbot, library)
    shown.preview.show_index(shown.row("stored.zip"))

    texts = wait_for_archive(qtbot, shown)

    assert texts["contents"] == "3 files (2 images)"
    assert texts["unpacked"] == format_size(3 * len(PICTURE))
    assert texts["packed"] == texts["unpacked"]
    assert texts["compression"] == "Stored"
    assert "pack" not in texts


def test_a_zip_that_mixes_methods_says_how_many_use_each(qtbot: QtBot, library: Path) -> None:
    """A mixed archive is not called by either method alone.

    **Test steps:**

    * show a zip with one stored and one deflated member
    * verify the compression line counts both
    """
    shown = Shown(qtbot, library)
    shown.preview.show_index(shown.row("mixed.zip"))

    assert wait_for_archive(qtbot, shown)["compression"] == "Mixed (1 stored, 1 deflated)"


def test_a_method_that_is_slow_to_read_is_warned_about_in_orange(qtbot: QtBot, library: Path) -> None:
    """bzip2 inflates far slower than deflate, which a pack would feel.

    **Test steps:**

    * show a bzip2 zip
    * verify the line names the method and the slowness, drawn in the expired-check orange
    """
    shown = Shown(qtbot, library)
    shown.preview.show_index(shown.row("bzip.zip"))

    text = wait_for_archive(qtbot, shown)["compression"]

    assert text == f"BZip2 - {SLOW_METHOD_NOTE}"
    assert ink(shown, "compression_value") == OLD_BAD_INK


def test_a_method_zipfile_cannot_read_is_warned_about_in_red(
    qtbot: QtBot, library: Path, mocker: MockerFixture
) -> None:
    """A member the app could never show reads as unreadable today, so the pane says so before it is opened.

    **Test steps:**

    * show a zip whose directory names deflate64
    * verify the line says it cannot be read, in red
    """
    mocker.patch(
        "rehuco_agent.rehuco.roots_preview.read_archive_facts",
        return_value=ArchiveFacts(files=1, images=1, unpacked=10, packed=5, methods={9: 1}),
    )
    shown = Shown(qtbot, library)
    shown.preview.show_index(shown.row("stored.zip"))

    text = wait_for_archive(qtbot, shown)["compression"]

    assert text == f"Deflate64 - {UNREADABLE_METHOD_NOTE}"
    assert ink(shown, "compression_value") == BAD_INK


def test_a_file_that_is_no_zip_says_so(qtbot: QtBot, library: Path) -> None:
    """A damaged archive is reported, not raised, and shows no sizes.

    **Test steps:**

    * show a ``.zip`` that holds no zip
    * verify the contents line and that no size is shown
    """
    shown = Shown(qtbot, library)
    shown.preview.show_index(shown.row("broken.zip"))

    assert wait_for_archive(qtbot, shown) == {"contents": UNREADABLE_ARCHIVE}


def test_the_pack_row_says_which_record_makes_a_zip_a_pack_and_when_nothing_is_known(
    qtbot: QtBot, library: Path
) -> None:
    """The cache's answer is shown as it is: a pack names its record, an unscanned record is said to be unscanned, and
    a zip that is no pack says nothing.

    **Test steps:**

    * show the same zip while the owner answers pack, unscanned and not a pack
    * verify the pack row each time
    """
    answer = [PackInfo(PackState.NOT_PACK)]
    shown = Shown(qtbot, library, pack_for=lambda _index: answer[0])
    cases = (
        (PackInfo(PackState.PACK, Path("lib/stored.rehu")), "Reference images, through stored.rehu"),
        (PackInfo(PackState.UNSCANNED, Path("lib/stored.rehu")), PACK_TEXTS[PackState.UNSCANNED]),
        (PackInfo(PackState.NOT_PACK), None),
    )

    for info, text in cases:
        answer[0] = info
        shown.preview.show_index(shown.row("stored.zip"))
        assert shown.preview.archive_texts.get("pack") == text


def test_a_stale_answer_is_dropped_and_other_rows_show_no_archive_lines(qtbot: QtBot, library: Path) -> None:
    """Moving to another row before the directory is read leaves nothing of the zip behind.

    **Test steps:**

    * show a zip, then at once a video, and let the read finish
    * verify no archive line is shown
    """
    shown = Shown(qtbot, library)
    shown.preview.show_index(shown.row("stored.zip"))
    shown.preview.show_index(shown.row("clip.mp4"))
    QThreadPool.globalInstance().waitForDone()
    QApplication.processEvents()

    assert shown.preview.archive_texts == {}


def test_an_archive_read_that_ends_after_the_preview_was_deleted_is_dropped(
    qtbot: QtBot, library: Path, mocker: MockerFixture
) -> None:
    """The worker's last step, telling the preview, does not raise once the preview is gone.

    **Test steps:**

    * make telling the preview raise, as a deleted C++ object does, and run the read of a zip
    * verify nothing is raised
    """
    shown = Shown(qtbot, library)
    mocker.patch.object(shown.preview, "archive_ready").emit.side_effect = RuntimeError
    read_archive = shown.preview._RootsPreview__read_archive  # type: ignore[attr-defined]  # pylint: disable=protected-access

    read_archive(1, library / "stored.zip", (".jpg",))
