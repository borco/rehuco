"""Each type's last preview arrangement (#39), apart from the type's default layout."""

from ..settings.default_layout_settings import PREVIEW_LAYOUT_GROUP, shared_default_layout_settings_in
from .document_widget import DocumentWidget


def preview_layout_for(widget: DocumentWidget) -> bytes | None:
    """The layout the preview last left ``widget``'s type in (#39), or ``None`` when it has none yet -- which
    :meth:`DocumentWidget.adopt_layout` answers with the type's default layout, else as built.

    :param widget: the preview's widget, showing the document about to be laid out.
    :returns: the stored layout, or ``None``.
    """
    return shared_default_layout_settings_in(PREVIEW_LAYOUT_GROUP).state_for(widget.sub_docks.layout_type) or None


def remember_preview_layout(widget: DocumentWidget) -> None:
    """Remember the preview's current arrangement as its type's preview layout, in memory.

    :param widget: the preview's widget.
    """
    layouts = shared_default_layout_settings_in(PREVIEW_LAYOUT_GROUP)
    layouts.states[widget.sub_docks.layout_type] = widget.save_layout_state()


def write_preview_layouts() -> None:
    """Write every type's preview layout to the settings, at exit."""
    shared_default_layout_settings_in(PREVIEW_LAYOUT_GROUP).save()
