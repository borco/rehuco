"""Frame-level filtering for one settings page: show only the QFrames whose text matches (#67)."""

from collections.abc import Callable
from typing import Protocol, cast, runtime_checkable

from borco_pyside.widgets import ActionButtonColumn, ItemListEditor
from PySide6.QtCore import QAbstractItemModel, QAbstractListModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)


@runtime_checkable
class ValueControl(Protocol):
    """A control that carries a settings value the built-in types below cannot express, and says so
    itself (#342).

    The seam for a page that would otherwise keep a value *beside* its widget, where nothing generic
    can see it: `ColorSwatchButton` is the first, holding the lightbox backdrop it paints. A control
    satisfying this shape is snapshotted, compared and restored exactly as a line edit is -- so its
    frame tints, its Reset and Defaults work, and its Apply commits, with no per-page wiring.
    """

    def settings_value(self) -> object:  # pyright: ignore[reportReturnType]
        """This control's current value, comparable across snapshots."""

    def set_settings_value(self, value: object) -> None:
        """Write a value this control returned earlier back into it."""


ValueWidget = QLineEdit | QPlainTextEdit | QAbstractButton | QSpinBox | QComboBox | ItemListEditor | ValueControl
"""The settings-page control types whose value :class:`SettingsFrameFilter` knows how to read for its
baseline snapshot (#77) -- exactly the ones the pages under `rehuco_agent.settings.ui` actually use,
plus anything implementing :class:`ValueControl` (#342). `QComboBox` snapshots `currentIndex` --
narrower than an item's data, but every combo box today (the Scrapers page's browser choice,
[[acquisition-tooling#browser-persona]]) is a fixed list, never repopulated at runtime."""


