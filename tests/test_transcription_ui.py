from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, QMetaObject, QEvent, QPointF
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


def test_live_results_follow_new_phrases_until_user_selects_a_result(ui):
    window, backend = ui
    backend.openTranscription()
    dialog = window.findChild(QObject, 'transcriptionDialog')
    backend.speech._preview_rows = [{'start': 1000, 'end': 2000, 'text': r'One\Ntwo'},
                                   {'start': 3000, 'end': 4000, 'text': 'Three'}]
    backend.speech.changed.emit()
    QTest.qWait(40)
    assert dialog.findChild(QObject, 'speechResultList').property('count') == 2
    assert dialog.property('previewIndex') == 1
    dialog.findChild(QObject, 'speechFollowResults').setProperty('checked', False)
    dialog.setProperty('previewIndex', 0)
    backend.speech._preview_rows.append({'start': 5000, 'end': 6000, 'text': 'Four'})
    backend.speech.changed.emit()
    QTest.qWait(30)
    assert dialog.property('previewIndex') == 0
    assert dialog.property('preview')['text'] == 'One\ntwo'
    assert not dialog.findChild(QObject, 'speechPlayPreview').property('enabled')
    assert dialog.property('visible')
    dialog.close()


def test_settings_preview_and_start_fit_small_window(ui):
    window, backend = ui
    backend.openTranscription()
    dialog = window.findChild(QObject, 'transcriptionDialog')
    dialog.resize(800, 680)
    dialog.findChild(QObject, 'speechAdvancedToggle').setProperty('checked', True)
    QTest.qWait(40)
    for name in ('speechResultList', 'speechSubtitlePreview', 'speechStartButton'):
        item = dialog.findChild(QObject, name)
        point = item.mapToScene(QPointF())
        assert point.x() >= 0 and point.y() >= 0, name
        assert point.x() + item.width() <= dialog.width(), name
        assert point.y() + item.height() <= dialog.height(), name
    dialog.close()


@pytest.mark.parametrize('size', [(800, 680), (1280, 900)])
def test_long_recognition_results_keep_cards_clear_of_scrollbar(ui, size):
    window, backend = ui
    backend.openTranscription()
    dialog = window.findChild(QObject, 'transcriptionDialog')
    dialog.resize(*size)
    backend.speech._preview_rows = [{'start': i * 3000, 'end': i * 3000 + 2500,
                                    'text': 'Длинная распознанная фраза для проверки ширины карточки. ' * 3}
                                   for i in range(194)]
    backend.speech.changed.emit()
    QTest.qWait(60)
    results = dialog.findChild(QObject, 'speechResultList')
    scrollbar = results.findChild(QObject, 'speechResultsScrollBar')
    assert results.property('count') == 194
    assert scrollbar.property('size') < 1
    card = results.property('currentItem')
    point = card.mapToItem(results, QPointF(card.width(), card.height()))
    assert point.x() <= scrollbar.x() - 6
    assert 0 < point.y() <= results.height() + 1
    assert results.property('contentX') == 0
    dialog.close()
