"""Regressions found in the Windows Fluent interface audit."""
from pathlib import Path
import sys

import pytest
import shiboken6
from PySide6.QtCore import QObject, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QFontMetricsF, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import load_document
from substance.images import ProjectImageProvider
from substance import tooltips, visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def evaluate(target, code):
    expression = QQmlExpression(qmlContext(target), target, code)
    expression.evaluate()
    assert not expression.hasError(), expression.error().toString()
    QTest.qWait(80)


@pytest.fixture
def ui(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    QQuickStyle.setStyle('FluentWinUI3' if sys.platform == 'win32' else 'Fusion')
    backend = Backend()
    backend._set_document(load_document(ROOT / 'substance/resources/example.ass'), '')
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(backend))
    engine.rootContext().setContextProperty('backend', backend)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]
    QTest.qWait(100)
    try:
        yield backend, window
        assert not [m for m in messages if any(text in m for text in (
            'ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign'))], messages
    finally:
        for child in qt_application.topLevelWindows():
            child.hide()
        backend.shutdown()
        shiboken6.delete(window)
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)


@pytest.mark.parametrize('ui_scale', [100, 125])
def test_compact_translation_keeps_text_and_apply_above_audio(ui, ui_scale):
    backend, window = ui
    backend.setMode('translation')
    backend.appearance.setValue('general', 'uiScale', ui_scale)
    window.resize(980, 650)
    QTest.qWait(200)
    field = window.findChild(QObject, 'subtitleEditor')
    apply = window.findChild(QObject, 'applyCueButton')
    audio = window.findChild(QObject, 'translationAudio')
    assert tooltips.tooltip_rect(field, window).height() >= 48
    apply_bottom = apply.mapToScene(QPointF(0, apply.height())).y()
    audio_top = audio.mapToScene(QPointF(0, 0)).y()
    assert apply_bottom <= audio_top
    before = backend.editor.document.to_dict()
    field.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_A)
    QTest.qWait(50)
    assert 'a' in field.property('text').lower()
    assert backend.editor.document.to_dict() == before  # Still a staged edit.


@pytest.mark.parametrize('name,toggle,button', [
    ('transcriptionDialog', 'speechAdvancedToggle', 'speechStartButton'),
    ('alignmentDialog', 'alignmentAdvancedToggle', 'alignmentApply'),
])
def test_expanded_small_dialog_retains_actions_and_scrollable_options(ui, name, toggle, button):
    _, window = ui
    dialog = window.findChild(QObject, name)
    evaluate(dialog, 'open()')
    dialog.resize(800, 680)
    dialog.findChild(QObject, toggle).setProperty('checked', True)
    QTest.qWait(120)
    action = dialog.findChild(QObject, button)
    top = action.mapToScene(QPointF(0, 0))
    assert top.y() >= 0 and top.y() + action.height() <= dialog.height()
    evaluate(dialog, 'reject()')


def test_slider_steps_survive_removing_windows_tick_marks(ui):
    backend, window = ui
    evaluate(window, 'backend.timingTools.open("shift")')
    dialog = window.findChild(QObject, 'shiftDialog')
    slider = dialog.findChild(QObject, 'shiftSlider')
    slider.forceActiveFocus()
    QTest.keyClick(dialog, Qt.Key.Key_Right)
    assert slider.property('value') == 10
    assert backend.timing.delta == 10
    if sys.platform == 'win32':
        assert slider.property('background').objectName() == 'sliderTrackWithoutTicks'
    evaluate(dialog, 'reject()')


def test_audio_slider_keyboard_steps_with_platform_style(ui):
    backend, window = ui
    volume = window.findChild(QObject, 'audioVolumeSlider')
    volume.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Left)
    assert backend.media.volume == pytest.approx(.99)
    gain = window.findChild(QObject, 'waveGainSlider')
    gain.forceActiveFocus()
    QTest.keyClick(window, Qt.Key.Key_Right)
    assert backend.appearance.audio['waveGain'] == 119
    if sys.platform == 'win32':
        for slider in (volume, gain):
            assert slider.property('background').objectName() == 'sliderTrackWithoutTicks'


@pytest.mark.skipif(sys.platform != 'win32', reason='Fluent numeric field dimensions')
def test_three_digit_settings_fit_the_native_spinbox(ui):
    _, window = ui
    dialog = window.findChild(QObject, 'settingsDialog')
    evaluate(dialog, 'open()')
    dialog.findChild(QObject, 'settingsNavigation').setProperty('page', 1)
    QTest.qWait(80)
    spin = dialog.findChild(QObject, 'setting_general_uiScale')
    content = spin.property('contentItem')
    assert spin.property('value') == 100
    assert content.width() >= QFontMetricsF(spin.property('font')).horizontalAdvance(spin.property('displayText'))
    evaluate(dialog, 'reject()')


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Win32 tooltip lifecycle')
def test_tooltips_recreate_after_dialog_native_window_is_closed(ui):
    if QGuiApplication.platformName() != 'windows':
        pytest.skip('Requires QT_QPA_PLATFORM=windows')
    _, window = ui
    dialog = window.findChild(QObject, 'findDialog')
    generations = []
    for _ in range(3):
        evaluate(dialog, 'open()')
        host = getattr(dialog, '_substance_tooltip_host')
        assert host.user32.IsWindow(host.hwnd)
        assert host.parent == int(dialog.winId())
        generations.append(host.generation)
        assert any(tip._region.info is not None for tip in dialog.findChildren(tooltips.NativeToolTip))
        evaluate(dialog, 'reject()')
        assert host.hwnd is None
    assert generations == sorted(set(generations))
