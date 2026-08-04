"""The path editor widget: the resource's current name over a collapsible list of clickable
rename-suggestion labels ([[plugins#field-toolkit]]).

The expand/collapse control is deliberately *not* part of this widget -- the form places one in its
own "misc" grid column (see `FieldsForm`/`PathField`); this widget only exposes :attr:`expanded`.
"""

from collections.abc import Callable, Sequence
from typing import Final

from borco_pyside.core import SimpleProperty
from borco_pyside.widgets import ElidedLabel
from pathvalidate import is_valid_filename, sanitize_filename
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget
from unidecode import unidecode

from ..colors import WARNING_COLOR

WARNING_STYLESHEET: Final = f"QLabel {{ color: {WARNING_COLOR}; }}"
"""Applied to the current-name label when the name matches none of the suggestions ([[plugins#field-toolkit]])."""

UNAVAILABLE_SUFFIX: Final = " ⚿"
"""Appended to a suggestion something already occupies (#162) -- a marker, not a color, so the row
carries its own meaning instead of relying on a hue the disabled palette fights and a colorblind reader
may not separate at all. `ElidedLabel` middle-elides, keeping both ends, so the marker survives however
narrow the column gets.

A plain Unicode codepoint (U+26BF SQUARED KEY), not one of the app's Phosphor glyphs
(:mod:`rehuco_agent.glyphs`): those resolve only in their own font family, and this rides inline in a
label already rendering the resource name in the UI font. The same trade `MessageBanner` makes for its
own fallback glyph. It therefore leans on the platform's font fallback covering U+26BF; should that
ever render as tofu, the guaranteed alternative is a separate marker label per row drawn in Phosphor."""

LOCKED_SUFFIX: Final = " ⧗"
"""Appended to a suggestion that would otherwise be clickable but is locked by a busy task-queue job
(#240) -- a distinct marker from :data:`UNAVAILABLE_SUFFIX`, since "something already has this name"
and "a job is using this resource right now" are different reasons a suggestion isn't offered, and
conflating their markers would blur which one applies. Same reasoning as :data:`UNAVAILABLE_SUFFIX`
for riding in the label's own text rather than a stylesheet or color alone -- an hourglass glyph, so
its shape reads as "busy" independent of any tooltip."""


