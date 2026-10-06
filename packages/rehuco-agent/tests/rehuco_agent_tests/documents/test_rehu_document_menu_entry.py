"""Tests for RehuDocumentMenuEntry: title-over-dimmed-path layout, right-elision, and width cap.

The entry backs the `File` menu's open-documents list (#61) and its `Open recents` list (#64); those
menus are exercised through `MainWindow` in ``test_main_window.py``. These tests cover the widget itself
in isolation (the audit's zero-gap goal, #153).

The entry is drawn by the style rather than built from child widgets (#79), so the assertions here
read the text it actually draws (:meth:`RehuDocumentMenuEntry.displayed_title` /
:meth:`~RehuDocumentMenuEntry.displayed_path`, the same calls ``paintEvent`` draws with) instead of
reaching for `QLabel` children that no longer exist.
"""

from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QEnterEvent, QImage, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QProxyStyle,
    QStyle,
    QStyleFactory,
    QStyleOption,
    QStyleOptionMenuItem,
    QWidget,
    QWidgetAction,
)
from pytest import mark, skip
from pytestqt.qtbot import QtBot
from rehuco_agent.documents.document_dock import DIRTY_DOCK_MARKER
from rehuco_agent.documents.rehu_document_menu_entry import (
    ICON_COLUMN_CLEARANCE,
    ICON_COLUMN_PAD,
    MAX_WIDTH,
    RehuDocumentMenuEntry,
)

ELLIPSIS = "\N{HORIZONTAL ELLIPSIS}"
"""The character `QFontMetrics.elidedText` appends when it trims text to fit."""


def make_entry(
    qtbot: QtBot, title: str, path: Path | None, *, checked: bool = False, dirty: bool = False
) -> RehuDocumentMenuEntry:
    """Build a `RehuDocumentMenuEntry` sized to its cap, registered with qtbot for teardown."""
    entry = RehuDocumentMenuEntry(title, path, checked=checked, dirty=dirty)
    qtbot.addWidget(entry)
    entry.resize(MAX_WIDTH, entry.sizeHint().height())
    return entry


def test_shows_the_title_and_the_path(qtbot: QtBot) -> None:
    """The entry draws the title on its first line and the full path on its second.

    **Test steps:**

    * build an entry over a short title and path (short enough that neither elides)
    * verify it draws the title and ``str(path)``
    """
    path = Path("/home/ada/tutorials/my.rehu")
    entry = make_entry(qtbot, "My Tutorial", path)

    assert entry.displayed_title() == "My Tutorial"
    assert entry.displayed_path() == str(path)


def test_a_not_yet_saved_document_shows_an_empty_path_line(qtbot: QtBot) -> None:
    """A ``None`` path (a not-yet-saved document) draws an empty path line, not ``"None"``.

    **Test steps:**

    * build an entry with no path
    * verify the title still draws and the path line is empty
    """
    entry = make_entry(qtbot, "Untitled", None)

    assert entry.displayed_title() == "Untitled"
    assert entry.displayed_path() == ""


def test_a_long_title_is_right_elided(qtbot: QtBot) -> None:
    """A title too wide for the entry is right-elided rather than growing the menu.

    **Test steps:**

    * build an entry over a very long title
    * verify the drawn title is trimmed and ends with the ellipsis
    """
    long_title = "A very long tutorial title " * 40
    entry = make_entry(qtbot, long_title, Path("/home/ada/my.rehu"))

    assert entry.displayed_title() != long_title
    assert entry.displayed_title().endswith(ELLIPSIS)


def test_a_long_path_is_right_elided(qtbot: QtBot) -> None:
    """A path too wide for the entry is right-elided just like the title.

    **Test steps:**

    * build an entry over a deeply nested path
    * verify the drawn path is trimmed and ends with the ellipsis
    """
    long_path = Path("/home/ada/" + "nested/" * 60 + "my.rehu")
    entry = make_entry(qtbot, "My Tutorial", long_path)

    assert entry.displayed_path() != str(long_path)
    assert entry.displayed_path().endswith(ELLIPSIS)


