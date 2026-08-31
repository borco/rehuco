"""A `ScintillaEdit` configured for editing Markdown prose ([[plugins#field-toolkit]], #74): line
numbers, wrapped long lines, a visible end-of-line glyph, typing across a block (rectangular)
selection, and filename autocomplete for embedded ``![alt](...)`` image references.
"""

import re
from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.theming import ApplicationPaletteChangeNotifier
from PySide6.QtGui import QFontDatabase, QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QWidget
from pyside6_scintilla import Scintilla, ScintillaEdit

from ..image_scanner import ImageScanner

LINE_NUMBER_MARGIN: Final = 0
"""Margin index used for the line-number margin."""

SYMBOL_MARGIN: Final = 1
"""Margin index used for the (otherwise unused, hidden) symbol margin."""

EOL_REPRESENTATION: Final = "¶"
"""Glyph shown for a visible end-of-line (`setViewEOL`), replacing Scintilla's default boxed ``CR``/
``LF``/``CR LF`` labels -- one glyph regardless of which sequence the line actually ends with, so
editing reads the same whichever platform wrote the file."""

IMAGE_LINK_PATTERN: Final = re.compile(r"!\[[^\]]*\]\(([^)]*)$")
"""Matches an in-progress Markdown image reference up to the caret, e.g. ``![alt](already-typed``
-- capturing the filename fragment typed so far, for image-filename autocomplete."""

WRAPPED: Final = Scintilla.Wrap.Word
"""Wrap mode applied while :attr:`MarkdownEdit.wrap_long_lines` is on."""

NOT_WRAPPED: Final = Scintilla.Wrap.None_
"""Wrap mode applied while :attr:`MarkdownEdit.wrap_long_lines` is off -- Scintilla's own default."""


