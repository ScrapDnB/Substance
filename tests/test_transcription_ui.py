from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, QMetaObject, QEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from substance.backend import Backend
from substance.images import ProjectImageProvider
from substance import visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    QQuickStyle.setStyle('Fusion')
    backend = Backend()
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(backend))
    engine.rootContext().setContextProperty('backend', backend)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects()
    window = engine.rootObjects()[0]
    yield window, backend
    window.hide()
    shiboken6.delete(engine)
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    backend.shutdown()


def test_dialog_is_accessible_from_main_window_and_keeps_start_guarded(ui):
    window, backend = ui
    assert window.findChild(QObject, 'transcriptionMenuItem')
    assert window.findChild(QObject, 'transcribeEmptyDocument')
    media = window.findChild(QObject, 'toolbarMedia')
    transcribe = window.findChild(QObject, 'toolbarTranscribe')
    assert media and transcribe and transcribe.x() > media.x()
    assert not window.findChild(QObject, 'transcribeTable')
    dialog = window.findChild(QObject, 'transcriptionDialog')
    assert dialog
    QMetaObject.invokeMethod(dialog, 'open')
    QTest.qWait(50)
    assert dialog.property('visible')
    assert window.property('modalOpen')
    assert window.findChild(QObject, 'speechModel').property('currentIndex') == 2
    assert not window.findChild(QObject, 'speechStartButton').property('enabled')
    assert window.findChild(QObject, 'speechDownloadModel').property('visible')
    assert window.findChild(QObject, 'speechReadingSpeed').property('value') == 17
    assert window.findChild(QObject, 'speechMaxHold').property('value') == 800
    dialog.close()
    assert not window.property('modalOpen')


def test_native_toolbar_request_opens_recognition_settings(ui):
    window, backend = ui
    backend.openTranscription()
    QTest.qWait(30)
    assert window.findChild(QObject, 'transcriptionDialog').property('visible')
    window.findChild(QObject, 'transcriptionDialog').close()


def test_error_status_and_dismiss_are_visible_in_main_window(ui):
    window, backend = ui
    backend.speech._set_status('Test inference error', True)
    QTest.qWait(20)
    row = window.findChild(QObject, 'transcriptionProgressRow')
    assert row.property('visible')
    assert not window.findChild(QObject, 'speechStopButton').property('visible')
    backend.speech.dismiss()
    QTest.qWait(20)
    assert not row.property('visible')