def test_caps_the_width_it_asks_for_to_keep_the_menu_bounded(qtbot: QtBot) -> None:
    """The entry never *asks* for more than the cap, so a long title elides instead of widening the
    menu -- but it does not refuse to be wider, which is a different thing (#79).

    **Test steps:**

    * build an entry over a very long title
    * verify its preferred width is the cap, and that it is free to be stretched past it
    """
    entry = make_entry(qtbot, "A very long tutorial title " * 40, Path("/home/ada/my.rehu"))

    assert entry.sizeHint().width() == MAX_WIDTH
    assert entry.maximumWidth() > MAX_WIDTH  # a hard cap would leave it short of a wider menu's edge


def test_a_stretched_entry_fills_its_row_and_uses_the_extra_width(qtbot: QtBot) -> None:
    """A menu is as wide as its widest row, and every narrower row is stretched to fill it. The
    entry has to fill that width too, or its highlight stops mid-row and its path elides against a
    boundary the reader cannot see (#79).

    **Test steps:**

    * build one entry left at its cap and an identical one in a much wider menu
    * verify the stretched widget fills the row, and shows more of its path than the capped one
    """
    long_path = Path("/home/ada/" + "nested/" * 60 + "my.rehu")
    at_the_cap = make_entry(qtbot, "My Tutorial", long_path)

    menu = QMenu()
    qtbot.addWidget(menu)
    action = QWidgetAction(menu)
    stretched = RehuDocumentMenuEntry("My Tutorial", long_path, menu)
    action.setDefaultWidget(stretched)
    menu.addAction(action)
    wide = MAX_WIDTH + 200
    menu.setMinimumWidth(wide)
    menu.resize(wide, menu.sizeHint().height())
    menu.show()
    qtbot.waitExposed(menu)

    assert stretched.width() > MAX_WIDTH
    assert len(stretched.displayed_path()) > len(at_the_cap.displayed_path())


def test_the_path_line_is_set_in_a_smaller_font_than_the_title(qtbot: QtBot) -> None:
    """The path line is drawn smaller than the title, so the title reads as primary.

    **Test steps:**

    * build an entry whose title and path are the same string
    * verify the entry is tall enough for two lines but shorter than two title-sized ones
    """
    same = "identical"
    entry = make_entry(qtbot, same, Path(same))

    # the second line is scaled down, so two lines cost less than twice the first line's height
    two_title_lines = 2 * entry.fontMetrics().height()
    assert entry.sizeHint().height() < two_title_lines + entry.fontMetrics().height()
    assert entry.sizeHint().height() > entry.fontMetrics().height()


def test_the_dirty_marker_goes_in_the_icon_column_not_into_the_title(qtbot: QtBot) -> None:
    """An unsaved document's marker is drawn in the menu's icon column, not written into the title
    (#79) -- in the text it would land wherever that document's title happened to start, ragged
    against the icons of the rows above.

    **Test steps:**

    * build a dirty entry and a clean one
    * verify ``dirty`` reports the difference while both draw the same, unprefixed title
    """
    dirty = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"), dirty=True)
    clean = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))

    assert dirty.dirty
    assert not clean.dirty
    assert dirty.displayed_title() == clean.displayed_title() == "My Tutorial"
    assert DIRTY_DOCK_MARKER.strip() not in dirty.displayed_title()