class MarkdownEdit(ScintillaEdit):  # pylint: disable=too-few-public-methods
    """A `ScintillaEdit` configured as a Markdown source editor (#74): a line-number margin, wrapped
    long lines, a visible end-of-line glyph -- each independently toggleable (:attr:`line_numbers`,
    :attr:`wrap_long_lines`, :attr:`line_endings_visible`, #69) -- typing that reaches every line of a
    block (rectangular) selection (Alt+drag / Alt+Shift+Arrow) at once, and autocomplete offering this
    resource's own image filenames while typing an in-progress ``![alt](...)`` reference, or on
    demand (the full list) via Ctrl+Space.

    :param parent: optional Qt parent.
    :param image_scanner: resolves this resource's own image filenames, offered by autocomplete;
        omit for an editor that offers none (e.g. a bare instance in isolation/tests).
    :param line_numbers: the starting state of :attr:`line_numbers`.
    :param line_endings_visible: the starting state of :attr:`line_endings_visible`.
    :param wrap_long_lines: the starting state of :attr:`wrap_long_lines`.
    """

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """Resolves this resource's own image filenames, offered by autocomplete; ``None`` offers none."""

    line_numbers = SimpleProperty(True)
    """Whether the line-number margin (:data:`LINE_NUMBER_MARGIN`) is shown."""

    line_endings_visible = SimpleProperty(True)
    """Whether a visible end-of-line glyph (:data:`EOL_REPRESENTATION`) is drawn at each line's end."""

    wrap_long_lines = SimpleProperty(True)
    """Whether long lines wrap instead of scrolling horizontally."""

    def __init__(
        self,
        parent: QWidget | None = None,
        image_scanner: ImageScanner | None = None,
        *,
        line_numbers: bool = True,
        line_endings_visible: bool = True,
        wrap_long_lines: bool = True,
    ) -> None:
        super().__init__(parent)
        self.image_scanner = image_scanner
        self.__setup_appearance()
        self.__setup_toggles(line_numbers, line_endings_visible, wrap_long_lines)
        self.__setup_autocomplete()
        self.__setup_theme_reactivity()

    def __setup_appearance(self) -> None:
        """Static appearance, independent of the three toggleable states :meth:`__setup_toggles`
        seeds and applies: the line-number margin's type, the EOL glyph's look, and block
        (rectangular) select/edit.

        Rectangular selection itself (Alt+drag / Alt+Shift+Arrow) and its virtual-space placement
        past a shorter line's real end are left at Scintilla's own defaults, deliberately not
        configured here -- an earlier attempt to also customize those caused enough follow-on
        trouble (a confusing selection box past a shorter line's real end, then broken keyboard
        block-selection extension while chasing that) that it isn't worth revisiting without a
        much more careful, separate pass (#74). `additionalSelectionTyping` is the one setting
        actually needed on top of the defaults: without it, typing only reaches the most recently
        touched line's caret, not every selected line's.
        """
        self.setCodePage(Scintilla.CpUtf8)  # already this binding's default; explicit for clarity
        self.__setup_font()

        self.setMarginTypeN(LINE_NUMBER_MARGIN, Scintilla.MarginType.Number)
        self.setMarginWidthN(SYMBOL_MARGIN, 0)

        # CR LF has its own representation slot, separate from CR and LF's own -- Scintilla falls
        # back to drawing CR's and LF's individual representations side by side when it's unset,
        # doubling the glyph on a CRLF-terminated line, so all three need setting, not just CR/LF.
        # Configuring the glyph's look is independent of whether it's shown (setViewEOL, applied by
        # __setup_toggles) -- Scintilla just doesn't draw it while that's off.
        for sequence in ("\r", "\n", "\r\n"):
            self.setRepresentation(sequence, EOL_REPRESENTATION)
            self.setRepresentationAppearance(sequence, Scintilla.RepresentationAppearance.Colour)
        # loaded/echoed text is already LF-only (RehuDocument.description normalizes on read) --
        # this only governs what a newly-typed Enter inserts, keeping live edits consistent too
        self.setEOLMode(Scintilla.EndOfLine.Lf)

        self.setMultipleSelection(True)
        self.setAdditionalSelectionTyping(True)

    def __setup_toggles(self, line_numbers: bool, line_endings_visible: bool, wrap_long_lines: bool) -> None:
        """Seed the three toggleable states and apply them, then keep applying on every later change
        -- e.g. the description field's misc-bar toggle buttons (#69).

        Assigning a `~borco_pyside.core.SimpleProperty` its own default value is a no-op (no
        ``*_changed`` emission), so seeding alone would silently skip applying a start state that
        happens to match the class default (``True``) -- each is therefore applied once here
        explicitly, in addition to being connected for every later change.

        :param line_numbers: the starting state of :attr:`line_numbers`.
        :param line_endings_visible: the starting state of :attr:`line_endings_visible`.
        :param wrap_long_lines: the starting state of :attr:`wrap_long_lines`.
        """
        self.line_numbers_changed.connect(self.__apply_line_numbers)  # type: ignore[attr-defined]
        self.line_endings_visible_changed.connect(self.__apply_line_endings_visible)  # type: ignore[attr-defined]
        self.wrap_long_lines_changed.connect(self.__apply_wrap_long_lines)  # type: ignore[attr-defined]

        self.line_numbers = line_numbers
        self.line_endings_visible = line_endings_visible
        self.wrap_long_lines = wrap_long_lines
        self.__apply_line_numbers(self.line_numbers)
        self.__apply_line_endings_visible(self.line_endings_visible)
        self.__apply_wrap_long_lines(self.wrap_long_lines)

    def __apply_line_numbers(self, visible: bool) -> None:
        """Show or hide the line-number margin.

        :param visible: the new :attr:`line_numbers` state.
        """
        width = self.textWidth(Scintilla.StylesCommon.LineNumber, "9999") if visible else 0
        self.setMarginWidthN(LINE_NUMBER_MARGIN, width)

    def __apply_line_endings_visible(self, visible: bool) -> None:
        """Show or hide the end-of-line glyph.

        :param visible: the new :attr:`line_endings_visible` state.
        """
        self.setViewEOL(visible)

    def __apply_wrap_long_lines(self, wrap: bool) -> None:
        """Wrap long lines, or let them scroll horizontally instead.

        :param wrap: the new :attr:`wrap_long_lines` state.
        """
        self.setWrapMode(WRAPPED if wrap else NOT_WRAPPED)

    def __setup_font(self) -> None:
        """Force a monospace font onto every style (#75).

        Rectangular (block) selection derives each selected line's column from a pixel x-position
        captured once via `setRectangularSelectionAnchor`/`setRectangularSelectionCaret`, then
        re-derives the matching column on every other line from that same pixel offset. With a
        proportional font -- Scintilla's own default, inherited from whatever platform UI font Qt
        resolves -- the same column lands at a different pixel offset on lines drawn with different
        glyphs, so typing across a block selection silently drops or misplaces characters on some
        lines. A monospace font gives every glyph an identical pixel advance, making the
        column<->pixel round-trip exact regardless of line content.

        `styleClearAll` copies `StylesCommon.Default`'s attributes -- just set on the line above --
        to every style, including style 0, the one actually used to draw text while no lexer is set.
        """
        family = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        self.styleSetFont(Scintilla.StylesCommon.Default, family)
        self.styleClearAll()

    def __setup_theme_reactivity(self) -> None:
        """Keep :data:`EOL_REPRESENTATION` coloured with the current theme's disabled/muted text
        colour, live -- not just at construction -- mirroring `ActionIconThemeHandler`'s own
        :class:`ApplicationPaletteChangeNotifier` wiring (not ``QStyleHints.colorSchemeChanged``, which can
        fire before the palette itself has actually updated).
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("MarkdownEdit requires a running QApplication")
        ApplicationPaletteChangeNotifier.for_application(app).palette_changed.connect(self.__apply_muted_color)
        self.__apply_muted_color()

    def __apply_muted_color(self, *_args: object) -> None:
        """Recolor :data:`EOL_REPRESENTATION` from the current theme's disabled ``Text`` colour.

        `setRepresentationColour` takes 0xAARRGGBB, not the classic Scintilla/COLORREF 0x00BBGGRR
        `styleSetFore` uses -- easy to mix up.
        """
        color = QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        argb = (color.alpha() << 24) | (color.red() << 16) | (color.green() << 8) | color.blue()
        for sequence in ("\r", "\n", "\r\n"):
            self.setRepresentationColour(sequence, argb)

    def __setup_autocomplete(self) -> None:
        """Offer this resource's own image filenames while typing a ``![alt](...)`` reference, or
        on demand via Ctrl+Space -- the full list, regardless of context, e.g. to browse what's
        available before deciding what to reference."""
        self.autoCSetSeparator(ord("\n"))  # filenames can contain spaces; the default separator is one
        self.autoCSetIgnoreCase(True)
        self.autoCSetChooseSingle(True)
        self.charAdded.connect(self.__on_char_added)

        show_all = QShortcut(QKeySequence("Ctrl+Space"), self)
        show_all.activated.connect(lambda: self.__show_image_completions(0))

    def __on_char_added(self, _ch: int) -> None:
        """Show the image-filename completion list when the caret sits inside an in-progress
        ``![alt](...)`` reference; otherwise leave any currently-shown list alone.

        :param _ch: the character just typed (`SCN_CHARADDED`); unused -- the context is read
            straight from the buffer instead of tracked incrementally.
        """
        match = IMAGE_LINK_PATTERN.search(self.__current_line_prefix())
        if match is None:
            return
        self.__show_image_completions(len(match.group(1)))

    def __show_image_completions(self, length_entered: int) -> None:
        """Show this resource's own image filenames as a completion list.

        :param length_entered: how many already-typed characters before the caret Scintilla should
            treat as the filter prefix -- 0 shows the full, unfiltered list (Ctrl+Space).
        """
        scanner = self.image_scanner
        if scanner is None:
            return
        names = sorted(path.name for path in scanner.files())
        if not names:
            return
        self.autoCShow(length_entered, "\n".join(names))

    def __current_line_prefix(self) -> str:
        """The current line's text up to the caret.

        Slices the raw UTF-8 bytes *before* decoding, not the decoded string -- `currentPos()` is a
        byte offset (`setCodePage(Scintilla.CpUtf8)`), which only lines up with a Python string index when the
        line is pure ASCII; slicing the decoded string directly would cut mid-character (or land on
        the wrong byte entirely) once the line has any multi-byte character before the caret.

        :returns: the prefix text.
        """
        current_pos = self.currentPos()
        line = self.lineFromPosition(current_pos)
        line_start = self.positionFromLine(line)
        line_bytes = bytes(self.getCurLine(self.lineLength(line) + 1).data())
        return line_bytes[: current_pos - line_start].decode("utf-8", errors="replace")
