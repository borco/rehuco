"""Tests for ApplicationPaletteChangeNotifier."""

from borco_pyside.theming.application_palette_change_notifier import ApplicationPaletteChangeNotifier
from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget
from pytestqt.qtbot import QtBot


def test_for_application_returns_the_same_shared_instance(qtbot: QtBot) -> None:
    """``for_application`` hands every caller the one notifier per app, not a fresh one each time --
    so many themed-icon handlers share a single application-wide event filter.

    **Test steps:**

    * call ``for_application`` twice for the running app
    * verify both calls return the same object
    """
    del qtbot
    app = QApplication.instance()
    assert isinstance(app, QApplication)

    first = ApplicationPaletteChangeNotifier.for_application(app)
    second = ApplicationPaletteChangeNotifier.for_application(app)

    assert first is second


def test_a_real_palette_change_emits_once(qtbot: QtBot) -> None:
    """A real ``app.setPalette`` emits ``palette_changed`` exactly once.

    **Test steps:**

    * get the app's notifier and record its ``palette_changed`` emissions
    * change the app's palette for real
    * verify the signal fired exactly once
    """
    del qtbot
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    notifier = ApplicationPaletteChangeNotifier.for_application(app)
    emissions: list[None] = []
    notifier.palette_changed.connect(lambda: emissions.append(None))

    original_palette = app.palette()
    try:
        # pylint: disable=duplicate-code
        palette = app.palette()
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("lime"))
        app.setPalette(palette)
        # pylint: enable=duplicate-code

        assert len(emissions) == 1
    finally:
        app.setPalette(original_palette)


def test_repeated_events_for_the_same_palette_coalesce_to_one_emit(qtbot: QtBot) -> None:
    """Several ``ApplicationPaletteChange`` events carrying the *same* palette emit only once.

    Qt fires this event several times per theme switch (four on Windows), all with the identical new
    palette; the old ``paletteChanged`` signal fired once. Coalescing by ``QPalette.cacheKey`` keeps
    each switch to a single rebuild -- without it every themed icon would re-render N times per switch.

    **Test steps:**

    * change the app's palette for real (one genuine change), recording emissions
    * then hand the notifier three more ``ApplicationPaletteChange`` events without changing the palette
    * verify only the one genuine change emitted -- the duplicates were coalesced away
    """
    del qtbot
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    notifier = ApplicationPaletteChangeNotifier.for_application(app)
    emissions: list[None] = []
    notifier.palette_changed.connect(lambda: emissions.append(None))

    original_palette = app.palette()
    try:
        # pylint: disable=duplicate-code
        palette = app.palette()
        palette.setColor(QPalette.ColorRole.ButtonText, QColor("lime"))
        # pylint: enable=duplicate-code
        app.setPalette(palette)  # one genuine change

        for _ in range(3):  # Qt's repeat firings -- same palette, no further change
            QApplication.sendEvent(app, QEvent(QEvent.Type.ApplicationPaletteChange))

        assert len(emissions) == 1
    finally:
        app.setPalette(original_palette)


def test_events_for_a_widget_are_ignored(qtbot: QtBot) -> None:
    """An ``ApplicationPaletteChange`` delivered to a *widget* rather than the app object emits nothing.

    **Test steps:**

    * get the app's notifier and record its ``palette_changed`` emissions
    * send an ``ApplicationPaletteChange`` event to a plain widget
    * verify the signal never fired
    """
    del qtbot
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    notifier = ApplicationPaletteChangeNotifier.for_application(app)
    emissions: list[None] = []
    notifier.palette_changed.connect(lambda: emissions.append(None))

    widget = QWidget()
    QApplication.sendEvent(widget, QEvent(QEvent.Type.ApplicationPaletteChange))

    assert not emissions
