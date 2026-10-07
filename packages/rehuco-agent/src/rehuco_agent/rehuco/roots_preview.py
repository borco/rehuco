"""The Roots view's details pane: what the current row is -- a root, a folder or a file -- the editors of a root, and a
button for everything its context menu offers (#378)."""

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import UUID

import humanize
from PySide6.QtCore import (
    QDateTime,
    QLocale,
    QModelIndex,
    QPersistentModelIndex,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QAction, QFont, QFontMetrics, QImage, QImageReader, QPalette
from PySide6.QtWidgets import QComboBox, QFrame, QLineEdit, QSizePolicy, QToolButton, QWidget
from rehuco_core import FileType, RehucoRoot, RenameCoordinator

from ..documents.files_rows import CHECKSUM_STATE_ICONS
from ..svg_icon_cache import SvgIconCache
from .root_storage import fill_root_storage_combo, select_root_storage
from .roots_checksum import RowChecksum, checksum_lines, warning_ink
from .roots_folder_model import NodeListing, RootsFolderModel, RootsNodeKind
from .roots_preview_ui import Ui_RootsPreview

type ActionsForRow = Callable[[QModelIndex], tuple[Sequence[QAction], QAction | None]]
"""What the pane asks its owner for a row: the actions its context menu holds, separators among them, and the one of
them that is its default."""

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

MINIMUM_WIDTH: Final = 300
"""The least width the pane is given, in pixels -- above what any row's lines ask for, so what is shown never changes
the width the pane needs and the splitter beside it never has to move when another row is selected."""

TITLE_ICON_SIZE: Final = 16
"""The state icon beside the title is as big as the one in the column."""

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
# splitting them would only pass that row around
# pylint: disable-next=too-many-instance-attributes
class RootsPreview(QWidget):
    """The pane beside the Roots view's columns, showing the current row whatever it is: name, type, size, when it was
    changed, how much a folder holds, where it is, and the picture itself for an image.

    **A root is edited here**: its **Name** and **Storage** replace the name header and the type, and are shown for a
    root row only. The owner reads them through :attr:`root_name_edit` and :attr:`root_storage_combo`, and says
    whether they may be used with :meth:`set_editable`.

    **Below the details is a button for each action the row's context menu holds**, in its order, the default one in
    bold -- the owner supplies them through ``actions_for``. They are tool buttons set to the shared actions, so their
    text, tooltip, icon and enabled state are the actions' own.

    Everything but the picture comes from what the listing already gave the model, so showing a row reads nothing.
    The picture is read on the global thread pool inside the rename coordinator's hold, scaled as it is read, and an
    answer for a row that is no longer shown is dropped.

    :param model: the model the rows are of.
    :param coordinator: what an image read is held under, so it never blocks a rename; ``None`` holds nothing.
    :param actions_for: asked for a row's actions each time it is shown; ``None`` shows no buttons.
    :param parent: optional Qt parent.
    """

    image_ready = Signal(int, QImage, QSize)
    """``(serial, image, size)``: one thumbnail's answer -- null when the file could not be read -- and the picture's
    own size in pixels, which the thumbnail is smaller than."""

    def __init__(
        self,
        model: RootsFolderModel,
        coordinator: RenameCoordinator | None = None,
        actions_for: ActionsForRow | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.__ui: Final = Ui_RootsPreview()
        self.__ui.setupUi(self)
        self.setMinimumWidth(MINIMUM_WIDTH)
        self.__model: Final = model
        self.__coordinator: Final = coordinator
        self.__actions_for: Final = actions_for
        self.__index = QPersistentModelIndex()
        self.__serial = 0
        self.__location = ""
        self.__title = ""
        self.__checksum_lines: tuple[str, str] | None = None
        self.__shown_root: UUID | None = None
        fill_root_storage_combo(self.__ui.root_storage_combo)
        self.__setup_checksum_rows()
        self.image_ready.connect(self.__on_image, Qt.ConnectionType.QueuedConnection)
        self.show_index(QModelIndex())

    @property
    def root_name_edit(self) -> QLineEdit:
        """The name field of a root row."""
        return self.__ui.root_name_edit

    @property
    def root_storage_combo(self) -> QComboBox:
        """The storage combo of a root row."""
        return self.__ui.root_storage_combo

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
    def location(self) -> str:
        """The full location shown, which the label itself may have elided to fit."""
        return self.__location

    @property
    def buttons(self) -> tuple[QToolButton, ...]:
        """The row's buttons, in the order of its context menu."""
        return tuple(button for button in self.findChildren(QToolButton) if not button.isHidden())

    def set_editable(self, editable: bool) -> None:
        """Say whether a root's name and storage may be changed -- they may not while the file is read-only or none is
        open.

        :param editable: whether they may.
        """
        self.__ui.root_name_edit.setEnabled(editable)
        self.__ui.root_storage_combo.setEnabled(editable)

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
        ui.image_label.set_image(None)
        ui.resolution_label.hide()
        ui.resolution_value.hide()
        path = self.__model.path_of(index)
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
        self.__location = "" if path is None else str(path)
        ui.path_value.set_text(self.__location)
        ui.path_label.setVisible(bool(self.__location))
        ui.path_value.setVisible(bool(self.__location))
        self.__rebuild_buttons(index)
        if path is not None and file_type is FileType.IMAGE:
            self.__start_image(path)

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

    def __show_root_editors(self, root: RehucoRoot | None) -> None:
        """Show a root's name and storage, or hide them for any other row.

        A name being typed is left alone while the same root is still shown, so a listing that lands meanwhile does not
        eat it. Filling the editors never tells anyone.

        :param root: the root of a root row, or ``None`` for any other.
        """
        ui = self.__ui
        for widget in (ui.root_name_label, ui.root_name_edit, ui.root_storage_label, ui.root_storage_combo):
            widget.setVisible(root is not None)
        if root is None:
            self.__shown_root = None
            return
        retyping = self.__shown_root == root.root_id and ui.root_name_edit.hasFocus()
        self.__shown_root = root.root_id
        if not retyping:
            blocked = ui.root_name_edit.blockSignals(True)
            ui.root_name_edit.setText(root.label)
            ui.root_name_edit.blockSignals(blocked)
        select_root_storage(ui.root_storage_combo, root.storage)

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
        QThreadPool.globalInstance().start(lambda: self.__read_image(serial, path))

    def __read_image(self, serial: int, path: Path) -> None:
        """Read and scale one image, on a pool thread, and hand it back.

        :param serial: the request's serial.
        :param path: the image file.
        """
        holding: AbstractContextManager[None] = (
            nullcontext() if self.__coordinator is None else self.__coordinator.holding()
        )
        with holding:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid() and max(size.width(), size.height()) > THUMBNAIL_SIDE:
                reader.setScaledSize(
                    size.scaled(QSize(THUMBNAIL_SIDE, THUMBNAIL_SIDE), Qt.AspectRatioMode.KeepAspectRatio)
                )
            image = reader.read()
        try:
            self.image_ready.emit(serial, image, size if size.isValid() else image.size())
        except RuntimeError:  # the preview was destroyed while the read was out
            pass

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
