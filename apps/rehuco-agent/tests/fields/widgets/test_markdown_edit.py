"""Tests for MarkdownEdit: Scintilla configuration for a Markdown source editor (#74)."""

from pathlib import Path

from PySide6.QtGui import QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication
from pyside6_scintilla import Scintilla
from pytest import mark, param, raises
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.fields.widgets.markdown_edit import EOL_REPRESENTATION, MarkdownEdit


def test_line_number_margin_is_visible(qtbot: QtBot) -> None:
    """The line-number margin is shown with a nonzero width, not Scintilla's default 0px (#74).

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify its margin 0 has a nonzero width and reports the `Number` margin type
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    assert editor.marginWidthN(0) > 0
    assert editor.marginTypeN(0) == int(Scintilla.MarginType.Number)


def test_symbol_margin_is_hidden(qtbot: QtBot) -> None:
    """The (unused) symbol margin stays hidden, not Scintilla's default 16px (#74).

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify its margin 1 has zero width
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    assert editor.marginWidthN(1) == 0


def test_end_of_line_characters_are_visible(qtbot: QtBot) -> None:
    """End-of-line characters are shown as visible glyphs, not Scintilla's default hidden (#74).

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify `viewEOL` is on
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    assert editor.viewEOL() is True


@mark.parametrize(
    "sequence",
    [
        param("\r", id="CR"),
        param("\n", id="LF"),
        param("\r\n", id="CRLF"),
    ],
)
def test_end_of_line_shows_one_platform_independent_glyph(qtbot: QtBot, sequence: str) -> None:
    """Every end-of-line sequence -- CR, LF, or CRLF -- shows the same plain glyph, not Scintilla's
    default boxed ``CR``/``LF``/``CR LF`` labels, so editing reads the same regardless of which
    platform wrote the file (#74).

    CRLF has its own representation slot, separate from CR's and LF's own -- if it were left
    unset, Scintilla would fall back to drawing CR's and LF's individual representations side by
    side, doubling the glyph on a CRLF-terminated line.

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify the sequence's representation is the single configured glyph
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    representation = bytes(editor.representation(sequence).data()).decode("utf-8")

    assert representation == EOL_REPRESENTATION


def test_end_of_line_glyph_uses_the_disabled_text_colour(qtbot: QtBot) -> None:
    """The EOL glyph is coloured from the current theme's disabled ``Text`` colour, not left in the
    ordinary text colour (#74).

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify the EOL representation's colour matches the application palette's disabled ``Text``
      colour, encoded as `setRepresentationColour` expects (0xAARRGGBB)
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    color = QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    expected_argb = (color.alpha() << 24) | (color.red() << 16) | (color.green() << 8) | color.blue()

    # & 0xFFFFFFFF: the Scintilla getter returns a signed 32-bit int, so a colour with the high
    # (alpha) bit set comes back negative -- the same bit pattern as the unsigned expected value
    assert editor.representationColour("\n") & 0xFFFFFFFF == expected_argb


def test_end_of_line_glyph_colour_follows_a_live_palette_change(qtbot: QtBot, mocker: MockerFixture) -> None:
    """A theme switch (palette change) re-colours the EOL glyph immediately, not just at
    construction (#74).

    **Test steps:**

    * construct a `MarkdownEdit`
    * spy on the colour setter and emit ``QApplication.paletteChanged``
    * verify it ran again
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)
    set_representation_colour = mocker.spy(editor, "setRepresentationColour")
    app = QApplication.instance()
    assert isinstance(app, QApplication)

    app.paletteChanged.emit(app.palette())

    set_representation_colour.assert_called()


def test_construction_raises_without_a_running_qapplication(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Construction requires a running QApplication, to have somewhere to connect paletteChanged.

    **Test steps:**

    * mock QApplication.instance() to return None
    * construct a MarkdownEdit
    * verify RuntimeError is raised
    """
    del qtbot  # only needed so a real QApplication already exists for Qt's own widget machinery
    mocker.patch("rehuco_agent.fields.widgets.markdown_edit.QApplication.instance", return_value=None)

    with raises(RuntimeError, match="QApplication"):
        MarkdownEdit()


def test_long_lines_wrap(qtbot: QtBot) -> None:
    """Long lines wrap instead of scrolling horizontally, not Scintilla's default no-wrap (#74).

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify its wrap mode is `Wrap.Word`
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    assert editor.wrapMode() == int(Scintilla.Wrap.Word)


def test_additional_selection_typing_is_enabled(qtbot: QtBot) -> None:
    """Typing reaches every selection at once, not just the most recently touched one -- not
    Scintilla's default of only the main selection (#74).

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify `additionalSelectionTyping` is on
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    assert editor.additionalSelectionTyping() is True


def test_text_style_uses_the_platform_monospace_font(qtbot: QtBot) -> None:
    """The main text style is set to the platform's fixed-width font, not Scintilla's default
    proportional one -- required for block (rectangular) selection typing to land on the correct
    column on every line (#75).

    **Test steps:**

    * construct a `MarkdownEdit`
    * verify style 0 -- the one used to draw text while no lexer is set -- reports the platform's
      fixed-font family
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)

    expected_family = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
    font = bytes(editor.styleFont(0).data()).decode("utf-8")

    assert font == expected_family


# Scintilla's column<->pixel text measurement (pointXFromPosition) collapses to a constant under
# the offscreen QPA platform the instant any QFontDatabase.addApplicationFont() call happens
# anywhere in the process -- app.py's own icon-font loading triggers it, so this is unavoidable in
# the shared-QApplication test session, not this test's own doing (confirmed: even an
# already-loaded font, referenced explicitly by name, still collapses). Does not reproduce on a
# real platform. Needs an upstream pyside6-scintilla/Qt report, matching #74's own
# borco/pyside6-scintilla#12 precedent, before this can run headless.
@mark.fails_offscreen
def test_typing_reaches_every_line_of_a_block_selection(qtbot: QtBot) -> None:
    """Typing a character with a rectangular (block) selection spanning several equal-length lines
    inserts it on every one of them, not just the last-touched line (#74).

    **Test steps:**

    * construct a `MarkdownEdit` with three equal-length lines
    * make a rectangular selection at the same column on all three lines
    * type a character and verify it landed at that column on every line
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)
    editor.setText("aaaaaaaaaa\nbbbbbbbbbb\ncccccccccc")
    editor.setRectangularSelectionAnchor(3)
    line_2_start = editor.positionFromLine(2)
    editor.setRectangularSelectionCaret(line_2_start + 3)

    qtbot.keyClicks(editor, "x")

    text = bytes(editor.getText(editor.length() + 1).data()).decode("utf-8")
    lines = text.split("\n")
    assert lines[0] == "aaaxaaaaaaa"
    assert lines[1] == "bbbxbbbbbbb"
    assert lines[2] == "cccxccccccc"


def test_autocomplete_offers_image_filenames_inside_an_image_link(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Typing inside an in-progress ``![alt](...)`` reference shows the resource's own image
    filenames (#74).

    **Test steps:**

    * attach a scanner resolving two image files
    * set the buffer to an in-progress image link and fire `charAdded` as if typed
    * verify the completion popup becomes active
    """
    scanner = mocker.Mock(files=mocker.Mock(return_value=[Path("/res/b.png"), Path("/res/a.jpg")]))
    editor = MarkdownEdit(image_scanner=scanner)
    qtbot.addWidget(editor)
    editor.setText("![alt](")
    editor.gotoPos(editor.length())

    editor.charAdded.emit(ord("("))

    assert editor.autoCActive()


def test_autocomplete_is_not_shown_outside_an_image_link(qtbot: QtBot, mocker: MockerFixture) -> None:
    """Typing plain text, not inside ``![alt](...)``, never shows the popup (#74).

    **Test steps:**

    * attach a scanner resolving an image file
    * set the buffer to plain prose and fire `charAdded`
    * verify the popup stays inactive
    """
    scanner = mocker.Mock(files=mocker.Mock(return_value=[Path("/res/a.jpg")]))
    editor = MarkdownEdit(image_scanner=scanner)
    qtbot.addWidget(editor)
    editor.setText("just some prose")
    editor.gotoPos(editor.length())

    editor.charAdded.emit(ord("e"))

    assert not editor.autoCActive()


def test_autocomplete_is_not_shown_without_an_image_scanner(qtbot: QtBot) -> None:
    """No ``image_scanner`` attached means no autocomplete is ever offered (#74).

    **Test steps:**

    * construct a `MarkdownEdit` with no ``image_scanner``
    * set the buffer to an in-progress image link and fire `charAdded`
    * verify the popup stays inactive
    """
    editor = MarkdownEdit()
    qtbot.addWidget(editor)
    editor.setText("![alt](")
    editor.gotoPos(editor.length())

    editor.charAdded.emit(ord("("))

    assert not editor.autoCActive()


def test_autocomplete_is_not_shown_when_the_scanner_resolves_no_images(qtbot: QtBot, mocker: MockerFixture) -> None:
    """An attached scanner resolving no files never shows an empty popup (#74).

    **Test steps:**

    * attach a scanner resolving no files
    * set the buffer to an in-progress image link and fire `charAdded`
    * verify the popup stays inactive
    """
    scanner = mocker.Mock(files=mocker.Mock(return_value=[]))
    editor = MarkdownEdit(image_scanner=scanner)
    qtbot.addWidget(editor)
    editor.setText("![alt](")
    editor.gotoPos(editor.length())

    editor.charAdded.emit(ord("("))

    assert not editor.autoCActive()


def test_autocomplete_prefix_detection_handles_multi_byte_characters_before_the_caret(
    qtbot: QtBot, mocker: MockerFixture
) -> None:
    """The image-link context is detected correctly even with a multi-byte character earlier on the
    same line -- `currentPos()` is a byte offset, so naively slicing the decoded line by that same
    number would cut into the wrong character (#74).

    **Test steps:**

    * attach a scanner resolving two image files
    * set the buffer to prose containing an accented character, followed by an in-progress image
      link with nothing typed for the filename yet, and position the caret right after the ``(``
    * fire `charAdded` and verify the popup becomes active -- if the byte-slicing were wrong, the
      truncated/corrupted prefix would fail to match ``![alt](`` and the popup would stay closed
    """
    scanner = mocker.Mock(files=mocker.Mock(return_value=[Path("/res/a.jpg"), Path("/res/b.png")]))
    editor = MarkdownEdit(image_scanner=scanner)
    qtbot.addWidget(editor)
    text = "café ![alt]("
    editor.setText(text)
    editor.gotoPos(len(text.encode("utf-8")))

    editor.charAdded.emit(ord("("))

    assert editor.autoCActive()
