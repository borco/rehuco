"""Tests for CuratingImageLightbox: the visibility line and the curating keys of the viewer the
screenshots editor opens (#370)."""

from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QWidget
from pytest import fixture, mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.curating_image_lightbox import CuratingImageLightbox
from rehuco_agent.fields.widgets.image_lightbox import (
    HOVER_INFO_NAME,
    INFO_OVERLAY_NAME,
    ImageInfoOverlay,
    ImageViewerMode,
)
from rehuco_agent.fields.widgets.image_selector import MoveDirection
from rehuco_agent.fields.widgets.image_source import ImageVisibility, PathImageSource, ScreenshotRowsImageSource
from rehuco_agent.fields.widgets.thumbnail_row import ThumbnailRow

VISIBLE: Final = Path("/fake/info00.png")
HIDDEN: Final = Path("/fake/info01.png")
UNCONVERTED: Final = Path("/fake/cover.png")
ROWS: Final = [
    (VISIBLE, ImageVisibility.VISIBLE),
    (HIDDEN, ImageVisibility.HIDDEN),
    (UNCONVERTED, ImageVisibility.UNCONVERTED),
]
"""One row of each kind, in the order the editor lists them: numbered first, then un-converted."""


# region fixtures


@fixture(autouse=True)
def loadable_image(mocker: MockerFixture) -> None:
    """Make every screenshot decode as a real image, with no file on disk -- at the file source's seam,
    which the rows source reads through.

    :param mocker: pytest-mock fixture.
    """
    mocker.patch.object(PathImageSource, "load", return_value=QImage(320, 180, QImage.Format.Format_RGB32))


def curating(qtbot: QtBot, document: QWidget, current: int, *, info_visible: bool = True) -> CuratingImageLightbox:
    """Reveal a curating viewer over :data:`ROWS`, on ``current``.

    :param qtbot: pytest-qt fixture, which takes ownership of the viewer.
    :param document: the document stand-in to cover.
    :param current: the row to open on.
    :param info_visible: whether the info box starts shown.
    :returns: the revealed viewer.
    """
    source = ScreenshotRowsImageSource(ROWS)
    lightbox = CuratingImageLightbox(
        source, current, ImageViewerMode.DOCUMENT_OVERLAY, document, info_visible=info_visible, strip_visible=True
    )
    qtbot.addWidget(lightbox)
    lightbox.reveal()
    return lightbox


def overlay(lightbox: CuratingImageLightbox, name: str) -> ImageInfoOverlay:
    """One of the viewer's two info boxes.

    :param lightbox: the viewer under test.
    :param name: the box's object name.
    :returns: the box.
    """
    box = lightbox.findChild(ImageInfoOverlay, name)
    assert isinstance(box, ImageInfoOverlay)
    return box


def recorded(lightbox: CuratingImageLightbox) -> list[tuple[str, ...]]:
    """Every request the viewer sends, as ``(signal, *arguments)`` tuples in the order sent.

    :param lightbox: the viewer under test.
    :returns: the list the requests land in.
    """
    requests: list[tuple[str, ...]] = []
    lightbox.delete_requested.connect(lambda path: requests.append(("delete", path)))
    lightbox.visibility_toggle_requested.connect(lambda path: requests.append(("toggle", path)))
    lightbox.convert_requested.connect(lambda path: requests.append(("convert", path)))
    lightbox.move_requested.connect(lambda path, direction: requests.append(("move", path, direction)))
    return requests


# endregion


@mark.parametrize(("current", "word"), [(0, "visible"), (1, "hidden"), (2, "unconverted")])
def test_the_info_box_names_where_the_image_stands(document: QWidget, qtbot: QtBot, current: int, word: str) -> None:
    """A bold last line says whether the image is shown, hidden or not yet numbered.

    **Test steps:**

    * reveal a curating viewer, info shown, on each kind of row
    * verify the info box still starts with the path and ends with that word in bold
    """
    lightbox = curating(qtbot, document, current)

    info = overlay(lightbox, INFO_OVERLAY_NAME)
    assert info.textFormat() == Qt.TextFormat.RichText
    assert info.text().startswith(str(ROWS[current][0]))
    assert info.text().endswith(f"<br><b>{word}</b>")


def test_the_hover_box_names_where_the_hovered_thumbnail_stands(document: QWidget, qtbot: QtBot) -> None:
    """The thumbnail hover box carries the same line, for the thumbnail rather than the current image.

    **Test steps:**

    * reveal a curating viewer on the visible image, with its row shown
    * hover the unconverted image's thumbnail and verify the hover box ends with **unconverted**
    """
    lightbox = curating(qtbot, document, 0)
    row = lightbox.findChild(ThumbnailRow)
    assert isinstance(row, ThumbnailRow)

    row.hovered_index.emit(2)

    assert overlay(lightbox, HOVER_INFO_NAME).text().endswith("<br><b>unconverted</b>")


