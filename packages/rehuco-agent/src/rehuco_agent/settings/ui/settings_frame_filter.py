"""Frame-level filtering for one settings page: show only the QFrames whose text matches (#67)."""

from borco_pyside.widgets import StringListEditor
from PySide6.QtWidgets import QAbstractButton, QFrame, QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QWidget

ValueWidget = QLineEdit | QPlainTextEdit | QAbstractButton | QSpinBox | StringListEditor
"""The settings-page control types whose value :class:`SettingsFrameFilter` knows how to read for its
baseline snapshot (#77) -- exactly the ones the pages under `rehuco_agent.settings.ui` actually use."""


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
    :meth:`resync_baseline`) and comparing the live values against that snapshot -- no per-page
    wiring needed, and it works out to exactly what `SettingsPage.is_dirty` itself checks for every
    page that stages its edits straight in its widgets. One page bends that: `DescriptionsPage` keeps
    the *other* engine's CSS draft off-widget while its own is shown, which this snapshot can't see --
    an accepted gap, since the frame highlight is a visual aid, not the dirty flag of record (`is_dirty`
    still is).

    :param page: the page widget to discover filterable frames in (already built via ``setupUi``).
    :param title: the owning page's title, for the title-match rule.
    """

    def __init__(self, page: QWidget, title: str) -> None:
        self.__title_lower = title.lower()
        frames = [child for child in page.findChildren(QFrame) if self.__is_group_frame(child, page)]
        self.__frames = [(frame, self.__frame_text(frame)) for frame in frames]
        self.__baselines = {frame: self.__snapshot(frame) for frame in frames}

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
        return [frame for frame, _ in self.__frames if self.__is_dirty(frame)]

    def resync_baseline(self) -> None:
        """Recapture every frame's current widget values as the new "clean" baseline (#77).

        Call once the page's staged edits have been committed or discarded (``save_changes``/
        ``drop_changes``) -- otherwise :meth:`dirty_frames` keeps comparing against the *previous*
        clean state and reports a settled page as still dirty.
        """
        self.__baselines = {frame: self.__snapshot(frame) for frame, _ in self.__frames}

    def __is_dirty(self, frame: QFrame) -> bool:
        """Whether any of ``frame``'s value widgets differs from its captured baseline.

        :param frame: the frame to check; must be one of :attr:`__frames`.
        :returns: whether the frame is dirty.
        """
        return any(self.__value(widget) != value for widget, value in self.__baselines[frame].items())

    def __snapshot(self, frame: QFrame) -> dict[ValueWidget, object]:
        """Every :data:`ValueWidget` inside ``frame``, paired with its current value.

        :param frame: the frame to snapshot.
        :returns: each value widget found, keyed to its current value.
        """
        return {widget: self.__value(widget) for widget in self.__value_widgets(frame)}

    def __value_widgets(self, frame: QFrame) -> list[ValueWidget]:
        """``frame``'s value widgets, a composite one (`StringListEditor`) counted once rather than
        recursed into -- its own internal edit row is scratch space, not part of its ``values``.

        :param frame: the frame to walk.
        :returns: the value widgets found, outermost first.
        """
        widgets: list[ValueWidget] = []
        for widget in frame.findChildren(QWidget):
            if isinstance(widget, ValueWidget) and not self.__inside_value_widget(widget, frame):
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
    def __value(widget: ValueWidget) -> object:
        """``widget``'s current value, read by type.

        :param widget: the value widget to read.
        :returns: its current value, comparable across snapshots.
        """
        if isinstance(widget, QLineEdit):
            return widget.text()
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, StringListEditor):
            return widget.values
        return widget.isChecked()  # the remaining ValueWidget member: QAbstractButton

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

        :param frame: the frame to gather searchable text from.
        :returns: the concatenated captions, lowercased for case-insensitive matching.
        """
        parts: list[str] = []
        for widget in frame.findChildren(QWidget):
            if isinstance(widget, QLabel | QAbstractButton):
                parts.append(widget.text())
            elif isinstance(widget, QGroupBox):
                parts.append(widget.title())
        return " ".join(part for part in parts if part).lower()
