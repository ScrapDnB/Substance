"""Tooltip regions must follow nonvisual items without waiting for rendered frames."""
from PySide6.QtCore import QCoreApplication
from PySide6.QtQuick import QQuickItem, QQuickWindow
import shiboken6

from substance import tooltips


class Region:
    def __init__(self, window):
        self.rect = self.text = None

    def set(self, rect, text):
        self.rect, self.text = rect, text

    def close(self):
        self.rect = self.text = None


def make_tooltip(monkeypatch):
    monkeypatch.setattr(tooltips.QGuiApplication, 'platformName', lambda: 'cocoa')
    monkeypatch.setattr(tooltips, '_MacRegion', Region)
    monkeypatch.setattr(tooltips, '_WindowsRegion', Region)
    window = QQuickWindow()
    window.resize(400, 300)
    viewport = QQuickItem(window.contentItem())
    viewport.setX(30)
    viewport.setWidth(100)
    viewport.setHeight(40)
    viewport.setClip(True)
    target = QQuickItem(viewport)
    target.setX(85)
    target.setWidth(100)
    target.setHeight(40)
    tip = tooltips.NativeToolTip()
    tip.text = 'Test tooltip'
    tip.setParentItem(target)
    QCoreApplication.processEvents()
    return window, viewport, target, tip


def test_region_follows_nonvisual_ancestors_and_reparenting(monkeypatch):
    window, viewport, target, tip = make_tooltip(monkeypatch)
    try:
        assert not window.isVisible()  # There will be no animation frames.
        assert tip._region.rect.getRect() == (115, 0, 15, 40)
        target.setX(60)
        QCoreApplication.processEvents()
        assert tip._region.rect.getRect() == (90, 0, 40, 40)
        viewport.setX(50)
        QCoreApplication.processEvents()
        assert tip._region.rect.getRect() == (110, 0, 40, 40)
        target.setParentItem(window.contentItem())
        QCoreApplication.processEvents()
        assert tip._region.rect.getRect() == (60, 0, 100, 40)
        viewport.setX(10)
        QCoreApplication.processEvents()
        assert tip._region.rect.getRect() == (60, 0, 100, 40)
    finally:
        shiboken6.delete(window)


def test_hidden_items_clear_the_region_and_deletion_cancels_queued_update(monkeypatch):
    window, viewport, target, tip = make_tooltip(monkeypatch)
    try:
        region = tip._region
        viewport.setVisible(False)
        QCoreApplication.processEvents()
        assert region.rect is None
        viewport.setVisible(True)
        tip.text = 'Updated tooltip'
        QCoreApplication.processEvents()
        assert region.text == 'Updated tooltip'
        target.setX(20)
        shiboken6.delete(tip)
        QCoreApplication.processEvents()
        assert region.rect is None
    finally:
        shiboken6.delete(window)
