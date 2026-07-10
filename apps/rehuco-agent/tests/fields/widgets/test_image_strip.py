"""Tests for ImageStrip: the fixed-height horizontal thumbnail row."""

from pathlib import Path

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QWidget
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_strip import ImageStrip

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png")]


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
