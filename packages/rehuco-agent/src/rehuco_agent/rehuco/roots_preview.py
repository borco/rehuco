"""The Roots view's details pane: what the current row is -- a root, a folder or a file -- the editors of a root, a
button for everything its context menu offers (#378), what a record says about its resource (#458), and what a zip is
made of (#456)."""

import logging
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID

import humanize
from borco_pyside.theming import ActionIconThemeHandler
from PySide6.QtCore import (
    QDateTime,
    QLocale,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QSize,
    Qt,
    QThreadPool,
    QUrl,
)
from PySide6.QtGui import QAction, QDesktopServices, QFont, QFontMetrics, QImage, QPalette, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QLineEdit, QSizePolicy, QToolButton, QWidget
from rehuco_core import (
    DEFAULT_CURRENT_USERNAME,
    DEFAULT_UNKNOWN_USERNAME,
    ArchiveFacts,
    FileType,
    MappedRoot,
    RehucoFile,
    RehucoRoot,
    RenameCoordinator,
    layout_rows,
    read_archive_facts,
)
from rehuco_core.access import Records, ResourceKey

from ..documents.files_rows import CHECKSUM_STATE_ICONS
from ..fields.widgets.image_export import PressDragFilter
from ..fields.widgets.image_source import FORMAT_HEAD_SIZE, format_reader
from ..pool_relay import PoolRelay
from ..settings.image_viewer_settings import shared_image_viewer_settings
from ..settings.markdown_rendering_settings import shared_markdown_rendering_settings
from ..settings.reference_images_settings import shared_reference_images_settings
from ..svg_icon_cache import SvgIconCache
from .record_images import RecordImages
from .root_edit_pane import RootEditPane
from .root_layouts_editor import RootLayoutsEditor
from .root_storage import NOT_MAPPED_ROW, ROOT_STORAGE_LABELS, UNREADABLE_ROW
from .roots_checksum import BAD_INK, OLD_BAD_INK, RowChecksum, checksum_lines, warning_ink
from .roots_folder_model import RootsFolderModel
from .roots_management import PackInfo, PackState
from .roots_node import NodeListing, RootsNodeKind, ShownRoot, root_where
from .roots_preview_ui import Ui_RootsPreview

LOG: Final = logging.getLogger(__name__)

type ActionsForRow = Callable[[QModelIndex], tuple[Sequence[QAction], QAction | None]]
"""What the pane asks its owner for a row: the actions its context menu holds, separators among them, and the one of
them that is its default."""

OPENABLE_SCHEMES: Final = frozenset({"http", "https"})
"""The schemes a record's URL is a link for. A ``.rehu`` is outside input, so what it says is shown, and only a web
address is handed to the system to open."""

type RecordForRow = Callable[[QModelIndex], Path | None]
"""What the pane asks its owner for a folder row: the record that stands for it -- its ``info.rehu`` or ``info.tc`` --
or ``None`` when it has none."""

type PackForRow = Callable[[QModelIndex], PackInfo | None]
"""What the pane asks its owner for an archive row: whether it is a reference pack, and through which record; ``None``
for a row that is not an archive."""

type DragImage = Callable[[QModelIndex, QWidget, QPixmap], None]
"""Drags an image row out to other apps (#395): the row, the widget the drag starts from, and the picture shown under
the pointer. The owner knows what record manages the row."""

THUMBNAIL_SIDE: Final = 320
"""The longest side, in pixels, an image's thumbnail is read at -- smaller ones are shown as they are."""

FILE_TYPE_LABELS: Final[dict[FileType, str]] = {
    FileType.DIRECTORY: "Folder",
    FileType.RECORD: "rehu record",
    FileType.MANIFEST: "Checksum manifest",
    FileType.BACKUP: "Conversion backup",
    FileType.IMAGE: "Image",
    FileType.VIDEO: "Video",
    FileType.AUDIO: "Audio",
    FileType.ARCHIVE: "Archive",
    FileType.GENERIC: "File",
}
"""What the Type line says, one entry per shape."""

FOLDER_LABEL: Final = "Folder"

SMALL_SIZE: Final = 1000
"""Below this many bytes the human form is the byte count, so it is not said twice."""

EMPTY_FOLDER: Final = "Empty"

UNREADABLE_ARCHIVE: Final = "Not a readable zip"
"""What an archive whose central directory cannot be read says it holds."""

SLOW_METHOD_NOTE: Final = "slow to read"
UNREADABLE_METHOD_NOTE: Final = "cannot be read"

PACK_TEXTS: Final = {
    PackState.UNSCANNED: "Not scanned yet: Scan to know whether it is a reference pack",
}
"""What the *Pack* row says for a state that is not a pack; a pack names its record instead."""

MINIMUM_WIDTH: Final = 300
"""The least width the pane is given, in pixels -- above what any row's lines ask for, so what is shown never changes
the width the pane needs and the splitter beside it never has to move when another row is selected."""

