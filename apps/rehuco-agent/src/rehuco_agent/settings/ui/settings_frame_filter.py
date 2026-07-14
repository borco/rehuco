"""Frame-level filtering for one settings page: show only the QFrames whose text matches (#67)."""

from PySide6.QtWidgets import QAbstractButton, QFrame, QGroupBox, QLabel, QWidget


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

    :param page: the page widget to discover filterable frames in (already built via ``setupUi``).
    :param title: the owning page's title, for the title-match rule.
    """

    def __init__(self, page: QWidget, title: str) -> None:
        self.__title_lower = title.lower()
        frames = [child for child in page.findChildren(QFrame) if self.__is_group_frame(child, page)]
        self.__frames = [(frame, self.__frame_text(frame)) for frame in frames]

    def field_labels(self) -> list[str]:
        """Each frame's gathered caption text, for the category tree's own (page-level) filter."""
        return [text for _, text in self.__frames]

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
