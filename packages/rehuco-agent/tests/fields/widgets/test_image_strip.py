"""Tests for ImageStrip: the fixed-height horizontal thumbnail row."""

from collections.abc import Iterator
from pathlib import Path

from PySide6.QtCore import QMargins, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QPalette, QPixmap, QWheelEvent
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QVBoxLayout, QWidget
from pytest import fixture
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.image_strip import (
    THUMBNAIL_BORDER,
    ImageStrip,
    ThumbnailLabel,
)

PATHS = [Path("/fake/info00.jpg"), Path("/fake/info01.png")]
WIDE_PIXMAP = 400
"""Source size for a thumbnail whose scaled height is worth asserting on -- big enough that the
strip scales it down rather than leaving it at its own size."""


ODD_STRIP_HEIGHT = 41
"""A strip height with no even factor to hide behind: a frame centred on the thumbnail's edge
rasterizes unevenly here, where an even one can come out symmetric by luck."""

FLAT_COLOUR = "#F4511E"
"""A screenshot colour that is nothing like the palette highlight, so a test can tell the current
thumbnail's frame apart from the image it is painted over."""


def flat_pixmap() -> QPixmap:
    """A thumbnail-sized pixmap in one flat colour.

    :returns: the pixmap, filled with :data:`FLAT_COLOUR`.
    """
    pixmap = QPixmap(WIDE_PIXMAP, WIDE_PIXMAP)
    pixmap.fill(QColor(FLAT_COLOUR))
    return pixmap


WHEEL_STEP = 120
"""One wheel notch, in eighths of a degree -- the unit Qt reports and every mouse produces."""


def send_wheel(target: QWidget, degrees: int, *, horizontal: bool = False) -> bool:
    """Turn the wheel over ``target`` by ``degrees``, as a real mouse does.

    :param target: the widget under the pointer.
    :param degrees: the wheel delta; negative is a downward (or rightward) turn.
    :param horizontal: send it as a sideways turn -- a tilt wheel, or the platform's shift-wheel.
    :returns: whether ``target`` accepted the event; ``False`` means it was left to its ancestors.
    """
    position = QPointF(target.rect().center())
    delta = QPoint(degrees, 0) if horizontal else QPoint(0, degrees)
    event = QWheelEvent(
        position,
        target.mapToGlobal(position),
        QPoint(0, 0),
        delta,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,  # noqa: FBT003  # positional-only in Qt's signature
    )
    QApplication.sendEvent(target, event)
    return event.isAccepted()


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


@fixture
def hosted_wheel_strip(qtbot: QtBot) -> Iterator[ImageStrip]:
    """A hosted strip that takes the plain wheel, as the maximized viewer's own row does.

    Same host-keeps-it-alive shape as :func:`hosted_strip`; only ``wheel_scrolls`` differs.

    :param qtbot: pytest-qt fixture.
    :returns: the strip, parented and shown.
    """
    host = QWidget()
    layout = QVBoxLayout(host)
    strip = ImageStrip(wheel_scrolls=True)
    layout.addWidget(strip)
    qtbot.addWidget(host)
    host.show()
    yield strip


def current_of(strip: ImageStrip, index: int) -> bool:
    """Whether the thumbnail at ``index`` is marked as the current screenshot.

    :param strip: the strip under test.
    :param index: the thumbnail's position in the row.
    :returns: whether it carries the current-item mark.
    """
    thumbnail = thumbnail_at(strip, index)
    assert isinstance(thumbnail, ThumbnailLabel)
    return thumbnail.current


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

    assert not current_of(strip, 0)
    assert current_of(strip, 1)


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

    assert current_of(strip, 1)


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

    assert not current_of(strip, 0)


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
    assert not thumbnail.current


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
    assert thumbnail.pixmap().height() == 100


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
    assert thumbnail.pixmap().height() == 80


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


def test_the_wheel_scrolls_the_row_sideways(mocker: MockerFixture, hosted_wheel_strip: ImageStrip) -> None:
    """A plain wheel scrolls the one-row strip horizontally (#161).

    Regression: a wheel reports a *vertical* delta, which the inherited handler spends on a vertical
    scrollbar this widget does not have -- so the wheel did nothing at all over a row too long to fit.
    Sent to the viewport, which is where Qt delivers it (a thumbnail ignores wheels, so a real one
    propagates there from wherever the pointer sits).

    **Test steps:**

    * fill a strip past its width, then wheel down over it and back up
    * verify the row scrolled out and back
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(WIDE_PIXMAP, 10))
    hosted_wheel_strip.set_images(PATHS * 8)
    scrollbar = hosted_wheel_strip.horizontalScrollBar()
    assert scrollbar.maximum() > 0

    send_wheel(hosted_wheel_strip.viewport(), -WHEEL_STEP)
    assert scrollbar.value() > 0

    send_wheel(hosted_wheel_strip.viewport(), WHEEL_STEP)
    assert scrollbar.value() == 0


def test_a_thumbnail_click_is_not_passed_on_to_whatever_is_behind(
    mocker: MockerFixture, hosted_strip: ImageStrip, qtbot: QtBot
) -> None:
    """A thumbnail consumes its click, so it never doubles as a click on the surface underneath.

    Regression: a ``QLabel`` ignores mouse events, which propagates them to its ancestors -- and the
    maximized viewer reads a click on itself as prev/next, so every thumbnail click was also a
    navigation step (#161).

    **Test steps:**

    * paint a thumbnail and click it
    * verify it reported its own screenshot and the click did not reach the host behind it
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(10, 10))
    hosted_strip.set_images(PATHS[:1])
    activated: list[Path] = []
    hosted_strip.image_activated.connect(activated.append)
    host = hosted_strip.parentWidget()
    assert host is not None
    reached_host: list[bool] = []
    host.mouseReleaseEvent = lambda _event: reached_host.append(True)  # type: ignore[method-assign]

    qtbot.mouseClick(thumbnail_at(hosted_strip, 0), Qt.MouseButton.LeftButton)

    assert activated == PATHS[:1]
    assert not reached_host


