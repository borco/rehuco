"""The `url` leaf field: an external-hyperlink viewer, reusing `TextField`'s `QLineEdit` editor
([[plugins#field-toolkit]]).
"""

import html
from typing import override

from PySide6.QtWidgets import QLabel, QWidget

from rehuco_agent.fields.field import FieldBinding
from rehuco_agent.fields.text_field import TextField


class UrlField(TextField):
    """A ``url`` field ([[plugins#field-toolkit]], [[field-schema#field-types]]): the viewer renders an
    external hyperlink; the editor is inherited unchanged from
    :class:`~rehuco_agent.fields.text_field.TextField` -- a ``url`` really is a ``text`` value, only the
    viewer differs. Covers the primary source's ``url`` ([[field-schema#sources]]).

    The viewer doesn't restrict the link to ``http(s)`` -- ``QLabel``'s hyperlink dispatches through
    ``QDesktopServices::openUrl``, which already resolves whatever scheme the OS can handle.
    """

    TYPE = "url"

    @override
    def make_viewer(self, binding: FieldBinding[str]) -> QWidget:
        label = QLabel()
        label.setOpenExternalLinks(True)
        self.__render(label, binding.value)
        binding.changed.connect(lambda value: self.__render(label, value))
        return label

    @staticmethod
    def __render(label: QLabel, value: str) -> None:
        """Show ``value`` as an external hyperlink, or nothing when empty.

        :param label: the viewer label to update.
        :param value: the new url.
        """
        escaped = html.escape(value)
        label.setText(f'<a href="{escaped}">{escaped}</a>' if value else "")
