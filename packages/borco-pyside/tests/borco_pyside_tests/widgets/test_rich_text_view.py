"""Tests for RichTextView: content-sizing (no inner scrollbars), wrap-to-width, background modes.

The offscreen platform lays documents out for real, so the height-tracking tests assert on relative
growth (more content is taller) rather than exact pixel counts, which depend on the platform font.
"""

from borco_pyside.widgets import RichTextView
from PySide6.QtCore import Qt
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot


def test_both_scrollbars_are_disabled(qtbot: QtBot) -> None:
    """The view never scrolls within itself: both scrollbar policies are always-off.

    **Test steps:**

    * build a view
    * verify the vertical and horizontal scrollbar policies are always-off
    """
    view = RichTextView()
    qtbot.addWidget(view)

    assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_body_is_read_only_but_selectable(qtbot: QtBot) -> None:
    """The body cannot be edited yet its text can be selected and copied.

    **Test steps:**

    * build a view
    * verify it is read-only and its interaction flags allow mouse text selection
    """
    view = RichTextView()
    qtbot.addWidget(view)

    assert view.isReadOnly()
    assert view.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse


def test_size_hint_reports_the_rendered_content_height(qtbot: QtBot) -> None:
    """The view advertises its rendered height, so more content makes it taller.

    **Test steps:**

    * set short content on a fixed-width view and read its size-hint height
    * set much longer content and read it again
    * verify the taller content yields a larger size hint
    """
    view = RichTextView()
    qtbot.addWidget(view)
    view.setFixedWidth(200)

    view.setHtml("<p>one line</p>")
    short = view.sizeHint().height()
    view.setHtml("<p>" + "<br>".join(f"line {i}" for i in range(40)) + "</p>")
    tall = view.sizeHint().height()

    assert tall > short


def test_resizing_reflows_the_document_to_the_new_viewport_width(qtbot: QtBot) -> None:
    """A resize re-wraps the live document to the new viewport width.

    **Test steps:**

    * show a view over some content, then resize it wider
    * verify the document's text width tracks the resized viewport width
    """
    view = RichTextView()
    qtbot.addWidget(view)
    view.setHtml("<p>some wrapping content here</p>")
    view.resize(300, 200)
    view.show()
    qtbot.waitExposed(view)

    view.resize(500, 200)

    assert view.document().textWidth() == view.viewport().width()


def test_height_only_resize_does_not_reflow(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A resize that leaves the width unchanged skips the reflow -- the wrapping can't have changed.

    Guards against a runaway resize loop seen on a large, complex document: an enclosing scroll
    area resizes this view to its own cached content height on every ``documentSizeChanged``, and
    reflowing on that height-only resize could re-lay-out the same width and (for such a document)
    come back with a *different* height, re-triggering another resize forever.

    **Test steps:**

    * show a view over some content
    * resize it with the same width but a different height
    * verify the document was not asked to re-wrap
    """
    view = RichTextView()
    qtbot.addWidget(view)
    view.setHtml("<p>some wrapping content here</p>")
    view.resize(300, 200)
    view.show()
    qtbot.waitExposed(view)
    set_text_width = mocker.spy(view.document(), "setTextWidth")

    view.resize(300, 400)

    set_text_width.assert_not_called()


def test_height_for_width_matches_the_size_hint_height(qtbot: QtBot) -> None:
    """The view opts into height-for-width, reporting the same cached content height.

    **Test steps:**

    * set content on a view
    * verify it advertises height-for-width and returns the size-hint height
    """
    view = RichTextView()
    qtbot.addWidget(view)
    view.setFixedWidth(200)
    view.setHtml("<p>some wrapping content here</p>")

    assert view.hasHeightForWidth()
    assert view.heightForWidth(200) == view.sizeHint().height()


def test_minimum_size_hint_width_is_zero_so_long_lines_wrap(qtbot: QtBot) -> None:
    """The minimum width is zero, so a long line can never force the view wider -- it wraps instead.

    **Test steps:**

    * build a view
    * verify its minimum size-hint width is zero
    """
    view = RichTextView()
    qtbot.addWidget(view)

    assert view.minimumSizeHint().width() == 0


def test_background_none_is_transparent(qtbot: QtBot) -> None:
    """The default (``NONE``) background paints transparent, so the parent shows through.

    **Test steps:**

    * build a view with the default background
    * verify its stylesheet fills the background transparently
    """
    view = RichTextView()
    qtbot.addWidget(view)

    assert "transparent" in view.styleSheet()


def test_background_normal_uses_the_window_palette(qtbot: QtBot) -> None:
    """Switching to ``NORMAL`` fills with the window panel colour.

    **Test steps:**

    * build a view then set the ``NORMAL`` background
    * verify its stylesheet fills the background from the window palette
    """
    view = RichTextView(background=RichTextView.Background.NORMAL)
    qtbot.addWidget(view)

    assert "palette(window)" in view.styleSheet()
