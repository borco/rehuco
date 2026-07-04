"""Viewer/editor window for a single ``.rehu`` file: generic fields + Markdown + image strip
([[plugins#plugin-blocks]], [[plugins#browsers]]).
"""

from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QMainWindow
from rehuco_core import RehuDocument

from rehuco_agent.viewer_window_ui import Ui_ViewerWindow

IMAGE_SUFFIXES: Final = {".jpg", ".jpeg", ".png", ".gif"}
"""Recognized sibling-screenshot extensions ([[data-model#image-meanings]])."""

THUMBNAIL_HEIGHT: Final = 120
"""Pixel height thumbnails in the image strip are scaled to."""


class ViewerWindow(QMainWindow):
    """Generic viewer/editor for one ``.rehu`` file ([[plugins#plugin-blocks]]): common fields, Markdown, image strip.

    :param path: filesystem path to the ``.rehu`` file to open.
    """

    def __init__(self, path: Path | str) -> None:
        super().__init__()
        self.ui: Final = Ui_ViewerWindow()
        self.ui.setupUi(self)
        self.addAction(self.ui.actionSave)
        self.ui.saveButton.clicked.connect(self.save)
        self.ui.actionSave.triggered.connect(self.save)

        self.__folder: Final = Path(path).parent
        self.__document: Final = RehuDocument.load(path)
        self.__populate()

    def save(self) -> None:
        """Write the edited title back into the document and atomically save it ([[data-model#write-integrity]])."""
        self.__document.title = self.ui.titleLineEdit.text()
        self.__document.save()

    def __populate(self) -> None:
        """Fill every widget from the loaded document's common-core fields ([[field-schema#resource-types]])."""
        document = self.__document
        self.setWindowTitle(document.title or self.__folder.name)
        self.ui.titleLineEdit.setText(document.title)
        self.ui.publisherLabel.setText(document.publisher)
        self.ui.urlLabel.setText(document.url)
        self.ui.authorsLabel.setText(", ".join(document.authors))
        self.ui.releasedLabel.setText(document.released)
        self.ui.tagsLabel.setText(", ".join(document.advertised_tags))
        self.ui.extraTagsLabel.setText(", ".join(document.extra_tags))

        self.ui.descriptionBrowser.document().setBaseUrl(QUrl.fromLocalFile(f"{self.__folder}/"))
        self.ui.descriptionBrowser.setMarkdown(document.description)

        self.__populate_image_strip()

    def __populate_image_strip(self) -> None:
        """Populate the image strip with sibling ``infoXX.*`` screenshots ([[data-model#image-meanings]])."""
        layout = self.ui.imageStripLayout
        for image_path in sorted(self.__folder.glob("info[0-9][0-9].*")):
            if image_path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            pixmap = QPixmap(str(image_path))
            if pixmap.isNull():
                continue
            thumbnail = QLabel()
            thumbnail.setPixmap(pixmap.scaledToHeight(THUMBNAIL_HEIGHT, Qt.TransformationMode.SmoothTransformation))
            layout.addWidget(thumbnail)
        layout.addStretch()
