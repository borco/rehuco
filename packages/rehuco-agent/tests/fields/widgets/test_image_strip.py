"""Tests for ImageStrip: the fixed-height horizontal thumbnail row."""

from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_strip import (
    CURRENT_THUMBNAIL_STYLE,
    THUMBNAIL_BORDER,
    THUMBNAIL_STYLE,
    ImageStrip,
    ThumbnailLabel,
)

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png")]
WIDE_PIXMAP = 400
"""Source size for a thumbnail whose scaled height is worth asserting on -- big enough that the
strip scales it down rather than leaving it at its own size."""


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


@fixture
def hosted_strip(qtbot: QtBot) -> Iterator[ImageStrip]:
    """A shown strip inside a host widget, the way a form actually holds one.

    The show/hide rule only applies once a strip has a parent -- showing a parentless widget would
    flash it as a bare top-level window of its own -- so a test asserting on that rule needs a real
    host rather than a free-floating strip.

    A generator fixture, not a plain one: the host is a local, and yielding from inside the fixture is
    what keeps it alive for the test -- pytest-qt tracks registered widgets weakly, so returning only
    its descendant would let Python collect the host, taking the strip's own content down with it.

    :param qtbot: pytest-qt fixture.
    :returns: the strip, parented and shown.
    """
    host = QWidget()
    layout = QVBoxLayout(host)
    strip = ImageStrip()
    layout.addWidget(strip)
    qtbot.addWidget(host)
    host.show()
    yield strip


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