DEFAULT_NAME_ICON: Final = ":/icons/settings_reset_to_defaults.svg"
"""The icon of the settings pages' *defaults* button, on the button that puts a root's default name back."""

TITLE_ICON_SIZE: Final = 16
"""The state icon beside the title is as big as the one in the column."""

NO_FALLBACKS: Final = "None"
"""What the *Fallbacks* row says for a root that has none."""

SMALL_FONT_SCALE: Final = 0.85
"""How much smaller than the pane's font the *Checked on* row is drawn, dimmed."""


def format_size(size: int) -> str:
    """A size in words **and** in exact bytes, so two files whose human sizes read alike can be told apart:
    ``1.0 GB (1,073,741,824 B)``.

    :param size: the size in bytes.
    :returns: the text; just ``512 B`` for a size too small to have a human form.
    """
    if size < SMALL_SIZE:
        return f"{size:,} B"
    return f"{humanize.naturalsize(size)} ({size:,} B)"


# the pane is one surface: what a row is, a root's two editors and the row's buttons all turn on the same row, and
# splitting them would only pass that row around; the root's rows and edit mode are part of that one surface
# pylint: disable-next=too-many-instance-attributes,too-many-public-methods
class RootsPreview(QWidget):
    """The pane beside the Roots view's columns, showing the current row whatever it is: name, type, size, when it was
    changed, how much a folder holds, where it is, and the picture itself for an image.

    **A root is edited here**: its **Name** replaces the name header and the type, and is shown for a root row only,
    with a button to its right that gives the root its default name, the one it was added with
    (:attr:`default_root_name_action`), also shown as the field's placeholder -- beside its **Storage** -- detected, so
    read-only text (#514), or *Not mapped on this machine*. The owner reads the name through :attr:`root_name_edit`,
    and says whether it may be used with :meth:`set_editable`.

    **Below the details is a button for each action the row's context menu holds**, in its order, the default one in
    bold -- the owner supplies them through ``actions_for``. They are tool buttons set to the shared actions, so their
    text, tooltip, icon and enabled state are the actions' own.

    Everything but the picture comes from what the listing already gave the model, so showing a row reads nothing.
    The picture is read on the global thread pool inside the rename coordinator's hold, scaled as it is read, and an
    answer for a row that is no longer shown is dropped.

    **A zip's contents** (#456) are read from its central directory on the pool, inside the coordinator's hold, when
    an archive row becomes current: how many files (and images), their size unpacked and packed, and the compression
    method -- with a warning for one that is slow to read and another that cannot be read at all. A *Pack* row says
    whether the cache knows it as a reference pack, through which record, or that it has not scanned it yet.

    **A record's URL and description** (#458) are read from the file, the same way, when a ``.rehu`` or ``.tc`` row
    becomes current -- or a folder that has one, which ``record_for`` names -- so they are as current as the file and
    need no scan. They sit below the buttons under a line, a field the record lacks is left out, and a record with
    neither shows no line. The description is the description dock's own view -- the same renderer, stylesheet,
    image-width cap and previews toggle, its images resolved against the record's folder -- on the pane's background.
    **It takes the height left below the buttons** and scrolls inside it when the text is longer, so the pane itself
    never grows or scrolls. A record that cannot be read shows nothing more, and the reason is logged.

    :param model: the model the rows are of.
    :param coordinator: what an image read is held under, so it never blocks a rename; ``None`` holds nothing.
    :param actions_for: asked for a row's actions each time it is shown; ``None`` shows no buttons.
    :param record_for: asked for the record of a folder row, whose URL and description the pane then shows; ``None``
        shows none for a folder.
    :param pack_for: asked for an archive row, to say whether it is a reference pack; ``None`` says nothing of it.
    :param parent: optional Qt parent.
    :param drag_image: starts the drag of the picture shown; ``None`` drags nothing.
    :param records: what a record is read through ([[nodes#access-seam]], #416); records announcing on a private feed
        when not given.
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        model: RootsFolderModel,
        coordinator: RenameCoordinator | None = None,
        actions_for: ActionsForRow | None = None,
        record_for: RecordForRow | None = None,
        pack_for: PackForRow | None = None,
        parent: QWidget | None = None,
        drag_image: DragImage | None = None,
        records: Records | None = None,
    ) -> None:
        super().__init__(parent)
        self.__records: Final = records if records is not None else Records()
        self.__ui: Final = Ui_RootsPreview()
        self.__ui.setupUi(self)
        self.setMinimumWidth(MINIMUM_WIDTH)
        self.__model: Final = model
        self.__coordinator: Final = coordinator
        self.__actions_for: Final = actions_for
        self.__record_for: Final = record_for
        self.__pack_for: Final = pack_for
        self.__drag_image: Final = drag_image
        self.__index = QPersistentModelIndex()
        self.__serial = 0
        self.__location = ""
        self.__title = ""
        self.__url = ""
        self.__record: Path | None = None
        """The record the pane reads what it shows from, while it shows one."""
        self.__checksum_lines: tuple[str, str] | None = None
        self.__shown_root: UUID | None = None
        self.__editable = True
        """Whether a root's name may be changed at all, as :meth:`set_editable` last said."""
        self.__renamable = True
        """Whether the root shown has a file its name can be written to (#577)."""
        self.__editing = False
        """Whether the edit mode is on, as :meth:`set_editing` last said (#578)."""
        self.__root_file = ""
        """The full path the *Root file* row shows, which the label itself may have elided."""
        self.__default_name = ""
        self.__images: Final = RecordImages()
        self.__default_name_action: Final = QAction("Use Default Name", self)
        self.__setup_default_name()
        self.__setup_checksum_rows()
        self.__ui.url_value.linkActivated.connect(RootsPreview.__open_link)
        self.__setup_description()
        PressDragFilter(self.__ui.image_label, self.__image_token, self.__on_image_drag)
        self.show_index(QModelIndex())

    @property
    def root_name_edit(self) -> QLineEdit:
        """The name field of a root row, in the edit pane."""
        return self.__ui.root_edit_pane.name_edit

    @property
    def root_layouts_editor(self) -> RootLayoutsEditor:
        """The layouts and fallbacks of a root row, in the edit pane."""
        return self.__ui.root_edit_pane.layouts_editor

    @property
    def root_edit_pane(self) -> RootEditPane:
        """The editors of a root row, shown while :meth:`set_editing` says so."""
        return self.__ui.root_edit_pane

    @property
    def root_texts(self) -> dict[str, str]:
        """What the read-only root rows say, by row: ``name``, ``file``, ``layouts`` and ``fallbacks``, for tests."""
        ui = self.__ui
        return {
            "name": ui.root_name_value.text(),
            "file": self.__root_file,
            "layouts": ui.root_layouts_value.text(),
            "fallbacks": ui.root_fallbacks_value.text(),
        }

    def set_edit_action(self, action: QAction) -> None:
        """Put the owner's *Edit* toggle on the button the root rows show.

        :param action: the checkable action that turns the edit mode on and off.
        """
        self.__ui.edit_root_button.setDefaultAction(action)

    def set_editing(self, editing: bool) -> None:
        """Show a root's editors in place of its read-only name, layouts and fallbacks, or the other way back. The
        mode outlives the row: another root shown while it is on is shown in its editors.

        :param editing: whether the edit mode is on.
        """
        self.__editing = editing
        self.refresh()

    @property
    def default_root_name_action(self) -> QAction:
        """Gives the root its default name; enabled while the field differs from it."""
        return self.__default_name_action

    @property
    def default_root_name(self) -> str:
        """The default name of the root shown: the last segment of its location, which it was added with."""
        return self.__default_name

    def __setup_default_name(self) -> None:
        """Give the button beside the name field its action and icon, and keep it enabled only while the field differs
        from the default name."""
        action = self.__default_name_action
        action.setToolTip("Use the default name: the one the root was added with")
        ActionIconThemeHandler(action, DEFAULT_NAME_ICON)
        self.__ui.root_edit_pane.default_name_button.setDefaultAction(action)
        self.root_name_edit.textChanged.connect(self.__update_default_name)
        self.__update_default_name()

    def __update_default_name(self) -> None:
        """Enable the button while the name field is usable and not the default name."""
        edit = self.root_name_edit
        self.__default_name_action.setEnabled(edit.isEnabled() and edit.text().strip() != self.__default_name)

    @property
    def root_storage_value(self) -> QLabel:
        """The read-only storage line of a root row."""
        return self.__ui.root_storage_value

    @property
    def image(self) -> QImage | None:
        """The thumbnail shown, or ``None`` while there is none."""
        return self.__ui.image_label.image

    @property
    def resolution(self) -> str:
        """The resolution line, or empty while there is none."""
        return "" if self.__ui.resolution_value.isHidden() else self.__ui.resolution_value.text()

    @property
    def title(self) -> str:
        """The name shown in the title, whole -- the label itself may have elided it to fit."""
        return self.__title

    @property
    def checksum_texts(self) -> tuple[str, str] | None:
        """The *Checksum* row's verdict and the *Checked on* row's text; ``None`` when the row shown is not a file and
        the rows are hidden (#457)."""
        return self.__checksum_lines

    @property
    def record_texts(self) -> tuple[str, str] | None:
        """The URL and the description (as plain text) shown below the buttons; ``None`` while the section is hidden."""
        ui = self.__ui
        if ui.record_section.isHidden():
            return None
        return self.__url, ui.description_view.toPlainText()

    @property
    def archive_texts(self) -> dict[str, str]:
        """What the archive rows say, by row (``contents``, ``unpacked``, ``packed``, ``compression``, ``pack``), the
        shown ones only; empty while none is."""
        ui = self.__ui
        rows = {
            "contents": (ui.contents_label, ui.contents_value),
            "unpacked": (ui.unpacked_label, ui.unpacked_value),
            "packed": (ui.packed_label, ui.packed_value),
            "compression": (ui.compression_label, ui.compression_value),
            "pack": (ui.pack_label, ui.pack_value),
        }
        return {name: value.text() for name, (_label, value) in rows.items() if not value.isHidden() and value.text()}

    @property
    def location(self) -> str:
        """The full location shown, which the label itself may have elided to fit."""
        return self.__location

    @property
    def buttons(self) -> tuple[QToolButton, ...]:
        """The row's buttons, in the order of its context menu."""
        layout = self.__ui.buttons_layout
        items = (layout.itemAt(at) for at in range(layout.count()))
        widgets = (None if item is None else item.widget() for item in items)
        return tuple(widget for widget in widgets if isinstance(widget, QToolButton) and not widget.isHidden())

    def set_editable(self, editable: bool) -> None:
        """Say whether a root may be edited -- it may not while the file is read-only or none is open.

        :param editable: whether it may.
        """
        self.__editable = editable
        self.__enable_root_editors()

    def __enable_root_editors(self) -> None:
        """Let the editors be used only while the file may be edited and the root shown has a file to write to."""
        usable = self.__editable and self.__renamable
        self.root_name_edit.setEnabled(usable)
        self.root_layouts_editor.setEnabled(usable)
        self.__update_default_name()

    def __image_token(self, point: QPoint) -> object | None:
        """What a press on the picture would drag: the row shown, while it is an image whose picture is up (#395).

        :param point: where the press landed; unused, the whole picture being one thing.
        :returns: the row, or ``None``.
        """
        del point
        index = self.__shown()
        shown = self.image is not None and index.isValid() and self.__model.file_type_of(index) is FileType.IMAGE
        return QPersistentModelIndex(index) if shown else None

    def __on_image_drag(self, token: object) -> None:
        """Report that the picture was dragged away from (#395).

        :param token: the row, as :meth:`__image_token` gave it.
        """
        del token
        image = self.image
        if image is not None and self.__drag_image is not None:
            self.__drag_image(self.__shown(), self.__ui.image_label, QPixmap.fromImage(image))

    def __setup_description(self) -> None:
        """Make the description view the description dock's: its renderer and stylesheet, the scanner that finds its
        images, and the previews toggle -- each followed live."""
        view = self.__ui.description_view
        view.image_scanner = self.__images
        rendering = shared_markdown_rendering_settings()
        view.apply_rendering_settings(engine=rendering.engine, css=rendering.css)
        rendering.description_rendering_changed.connect(self.__apply_rendering)
        previews = shared_image_viewer_settings()
        view.set_images_visible(previews.previews_visible)
        previews.previews_visible_changed.connect(view.set_images_visible)  # type: ignore[attr-defined]

    def __apply_rendering(self) -> None:
        """Render the description again after the Markdown settings changed."""
        rendering = shared_markdown_rendering_settings()
        self.__ui.description_view.apply_rendering_settings(engine=rendering.engine, css=rendering.css)

    def __setup_checksum_rows(self) -> None:
        """Make the *Checked on* row smaller and dimmed, and give both checksum rows the height of a line, so the
        block never changes size from one file to the next."""
        ui = self.__ui
        small = QFont(ui.checked_value.font())
        small.setPointSizeF(small.pointSizeF() * SMALL_FONT_SCALE)
        for widget in (ui.checked_label, ui.checked_value):
            widget.setFont(small)
            widget.setEnabled(False)
        ui.checked_value.setMinimumHeight(QFontMetrics(small).lineSpacing())
        ui.checksum_value.setMinimumHeight(QFontMetrics(ui.checksum_value.font()).lineSpacing())

    def show_index(self, index: QModelIndex | QPersistentModelIndex) -> None:
        """Show a row.

        :param index: the row; an invalid index shows nothing.
        """
        self.__index = QPersistentModelIndex(index)
        self.refresh()

    def __shown(self) -> QModelIndex:
        """The row shown, as a plain index.

        :returns: the index; invalid when none is shown or it has been removed.
        """
        held = self.__index
        return self.__model.index(held.row(), held.column(), held.parent())

    def refresh(self) -> None:
        """Show the row again as the model has it now -- after a rename or a fresh listing changed it."""
        ui = self.__ui
        index = self.__shown()
        self.__serial += 1
        self.__record = None
        ui.image_label.set_image(None)
        self.__show_record("", "")
        ui.resolution_label.hide()
        ui.resolution_value.hide()
        path = self.__model.path_of(index)
        self.__images.record = path
        file_type = self.__model.file_type_of(index)
        kind = self.__model.node_kind(index)
        root = self.__model.root_at(index)
        self.__title = str(index.data() or "")
        ui.name_label.set_text(self.__title)
        ui.name_label.setVisible(root is None)
        checksum = index.data(RootsFolderModel.CHECKSUM_ROLE)
        self.__show_checksum(index, checksum if isinstance(checksum, RowChecksum) else None, kind)
        self.__show_root_editors(root)
        if kind is RootsNodeKind.FOLDER:
            type_text = FOLDER_LABEL
        else:
            type_text = FILE_TYPE_LABELS.get(file_type, "") if file_type is not None else ""
        size = index.data(RootsFolderModel.SIZE_ROLE)
        modified = index.data(RootsFolderModel.MODIFIED_ROLE)
        rows = (
            (ui.type_label, ui.type_value, type_text),
            (ui.size_label, ui.size_value, format_size(size) if isinstance(size, int) else ""),
            (ui.modified_label, ui.modified_value, RootsPreview.__format_time(modified)),
            (ui.contents_label, ui.contents_value, self.__contents(index)),
        )
        for label, value, text in rows:
            value.setText(text)
            label.setVisible(bool(text))
            value.setVisible(bool(text))
        self.__show_archive(None)
        self.__show_pack(index)
        self.__location = RootsPreview.__where(path, root)
        ui.path_value.set_text(self.__location)
        ui.path_label.setVisible(bool(self.__location))
        ui.path_value.setVisible(bool(self.__location))
        self.__rebuild_buttons(index)
        if path is not None and file_type is FileType.IMAGE:
            self.__start_image(path)
        elif path is not None and file_type is FileType.ARCHIVE and kind is RootsNodeKind.FILE:
            self.__start_archive(path)
        else:
            self.__start_record_reads(index, path, file_type, kind)

    def __start_record_reads(
        self, index: QModelIndex, path: Path | None, file_type: FileType | None, kind: RootsNodeKind | None
    ) -> None:
        """Read the record a row stands for: a record itself, or the one a folder has.

        :param index: the row.
        :param path: the row's path.
        :param file_type: what the row is by shape.
        :param kind: what the row is.
        """
        if path is not None and file_type is FileType.RECORD:
            self.__start_record(path)
        elif kind is RootsNodeKind.FOLDER and self.__record_for is not None:
            record = self.__record_for(index)
            if record is not None:
                self.__images.record = record
                self.__start_record(record)

    def __show_checksum(self, index: QModelIndex, checksum: RowChecksum | None, kind: RootsNodeKind | None) -> None:
        """Show a file's checksum: the state's icon beside the title, and the two fixed rows under *Modified*.

        :param index: the row.
        :param checksum: what the record that covers it says, or ``None`` when none does.
        :param kind: what the row is; only a file has the rows.
        """
        ui = self.__ui
        palette = self.palette()
        warning = warning_ink(checksum)
        if warning is not None:
            palette.setColor(QPalette.ColorRole.WindowText, warning)
        ui.name_label.setPalette(palette)
        path = None if checksum is None else CHECKSUM_STATE_ICONS.get(checksum.state)
        if path is None or kind is not RootsNodeKind.FILE:
            ui.title_icon.clear()
        else:
            pixmap = SvgIconCache().icon(path, palette.windowText().color()).pixmap(TITLE_ICON_SIZE, TITLE_ICON_SIZE)
            ui.title_icon.setPixmap(pixmap)
        is_file = kind is RootsNodeKind.FILE
        for widget in (ui.checksum_label, ui.checksum_value, ui.checked_label, ui.checked_value):
            widget.setVisible(is_file)
        if is_file:
            bookkeeping = bool(index.data(RootsFolderModel.BOOKKEEPING_ROLE))
            verdict, checked = checksum_lines(checksum, bookkeeping=bookkeeping, now=datetime.now(UTC))
            ui.checksum_value.set_text(verdict)
            ui.checked_value.set_text(checked)
            self.__checksum_lines = (verdict, checked)
        else:
            self.__checksum_lines = None

    @staticmethod
    def __where(path: Path | None, root: ShownRoot | None) -> str:
        """Where a row is, as the Location line says it: its folder or file, a root's location when this machine has
        no folder for it, or its root file when that cannot be read.

        :param path: the row's path on this machine, if it has one.
        :param root: the root of a root row, or ``None`` for any other.
        :returns: the text; empty when there is nothing to say.
        """
        if path is not None:
            return str(path)
        return root_where(root) if isinstance(root, RehucoRoot) else ""

    def __show_root_editors(self, root: ShownRoot | None) -> None:
        """Show a root's rows -- its name, layouts and fallbacks read-only, or in their editors while the edit mode is
        on, and its storage and root file either way -- or hide them for any other row.

        What is being edited is left alone while the same root is still shown, so a listing or a save that lands
        meanwhile does not eat it. Filling the editors never tells anyone.

        :param root: the root of a root row, or ``None`` for any other.
        """
        ui = self.__ui
        self.__renamable = root is not None and (isinstance(root, MappedRoot) or root.readable)
        editing = root is not None and self.__editing and self.__renamable
        shown = {
            ui.root_storage_label: root is not None,
            ui.root_storage_value: root is not None,
            ui.root_file_label: root is not None and root.file is not None,
            ui.root_file_value: root is not None and root.file is not None,
            ui.edit_root_button: self.__renamable,
            ui.root_edit_pane: editing,
            ui.root_name_label: root is not None and not editing,
            ui.root_name_value: root is not None and not editing,
            ui.root_layouts_label: self.__renamable and not editing,
            ui.root_layouts_value: self.__renamable and not editing,
            ui.root_fallbacks_label: self.__renamable and not editing,
            ui.root_fallbacks_value: self.__renamable and not editing,
        }
        for widget, visible in shown.items():
            widget.setVisible(visible)
        if root is None:
            self.__shown_root = None
            return
        layouts, fallbacks = root.layouts, root.fallbacks
        ui.root_name_value.setText(root.label or root_where(root))
        ui.root_layouts_value.setText(RootsPreview.__rows_lines(layout_rows(layouts)))
        ui.root_fallbacks_value.setText(RootsPreview.__rows_lines(fallbacks.items()) or NO_FALLBACKS)
        self.__root_file = "" if root.file is None else str(root.file)
        ui.root_file_value.set_text(self.__root_file)
        self.__default_name = RehucoFile.default_label(root.location)
        self.root_name_edit.setPlaceholderText(self.__default_name)
        retyping = self.__shown_root == root.root_id and ui.root_edit_pane.editing_here()
        self.__shown_root = root.root_id
        if not retyping:
            edit = self.root_name_edit
            blocked = edit.blockSignals(True)
            edit.setText(root.label)
            edit.blockSignals(blocked)
            self.root_layouts_editor.set_values(layouts, fallbacks)
        self.__enable_root_editors()
        if isinstance(root, MappedRoot):
            ui.root_storage_value.setText(ROOT_STORAGE_LABELS[root.storage])
        else:
            ui.root_storage_value.setText(NOT_MAPPED_ROW if root.readable else UNREADABLE_ROW)

    @staticmethod
    def __rows_lines(rows: Iterable[tuple[str, str]]) -> str:
        """Rows as the read-only display shows them, one ``key → value`` line each (#638).

        :param rows: the layouts' rows (:func:`~rehuco_core.layout_rows`) or the fallbacks' entries.
        :returns: the lines; empty for no rows.
        """
        return "\n".join(f"{key} \N{RIGHTWARDS ARROW} {value}" for key, value in rows)

    def __rebuild_buttons(self, index: QModelIndex) -> None:
        """Make one button for each action the row's context menu holds.

        :param index: the row.
        """
        layout = self.__ui.buttons_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = None if item is None else item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        if self.__actions_for is None or not index.isValid():
            return
        actions, default = self.__actions_for(index)
        for action in actions:
            if action.isSeparator():
                line = QFrame(self)
                line.setFrameShape(QFrame.Shape.HLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                layout.addWidget(line)
                line.show()  # a child made after its parent was shown is not shown with it
                continue
            button = QToolButton(self)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.setDefaultAction(action)
            if action is default:
                bold = QFont(button.font())
                bold.setBold(True)
                button.setFont(bold)
            layout.addWidget(button)
            button.show()  # a child made after its parent was shown is not shown with it

    def __contents(self, index: QModelIndex) -> str:
        """What a listed folder or root holds.

        :param index: the row.
        :returns: how many items, or :data:`EMPTY_FOLDER`; empty for a file, or a folder not listed yet or away.
        """
        if self.__model.node_kind(index) not in (RootsNodeKind.ROOT, RootsNodeKind.FOLDER):
            return ""
        if self.__model.listing_state(index) is not NodeListing.LISTED:
            return ""
        count = self.__model.rowCount(index)
        return EMPTY_FOLDER if count == 0 else f"{count:,} item{'' if count == 1 else 's'}"

    def follow(self, top_left: QModelIndex, bottom_right: QModelIndex, *_roles: object) -> None:
        """Show the row again if the model says it changed -- and only then, so a listing landing somewhere else does
        not restart a thumbnail.

        :param top_left: the first changed index.
        :param bottom_right: the last changed index.
        """
        shown = self.__shown()
        if (
            shown.isValid()
            and shown.parent() == top_left.parent()
            and top_left.row() <= shown.row() <= bottom_right.row()
        ):
            self.refresh()

    def follow_changes(self, keys: tuple[ResourceKey, ...]) -> None:
        """Show the row again when the record it shows changed on disk (#487, #511).

        :param keys: the files or folders that changed.
        """
        record = self.__record
        if record is not None and any(ResourceKey(record).is_at_or_beneath(key) for key in keys):
            self.refresh()

    def forget_if_gone(self, *_args: object) -> None:
        """Show nothing once the row shown has been removed."""
        if not self.__index.isValid():
            self.show_index(QModelIndex())

    @staticmethod
    def __format_time(modified: object) -> str:
        """A modification time in the user's own date format.

        :param modified: a POSIX timestamp, or anything else for none.
        :returns: the text; empty when there is no time.
        """
        if not isinstance(modified, float | int):
            return ""
        return QLocale().toString(QDateTime.fromSecsSinceEpoch(int(modified)), QLocale.FormatType.ShortFormat)

    def __start_image(self, path: Path) -> None:
        """Read a thumbnail on the pool.

        :param path: the image file.
        """
        serial = self.__serial
        relay = PoolRelay.instance()
        QThreadPool.globalInstance().start(lambda: self.__read_image(relay, serial, path))

    def __holding(self) -> AbstractContextManager[None]:
        """What a read on the pool is held under, so it never blocks a rename.

        :returns: the coordinator's hold, or one that holds nothing without a coordinator.
        """
        return nullcontext() if self.__coordinator is None else self.__coordinator.holding()

    def __read_image(self, relay: PoolRelay, serial: int, path: Path) -> None:
        """Read and scale one image, on a pool thread, and hand it back through ``relay``: the thumbnail -- null when
        the file could not be read -- and the picture's own size in pixels, which the thumbnail is smaller than.

        :param relay: the application's relay, so a preview deleted while the read was out hears nothing.
        :param serial: the request's serial.
        :param path: the image file.
        """
        with self.__holding():
            image, size = RootsPreview.__read_thumbnail(path)
        relay.post(self, self.__on_image, serial, image, size if size.isValid() else image.size())

    @staticmethod
    def __read_thumbnail(path: Path) -> tuple[QImage, QSize]:
        """Read the image at ``path``, scaled down to :data:`THUMBNAIL_SIDE`, with a reader told its format
        up front -- on a pool thread a probing reader can deadlock (`format_reader`, #529).

        :param path: the image file.
        :returns: the thumbnail and the picture's own size; a null image and an invalid size when the file
            cannot be read or is no format the reader is told.
        """
        try:
            with path.open("rb") as stream:
                head = stream.read(FORMAT_HEAD_SIZE)
        except OSError:
            return QImage(), QSize()
        reader = format_reader(str(path), head)
        if reader is None:
            return QImage(), QSize()
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > THUMBNAIL_SIDE:
            reader.setScaledSize(size.scaled(QSize(THUMBNAIL_SIDE, THUMBNAIL_SIDE), Qt.AspectRatioMode.KeepAspectRatio))
        return reader.read(), size

    def __on_image(self, serial: int, image: QImage, size: QSize) -> None:
        """Show a thumbnail and the picture's resolution, unless the row they were for is no longer the one shown.

        :param serial: the request's serial.
        :param image: what was read.
        :param size: the picture's own size.
        """
        if serial != self.__serial or image.isNull():
            return
        ui = self.__ui
        ui.image_label.set_image(image)
        ui.resolution_value.setText(f"{size.width():,} × {size.height():,}")
        ui.resolution_label.show()
        ui.resolution_value.show()

    def __show_pack(self, index: QModelIndex) -> None:
        """Say whether an archive row is a reference pack: the *Pack* row, from the cache and so immediate.

        :param index: the row.
        """
        ui = self.__ui
        info = None if self.__pack_for is None else self.__pack_for(index)
        if info is None or info.state is PackState.NOT_PACK:
            text = ""
        elif info.state is PackState.PACK and info.record is not None:
            text = f"Reference images, through {info.record.name}"
        else:
            text = PACK_TEXTS.get(info.state, "")
        ui.pack_value.setText(text)
        ui.pack_label.setVisible(bool(text))
        ui.pack_value.setVisible(bool(text))

    def __start_archive(self, path: Path) -> None:
        """Read a zip's central directory on the pool.

        :param path: the archive file.
        """
        serial = self.__serial
        extensions = shared_reference_images_settings().content_image_extensions
        relay = PoolRelay.instance()
        QThreadPool.globalInstance().start(lambda: self.__read_archive(relay, serial, path, extensions))

    def __read_archive(self, relay: PoolRelay, serial: int, path: Path, extensions: tuple[str, ...]) -> None:
        """Read one archive's facts, on a pool thread, and hand them back through ``relay`` -- ``None`` when the
        central directory could not be read.

        :param relay: the application's relay, so a preview deleted while the read was out hears nothing.
        :param serial: the request's serial.
        :param path: the archive file.
        :param extensions: the recognized image extensions.
        """
        try:
            facts = read_archive_facts(path, extensions, self.__coordinator)
        except Exception:  # pylint: disable=broad-exception-caught
            # the pool would swallow it and the rows would stay blank: answer as an unreadable zip
            LOG.exception("Reading the facts of %s failed", path)
            facts = None
        relay.post(self, self.__on_archive, serial, facts)

    def __on_archive(self, serial: int, facts: object) -> None:
        """Show what an archive is made of, unless the row it was for is no longer the one shown.

        :param serial: the request's serial.
        :param facts: what was read: an :class:`~rehuco_core.ArchiveFacts`, or ``None`` for a zip that is not readable.
        """
        if serial == self.__serial:
            self.__show_archive(facts if isinstance(facts, ArchiveFacts) else None, read=True)

    def __show_archive(self, facts: ArchiveFacts | None, *, read: bool = False) -> None:
        """Fill the archive rows, or hide them.

        :param facts: what the central directory says.
        :param read: whether the read has answered; with no facts, the zip is then not readable.
        """
        ui = self.__ui
        if facts is None and not read:
            for widget in (
                ui.unpacked_label,
                ui.unpacked_value,
                ui.packed_label,
                ui.packed_value,
                ui.compression_label,
                ui.compression_value,
            ):
                widget.hide()
            return
        if facts is None:
            contents = UNREADABLE_ARCHIVE
            shown: tuple[tuple[QLabel, QLabel, str], ...] = ()
        else:
            files = f"{facts.files:,} file{'' if facts.files == 1 else 's'}"
            contents = f"{files} ({facts.images:,} image{'' if facts.images == 1 else 's'})"
            note = UNREADABLE_METHOD_NOTE if facts.unreadable else SLOW_METHOD_NOTE if facts.slow else ""
            method = facts.method_text
            shown = (
                (ui.unpacked_label, ui.unpacked_value, format_size(facts.unpacked)),
                (ui.packed_label, ui.packed_value, format_size(facts.packed)),
                (ui.compression_label, ui.compression_value, f"{method} - {note}" if method and note else method),
            )
            palette = self.palette()
            if note:
                palette.setColor(QPalette.ColorRole.WindowText, BAD_INK if facts.unreadable else OLD_BAD_INK)
            ui.compression_value.setPalette(palette)
        ui.contents_value.setText(contents)
        ui.contents_label.show()
        ui.contents_value.show()
        for label, value, text in shown:
            value.setText(text)
            label.setVisible(bool(text))
            value.setVisible(bool(text))

    def __start_record(self, path: Path) -> None:
        """Read a record's URL and description on the pool.

        :param path: the ``.rehu`` or ``.tc`` file.
        """
        serial = self.__serial
        self.__record = path
        relay = PoolRelay.instance()
        QThreadPool.globalInstance().start(lambda: self.__read_record(relay, serial, path))

    def __read_record(self, relay: PoolRelay, serial: int, path: Path) -> None:
        """Read one record, on a pool thread, and hand its URL and description back through ``relay``, the
        description as Markdown -- either may be empty.

        A record that cannot be read answers nothing, and ``records`` logs the reason.

        :param relay: the application's relay, so a preview deleted while the read was out hears nothing.
        :param serial: the request's serial.
        :param path: the record file.
        """
        with self.__holding():
            # the identities only decide whose per-user fields are read, and the pane shows none
            record = self.__records.load(
                ResourceKey(path), username=DEFAULT_CURRENT_USERNAME, unknown_username=DEFAULT_UNKNOWN_USERNAME
            )
        if record.document.load_failed:
            # the records logged why
            return
        url, description = record.document.url.strip(), record.document.description
        relay.post(self, self.__on_record, serial, url, description if description.strip() else "")

    def __on_record(self, serial: int, url: str, description: str) -> None:
        """Show what a record says, unless the row it was for is no longer the one shown.

        :param serial: the request's serial.
        :param url: the record's URL.
        :param description: the record's description, as Markdown.
        """
        if serial == self.__serial:
            self.__show_record(url, description)

    def __show_record(self, url: str, description: str) -> None:
        """Fill the section under the buttons and show it, or hide it when both are empty.

        :param url: the URL; empty for none.
        :param description: the description as Markdown; empty for none.
        """
        ui = self.__ui
        self.__url = url
        openable = QUrl(url).scheme().lower() in OPENABLE_SCHEMES
        ui.url_value.set_text(url, href=url if openable else "")
        ui.url_value.setVisible(bool(url))
        ui.description_view.set_markdown(description)
        ui.description_view.setVisible(bool(description))
        ui.record_section.setVisible(bool(url or description))
        # the description takes what the pane has left; with none, the spacer below keeps the rest
        self.__ui.main_layout.setStretchFactor(ui.record_section, 1 if description else 0)

    @staticmethod
    def __open_link(href: str) -> None:
        """Open a record's URL in the system's browser.

        :param href: the address of the link clicked.
        """
        QDesktopServices.openUrl(QUrl(href))
