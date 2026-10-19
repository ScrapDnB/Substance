"""Sidebar labels and counts fit the viewport as its width and UI scale change."""
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QEventLoop, QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from substance.backend import Backend
from substance.document import Cue, Document
from substance.macos import MacOSIntegration
from substance import visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def settle():
    loop = QEventLoop()
    QTimer.singleShot(100, loop.quit)
    loop.exec()


@pytest.mark.parametrize('native', [False, True], ids=['qml', 'appkit'])
def test_sidebar_resize_and_scale(qt_application, tmp_path, monkeypatch, native):
    if native and qt_application.platformName() != 'cocoa':
        pytest.skip('AppKit requires a real Cocoa window')
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    QQuickStyle.setStyle('Fusion')
    backend = Backend()
    document = Document()
    for i in range(305):
        cue = Cue(start=i * 2000, end=i * 2000 + 1000, text='Тест')
        document.register_source(cue)
        document.cues.append(cue)
    backend._set_document(document, '')
    chrome = MacOSIntegration(backend, qt_application) if native else None
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', backend)
    if chrome:
        engine.setInitialProperties({'macOSIntegration': chrome})
    window = None
    try:
        engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
        window = engine.rootObjects()[0]
        if chrome:
            chrome.configure(window)
        settle()
        sidebar = window.findChild(QObject, 'nativeGlassSidebar')
        if native and not chrome.liquidGlassAvailable:
            pytest.skip('Liquid Glass is unavailable on this macOS version')
        assert sidebar.active == native
        pane = window.findChild(QObject, 'sidebarPane')
        filters = window.findChild(QObject, 'sidebarFilters')
        for scale in (85, 100, 125):
            backend.appearance.setValue('general', 'uiScale', scale)
            for width in (180, 340, 220):
                backend.appearance.setValue('general', 'sidebarWidth', width)
                settle()
                assert pane.width() >= round(260 * scale / 100)
                if native:
                    host = sidebar._host
                    host.content.layoutSubtreeIfNeeded()
                    viewport = host.outline.enclosingScrollView().contentView().bounds()
                    assert host.outline.frame().size.width == pytest.approx(viewport.size.width)
                    for row in range(host.outline.numberOfRows()):
                        cell = host.outline.viewAtColumn_row_makeIfNecessary_(0, row, True)
                        cell.layoutSubtreeIfNeeded()
                        title, count = cell.textField(), cell.subviews()[-1]
                        assert title.frame().size.width >= title.intrinsicContentSize().width
                        assert count.frame().size.width >= count.intrinsicContentSize().width
                        assert title.frame().origin.x + title.frame().size.width < count.frame().origin.x
                        assert cell.frame().origin.x + cell.frame().size.width <= viewport.size.width
                    # An unusually large count can shorten a title, but remains
                    # fully visible and separate from it.
                    count.setStringValue_('9999999')
                    cell.layoutSubtreeIfNeeded()
                    assert count.frame().size.width >= count.intrinsicContentSize().width
                    assert title.frame().origin.x + title.frame().size.width < count.frame().origin.x
                else:
                    column = window.findChild(QObject, 'fallbackSidebar')
                    items = [item for item in column.childItems() if item.property('modelData') is not None]
                    assert len(items) == filters.property('count')
                    for item in items:
                        icon, title, count = item.property('contentItem').childItems()
                        assert title.width() >= title.property('implicitWidth')
                        assert count.width() >= count.property('implicitWidth')
                        assert title.x() + title.width() < count.x()
                        assert count.x() + count.width() <= item.property('contentItem').width() + 1
    finally:
        if window:
            window.hide()
            sidebar = window.findChild(QObject, 'nativeGlassSidebar')
            sidebar.detach()
            if chrome:
                chrome.detach()
            shiboken6.delete(window)
        shiboken6.delete(engine)
        backend.shutdown()