class SettingsFrameFilter:
    """Shows or hides a settings page's labeled QFrames against a filter string (#67).

    A page groups its controls into labeled top-level QFrames; the frame is the smallest unit the
    filter shows or hides (never a single control inside one), so a crowded page collapses to just
    the group the user is looking for. Each frame's searchable text is gathered **once, here**, by
    walking its child widgets for user-visible captions (`QLabel` text, button text, `QGroupBox`
    titles) after the page's UI is built -- so it tracks whatever the ``.ui`` actually says
    (renamed labels, translations) with no hand-maintained per-page term list, and isn't recomputed
    per keystroke.

    "Top-level" frames are the direct `QFrame` children of the page (exact type, so a `QFrame`
    subclass such as a decorative rule isn't mistaken for a settings group); a frame nested inside
    another is part of its parent's text, not a group of its own.

    Matching rules for :meth:`apply`, given filter text *foo*:

    - empty *foo* -> every frame shown;
    - *foo* matches the page title and ``show_full_on_title_match`` -> every frame shown (a title
      match shows the page in full, whether or not individual frames also match);
    - otherwise -> exactly the frames whose gathered text contains *foo* are shown, the rest hidden
      (so a *foo* matching nothing leaves every frame hidden).

    Also the home of this page's **frame-level dirty tracking** (#77): `SettingsPage.is_dirty` only
    answers for the whole page, so :meth:`dirty_frames` derives a per-frame answer generically, by
    snapshotting every frame's :data:`ValueWidget` values at construction (and again on
    :meth:`resync_baseline`) -- a button only when checkable, since a push button holds nothing --
    and comparing the live values against that snapshot -- no per-page
    wiring needed, and it works out to exactly what `SettingsPage.is_dirty` itself checks for every
    page that stages its edits straight in its widgets. One page bends that: `DescriptionsPage` keeps
    the *other* engine's CSS draft off-widget while its own is shown, which this snapshot can't see --
    an accepted gap, since the frame highlight is a visual aid, not the dirty flag of record (`is_dirty`
    still is).

    The same snapshot machinery serves the per-frame **Apply**, **Reset** and **Defaults** buttons
    (#342): a second snapshot, taken by :meth:`capture_defaults` while the page holds its factory
    values, answers :meth:`frames_at_defaults`; :meth:`restore_saved` / :meth:`restore_defaults` are
    the inverse of the reader, writing either snapshot back into the frame's widgets by type; and
    :meth:`apply_frame` stages a one-frame commit around the page's whole-page save by parking the
    other frames' edits. Restoring is a staged edit like any other -- nothing is saved, the baseline
    is not resynced, and the dirty comparison simply finds the frame back at (or away from) its clean
    state.

    :param page: the page widget to discover filterable frames in (already built via ``setupUi``).
    :param title: the owning page's title, for the title-match rule.
    """

    def __init__(self, page: QWidget, title: str) -> None:
        self.__title_lower = title.lower()
        frames = [child for child in page.findChildren(QFrame) if self.__is_group_frame(child, page)]
        self.__frames = [(frame, self.__frame_text(frame)) for frame in frames]
        self.__baselines = {frame: self.__snapshot(frame) for frame in frames}
        self.__defaults: dict[QFrame, dict[ValueWidget, object]] = {frame: {} for frame in frames}

    def field_labels(self) -> list[str]:
        """Each frame's gathered caption text, for the category tree's own (page-level) filter."""
        return [text for _, text in self.__frames]

    def blocks(self) -> list[QFrame]:
        """This page's blocks -- its top-level frames, in the order the page declares them (#230).

        The same frames this filter shows and hides, handed out so a group's `SettingsBlockColumn` can
        show them without taking the whole page with them.

        :returns: the page's blocks, in page order.
        """
        return [frame for frame, _ in self.__frames]

    def apply(self, text: str, show_full_on_title_match: bool) -> None:
        """Show only the frames matching ``text`` (case-insensitive substring), per the class rules.

        :param text: the filter text; empty shows every frame.
        :param show_full_on_title_match: whether a title match shows the whole page, regardless of
            which individual frames match.
        """
        if not text:
            self.__set_all_visible(True)
            return
        needle = text.lower()
        if show_full_on_title_match and needle in self.__title_lower:
            self.__set_all_visible(True)
            return
        for frame, frame_text in self.__frames:
            frame.setVisible(needle in frame_text)

    def dirty_frames(self) -> list[QFrame]:
        """Which of this page's top-level frames have a :data:`ValueWidget` differing from the
        baseline last captured at construction or by :meth:`resync_baseline` (#77).

        :returns: the dirty frames, in page order.
        """
        return [frame for frame, _ in self.__frames if self.differs_from_saved(frame)]

    def frames_at_defaults(self) -> list[QFrame]:
        """Which of this page's top-level frames currently hold their factory values (#342).

        :returns: the frames at their defaults, in page order. A frame with no captured defaults
            snapshot (:meth:`capture_defaults` was never called, or the frame has no value widgets)
            counts as never at its defaults.
        """
        return [frame for frame, _ in self.__frames if not self.differs_from_defaults(frame)]

    def differs_from_saved(self, frame: QFrame) -> bool:
        """Whether any of ``frame``'s value widgets differs from its saved baseline -- what enables
        its Reset and Apply buttons (#342).

        :param frame: the frame to check; must be one of :attr:`__frames`.
        :returns: whether the frame is away from its baseline.
        """
        return self.__differs_from(self.__baselines[frame])

    def differs_from_defaults(self, frame: QFrame) -> bool:
        """Whether any of ``frame``'s value widgets differs from its factory snapshot -- what enables
        its Defaults button (#342).

        :param frame: the frame to check; must be one of :attr:`__frames`.
        :returns: whether the frame is away from its defaults; ``True`` while none were captured.
        """
        return not self.__defaults[frame] or self.__differs_from(self.__defaults[frame])

    def has_values(self, frame: QFrame) -> bool:
        """Whether ``frame`` holds any :data:`ValueWidget` this filter snapshots at all (#342).

        A frame with nothing to snapshot -- no recognized control, or only push buttons -- has nothing
        for a Reset/Defaults pair to act on.

        :param frame: the frame to check; must be one of :attr:`__frames`.
        :returns: whether the frame's saved-value snapshot is non-empty.
        """
        return bool(self.__baselines[frame])

    def list_editors(self, frame: QFrame) -> list[ItemListEditor]:
        """The `ItemListEditor`\\ s among ``frame``'s value widgets (#342).

        Each carries a restore button of its own that puts its ``defaults`` back -- which, once the
        frame's header offers Defaults, says the same thing twice from two places; the dialog hides
        the editor's copy.

        :param frame: the frame to check; must be one of :attr:`__frames`.
        :returns: the frame's list editors, outermost first.
        """
        return [widget for widget in self.__baselines[frame] if isinstance(widget, ItemListEditor)]

    def apply_frame(self, frame: QFrame, save: Callable[[], None]) -> None:
        """Commit ``frame``'s staged values alone, through the page's whole-page ``save`` (#342).

        A page can only ever save all of itself, so a one-frame commit is staged around it: every
        *other* frame's edits are parked -- its widgets put back to their saved baseline -- for the
        duration of ``save``, then the baseline is resynced (every widget now shows a saved value) and
        the parked edits are written back, where the dirty comparison finds them again. What ``save``
        persisted is exactly this frame's edits on top of what was already saved; what the user still
        sees is exactly what they had typed.

        The one thing this cannot park is state a page keeps *off* its widgets -- and writing a
        widget back can fire a signal that overwrites such state with the parked value (a
        ``textChanged`` handler copying the editor into a draft slot). A page in that position takes
        over its own buttons through `FrameRestoringPage` instead of coming through here:
        `DescriptionsPage`, whose two frames map onto its two settings objects, is the one that does.

        :param frame: the frame whose edits to commit; must be one of :attr:`__frames`.
        :param save: the page's ``save_changes``.
        """
        others = [(other, self.__snapshot(other)) for other, _ in self.__frames if other is not frame]
        for other, _ in others:
            self.__restore(self.__baselines[other])
        save()
        self.resync_baseline()
        for _, staged in others:
            self.__restore(staged)

    def resync_baseline(self) -> None:
        """Recapture every frame's current widget values as the new "clean" baseline (#77).

        Call once the page's staged edits have been committed or discarded (``save_changes``/
        ``drop_changes``) -- otherwise :meth:`dirty_frames` keeps comparing against the *previous*
        clean state and reports a settled page as still dirty.
        """
        self.__baselines = {frame: self.__snapshot(frame) for frame, _ in self.__frames}

    def capture_defaults(self) -> None:
        """Snapshot every frame's current widget values as its factory-defaults snapshot (#342).

        Call while the page's widgets hold the values `SettingsPage.seed_defaults` just put there --
        the same "capture whatever is on screen right now" idiom as :meth:`resync_baseline`, aimed at
        the other reference point.
        """
        self.__defaults = {frame: self.__snapshot(frame) for frame, _ in self.__frames}

    def restore_saved(self, frame: QFrame) -> None:
        """Write ``frame``'s last-captured saved baseline back into its widgets (#342).

        :param frame: the frame to restore; must be one of :attr:`__frames`.
        """
        self.__restore(self.__baselines[frame])

    def restore_defaults(self, frame: QFrame) -> None:
        """Write ``frame``'s captured factory-defaults snapshot back into its widgets (#342).

        :param frame: the frame to restore; must be one of :attr:`__frames`.
        """
        self.__restore(self.__defaults[frame])

    def __differs_from(self, snapshot: dict[ValueWidget, object]) -> bool:
        """Whether any widget ``snapshot`` names now holds a different value.

        :param snapshot: one frame's reference values, to compare its live widgets against.
        :returns: whether the frame differs from ``snapshot``.
        """
        return any(self.__value(widget) != value for widget, value in snapshot.items())

    def __snapshot(self, frame: QFrame) -> dict[ValueWidget, object]:
        """Every :data:`ValueWidget` inside ``frame``, paired with its current value.

        :param frame: the frame to snapshot.
        :returns: each value widget found, keyed to its current value.
        """
        return {widget: self.__value(widget) for widget in self.__value_widgets(frame)}

    def __value_widgets(self, frame: QFrame) -> list[ValueWidget]:
        """``frame``'s value widgets, a composite one (an `ItemListEditor`) counted once rather than
        recursed into -- its buttons and any open cell editor are machinery, not values.

        A button counts only when it is **checkable** (or a :class:`ValueControl`, which says its own
        value): a radio or a check box holds a value, where a Browse..., Register or Reload push
        button only does something when pressed -- it has no value to differ, and a frame holding
        nothing else has no setting for a Reset to act on (#342).

        :param frame: the frame to walk.
        :returns: the value widgets found, outermost first.
        """
        widgets: list[ValueWidget] = []
        for widget in frame.findChildren(QWidget):
            if (
                isinstance(widget, ValueWidget)
                and not (
                    isinstance(widget, QAbstractButton)
                    and not widget.isCheckable()
                    and not isinstance(widget, ValueControl)
                )
                and not self.__inside_value_widget(widget, frame)
            ):
                widgets.append(widget)
        return widgets

    @staticmethod
    def __inside_value_widget(widget: QWidget, frame: QFrame) -> bool:
        """Whether one of ``widget``'s ancestors, up to ``frame``, is itself a value widget.

        :param widget: the candidate widget.
        :param frame: the ancestor to stop climbing at.
        :returns: whether ``widget`` is nested inside a composite value widget.
        """
        ancestor = widget.parentWidget()
        while ancestor is not None and ancestor is not frame:
            if isinstance(ancestor, ValueWidget):
                return True
            ancestor = ancestor.parentWidget()
        return False

    @staticmethod
    def __value(widget: ValueWidget) -> object:  # pylint: disable=too-many-return-statements
        """``widget``'s current value, read by type.

        :param widget: the value widget to read.
        :returns: its current value, comparable across snapshots.
        """
        # first, so a control that says what its value is wins over whatever it happens to subclass
        # (the backdrop swatch is a QPushButton, whose checked state says nothing about the colour)
        if isinstance(widget, ValueControl):
            return widget.settings_value()
        if isinstance(widget, QLineEdit):
            return widget.text()
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentIndex()
        if isinstance(widget, ItemListEditor):
            # every cell under EditRole, which is what the list *holds*: a derived, read-only column
            # (the try-it table's slot, #287) answers nothing there, so a change upstream of it is not
            # this frame's edit
            model = widget.model
            root = QModelIndex()
            # a list model makes columnCount private -- a list has one column by definition
            columns = range(1 if isinstance(model, QAbstractListModel) else model.columnCount(root))
            return tuple(
                tuple(model.index(row, column).data(Qt.ItemDataRole.EditRole) for column in columns)
                for row in range(model.rowCount(root))
            )
        return widget.isChecked()  # the remaining ValueWidget member: QAbstractButton

    def __restore(self, snapshot: dict[ValueWidget, object]) -> None:
        """Write ``snapshot``'s values back into the widgets it pairs them with, by type -- the
        inverse of :meth:`__value` (#342).

        :param snapshot: one frame's widget/value pairs to write back (its captured baseline or
            defaults snapshot).
        """
        for widget, value in snapshot.items():
            self.__restore_one(widget, value)

    @staticmethod
    def __restore_one(widget: ValueWidget, value: object) -> None:
        """Write a single captured ``value`` back into ``widget``, by type.

        :param widget: the value widget to write into.
        :param value: the value :meth:`__value` read from it earlier.
        """
        if isinstance(widget, ValueControl):  # first, mirroring __value
            widget.set_settings_value(value)
        elif isinstance(widget, QLineEdit):
            widget.setText(cast(str, value))
        elif isinstance(widget, QPlainTextEdit):
            widget.setPlainText(cast(str, value))
        elif isinstance(widget, QSpinBox):
            widget.setValue(cast(int, value))
        elif isinstance(widget, QComboBox):
            widget.setCurrentIndex(cast(int, value))
        elif isinstance(widget, ItemListEditor):
            SettingsFrameFilter.__restore_rows(widget.model, cast(tuple[tuple[object, ...], ...], value))
        else:  # the remaining ValueWidget member: QAbstractButton
            cast(QAbstractButton, widget).setChecked(cast(bool, value))

    @staticmethod
    def __restore_rows(model: QAbstractItemModel, rows: tuple[tuple[object, ...], ...]) -> None:
        """Replace ``model``'s rows wholesale with ``rows``, each already ``EditRole``-shaped.

        :param model: the `ItemListEditor` model to overwrite -- flat, so every row lands at the root.
        :param rows: each row's cell values, column order, as :meth:`__value` captured them.
        """
        root = QModelIndex()
        if (existing := model.rowCount(root)) > 0:
            model.removeRows(0, existing, root)
        if not rows:
            return  # every model here refuses a zero-count insert, so an empty snapshot stops at emptied
        model.insertRows(0, len(rows), root)
        for row, cells in enumerate(rows):
            for column, cell in enumerate(cells):
                model.setData(model.index(row, column, root), cell, Qt.ItemDataRole.EditRole)

    def __set_all_visible(self, visible: bool) -> None:
        """Set every frame's visibility to ``visible``.

        :param visible: whether the frames should be shown.
        """
        for frame, _ in self.__frames:
            frame.setVisible(visible)

    @staticmethod
    def __is_group_frame(widget: QFrame, page: QWidget) -> bool:
        """Whether ``widget`` is one of ``page``'s top-level settings-group frames.

        :param widget: the candidate frame (a ``findChildren(QFrame)`` result).
        :param page: the page whose direct-child frames count as groups.
        :returns: whether ``widget`` is a direct child of ``page`` and an exact ``QFrame``.
        """
        # Exact type, not isinstance: a QFrame *subclass* (e.g. a decorative rule) is deliberately
        # excluded, so it isn't mistaken for a settings group.
        return type(widget) is QFrame and widget.parentWidget() is page  # pylint: disable=unidiomatic-typecheck

    @staticmethod
    def __frame_text(frame: QFrame) -> str:
        """The lowercased, space-joined user-visible caption text of every widget inside ``frame``.

        A widget carrying `ActionButtonColumn.NOT_A_CAPTION_PROPERTY` is skipped -- its `text()` mirrors a
        `QAction` shared by every list editor (#302), not a caption particular to this frame.

        :param frame: the frame to gather searchable text from.
        :returns: the concatenated captions, lowercased for case-insensitive matching.
        """
        parts: list[str] = []
        for widget in frame.findChildren(QWidget):
            if widget.property(ActionButtonColumn.NOT_A_CAPTION_PROPERTY):
                continue
            if isinstance(widget, QLabel | QAbstractButton):
                parts.append(widget.text())
            elif isinstance(widget, QGroupBox):
                parts.append(widget.title())
        return " ".join(part for part in parts if part).lower()