class IconRecordingStyle(QProxyStyle):
    """A style that records whether each menu row it is asked to draw carried an icon.

    Wraps the default application style (the no-argument `QProxyStyle`, which borrows it rather than
    taking ownership) so what it records is the real style's own behavior. Lets a test assert that the
    entry *hands the marker to the style* without depending on whether the process can actually render
    the marker's glyph -- see :func:`is_renderable`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.menu_row_icons: list[bool] = []
        """One entry per ``CE_MenuItem`` drawn: whether that row carried a non-null icon."""

    def drawControl(  # noqa: N802  (Qt's own camelCase override)
        self,
        element: QStyle.ControlElement,
        option: QStyleOption,
        painter: QPainter,
        widget: QWidget | None = None,
    ) -> None:
        """Record whether a menu row carried an icon, then draw it as the real style would."""
        if element == QStyle.ControlElement.CE_MenuItem:
            self.menu_row_icons.append(not option.icon.isNull())  # type: ignore[attr-defined]
        super().drawControl(element, option, painter, widget)


def is_renderable(entry: RehuDocumentMenuEntry, text: str) -> bool:
    """Whether this process can actually draw ``text`` in ``entry``'s font.

    The suite runs on the **offscreen** platform, whose font database starts empty (root
    ``conftest.py``), so the marker normally reaches the pixels only as a tofu box. Once a test has
    loaded an icon font -- ``borco-pyside``'s theming tests add ``Phosphor-Fill.ttf``, which that
    package's ``conftest`` documents as changing plain-text rendering **permanently and process-wide**
    -- that font becomes the only family, and it has no glyph at the marker's codepoint and no tofu
    either, so the marker renders to nothing. Which of those two states a process is in depends on what
    else ran in it, and under ``pytest -n auto`` that is the xdist scheduler's choice.

    A real desktop is never in the second state: its font database has genuine families, and Qt's
    fallback supplies the codepoint (verified outside offscreen, with the icon font loaded first), which
    is why this is a test-environment artifact rather than a defect in what the app draws.

    :param entry: the entry whose font to probe.
    :param text: what to draw -- :data:`DIRTY_DOCK_MARKER`, or plain text for the tests that measure
        where text sits (#465), which the same loaded icon font leaves without a glyph.
    :returns: whether drawing ``text`` leaves any non-transparent pixel.
    """
    probe = QImage(32, 32, QImage.Format.Format_ARGB32)
    probe.fill(Qt.GlobalColor.transparent)
    painter = QPainter(probe)
    painter.setFont(entry.font())
    painter.setPen(QColor("black"))
    painter.drawText(probe.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return any(probe.pixelColor(x, y).alpha() > 0 for x in range(probe.width()) for y in range(probe.height()))


def test_the_dirty_marker_is_actually_drawn(qtbot: QtBot) -> None:
    """The dirty marker reaches the pixels -- ``dirty`` is not merely recorded (#79).

    Asserted in two halves, because only one of them can be stated unconditionally. That the entry
    **hands the marker to the style** holds whatever the process's fonts are, so it is checked always,
    through a recording style rather than by reaching into the widget. That the marker then **changes
    the pixels** depends on the font database actually having a glyph for it, which an earlier test in
    the same process may have taken away (:func:`is_renderable`) -- so that half runs only where
    it can mean anything, instead of failing on whichever worker xdist handed the icon-font tests to.

    **Test steps:**

    * paint a dirty entry and a clean one that are otherwise identical, through a recording style
    * verify the dirty row carried an icon and the clean row did not
    * where the marker's glyph renders at all, verify the two paintings differ
    """
    dirty = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"), dirty=True)
    clean = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))
    dirty_style, clean_style = IconRecordingStyle(), IconRecordingStyle()
    dirty.setStyle(dirty_style)
    clean.setStyle(clean_style)

    dirty_painting = dirty.grab().toImage()
    clean_painting = clean.grab().toImage()

    assert any(dirty_style.menu_row_icons)
    assert not any(clean_style.menu_row_icons)
    if is_renderable(dirty, DIRTY_DOCK_MARKER.strip()):
        assert dirty_painting != clean_painting


def test_the_checkmark_is_actually_drawn(qtbot: QtBot) -> None:
    """The focused document's checkmark reaches the pixels -- ``checked`` is not merely recorded
    (#79).

    **Test steps:**

    * paint a checked entry and an unchecked one that are otherwise identical
    * verify the two paintings differ
    """
    checked = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"), checked=True)
    unchecked = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))

    assert checked.grab().toImage() != unchecked.grab().toImage()


def test_checked_is_drawn_by_the_style_not_written_into_the_title(qtbot: QtBot) -> None:
    """The focused document's checkmark is the style's own, drawn in the menu's check column (#79) --
    not a glyph prepended to the title, which is what made it disagree with the native rows above it.

    **Test steps:**

    * build a checked entry and an unchecked one
    * verify ``checked`` reports the difference while the drawn title is identical
    """
    checked = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"), checked=True)
    unchecked = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))

    assert checked.checked
    assert not unchecked.checked
    assert checked.displayed_title() == unchecked.displayed_title() == "My Tutorial"


def test_hovering_repaints_the_row_as_highlighted(qtbot: QtBot) -> None:
    """The entry tracks its own hover, since a `QWidgetAction`'s custom widget is painted by us and
    never picks up the `QMenu`'s own row highlight (#79).

    **Test steps:**

    * build an entry inside a real menu and paint it once at rest
    * send it a real enter event, then a leave event, painting after each
    * verify the hovered painting differs from the two unhovered ones, which match each other
    """
    menu = QMenu()
    qtbot.addWidget(menu)
    action = QWidgetAction(menu)
    entry = RehuDocumentMenuEntry("My Tutorial", Path("/home/ada/my.rehu"), menu)
    action.setDefaultWidget(entry)
    menu.addAction(action)
    entry.resize(MAX_WIDTH, entry.sizeHint().height())

    at_rest = entry.grab().toImage()

    inside = QPointF(entry.rect().center())
    QApplication.sendEvent(entry, QEnterEvent(inside, inside, inside))
    hovered = entry.grab().toImage()

    QApplication.sendEvent(entry, QEvent(QEvent.Type.Leave))
    left = entry.grab().toImage()

    assert hovered != at_rest
    assert left == at_rest


@mark.parametrize("style_name", ["windows11", "windowsvista", "Windows", "Fusion"])
def test_the_highlighted_row_keeps_its_text_legible_under_every_style(style_name: str, qtbot: QtBot) -> None:
    """A highlighted row's text stays readable whatever the style highlights with (#79).

    Styles disagree about what highlighting a menu row means -- `windows11` tints it very light and
    keeps dark text, `Fusion` fills it with a saturated blue and switches to white -- so the entry
    measures the fill and picks the contrasting role rather than committing to one. The app ships on
    macOS and Linux too, where the resolved style is neither of the ones developed against, so this
    pins the *rule*, not one style's answer.

    **Test steps:**

    * for each style available here, build an entry using it and highlight it
    * verify the color it would draw text in contrasts with the color the style fills the row with
    """
    style = QStyleFactory.create(style_name)
    if style is None:  # a style Qt did not build on this platform
        skip(f"{style_name} unavailable")

    entry = make_entry(qtbot, "My Tutorial", Path("/home/ada/my.rehu"))
    entry.setStyle(style)
    inside = QPointF(entry.rect().center())
    QApplication.sendEvent(entry, QEnterEvent(inside, inside, inside))

    _, role = entry.row_style()
    text = entry.palette().color(role)
    # sampled at the right edge, clear of the left-aligned text, and vertically centered where the
    # text actually sits rather than at an edge some styles gradient away from
    fill = QColor(entry.grab().toImage().pixel(entry.width() - 4, entry.height() // 2))

    def brightness(color: QColor) -> float:
        return (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255

    darker, lighter = sorted((brightness(text), brightness(fill)))
    assert (lighter + 0.05) / (darker + 0.05) > 2.0, f"{style_name}: {text.name()} on {fill.name()}"


def make_menu(qtbot: QtBot, style: QStyle, *, native_icon: bool) -> tuple[QMenu, list[RehuDocumentMenuEntry]]:
    """A menu with one native row and four entries -- checked, unsaved, both and neither -- each in a
    `QWidgetAction`, as the `File` menu's open list builds them (#465).

    :param qtbot: registers the menu for teardown.
    :param style: the style the menu and every entry use -- set on each, since a widget's style does
        not reach its children the way the application's does.
    :param native_icon: whether the native row carries an icon, which is what widens the icon column
        for every row of the menu.
    :returns: the shown menu -- the caller holds it, or Python collects it and the entries with it -- and the
        entries in the order above.
    """
    menu = QMenu()
    qtbot.addWidget(menu)
    menu.setStyle(style)
    native = menu.addAction("Settings")
    if native_icon:
        native.setIcon(menu.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
    entries = [
        RehuDocumentMenuEntry("My Tutorial", Path("/home/ada/my.rehu"), menu, checked=checked, dirty=dirty)
        for checked, dirty in ((True, False), (False, True), (True, True), (False, False))
    ]
    for entry in entries:
        entry.setStyle(style)
        action = QWidgetAction(menu)
        action.setDefaultWidget(entry)
        menu.addAction(action)
    menu.show()
    qtbot.waitExposed(menu)
    return menu, entries


def pixels_differing_from(image: QImage, reference: QImage, *, from_x: int) -> list[tuple[int, int]]:
    """The pixels of ``image`` right of ``from_x`` that differ from ``reference``."""
    return [
        (x, y)
        for x in range(from_x, image.width())
        for y in range(image.height())
        if image.pixel(x, y) != reference.pixel(x, y)
    ]


def marks_reaching_the_text(entries: list[RehuDocumentMenuEntry], text_left: int) -> list[tuple[int, int]]:
    """What the marked entries (all but the last, plain one) paint at or right of ``text_left`` beyond the plain one."""
    reference = entries[-1].grab().toImage()
    return [
        pixel
        for entry in entries[:-1]
        for pixel in pixels_differing_from(entry.grab().toImage(), reference, from_x=text_left)
    ]


def native_column(menu: QMenu) -> int:
    """The icon column the menu reserves for its first (native) row."""
    option = QStyleOptionMenuItem()
    menu.initStyleOption(option, menu.actions()[0])
    return option.maxIconWidth


def entry_column(style: QStyle, entry: RehuDocumentMenuEntry) -> int:
    """The icon column an entry reserves for itself, whatever its menu holds."""
    small = style.pixelMetric(QStyle.PixelMetric.PM_SmallIconSize, None, entry)
    return small + ICON_COLUMN_PAD + ICON_COLUMN_CLEARANCE


@mark.parametrize("native_icon", [False, True])
@mark.parametrize("style_name", ["windows11", "Windows", "Fusion"])  # windowsvista draws no check offscreen: no theme
def test_an_entrys_marks_never_overlap_its_text_whatever_the_menus_other_rows_hold(
    style_name: str, native_icon: bool, qtbot: QtBot
) -> None:
    """An entry reserves its own check and icon columns (#465): with no icon on any native row the style
    reserves no icon column, and the check and the unsaved bullet used to be drawn over the title.

    **Test steps:**

    * for each style, build a menu with entries that are checked, unsaved, both and neither, with and
      without an icon on a native row; skip where plain text draws no ink in this worker, since where
      the text sits is then unobservable (:func:`is_renderable`)
    * verify the four entries start their text at the same x
    * verify that x is the same whether or not a native row has an icon, unless that icon makes the menu reserve
      a wider column than the entry does (macOS: a 25 px column) -- then the entries follow the native rows
    * verify everything the marks add to the painting lies left of that x
    """
    style = QStyleFactory.create(style_name)
    if style is None:  # a style Qt did not build on this platform
        skip(f"{style_name} unavailable")
    menu, entries = make_menu(qtbot, style, native_icon=native_icon)
    plain = entries[-1]
    if not is_renderable(plain, "Hg"):
        skip("plain text draws no ink in this worker (an icon font is the only family)")

    text_left = plain.row_style()[0]
    assert {entry.row_style()[0] for entry in entries} == {text_left}

    reaching = marks_reaching_the_text(entries, text_left)
    assert not reaching, f"{style_name}: marks reach into the text at {reaching[:3]}"
    assert entries[0].grab().toImage() != plain.grab().toImage()  # the checked one differs left of the text

    other_menu, other = make_menu(qtbot, style, native_icon=not native_icon)
    other_lefts = {entry.row_style()[0] for entry in other}
    assert len(other_lefts) == 1
    # an icon can only widen the column, and does not unless the menu reserves more than the entry does
    icon_left, plain_left = (text_left, other_lefts.pop()) if native_icon else (other_lefts.pop(), text_left)
    assert icon_left >= plain_left
    if native_column(menu if native_icon else other_menu) <= entry_column(style, plain):
        assert icon_left == plain_left