class PathEditor(QWidget):  # pylint: disable=too-many-instance-attributes
    """Edits a resource's name by picking a rename suggestion ([[plugins#field-toolkit]],
    [[field-schema#field-mapping]]). No free-text entry: the current name over a collapsible vertical
    list of clickable suggestion labels.

    :attr:`expanded` shows/hides the suggestions panel; the expand control itself lives in the form's
    misc column, not here. :meth:`set_current_name` and :meth:`set_suggestions` are slots so the owner
    can keep them live as the underlying fields change (e.g. editing ``authors`` re-renders the
    suggestions). Each suggestion is transliterated to ASCII (Unidecode) and sanitized into a valid
    filesystem name (``pathvalidate``); one that reduces to nothing is dropped, one equal to the
    current name renders disabled (a rename to it is a no-op). When the current name matches **none**
    of the suggestions it is drawn in the warning color, since it isn't one of the canonical names.
    Clicking a live suggestion emits :attr:`suggestion_selected` with its sanitized name -- this
    widget never touches the filesystem itself.

    A suggestion something already occupies renders **disabled, with a trailing**
    :data:`UNAVAILABLE_SUFFIX` marker (#162), so a rename that could only fail is never offered as a
    click. Which names those are is not this widget's to
    know -- it holds no path and reads no directory -- so it *asks*, through the
    :meth:`set_conflict_check` predicate its owner supplies: the toolkit's standing rule that a field
    decides *that* it needs something, never how the answer is obtained ([[plugins#field-toolkit]]).
    With no predicate set, nothing is unavailable, which is what keeps the widget usable on its own.

    Every suggestion is disabled the same way, marked with :data:`LOCKED_SUFFIX`, while a busy
    task-queue job would be moved by this resource's rename (#240) -- asked through
    :meth:`set_lock_reason`, the whole-editor sibling of :meth:`set_conflict_check`. With no predicate
    set, the editor is never locked by this.

    :param parent: optional Qt parent.
    """

    suggestion_selected = Signal(str)
    expanded_changed = Signal(bool)
    expanded = SimpleProperty(False)
    """Whether the suggestions panel is open; ``set_expanded`` is the slot-usable setter (the owner
    restores it per ``.rehu`` from persisted session state, and the misc-column toggle drives it)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.__current_name = ""
        self.__suggestions: list[str] = []
        self.__suggestion_labels: dict[str, ElidedLabel] = {}
        self.__conflicts: Callable[[str], bool] | None = None
        """Answers whether a candidate name is already taken, supplied by the owner
        (:meth:`set_conflict_check`); ``None`` until one is, so every name reads as available."""
        self.__lock_reason: Callable[[], str | None] | None = None
        """Answers whether -- and why -- this resource's rename is locked right now, supplied by the
        owner (:meth:`set_lock_reason`, #240); ``None`` until one is, so the editor is never locked on
        its own."""

        self.__name_label: Final = ElidedLabel()

        self.__suggestions_widget: Final = QWidget()
        self.__suggestions_layout: Final = QVBoxLayout(self.__suggestions_widget)
        self.__suggestions_layout.setContentsMargins(0, 0, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.__name_label)
        layout.addWidget(self.__suggestions_widget)

        self.expanded_changed.connect(self.__on_expanded_changed)
        self.__on_expanded_changed(self.expanded)

    @property
    def header_height(self) -> int:
        """The current-name line's natural height, stable regardless of :attr:`expanded`
        (`HeaderPinned` contract, [[plugins#field-toolkit]])."""
        return self.__name_label.sizeHint().height()

    def set_current_name(self, name: str) -> None:
        """Set the resource's current name and re-render.

        :param name: the current file/folder name.
        """
        self.__current_name = name
        self.__render()

    def set_conflict_check(self, conflicts: Callable[[str], bool] | None) -> None:
        """Supply the predicate deciding whether a candidate name is already taken (#162).

        Asked for every suggestion on every render, so it must be cheap: the owner is expected to hand
        over something that answers with a single existence check rather than a directory sweep (see
        :meth:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.rename_conflicts`).

        :param conflicts: called with a sanitized candidate name, returning whether something already
            occupies it; ``None`` to treat every name as available.
        """
        self.__conflicts = conflicts
        self.__render()

    def set_lock_reason(self, lock_reason: Callable[[], str | None] | None) -> None:
        """Supply the predicate deciding whether this resource's rename is locked right now, and why
        (#240).

        Unlike :meth:`set_conflict_check` -- *is this candidate name taken*, asked per suggestion --
        this is a **whole-editor** question, asked once per render: *may this resource be renamed at
        all*. A busy queue is narrower than
        :class:`~rehuco_agent.documents.document_widget.DocumentWidget`'s whole-document lock
        (``model.locked``): only this control is affected, and every other field on the resource stays
        editable.

        :param lock_reason: called with no arguments for the reason the rename is currently refused, or
            ``None`` when it isn't; ``None`` to leave the editor never locked.
        """
        self.__lock_reason = lock_reason
        self.__render()

    def set_suggestions(self, raw_suggestions: Sequence[str]) -> None:
        """Set the raw candidate names, sanitizing them and rebuilding the list when they change.

        :param raw_suggestions: the caller-formatted candidate strings (unsanitized).
        """
        sanitized = self.__sanitize_all(raw_suggestions)
        if sanitized != self.__suggestions:
            self.__suggestions = sanitized
            self.__rebuild()
        self.__render()

    def save_state(self) -> bytes:
        """Encode the expand state for per-``.rehu`` session persistence
        (:class:`~rehuco_agent.fields.field.StatefulWidget`).

        :returns: a one-byte blob restorable by :meth:`restore_state`.
        """
        return b"\x01" if self.expanded else b"\x00"

    def restore_state(self, state: bytes) -> None:
        """Restore the expand state produced by :meth:`save_state`.

        :param state: the blob to restore from; anything but a leading ``0x01`` reads as collapsed.
        """
        self.expanded = state[:1] == b"\x01"

    def __on_expanded_changed(self, value: bool) -> None:
        """Show or hide the suggestions panel to match :attr:`expanded`.

        :param value: the new expand state.
        """
        self.__suggestions_widget.setVisible(value)

    def __rebuild(self) -> None:
        """Recreate one clickable label per current sanitized suggestion, replacing the old set."""
        for label in self.__suggestion_labels.values():
            self.__suggestions_layout.removeWidget(label)
            label.deleteLater()
        self.__suggestion_labels.clear()
        for name in self.__suggestions:
            label = ElidedLabel()
            label.linkActivated.connect(lambda _href, name=name: self.suggestion_selected.emit(name))
            self.__suggestions_layout.addWidget(label)
            self.__suggestion_labels[name] = label  # pylint: disable=unsupported-assignment-operation

    def __render(self) -> None:
        """Refresh the current-name label (warning-colored when unmatched) and each suggestion's state.

        Four states per suggestion, in precedence order: the **current name** (disabled, plain -- a
        rename to it is a no-op, not a problem), a name something already **occupies** (disabled, and
        marked with :data:`UNAVAILABLE_SUFFIX`, #162), a name a busy task-queue job **locks** (disabled,
        marked with :data:`LOCKED_SUFFIX`, #240), and otherwise a live link. The current name wins over
        both disabled states, since a resource always "occupies" its own name and saying so would flag
        every document as a conflict with itself -- which is also why the conflict check is skipped
        entirely for it rather than merely overridden: no reason to ask about a name whose answer cannot
        matter. A lock, unlike a conflict, says nothing about *this* name in particular -- it is asked
        once per render, not once per suggestion -- so it applies uniformly to every non-current row.

        The marker rides in the label's own **text**, because Qt Style Sheets cannot inject content:
        they implement no ``content`` property and no ``::before``/``::after`` (Qt's pseudo-elements are
        widget subcontrols like ``::indicator``). ``name`` stays the dict key and the value
        :attr:`suggestion_selected` would carry, so the marker never leaks into what a rename renames to.

        The lock reason, when present, is also set as this whole widget's tooltip -- so hovering
        anywhere over the control, not just a disabled suggestion, explains why nothing here is
        clickable right now.
        """
        reason = self.__lock_reason() if self.__lock_reason is not None else None
        self.setToolTip(reason or "")
        self.__name_label.set_text(self.__current_name)
        unmatched = bool(self.__current_name) and self.__current_name not in self.__suggestions
        self.__name_label.setStyleSheet(WARNING_STYLESHEET if unmatched else "")
        for name, label in self.__suggestion_labels.items():
            is_current = name == self.__current_name
            unavailable = not is_current and self.__conflicts is not None and self.__conflicts(name)
            locked = not is_current and not unavailable and reason is not None
            label.setEnabled(not is_current and not unavailable and not locked)
            suffix = UNAVAILABLE_SUFFIX if unavailable else LOCKED_SUFFIX if locked else ""
            label.set_text(
                f"{name}{suffix}",
                href="" if is_current or unavailable or locked else "#",
            )
            # set_text (ElidedLabel) manages this label's tooltip itself -- showing the full text while
            # elided, clearing it otherwise -- so the lock reason must be applied *after*, or it would
            # be overwritten by that internal render.
            if locked:
                label.setToolTip(reason or "")

    @staticmethod
    def __sanitize_all(raw_suggestions: Sequence[str]) -> list[str]:
        """Transliterate and filesystem-sanitize every candidate, dropping duplicates and empties.

        :param raw_suggestions: the caller-formatted candidate strings.
        :returns: the sanitized, deduplicated, order-preserved names.
        """
        sanitized = (PathEditor.__sanitize(raw) for raw in raw_suggestions)
        return list(dict.fromkeys(name for name in sanitized if name is not None))

    @staticmethod
    def __sanitize(raw: str) -> str | None:
        """Transliterate ``raw`` to ASCII and sanitize it into a valid filesystem name.

        :param raw: a caller-formatted suggestion string (may hold unicode/invalid characters).
        :returns: the sanitized name, or ``None`` if nothing valid survives.
        """
        name = sanitize_filename(unidecode(raw)).strip()
        return name if name and is_valid_filename(name) else None
