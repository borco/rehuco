"""Tests for ImageStrip: the fixed-height horizontal thumbnail row."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_strip import ImageStrip

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png")]


def fake_scanner(mocker: MockerFixture, files: list[Path]) -> object:
    """A minimal ``ImageScanner`` stand-in returning a fixed file list.

    :param mocker: pytest-mock fixture.
    :param files: the fixed file list ``.files()`` reports.
    :returns: the stand-in scanner.
    """
    return mocker.Mock(files=mocker.Mock(return_value=files))


def strip_layout(strip: ImageStrip) -> QHBoxLayout:
    """The strip's inner thumbnail row layout.

    :param strip: the strip under test.
    :returns: the ``QHBoxLayout`` holding the thumbnail labels.
    """
    content = strip.widget()
    assert isinstance(content, QWidget)
    layout = content.layout()
    assert isinstance(layout, QHBoxLayout)
    return layout


def thumbnail_at(strip: ImageStrip, index: int) -> QWidget:
    """The thumbnail widget at ``index`` in the strip's row.

    :param strip: the strip under test.
    :param index: the thumbnail's position in the row.
    :returns: that thumbnail widget.
    """
    item = strip_layout(strip).itemAt(index)
    assert item is not None
    widget = item.widget()
    assert widget is not None
    return widget


def test_strip_is_fixed_to_its_height(qtbot: QtBot) -> None:
    """The strip is pinned to the height it is built with, never growing vertically.

    **Test steps:**

    * build a strip with an explicit height
    * verify its fixed min/max height both equal it
    """
    strip = ImageStrip(height=150)
    qtbot.addWidget(strip)

    assert strip.minimumHeight() == 150
    assert strip.maximumHeight() == 150


def test_set_images_adds_one_thumbnail_per_loadable_image(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Each loadable image becomes one thumbnail label in the row.

    **Test steps:**

    * make ``QPixmap`` construction yield a non-null pixmap (no real files on disk)
    * set two images
    * verify two thumbnails are laid out
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)

    strip.set_images(PATHS)

    assert strip_layout(strip).count() == 2


def test_set_images_skips_unloadable_images(mocker: MockerFixture, qtbot: QtBot) -> None:
    """An image that fails to load (null pixmap) contributes no thumbnail.

    **Test steps:**

    * make ``QPixmap`` construction yield a null pixmap
    * set two images
    * verify no thumbnails are laid out
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap())
    strip = ImageStrip()
    qtbot.addWidget(strip)

    strip.set_images(PATHS)

    assert strip_layout(strip).count() == 0


def test_set_images_replaces_the_previous_thumbnails(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A second ``set_images`` clears the earlier thumbnails rather than appending.

    **Test steps:**

    * seed two images, then re-seed with one
    * verify only the latest thumbnail remains
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)

    strip.set_images(PATHS)
    strip.set_images(PATHS[:1])

    assert strip_layout(strip).count() == 1


def test_set_hidden_filters_and_paints_the_visible_files(mocker: MockerFixture, qtbot: QtBot) -> None:
    """``set_hidden`` shows every current-scanner file except the hidden ones.

    **Test steps:**

    * attach a scanner reporting two files
    * set one of them hidden
    * verify only the other one is painted
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.image_scanner = fake_scanner(mocker, PATHS)  # type: ignore[assignment]

    strip.set_hidden(["info00.jpg"])

    assert strip_layout(strip).count() == 1


def test_assigning_a_new_scanner_rebuilds_keeping_the_hidden_list(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Assigning a new ``image_scanner`` rebuilds from its files, keeping the previously-set hidden list.

    **Test steps:**

    * seed the strip with a scanner and a hidden filename
    * assign a new scanner reporting a different, smaller file set that doesn't include that filename
    * verify the rebuild shows every one of the new scanner's files (the hidden filename no longer applies)
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.image_scanner = fake_scanner(mocker, PATHS)  # type: ignore[assignment]
    strip.set_hidden(["info00.jpg"])
    assert strip_layout(strip).count() == 1

    strip.image_scanner = fake_scanner(mocker, PATHS[:1])  # type: ignore[assignment]

    assert strip_layout(strip).count() == 0


def test_no_scanner_shows_nothing(qtbot: QtBot) -> None:
    """``set_hidden`` with no scanner attached shows nothing, rather than raising.

    **Test steps:**

    * call ``set_hidden`` on a strip with no scanner assigned (the default)
    * verify the row stays empty
    """
    strip = ImageStrip()
    qtbot.addWidget(strip)

    strip.set_hidden([])

    assert strip_layout(strip).count() == 0


def test_clicking_a_thumbnail_reports_its_screenshot(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Left-clicking a thumbnail emits ``image_activated`` with that thumbnail's own path (#160).

    **Test steps:**

    * paint two thumbnails and click the second
    * verify the strip reported the second path, not the first
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.set_images(PATHS)
    activated: list[Path] = []
    strip.image_activated.connect(activated.append)

    thumbnail = thumbnail_at(strip, 1)
    qtbot.mouseClick(thumbnail, Qt.MouseButton.LeftButton)

    assert activated == [PATHS[1]]


def test_a_rebuilt_thumbnail_still_reports_its_screenshot(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Thumbnails painted by a later rebuild are wired up too, not just the first set.

    Regression: the thumbnails are rebuilt from scratch on every curation edit and scanner swap, so a
    click affordance wired only at construction would go dead after the first one.

    **Test steps:**

    * paint two thumbnails, then re-paint with only the second
    * click the surviving thumbnail and verify it still reports its path
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.set_images(PATHS)
    strip.set_images(PATHS[1:])
    activated: list[Path] = []
    strip.image_activated.connect(activated.append)

    thumbnail = thumbnail_at(strip, 0)
    qtbot.mouseClick(thumbnail, Qt.MouseButton.LeftButton)

    assert activated == [PATHS[1]]


def test_a_right_click_activates_nothing(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Only a left-click opens a screenshot; other buttons are left alone.

    **Test steps:**

    * paint one thumbnail and right-click it
    * verify nothing was reported
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.set_images(PATHS[:1])
    activated: list[Path] = []
    strip.image_activated.connect(activated.append)

    thumbnail = thumbnail_at(strip, 0)
    qtbot.mouseClick(thumbnail, Qt.MouseButton.RightButton)

    assert not activated


def test_clearing_the_strip_skips_non_widget_layout_items(qtbot: QtBot) -> None:
    """Clearing tolerates a stray non-widget layout item (e.g. a spacer), leaving the row empty.

    **Test steps:**

    * seed the row with a bare spacer item (no widget)
    * call ``set_images([])`` and verify the row ends up empty
    """
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip_layout(strip).addStretch()
    assert strip_layout(strip).count() == 1

    strip.set_images([])

    assert strip_layout(strip).count() == 0