def test_a_plain_wheel_is_left_to_whatever_scrolls_around_the_strip(
    mocker: MockerFixture, hosted_strip: ImageStrip
) -> None:
    """By default the strip does not take the wheel at all (#161).

    Regression: taking it stopped a document's own viewer scrolling vertically whenever the pointer
    happened to be over the screenshots -- the strip is one row of a scrollable form there, not a
    control in its own right.

    **Test steps:**

    * fill a default strip past its width and wheel over it
    * verify it did not scroll and left the event unaccepted for the form around it
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(WIDE_PIXMAP, 10))
    hosted_strip.set_images(PATHS * 8)
    scrollbar = hosted_strip.horizontalScrollBar()
    assert scrollbar.maximum() > 0

    accepted = send_wheel(hosted_strip.viewport(), -WHEEL_STEP)

    assert scrollbar.value() == 0
    assert not accepted


def test_a_horizontal_wheel_scrolls_the_row_whoever_hosts_it(mocker: MockerFixture, hosted_strip: ImageStrip) -> None:
    """A sideways wheel scrolls the row even on a strip that leaves the plain wheel alone (#161).

    Nothing around the strip wants a horizontal wheel, so taking it costs the form nothing -- and it
    is what keeps an overflowing document strip reachable at all.

    **Test steps:**

    * fill a default strip past its width and send a horizontal wheel over it
    * verify the row scrolled
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: QPixmap(WIDE_PIXMAP, 10))
    hosted_strip.set_images(PATHS * 8)
    scrollbar = hosted_strip.horizontalScrollBar()

    send_wheel(hosted_strip.viewport(), -WHEEL_STEP, horizontal=True)

    assert scrollbar.value() > 0


def test_the_current_frame_is_even_on_every_side_and_closed_at_its_corners(
    mocker: MockerFixture, hosted_strip: ImageStrip
) -> None:
    """The mark is a frame of one thickness all round, with no gap at any corner (#161).

    Regression: it was stroked with a pen, which centres on the path it follows, so half of it fell
    outside the thumbnail -- the frame came out a pixel wider on two sides than the other two, and a
    pen's default bevel join cut the corners off, letting the screenshot (or, with the row's
    thumbnails flush, the neighbour) bleed through all four. Measured at an odd size, which is where
    a centred stroke rasterizes unevenly.

    **Test steps:**

    * paint a thumbnail in a known flat colour at an odd size and mark it as current
    * verify the frame is exactly ``THUMBNAIL_BORDER`` thick on all four sides
    * verify every corner pixel carries it, and the screenshot in the middle is untouched
    """
    mocker.patch("rehuco_agent.fields.widgets.image_strip.QPixmap", side_effect=lambda *_: flat_pixmap())
    hosted_strip.set_height(ODD_STRIP_HEIGHT)
    hosted_strip.set_images(PATHS[:1])
    hosted_strip.set_current(PATHS[0])

    thumbnail = thumbnail_at(hosted_strip, 0)
    painted = thumbnail.grab().toImage()
    highlight = thumbnail.palette().color(QPalette.ColorRole.Highlight).rgb()
    width, height = painted.width(), painted.height()
    middle_x, middle_y = width // 2, height // 2

    def thickness(pixels: Iterator[int]) -> int:
        """How many pixels of frame a scan line crosses before reaching the screenshot."""
        crossed = 0
        for pixel in pixels:
            if pixel != highlight:
                break
            crossed += 1
        return crossed

    assert thickness(painted.pixel(x, middle_y) for x in range(width)) == THUMBNAIL_BORDER
    assert thickness(painted.pixel(width - 1 - x, middle_y) for x in range(width)) == THUMBNAIL_BORDER
    assert thickness(painted.pixel(middle_x, y) for y in range(height)) == THUMBNAIL_BORDER
    assert thickness(painted.pixel(middle_x, height - 1 - y) for y in range(height)) == THUMBNAIL_BORDER
    corners = ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))
    assert [painted.pixel(x, y) for x, y in corners] == [highlight] * len(corners)
    assert painted.pixel(middle_x, middle_y) == QColor(FLAT_COLOUR).rgb()
