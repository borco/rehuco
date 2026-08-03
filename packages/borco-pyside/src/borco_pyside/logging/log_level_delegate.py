"""Draws a log row's level cell -- tinted by band, annotated with the record's serial."""

from collections.abc import Mapping
from typing import Final, override

from PySide6.QtCore import QModelIndex, QObject, QPersistentModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .log_entry import LogEntry
from .log_level_band import LogLevelBand
from .log_metrics import SERIAL_HPADDING, SERIAL_POINT_SIZE_REDUCTION, SERIAL_VPADDING, TEXT_HPADDING, TEXT_VPADDING
from .log_model import LogModel

type ModelIndex = QModelIndex | QPersistentModelIndex
"""What Qt hands a delegate method; the persistent form arrives from a view holding onto an index."""

BAND_TINT_ALPHA: Final = 48
"""How opaque a band's tint is drawn over the row, out of 255.

The tint is what makes a warning findable by eye, and it has to do that in **both** themes off one set
of colors. A low alpha over whatever the palette already painted is what buys that: the hue comes
from the caller, the lightness from the theme, so the same coral reads as a pale wash on white and a
dim glow on near-black. An opaque fill cannot -- it would have to be two color tables, one per
theme, kept in step by hand, and a caller passing one brand color would get white-on-white or
black-on-black in whichever theme it was not chosen for."""

LEVEL_COLUMN_WIDTH_HINT: Final = 100
"""Width this delegate asks for the level column, in pixels -- wide enough for the longest level name
plus its serial annotation. A hint, not a fixed width: the view is free to resize the section, and the
message column is the one that should take the space."""


class LogLevelDelegate(QStyledItemDelegate):
    """Paints the level name, tinted by the record's :class:`~.log_level_band.LogLevelBand`, with the
    record's serial in the corner.

    **Bands, not named levels.** The band is resolved through
    :meth:`~.log_level_band.LogLevelBand.of`, so a record logged at 15, at 5, or past ``CRITICAL``
    still gets painted -- where a ladder over ``DEBUG``/``INFO``/``WARNING``/``ERROR`` would leave it
    with whatever the last ``elif`` happened to be, or nothing.

    **The colors come from the caller.** This package ships no palette: an application passes the
    colors its own design already uses, and they are applied as a tint (:data:`BAND_TINT_ALPHA`) so
    one set works in either theme. A band left out of ``band_colors`` is drawn plain, which is the
    natural treatment for debugs -- there is nothing to draw attention to.

    **The corner number is the serial, not the row.** :attr:`~.log_entry.LogEntry.serial` counts from
    the first record of the run and is never reused, so it stays the same number as the ring buffer
    drops entries underneath it. A row index would renumber every record above a dropped one, and
    could not be lined up against *"N earlier records dropped"*.

    A row whose :attr:`~.log_model.LogModel.Roles.ENTRY` is not a :class:`~.log_entry.LogEntry` is
    handed to the base delegate untouched -- the same deference
    :meth:`~.log_filter_model.LogFilterModel.filterAcceptsRow` shows, so neither breaks when this is
    put over a model that is not a log.

    :param parent: optional Qt parent.
    :param band_colors: the tint per band; bands absent from it are drawn plain.
    """

    def __init__(
        self, parent: QObject | None = None, *, band_colors: Mapping[LogLevelBand, QColor] | None = None
    ) -> None:
        super().__init__(parent)
        self.__band_colors: dict[LogLevelBand, QColor] = dict(band_colors or {})

    @property
    def band_colors(self) -> dict[LogLevelBand, QColor]:
        """The tint per band, as passed in -- without this class's own alpha; see :meth:`tint_for`.

        A copy, so a caller cannot mutate what this delegate paints from without going through the
        setter, which is what a view watches to know it must repaint.
        """
        return dict(self.__band_colors)

    @band_colors.setter
    def band_colors(self, band_colors: Mapping[LogLevelBand, QColor]) -> None:
        """Replace the tints. A host must repaint its view; this class has none to repaint.

        :param band_colors: the new tint per band; bands absent from it are drawn plain.
        """
        self.__band_colors = dict(band_colors)

    def tint_for(self, band: LogLevelBand) -> QColor | None:
        """The color this delegate fills ``band``'s rows with, alpha already applied.

        Public because it is what a test asserts against and what a legend beside the view would draw
        from: the alpha is this class's decision, so asking it beats re-deriving the same product from
        the map that was passed in.

        :param band: the band to look up.
        :returns: the tint, or ``None`` when ``band`` is drawn plain.
        """
        color = self.__band_colors.get(band)
        if color is None:
            return None
        tint = QColor(color)
        tint.setAlpha(BAND_TINT_ALPHA)
        return tint

    @override
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        entry = index.data(LogModel.Roles.ENTRY)
        if not isinstance(entry, LogEntry):
            super().paint(painter, option, index)
            return

        painter.save()
        try:
            self.__paint_background(painter, option, entry)
            self.__paint_serial(painter, option, entry)
            painter.drawText(
                option.rect.adjusted(TEXT_HPADDING, TEXT_VPADDING, -TEXT_HPADDING, -TEXT_VPADDING),
                Qt.AlignmentFlag.AlignVCenter,
                entry.record.levelname,
            )
        finally:
            painter.restore()

    def __paint_background(self, painter: QPainter, option: QStyleOptionViewItem, entry: LogEntry) -> None:
        """Fill the cell: the selection color when selected, then the band's tint over it.

        The tint goes on **after** the highlight rather than instead of it, and inset by a pixel, so a
        selected row still reads as selected while keeping the band it belongs to -- a row that lost
        its color on selection would be exactly the row a reader had just picked out by that color.

        :param painter: the painter to draw with.
        :param option: the item's rect, palette and state.
        :param entry: the row's entry.
        """
        selected = QStyle.StateFlag.State_Selected in option.state
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
        tint = self.tint_for(LogLevelBand.of(entry.record.levelno))
        if tint is not None:
            painter.fillRect(option.rect.adjusted(1, 1, -1, -1) if selected else option.rect, tint)
        if selected:
            pen = painter.pen()
            pen.setBrush(option.palette.highlightedText())
            painter.setPen(pen)

    @staticmethod
    def __paint_serial(painter: QPainter, option: QStyleOptionViewItem, entry: LogEntry) -> None:
        """Draw the record's serial, small, in the cell's top-right corner.

        Saves and restores around the smaller font rather than keeping one built at construction: the
        font to reduce is whichever one the view is painting with now, which a theme or a settings
        change can replace after this delegate exists.

        :param painter: the painter to draw with.
        :param option: the item's rect.
        :param entry: the row's entry.
        """
        painter.save()
        try:
            font = painter.font()
            font.setPointSize(max(1, font.pointSize() - SERIAL_POINT_SIZE_REDUCTION))
            painter.setFont(font)
            painter.drawText(
                option.rect.adjusted(0, SERIAL_VPADDING, -SERIAL_HPADDING, 0),
                Qt.AlignmentFlag.AlignRight,
                str(entry.serial),
            )
        finally:
            painter.restore()

    @override
    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802  (Qt API name)
        del option, index  # a fixed width hint: the level names are short and of a known set
        return QSize(LEVEL_COLUMN_WIDTH_HINT, 0)
