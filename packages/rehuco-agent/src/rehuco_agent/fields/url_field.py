"""The `url` leaf field: an external-hyperlink viewer, reusing `TextField`'s `QLineEdit` editor
([[plugins#field-toolkit]]).
"""

from collections.abc import Sequence
from typing import Final, override

from borco_pyside.widgets import ElidedLabel
from PySide6.QtCore import SignalInstance
from PySide6.QtWidgets import QLabel

from .field import FieldBinding, FieldsTab, FieldViewerWidgets
from .text_field import TextField


class UrlField(TextField):
    """A ``url`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): the viewer renders an
    external hyperlink in an :class:`~borco_pyside.widgets.ElidedLabel` (a long url elides to fit
    rather than forcing the column wider, with the full url in a tooltip); the editor is inherited
    unchanged from :class:`~rehuco_agent.fields.text_field.TextField` -- a ``url`` really is a
    ``text`` value, only the viewer differs. Covers the primary source's ``url``
    ([[field-schema#sources]]).

    The viewer doesn't restrict the link to ``http(s)`` -- ``QLabel``'s hyperlink dispatches through
    ``QDesktopServices::openUrl``, which already resolves whatever scheme the OS can handle.

    **Two placements** (#620): the row is drawn on :attr:`~rehuco_agent.fields.field.Field.viewer_tab`
    and, when ``description_tab`` is given, once more on that tab. Each placement has its own
    visibility -- a value plus its change signal, the same shape the images strip takes its settings in --
    and follows it live: a placement turned off hides its label and link, so the row takes no room.

    :param description_tab: the second viewer surface to draw the row on; ``None`` for the one placement.
    :param main_visible: whether the row is shown on ``viewer_tab``.
    :param main_visible_changed: fires with the new visibility of the ``viewer_tab`` row.
    :param description_visible: whether the row is shown on ``description_tab``.
    :param description_visible_changed: fires with the new visibility of the ``description_tab`` row.
    """

    TYPE = "url"

    def __init__(  # pylint: disable=too-many-arguments
        self,
        name: str,
        label: str | None = None,
        *,
        viewer_tab: FieldsTab,
        editor_tab: FieldsTab,
        viewer_only: bool = False,
        description_tab: FieldsTab | None = None,
        main_visible: bool = True,
        main_visible_changed: SignalInstance | None = None,
        description_visible: bool = True,
        description_visible_changed: SignalInstance | None = None,
    ) -> None:
        super().__init__(name, label, viewer_tab=viewer_tab, editor_tab=editor_tab, viewer_only=viewer_only)
        self.__description_tab: Final = description_tab
        self.__main_visible: Final = main_visible
        self.__main_visible_changed: Final = main_visible_changed
        self.__description_visible: Final = description_visible
        self.__description_visible_changed: Final = description_visible_changed

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> FieldViewerWidgets:
        return self.__make_row(
            binding, self.viewer_tab, self.__main_visible, self.__main_visible_changed, labelled=True
        )

    @override
    def make_viewer_rows(self, bindings: Sequence[FieldBinding[str]]) -> Sequence[FieldViewerWidgets]:
        rows = [self.make_viewer(bindings[0])]
        if self.__description_tab is not None:
            rows.append(
                self.__make_row(
                    bindings[0],
                    self.__description_tab,
                    self.__description_visible,
                    self.__description_visible_changed,
                    labelled=False,
                )
            )
        return rows

    def __make_row(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        binding: FieldBinding[str],
        tab: FieldsTab,
        visible: bool,
        visible_changed: SignalInstance | None,
        *,
        labelled: bool,
    ) -> FieldViewerWidgets:
        """Build one placement of the row: its link, and its label when ``labelled``, shown or hidden as
        ``visible`` says. The Description View's link has no label and spans the full width.

        :param binding: the url's binding.
        :param tab: the surface the row belongs to.
        :param visible: whether the row starts shown.
        :param visible_changed: fires with the row's new visibility; ``None`` when it never changes.
        :param labelled: whether the row carries the field's name label.
        :returns: the row's bundle.
        """
        link = ElidedLabel()
        link.setOpenExternalLinks(True)
        self.__render(link, binding.value)
        self.bind_external(binding.changed, lambda value: self.__render(link, value))
        label = QLabel(self.label) if labelled else None
        widgets = [link] if label is None else [label, link]
        # hidden only when off: a still-parentless widget told to show would open as a window of its own
        if not visible:
            for widget in widgets:
                widget.hide()
        if visible_changed is not None:

            def show_row(shown: bool) -> None:
                for widget in widgets:
                    widget.setVisible(shown)

            self.bind_external(visible_changed, show_row)
        # a row with no label spans the whole grid width, flush with the image strip above it, instead of
        # sitting in the content column behind an empty label column
        return FieldViewerWidgets(tab, label, link, vertical=not labelled)

    @staticmethod
    def __render(label: ElidedLabel, value: str) -> None:
        """Show ``value`` as an external hyperlink, or nothing when empty.

        :param label: the viewer label to update.
        :param value: the new url.
        """
        label.set_text(value, href=value)
