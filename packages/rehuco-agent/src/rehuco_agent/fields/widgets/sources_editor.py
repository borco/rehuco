"""The ``sources`` editor: one card per source, Title / URL / Publisher ([[field-schema#sources]], #391)."""

from collections.abc import Mapping, Sequence
from typing import Any, Final

from borco_pyside.widgets import Card, CardListEditor, CardListModel, CardStateStyle
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget
from rehuco_core import duplicate_source_rows

from ...item_action_icons import apply_card_icons
from ..colors import FLAGGED_COLOR
from .line_edit import LineEdit
from .source_card_content import SourceCardContent


class SourcesEditor(CardListEditor):
    """A :class:`~borco_pyside.widgets.CardListEditor` over a resource's ``sources`` ([[field-schema#sources]]).

    Binds like any value widget (``value``, ``value_changed``, ``set_value``): the value is the list of source
    records **top first**, which is what :attr:`~rehuco_agent.documents.rehu_document_model.RehuDocumentModel.sources`
    holds, so the top card is the primary and moving a card to the top makes it so.

    What it adds to the generic card list:

    * a card holding none of Title, URL and Publisher is **blank**, and stays out of the value until something
      is typed -- so a card may be started from its URL, before its title, and is kept;
    * a card whose trimmed URL a card above it already has is **flagged** (`flagged`, pink), live as URLs are
      edited and cards moved or deleted. Nothing is removed for it: the user deletes the duplicate, an
      ordinary edit ([[field-schema#sources]], :func:`~rehuco_core.duplicate_source_rows`);
    * the app's icons on each card's actions;
    * every source shown, always; and the drag handles only while there are several sources -- one has
      nothing to reorder.

    A `HeaderPinned` editor (:attr:`header_height`): the row's label stays fixed beside the first card's Title
    row, like the ``location`` and ``authors`` labels, however many cards there are.

    :param parent: optional Qt parent.
    """

    FLAGGED_REASON: Final = "This address is already listed above."
    """Why a duplicate card is flagged."""

    FLAGGED_ALPHA: Final = 70
    """How strongly the flagged tint fills a card, out of 255 -- enough to read as pink, little enough to keep
    the captions and edits legible on both themes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        model = CardListModel(dict, SourcesEditor.is_blank, SourcesEditor.card_states)
        super().__init__(model, SourceCardContent, parent=parent)
        border = QColor(FLAGGED_COLOR)
        fill = QColor(border)
        fill.setAlpha(self.FLAGGED_ALPHA)
        self.style_map.register("flagged", CardStateStyle(fill=fill, border=border))
        self.card_added.connect(apply_card_icons)
        for card in self.cards:
            apply_card_icons(card)
        # after the base class's own slots, so a card it has just built is already there to be dressed
        model.rowsInserted.connect(self.__show_grips)
        model.rowsRemoved.connect(self.__show_grips)
        model.modelReset.connect(self.__show_grips)

    @property
    def header_height(self) -> int:
        """The height the row's label is centred against: the top of the first card down through its Title
        row, so the label sits level with that row whatever else the editor holds -- the `HeaderPinned`
        contract."""
        return 2 * Card.content_offset() + LineEdit().sizeHint().height()

    def __show_grips(self) -> None:
        """Show the drag handles while there is more than one card to reorder."""
        several = self.model.count > 1
        for card in self.cards:
            card.grip.setVisible(several)

    @staticmethod
    def is_blank(item: Mapping[str, Any]) -> bool:
        """Whether a source holds none of a title, an address and a publisher.

        :param item: the source record.
        :returns: whether all three are missing or empty.
        """
        return not any(
            isinstance(value := item.get(key), str) and value.strip()
            for key in (SourceCardContent.TITLE_KEY, SourceCardContent.URL_KEY, SourceCardContent.PUBLISHER_KEY)
        )

    @staticmethod
    def card_states(items: Sequence[Any]) -> list[dict[str, str]]:
        """Flag every source repeating the address of one above it.

        :param items: the sources, top first.
        :returns: per source, ``{"flagged": reason}`` for a duplicate, else nothing.
        """
        duplicates = set(duplicate_source_rows(items))
        return [{"flagged": SourcesEditor.FLAGGED_REASON} if row in duplicates else {} for row in range(len(items))]