def test_set_images_reports_what_it_painted(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A rebuild reports the screenshots now on the row, for a viewer following the same set (#161).

    **Test steps:**

    * connect to ``images_changed`` and set two images
    * verify the reported set is exactly those two
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    reported: list[list[Path]] = []
    strip.images_changed.connect(reported.append)

    strip.set_images(PATHS)

    assert reported == [PATHS]


def test_the_reported_set_leaves_out_what_would_not_load(mocker: MockerFixture, qtbot: QtBot) -> None:
    """An image that paints no thumbnail is not reported either, so the set is what a user can click.

    **Test steps:**

    * make ``QPixmap`` construction yield a null pixmap and set two images
    * verify the reported set is empty
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap())
    strip = ImageStrip()
    qtbot.addWidget(strip)
    reported: list[list[Path]] = []
    strip.images_changed.connect(reported.append)

    strip.set_images(PATHS)

    assert reported == [[]]


def test_set_current_frames_only_that_thumbnail(mocker: MockerFixture, qtbot: QtBot) -> None:
    """The current screenshot's thumbnail is framed and no other one is (#161).

    **Test steps:**

    * paint two thumbnails and mark the second as current
    * verify only it carries the current frame
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.set_images(PATHS)

    strip.set_current(PATHS[1])

    assert thumbnail_at(strip, 0).styleSheet() == THUMBNAIL_STYLE
    assert thumbnail_at(strip, 1).styleSheet() == CURRENT_THUMBNAIL_STYLE


def test_set_current_survives_a_rebuild(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A rebuild re-marks the same screenshot rather than losing the mark (#161).

    Regression: the thumbnails are rebuilt from scratch on every curation edit and scanner swap, so a
    mark applied only to the labels present at the time would vanish on the next one.

    **Test steps:**

    * mark the second of two screenshots as current, then re-paint the same set
    * verify the freshly-built thumbnail for it is the framed one
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.set_images(PATHS)
    strip.set_current(PATHS[1])

    strip.set_images(PATHS)

    assert thumbnail_at(strip, 1).styleSheet() == CURRENT_THUMBNAIL_STYLE


def test_set_current_leaves_the_row_unmarked_for_a_screenshot_it_does_not_show(
    mocker: MockerFixture, qtbot: QtBot
) -> None:
    """Marking a screenshot the row does not carry frames nothing, rather than raising.

    **Test steps:**

    * paint one thumbnail and mark a different screenshot as current
    * verify the painted thumbnail is left plain
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)
    strip.set_images(PATHS[:1])

    strip.set_current(Path("/fake/gone.png"))

    assert thumbnail_at(strip, 0).styleSheet() == THUMBNAIL_STYLE


def test_a_thumbnail_starts_unframed(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A freshly-painted thumbnail carries the plain frame, so the row starts unmarked.

    The frame is always reserved, transparent when not current, so marking one cannot shift the row.

    **Test steps:**

    * paint one thumbnail without marking anything current
    * verify it is a `ThumbnailLabel` carrying the plain style
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)

    strip.set_images(PATHS[:1])

    thumbnail = thumbnail_at(strip, 0)
    assert isinstance(thumbnail, ThumbnailLabel)
    assert thumbnail.styleSheet() == THUMBNAIL_STYLE


def test_a_strip_with_nothing_to_show_hides_itself(mocker: MockerFixture, hosted_strip: ImageStrip) -> None:
    """A resource with no screenshots leaves no empty band where a row would be (#161).

    **Test steps:**

    * paint a thumbnail, then re-paint with nothing
    * verify the strip showed itself and then hid itself
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = hosted_strip

    strip.set_images(PATHS[:1])
    assert not strip.isHidden()

    strip.set_images([])

    assert strip.isHidden()


def test_curating_every_screenshot_away_hides_the_strip(mocker: MockerFixture, hosted_strip: ImageStrip) -> None:
    """Hiding every screenshot empties the strip, which then hides itself too (#161).

    **Test steps:**

    * attach a scanner reporting two files and paint them
    * hide both through ``set_hidden``
    * verify the strip is hidden
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = hosted_strip
    strip.image_scanner = fake_scanner(mocker, PATHS)  # type: ignore[assignment]
    assert not strip.isHidden()

    strip.set_hidden([path.name for path in PATHS])

    assert strip.isHidden()


def test_an_owner_can_hide_a_populated_strip(mocker: MockerFixture, hosted_strip: ImageStrip) -> None:
    """The owner's intent hides a strip that does have thumbnails, and shows it again (#161).

    **Test steps:**

    * paint two thumbnails, then have the owner ask for the strip hidden and shown again
    * verify the strip followed each time
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = hosted_strip
    strip.set_images(PATHS)

    strip.set_requested_visible(False)
    assert strip.isHidden()

    strip.set_requested_visible(True)
    assert not strip.isHidden()


def test_an_owner_asking_for_a_strip_cannot_show_an_empty_one(mocker: MockerFixture, hosted_strip: ImageStrip) -> None:
    """Nothing to show beats the owner's intent, so an empty strip stays hidden either way (#161).

    Regression: a rebuild re-applies the owner's intent, which would otherwise re-show a strip that
    had just lost its last thumbnail.

    **Test steps:**

    * ask for the strip shown while it has no thumbnails
    * paint one, then take it away again
    * verify it is only ever on screen while it has something on it
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = hosted_strip

    strip.set_requested_visible(True)
    assert strip.isHidden()

    strip.set_images(PATHS[:1])
    assert not strip.isHidden()

    strip.set_images([])
    assert strip.isHidden()


def test_neither_scrollbar_is_ever_painted(qtbot: QtBot) -> None:
    """The strip shows no scrollbar at all -- overflow is reached by wheel/drag (#161).

    A bar would eat into a row whose height is fixed, and sit on the maximized viewer's backdrop.

    **Test steps:**

    * build a strip
    * verify both scrollbar policies suppress the bar outright
    """
    strip = ImageStrip()
    qtbot.addWidget(strip)

    assert strip.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert strip.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_a_thumbnail_fills_the_strip_height_less_its_frame(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A thumbnail takes the strip's whole height apart from the frame drawn around it (#161).

    Regression: reserving room for a scrollbar that is never painted left a permanently empty band
    under every thumbnail.

    **Test steps:**

    * paint one thumbnail in a strip of a known height
    * verify its pixmap is that height less the frame on both sides
    """
    mocker.patch(
        "rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(WIDE_PIXMAP, WIDE_PIXMAP)
    )
    strip = ImageStrip(height=100)
    qtbot.addWidget(strip)

    strip.set_images(PATHS[:1])

    thumbnail = thumbnail_at(strip, 0)
    assert isinstance(thumbnail, ThumbnailLabel)
    assert thumbnail.pixmap().height() == 100 - 2 * THUMBNAIL_BORDER


def test_a_parentless_strip_never_shows_itself(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A strip with no parent yet stays put, however many images it is given (#161).

    Regression: showing a parentless widget makes it a bare top-level window of its own -- app icon,
    title bar, min/max/close and all -- and a field builds and seeds its strip *before* the form adds
    it to a layout, so opening or reloading a document flashed one on screen every time.

    **Test steps:**

    * seed a strip that has not been given a parent yet
    * verify it never showed itself, and is still a window rather than a child
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    qtbot.addWidget(strip)

    strip.set_images(PATHS)

    assert strip.isWindow()
    assert not strip.isVisible()


def test_a_strip_applies_the_rule_once_it_is_given_a_parent(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A strip seeded with images before it had a parent is shown once a form adds it to one (#161).

    It is shown by *Qt*, not by the strip: a widget carrying no explicit hide comes up with the parent
    it is given, which is why the strip deliberately leaves that half alone rather than showing itself
    while parentless. Qt does that on the next event-loop turn, hence the wait.

    **Test steps:**

    * seed a parentless strip with images, then add it to a shown host's layout
    * verify it comes up with its new parent
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    strip.set_images(PATHS)
    host = QWidget()
    layout = QVBoxLayout(host)
    qtbot.addWidget(host)
    host.show()

    layout.addWidget(strip)

    qtbot.waitUntil(lambda: not strip.isHidden())


def test_an_empty_strip_added_to_a_layout_stays_hidden(mocker: MockerFixture, qtbot: QtBot) -> None:
    """A strip that was seeded empty is hidden as soon as it has a parent, not shown and then hidden.

    **Test steps:**

    * seed a parentless strip with nothing, then add it to a shown host's layout
    * verify it is hidden
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    strip = ImageStrip()
    strip.set_images([])
    host = QWidget()
    layout = QVBoxLayout(host)
    qtbot.addWidget(host)
    host.show()

    layout.addWidget(strip)

    assert strip.isHidden()


def test_set_height_rescales_the_thumbnails(mocker: MockerFixture, hosted_strip: ImageStrip) -> None:
    """Resizing the strip rescales the thumbnails already in it (#161).

    **Test steps:**

    * paint a thumbnail, then set a new strip height
    * verify the strip and its thumbnail both took the new size
    """
    mocker.patch(
        "rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(WIDE_PIXMAP, WIDE_PIXMAP)
    )
    hosted_strip.set_images(PATHS[:1])

    hosted_strip.set_height(80)

    assert hosted_strip.maximumHeight() == 80
    thumbnail = thumbnail_at(hosted_strip, 0)
    assert isinstance(thumbnail, ThumbnailLabel)
    assert thumbnail.pixmap().height() == 80 - 2 * THUMBNAIL_BORDER


def test_set_height_to_the_current_height_rebuilds_nothing(mocker: MockerFixture, hosted_strip: ImageStrip) -> None:
    """Re-applying the height the strip already has leaves its thumbnails exactly as they were.

    **Test steps:**

    * paint a thumbnail, then set the height it already has
    * verify the very same thumbnail widget is still in the row
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    hosted_strip.set_images(PATHS[:1])
    before = thumbnail_at(hosted_strip, 0)

    hosted_strip.set_height(hosted_strip.maximumHeight())

    assert thumbnail_at(hosted_strip, 0) is before


def test_the_strip_draws_no_frame_of_its_own(hosted_strip: ImageStrip) -> None:
    """The strip paints nothing but its thumbnails -- no border, no inset (#161).

    **Test steps:**

    * build a strip
    * verify it carries no frame and no margins of its own
    """
    assert hosted_strip.frameShape() == QFrame.Shape.NoFrame
    assert hosted_strip.frameWidth() == 0
    assert hosted_strip.viewportMargins() == QMargins(0, 0, 0, 0)