def test_a_source_without_visibility_shows_no_line(document: QWidget, qtbot: QtBot) -> None:
    """The line comes from the source: one that says nothing about curation gets the plain box.

    **Test steps:**

    * reveal a curating viewer over a plain path source
    * verify the info box is plain text with no bold line
    """
    source = PathImageSource([VISIBLE, HIDDEN])
    lightbox = CuratingImageLightbox(
        source,  # type: ignore[arg-type]
        0,
        ImageViewerMode.DOCUMENT_OVERLAY,
        document,
        info_visible=True,
    )
    qtbot.addWidget(lightbox)
    lightbox.reveal()

    info = overlay(lightbox, INFO_OVERLAY_NAME)
    assert info.textFormat() == Qt.TextFormat.PlainText
    assert info.text().startswith(str(VISIBLE))


def test_del_and_space_send_their_requests_for_the_current_image(document: QWidget, qtbot: QtBot) -> None:
    """Each key sends one request carrying the image's path, and does nothing to the viewer itself.

    **Test steps:**

    * reveal a curating viewer on the hidden image
    * press Space, then Del
    * verify the two requests, and that the viewer is still up on the same image
    """
    lightbox = curating(qtbot, document, 1)
    requests = recorded(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_Space)
    qtbot.keyClick(lightbox, Qt.Key.Key_Delete)

    assert requests == [("toggle", HIDDEN), ("delete", HIDDEN)]
    assert lightbox.isVisible()
    assert lightbox.current_index == 1


@mark.parametrize(
    ("key", "direction"),
    [
        (Qt.Key.Key_Home, MoveDirection.TOP),
        (Qt.Key.Key_Up, MoveDirection.UP),
        (Qt.Key.Key_Down, MoveDirection.DOWN),
        (Qt.Key.Key_End, MoveDirection.BOTTOM),
    ],
)
def test_the_ctrl_moves_send_a_move_request(
    document: QWidget, qtbot: QtBot, key: Qt.Key, direction: MoveDirection
) -> None:
    """Ctrl with Home / Up / Down / End asks to move the image, rather than navigating as bare Home and
    End do.

    **Test steps:**

    * reveal a curating viewer on the hidden image
    * press the Ctrl-modified key
    * verify one move request with its direction, and that the viewer did not navigate
    """
    lightbox = curating(qtbot, document, 1)
    requests = recorded(lightbox)

    qtbot.keyClick(lightbox, key, Qt.KeyboardModifier.ControlModifier)

    assert requests == [("move", HIDDEN, direction.value)]
    assert lightbox.current_index == 1


def test_an_unconverted_image_takes_c_and_del_only(document: QWidget, qtbot: QtBot) -> None:
    """Converting it or deleting it is all there is to do with an image that holds no slot.

    **Test steps:**

    * reveal a curating viewer on the unconverted image
    * press Space, Ctrl+Up, C and Del
    * verify only the convert and delete requests were sent
    """
    lightbox = curating(qtbot, document, 2)
    requests = recorded(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_Space)
    qtbot.keyClick(lightbox, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
    qtbot.keyClick(lightbox, Qt.Key.Key_C)
    qtbot.keyClick(lightbox, Qt.Key.Key_Delete)

    assert requests == [("convert", UNCONVERTED), ("delete", UNCONVERTED)]


def test_c_on_a_numbered_image_sends_nothing(document: QWidget, qtbot: QtBot) -> None:
    """There is nothing to convert on an image already in the set.

    **Test steps:**

    * reveal a curating viewer on the visible image and press C
    * verify no request was sent
    """
    lightbox = curating(qtbot, document, 0)
    requests = recorded(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_C)

    assert not requests


def test_every_other_key_is_still_the_viewers_own(document: QWidget, qtbot: QtBot) -> None:
    """Arrows, bare Home / End, I, T and Esc behave as they do in the read-only viewer.

    **Test steps:**

    * reveal a curating viewer on the first image, info and thumbnails shown
    * press Right, End, Home, I and T and verify each navigates or toggles
    * press Esc and verify the viewer closed, having sent no request
    """
    lightbox = curating(qtbot, document, 0)
    requests = recorded(lightbox)

    qtbot.keyClick(lightbox, Qt.Key.Key_Right)
    assert lightbox.current_index == 1
    qtbot.keyClick(lightbox, Qt.Key.Key_End)
    assert lightbox.current_index == 2
    qtbot.keyClick(lightbox, Qt.Key.Key_Home)
    assert lightbox.current_index == 0
    qtbot.keyClick(lightbox, Qt.Key.Key_I)
    assert not lightbox.info_visible
    qtbot.keyClick(lightbox, Qt.Key.Key_T)
    assert not lightbox.strip_visible

    with qtbot.waitSignal(lightbox.closed):
        qtbot.keyClick(lightbox, Qt.Key.Key_Escape)

    assert not requests


def test_a_re_pointed_viewer_follows_the_line_as_the_row_changes(document: QWidget, qtbot: QtBot) -> None:
    """The owner re-points the viewer after every request; the line then says the row's new state.

    **Test steps:**

    * reveal a curating viewer on the visible image
    * re-point it at rows where that image is hidden
    * verify it stayed on the image and its line now reads **hidden**
    """
    lightbox = curating(qtbot, document, 0)

    lightbox.set_source(ScreenshotRowsImageSource([(VISIBLE, ImageVisibility.HIDDEN), *ROWS[1:]]))

    assert lightbox.current_index == 0
    assert overlay(lightbox, INFO_OVERLAY_NAME).text().endswith("<b>hidden</b>")
