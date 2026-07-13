"""A `ScintillaEdit` configured for editing Markdown prose ([[plugins#field-toolkit]], #74): line
numbers, wrapped long lines, a visible end-of-line glyph, and filename autocomplete for embedded
``![alt](...)`` image references.
"""

import re
from typing import Final

from borco_pyside.core import SimpleProperty
from PySide6.QtGui import QKeySequence, QPalette, QShortcut
from PySide6.QtWidgets import QApplication, QWidget
from pyside6_scintilla import Scintilla, ScintillaEdit

from rehuco_agent.documents.image_scanner import ImageScanner

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


class MarkdownEdit(ScintillaEdit):  # pylint: disable=too-few-public-methods
    """A `ScintillaEdit` configured as a Markdown source editor (#74): a visible line-number margin,
    wrapped long lines, a visible end-of-line glyph, and autocomplete offering this resource's own
    image filenames while typing an in-progress ``![alt](...)`` reference, or on demand (the full
    list) via Ctrl+Space.

    :param parent: optional Qt parent.
    :param image_scanner: resolves this resource's own image filenames, offered by autocomplete;
        omit for an editor that offers none (e.g. a bare instance in isolation/tests).
    """

    image_scanner = SimpleProperty[ImageScanner | None](None)
    """Resolves this resource's own image filenames, offered by autocomplete; ``None`` offers none."""

    def __init__(self, parent: QWidget | None = None, image_scanner: ImageScanner | None = None) -> None:
        super().__init__(parent)
        self.image_scanner = image_scanner
        self.__setup_appearance()
        self.__setup_autocomplete()
        self.__setup_theme_reactivity()

    def __setup_appearance(self) -> None:
        """Line numbers, wrapped long lines, and a visible end-of-line glyph.

        Block (rectangular) select/edit is deliberately not configured here yet -- an earlier
        attempt caused enough follow-on trouble (a confusing selection box past a shorter line's
        real end, then broken keyboard block-selection extension while chasing that) that it's
        being retried separately, from a clean slate, rather than left half-fixed (#74).
        """
        self.setCodePage(Scintilla.CpUtf8)  # already this binding's default; explicit for clarity

        self.setMarginTypeN(LINE_NUMBER_MARGIN, Scintilla.MarginType.Number)
        self.setMarginWidthN(LINE_NUMBER_MARGIN, self.textWidth(Scintilla.StylesCommon.LineNumber, "9999"))
        self.setMarginWidthN(SYMBOL_MARGIN, 0)

        self.setViewEOL(True)
        # CR LF has its own representation slot, separate from CR and LF's own -- Scintilla falls
        # back to drawing CR's and LF's individual representations side by side when it's unset,
        # doubling the glyph on a CRLF-terminated line, so all three need setting, not just CR/LF.
        for sequence in ("\r", "\n", "\r\n"):
            self.setRepresentation(sequence, EOL_REPRESENTATION)
            self.setRepresentationAppearance(sequence, Scintilla.RepresentationAppearance.Colour)
        self.setWrapMode(Scintilla.Wrap.Word)
        # loaded/echoed text is already LF-only (RehuDocument.description normalizes on read) --
        # this only governs what a newly-typed Enter inserts, keeping live edits consistent too
        self.setEOLMode(Scintilla.EndOfLine.Lf)

    def __setup_theme_reactivity(self) -> None:
        """Keep :data:`EOL_REPRESENTATION` coloured with the current theme's disabled/muted text
        colour, live -- not just at construction -- mirroring `ActionIconThemeHandler`'s own
        ``QApplication.paletteChanged`` wiring (not ``QStyleHints.colorSchemeChanged``, which can
        fire before the palette itself has actually updated).
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("MarkdownEdit requires a running QApplication")
        app.paletteChanged.connect(self.__apply_muted_color)
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
