"""Tests for a maximized view through a document's real first read ([[plugins#session-restore]], #576): a real record
under ``tmp_path``, restored as a session restores it, with the sets arriving as they do. What the first read does on
its way -- the form rebuilt, the curated set changing, the type's docks built last -- is what these are about.
"""

# the document's parts are reached through their name-mangled members, as the other document tests do
# pylint: disable=protected-access

from pathlib import Path
from typing import Final

from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_widget import DocumentWidget
from rehuco_agent.documents.documents_dock import DocumentsDock
from rehuco_agent.fields.widgets.image_lightbox import ImageLightbox
from rehuco_agent.fields.widgets.overlay_surface import OverlayMode
from rehuco_agent.settings.document_session_settings import DocumentSessionSettings
from rehuco_agent.settings.maximized_view import CURATED_SET, LIGHTBOX_KIND, PLAYER_KIND, MaximizedView

from .player_view_support import fixture_media  # noqa: F401  # pylint: disable=unused-import
from .test_document_widget import loadable_lightbox_image
from .test_rehu_document_model_progress import write_tutorial

pytestmark = mark.usefixtures("real_path_stat", "real_sub_docks")

TIMEOUT: Final = 5000
SURFACE: Final = OverlayMode.DOCUMENT_OVERLAY.value


def restored_document(qtbot: QtBot, record: Path, view: MaximizedView) -> DocumentWidget:
    """Restore a session of one focused document with a maximized view, on a shown area, and wait for its first read.

    :param qtbot: pytest-qt fixture.
    :param record: the document.
    :param view: its view.
    :returns: the document's widget, read.
    """
    area = DocumentsDock()
    qtbot.addWidget(area)
    area.resize(1000, 700)
    session = DocumentSessionSettings()
    session.items[record] = DocumentSessionSettings.Item(open=True, maximized=view)
    session.focused_path = record
    area.restore_session(session)
    area.show()
    widget = area.open_document_widgets()[0]
    qtbot.waitUntil(lambda: not widget.model.pending and widget.model.reading is None, timeout=TIMEOUT)
    return widget


def test_a_maximized_player_comes_back_through_the_first_read(qtbot: QtBot, tmp_path: Path) -> None:
    """The player is only built late in the first read, after the curated set has already changed on its way.

    **Test steps:**

    * restore a tutorial with a maximized player on one of its videos, and let it be read
    * verify the player is on that video, maximized over the surface
    """
    record = write_tutorial(tmp_path / "t", ("a.mp4", "b.mp4"))

    widget = restored_document(qtbot, record, MaximizedView(PLAYER_KIND, "b.mp4", SURFACE))

    player = widget.sub_docks._DocumentSubDocks__player_view  # type: ignore[attr-defined]
    assert player is not None
    qtbot.waitUntil(lambda: player.maximized_mode is OverlayMode.DOCUMENT_OVERLAY, timeout=TIMEOUT)
    assert player.current_key == "b.mp4"


def test_a_curated_lightbox_comes_back_through_the_first_read(
    qtbot: QtBot, tmp_path: Path, mocker: MockerFixture
) -> None:
    """The curated set the first read gives is what the view opens against.

    **Test steps:**

    * restore a tutorial with screenshots beside it and a lightbox on the second, and let it be read
    * verify the lightbox opened on that one
    """
    loadable_lightbox_image(mocker)
    record = write_tutorial(tmp_path / "t", ("a.mp4",))
    for name in ("info00.jpg", "info01.jpg"):
        (record.parent / name).write_bytes(b"x")

    widget = restored_document(
        qtbot, record, MaximizedView(LIGHTBOX_KIND, "info01.jpg", SURFACE, CURATED_SET, False, False)
    )

    qtbot.waitUntil(lambda: widget.findChild(ImageLightbox) is not None, timeout=TIMEOUT)
    viewer = widget.findChild(ImageLightbox)
    assert isinstance(viewer, ImageLightbox)
    assert viewer.current_index == 1
