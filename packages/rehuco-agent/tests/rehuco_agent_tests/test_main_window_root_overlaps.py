"""Tests for the main window's banner saying which roots of the open ``.rehuco`` overlap (#498), whichever docks are
showing.

What the overlaps say is ``test_root_overlaps``' subject: here what they say is patched, and the window's catalog
told it changed.
"""

from borco_pyside.widgets import MessageBanner, MessageBannerSeverity
from PySide6.QtWidgets import QLabel
from pytest import mark
from pytest_mock import MockerFixture
from pytestqt.qtbot import QtBot
from rehuco_agent.main_window import MainWindow
from rehuco_agent.rehuco.root_overlaps import RootOverlaps

from .test_main_window import mock_persistent_settings  # noqa: F401  # pylint: disable=unused-import
from .test_main_window_verify import catalog_of

pytestmark = mark.usefixtures("stub_settings_pages", "stub_sub_docks")
"""Every window here is built over stub settings pages, and every document it opens over stub sub-docks (#545)."""


def banner_rows(banner: MessageBanner) -> list[tuple[str, str]]:
    """What the banner shows: each row's severity and message.

    :param banner: the banner.
    :returns: ``(severity, text)`` per row, in order.
    """
    rows: list[tuple[str, str]] = []
    for label in banner.findChildren(QLabel):
        row = label.parentWidget()
        if label.wordWrap() and row is not None:
            rows.append((str(row.property("severity")), label.text()))
    return rows


def test_the_banner_says_the_open_catalogs_overlaps_and_hides_once_clean(mocker: MockerFixture, qtbot: QtBot) -> None:
    """Each line the catalog's overlaps say is a warning row on the window's banner; with nothing to say, the banner
    is gone.

    **Test steps:**

    * build a window; make the overlaps say two lines and say they changed
    * verify the banner shows both as warnings
    * make them say nothing and say they changed
    * verify the banner is hidden and holds no rows
    """
    window = MainWindow()
    qtbot.addWidget(window)
    banner = window.findChild(MessageBanner, "banner")
    assert banner is not None
    overlaps = catalog_of(window).overlaps
    messages = mocker.patch.object(RootOverlaps, "messages", new_callable=mocker.PropertyMock)

    messages.return_value = ["Roots overlap: one.", "Roots overlap: two."]
    overlaps.changed.emit()
    assert banner_rows(banner) == [
        (MessageBannerSeverity.WARNING.value, "Roots overlap: one."),
        (MessageBannerSeverity.WARNING.value, "Roots overlap: two."),
    ]
    assert not banner.isHidden()

    messages.return_value = []
    overlaps.changed.emit()
    assert not banner_rows(banner)
    assert banner.isHidden()
