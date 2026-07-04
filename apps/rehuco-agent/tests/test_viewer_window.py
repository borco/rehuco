"""Tests for the generic .rehu viewer/editor window."""

import json
from pathlib import Path
from typing import Any, Final

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.viewer_window import ViewerWindow

FAKE_PATH: Final = Path("/fake/tutorials/sculpting/info.rehu")

# resembles rehuco-core's test_document.py fixture by design (same §17.7 shape); this tests a
# different layer (GUI rendering, not the document model) so sharing one constant across packages
# would be an inappropriate cross-package test dependency
# pylint: disable=duplicate-code
TUTORIAL: Final = {
    "format_version": 1,
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "Tutorial",
    "created": "2026-01-15T09:30:00Z",
    "updated": "2026-06-20T14:12:00Z",
    "sources": [
        {
            "title": "Intro to Sculpting",
            "publisher": "Example Publisher",
            "url": "https://example.com/x",
            "primary": True,
        }
    ],
    "authors": ["First Author", "Second Author"],
    "released": "2025-03",
    "description": "# Intro\n\nBody text.",
    "advertised_tags": ["sculpting", "3d"],
    "extra_tags": ["rework"],
    "tutorial": {"format_version": 0, "rating": 4, "complete": True},
}
# pylint: enable=duplicate-code


def open_window(
    mocker: MockerFixture,
    qtbot: QtBot,
    data: dict[str, Any] | None = None,
    image_paths: list[Path] | None = None,
) -> ViewerWindow:
    """Mock the filesystem and open a :class:`ViewerWindow` on a fixture document.

    :param mocker: pytest-mock fixture.
    :param qtbot: pytest-qt bot, registering the window for teardown.
    :param data: document JSON; defaults to :data:`TUTORIAL`.
    :param image_paths: sibling image paths ``Path.glob`` should report; defaults to none.
    :returns: the constructed, populated window.
    """
    mocker.patch.object(Path, "read_text", return_value=json.dumps(data if data is not None else TUTORIAL))
    mocker.patch.object(Path, "glob", return_value=image_paths or [])
    window = ViewerWindow(FAKE_PATH)
    qtbot.addWidget(window)
    return window


def test_populate_renders_common_fields(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Loading a document renders its common-core fields into the form widgets.

    **Test steps:**

    * mock the filesystem to serve the Tutorial fixture
    * open a :class:`ViewerWindow`
    * verify the title/publisher/url/authors/released/tags widgets hold the expected text
    * verify the window title reflects the document's title
    """
    window = open_window(mocker, qtbot)
    assert window.ui.titleLineEdit.text() == "Intro to Sculpting"
    assert window.ui.publisherLabel.text() == "Example Publisher"
    assert window.ui.urlLabel.text() == "https://example.com/x"
    assert window.ui.authorsLabel.text() == "First Author, Second Author"
    assert window.ui.releasedLabel.text() == "2025-03"
    assert window.ui.tagsLabel.text() == "sculpting, 3d"
    assert window.ui.extraTagsLabel.text() == "rework"
    assert window.windowTitle() == "Intro to Sculpting"


def test_populate_renders_markdown_description(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The Markdown description renders as rich text in the description browser.

    **Test steps:**

    * open a window on a document with a Markdown heading in its description
    * verify the browser's plain text contains the heading text but not the ``#`` marker
      (proving Markdown was parsed, not shown literally)
    """
    window = open_window(mocker, qtbot)
    text = window.ui.descriptionBrowser.toPlainText()
    assert "Intro" in text
    assert "#" not in text


def test_edit_title_and_save_writes_atomically(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Editing the title and clicking Save writes it back via the atomic-save path.

    **Test steps:**

    * open a window on the Tutorial fixture
    * mock ``atomic_write_text`` to capture the written JSON
    * clear and retype the title field, then click Save
    * verify the captured JSON has the new title and the untouched plugin block intact
    """
    window = open_window(mocker, qtbot)
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")

    window.ui.titleLineEdit.selectAll()
    qtbot.keyClicks(window.ui.titleLineEdit, "Renamed Title")
    qtbot.mouseClick(window.ui.saveButton, Qt.MouseButton.LeftButton)

    saved = json.loads(mock_write.call_args[0][1])
    assert saved["sources"][0]["title"] == "Renamed Title"
    assert saved["tutorial"] == {"format_version": 0, "rating": 4, "complete": True}


def test_ctrl_s_action_saves(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The ``Ctrl+S``-bound action triggers the same save path as the button.

    **Test steps:**

    * open a window, mock ``atomic_write_text``
    * trigger the save action directly (equivalent to the ``Ctrl+S`` shortcut firing)
    * verify a write happened
    """
    window = open_window(mocker, qtbot)
    mock_write = mocker.patch("rehuco_core.rehu_document.atomic_write_text")
    window.ui.actionSave.trigger()
    mock_write.assert_called_once()


def test_image_strip_populates_recognized_sibling_images(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Sibling ``infoXX.*`` images with recognized extensions become strip thumbnails.

    **Test steps:**

    * mock ``Path.glob`` to report two ``.jpg``/``.png`` sibling paths
    * mock ``QPixmap`` construction to return a real, non-null pixmap without touching disk
      (``QLabel.setPixmap`` is a real C++ binding that rejects a duck-typed mock, so the
      stand-in must be an actual ``QPixmap`` -- just not one decoded from a real file)
    * open a window
    * verify the image-strip layout holds one thumbnail per image plus the trailing stretch
    """
    mocker.patch("rehuco_agent.viewer_window.QPixmap", return_value=QPixmap(4, 4))

    images = [FAKE_PATH.parent / "info01.jpg", FAKE_PATH.parent / "info02.png"]
    window = open_window(mocker, qtbot, image_paths=images)

    assert window.ui.imageStripLayout.count() == 3  # two thumbnails + one trailing stretch


def test_image_strip_skips_null_pixmaps(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A sibling image that fails to decode (null pixmap) is skipped, not added as a blank thumbnail.

    **Test steps:**

    * mock ``QPixmap`` so construction reports a null pixmap
    * open a window with one matching sibling path
    * verify only the trailing stretch item is present -- no thumbnail was added
    """
    fake_pixmap = mocker.MagicMock()
    fake_pixmap.isNull.return_value = True
    mocker.patch("rehuco_agent.viewer_window.QPixmap", return_value=fake_pixmap)

    images = [FAKE_PATH.parent / "info01.jpg"]
    window = open_window(mocker, qtbot, image_paths=images)

    assert window.ui.imageStripLayout.count() == 1


def test_image_strip_skips_unrecognized_extensions(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A sibling matching the ``infoXX.*`` glob but with an unrecognized suffix is skipped.

    **Test steps:**

    * report a sibling path with a ``.sfv`` suffix (a checksum manifest, not an image)
    * open a window
    * verify no ``QPixmap`` was constructed and only the trailing stretch item is present
    """
    pixmap_cls = mocker.patch("rehuco_agent.viewer_window.QPixmap")
    images = [FAKE_PATH.parent / "info01.sfv"]
    window = open_window(mocker, qtbot, image_paths=images)

    pixmap_cls.assert_not_called()
    assert window.ui.imageStripLayout.count() == 1
