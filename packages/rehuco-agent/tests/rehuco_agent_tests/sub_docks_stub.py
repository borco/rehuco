"""The stub sub-docks a `DocumentWidget` is built over in a test of anything but the sub-docks themselves (#545);
with the fixtures that install them, imported by name into the package's ``conftest.py``."""

from typing import Final
from unittest.mock import MagicMock

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolBar, QWidget
from pytest import FixtureRequest, fixture
from pytest_mock import MockerFixture
from rehuco_agent.documents.rehu_document_model import RehuDocumentModel


class StubSubDocks(QObject):
    """What a `DocumentWidget` shows a document through, in a test of the dock or the window around it (#545): the
    sub-docks' signals, toolbar, actions and layout state, with no editor, viewer or inspection dock built. The real
    sub-docks are tested in ``test_document_widget.py``; a test that checks what they hold asks for ``real_sub_docks``.

    :param model: the document.
    :param _host: the widget's dock host, unused.
    :param parent: the owning widget.
    """

    status_message: Signal = Signal(str)
    filter_requested: Signal = Signal(str)
    record_activated: Signal = Signal(object)

    def __init__(self, model: RehuDocumentModel, _host: object, *, parent: QObject, **_kwargs: object) -> None:
        super().__init__(parent)
        self.__model: Final = model
        self.toolbar: Final = QToolBar()
        self.save_action: Final = QAction("Save", self)
        self.save_action.triggered.connect(model.save)
        self.revert_action: Final = QAction("Revert", self)
        self.upgrade_action: Final = QAction("Upgrade", self)
        self.conversion_backup_actions: Final = MagicMock()
        self.log_widget: Final = QWidget()

    @property
    def model(self) -> RehuDocumentModel:
        """The document."""
        return self.__model

    @property
    def checksum_actions(self) -> None:
        """No checksum actions: nothing is checked."""

    @property
    def layout_type(self) -> str:
        """The document's layout key, as the real sub-docks compute it."""
        return self.__model.document.plugins.main_key(self.__model.resource_type)

    def toggle_action(self, _tab: object) -> QAction:
        """A fresh toggle; nothing to toggle."""
        return QAction(self)

    def take_focus(self) -> None:
        """Nothing to focus."""

    def detach(self) -> None:
        """Nothing attached."""

    def stop_playback(self) -> None:
        """Nothing playing."""

    def teardown(self) -> None:
        """Nothing built."""

    def save_state(self) -> bytes:
        """A state naming the layout key."""
        return self.layout_type.encode()

    def save_layout_state(self) -> bytes:
        """A layout naming the layout key."""
        return self.layout_type.encode()

    def restore_state(self, _state: bytes) -> bool:
        """Always restored."""
        return True

    def adopt_layout(self, _state: bytes | None) -> None:
        """No docks to lay out."""

    def apply_default_layout(self) -> None:
        """No docks to lay out."""


@fixture(name="real_sub_docks")
def fixture_real_sub_docks() -> None:
    """Build each document's real sub-docks, for a test of what they hold; every other test of a module that uses
    ``stub_sub_docks`` gets :class:`StubSubDocks`."""


@fixture(name="stub_sub_docks")
def fixture_stub_sub_docks(request: FixtureRequest, mocker: MockerFixture) -> None:
    """Build every `DocumentWidget` over :class:`StubSubDocks`, unless the test asks for ``real_sub_docks`` (#545) --
    for the modules that open documents without testing them, each of which uses it module-wide.

    :param request: the test's request, to see whether it asked for the real sub-docks.
    :param mocker: pytest-mock fixture.
    """
    if "real_sub_docks" not in request.fixturenames:
        mocker.patch("rehuco_agent.documents.document_widget.DocumentSubDocks", StubSubDocks)
