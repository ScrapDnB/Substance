"""Audio display changes affect rendered data and remain usable in both workspaces."""
import numpy as np
import pytest
import shiboken6
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QSettings, QUrl, Qt, qInstallMessageHandler
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.appearance import AppearanceSettings
from substance.backend import Backend
from substance.document import load_document
from substance.media import MediaController
from substance.visuals import Waveform

ROOT = Path(__file__).resolve().parents[1]


def test_audio_preferences_validate_and_restore(tmp_path):
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    preferences = AppearanceSettings(settings)
    assert preferences.audio == {'waveGain': 100, 'spectralContrast': 100}
    preferences.setValue('audio', 'waveGain', 999)
    preferences.setValue('audio', 'spectralContrast', -20)
    restored = AppearanceSettings(settings)
    assert restored.audio == {'waveGain': 800, 'spectralContrast': 25}
    for invalid in (float('nan'), float('inf'), True, 'bad'):
        restored.setValue('audio', 'waveGain', invalid)
        restored.setValue('audio', 'spectralContrast', invalid)
        assert restored.audio == {'waveGain': 100, 'spectralContrast': 100}


def test_display_controls_change_pixels_without_changing_audio(qt_application):
    media = MediaController()
    wave = Waveform()
    wave.setWidth(400)
    wave.setHeight(160)
    wave.media = media
    wave.start, wave.end = 50000, 60000
    media.peaks = np.full(40000, 0.1, dtype=np.float32)
    media.spectrum = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (1000, 1))
    peaks, spectrum = media.peaks.copy(), media.spectrum.copy()

    def render():
        image = QImage(400, 160, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        try:
            wave.paint(painter)
        finally:
            painter.end()
        return image

    try:
        normal = render()
        wave.waveGain = 4
        amplified = render()
        assert normal.pixelColor(100, 70) != amplified.pixelColor(100, 70)
        assert normal.pixelColor(100, 17) == amplified.pixelColor(100, 17)
        wave.spectralContrast = 2
        assert render() == amplified
        wave.spectral = True
        high_contrast = render()
        wave.spectralContrast = 1
        normal_spectrum = render()
        assert high_contrast.pixelColor(100, 50).green() > normal_spectrum.pixelColor(100, 50).green()
        assert high_contrast.pixelColor(100, 130).green() < normal_spectrum.pixelColor(100, 130).green()
        wave.waveGain = 0.25
        assert render() == normal_spectrum
        assert media.volume == 1
        np.testing.assert_array_equal(media.peaks, peaks)
        np.testing.assert_array_equal(media.spectrum, spectrum)
    finally:
        shiboken6.delete(wave)
        media.shutdown()


@pytest.fixture
def ui(qt_application, tmp_path, monkeypatch):
    if QQuickStyle.name() != 'Fusion':
        QQuickStyle.setStyle('Fusion')
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    backend = Backend()
    backend._set_document(load_document(ROOT / 'substance/resources/example.ass'), '')
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', backend)
    try:
        engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
        assert engine.rootObjects(), messages
        window = engine.rootObjects()[0]
        QTest.qWait(100)
        yield backend, window
        errors = [m for m in messages if any(s in m for s in (
            'ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign',
            'failed to load', 'is not a function', 'Non-existent',
        ))]
        assert not errors, errors
    finally:
        backend.shutdown()
        if engine.rootObjects():
            shiboken6.delete(engine.rootObjects()[0])
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)


@pytest.mark.parametrize('mode', ['timing', 'translation'])
def test_audio_sliders_keyboard_persistence_and_volume_sync(ui, mode):
    backend, window = ui
    backend.setMode(mode)
    QTest.qWait(80)
    pane = window.findChild(QObject, 'timingAudio' if mode == 'timing' else 'translationAudio')
    wave = pane.findChild(QObject, 'audioWaveform')
    gain = pane.findChild(QObject, 'waveGainSlider')
    contrast = pane.findChild(QObject, 'spectralContrastSlider')
    volume = pane.findChild(QObject, 'audioVolumeSlider')
    before = backend.editor.document.to_dict()
    span = wave.property('span')
    assert gain.property('visible') and not contrast.property('visible')
    gain.forceActiveFocus()
    for _ in range(12):
        QTest.keyClick(window, Qt.Key.Key_Right)
    assert wave.waveGain == 8
    assert AppearanceSettings(backend.settings).audio['waveGain'] == 800
    assert backend.media.volume == 1
    wave.setProperty('spectral', True)
    QTest.qWait(30)
    assert contrast.property('visible') and not gain.property('visible')
    contrast.forceActiveFocus()
    for _ in range(40):
        QTest.keyClick(window, Qt.Key.Key_Right)
    assert wave.spectralContrast == 3
    assert AppearanceSettings(backend.settings).audio['spectralContrast'] == 300
    volume.forceActiveFocus()
    for _ in range(100):
        QTest.keyClick(window, Qt.Key.Key_Left)
    assert backend.media.volume == 0
    backend.media.setVolume(0.42)
    assert volume.property('value') == pytest.approx(42)
    for slider in window.findChildren(QObject, 'volumeSlider'):
        assert slider.property('value') == pytest.approx(0.42)
    for other in window.findChildren(QObject, 'audioWaveform'):
        assert other.waveGain == 8 and other.spectralContrast == 3
    assert backend.editor.document.to_dict() == before
    assert wave.property('span') == span


@pytest.mark.parametrize('mode', ['timing', 'translation'])
def test_controls_fit_small_window_with_largest_ui(ui, mode):
    backend, window = ui
    backend.setMode(mode)
    backend.appearance.setValue('general', 'uiScale', 125)
    backend.appearance.setValue('general', 'sidebarWidth', 340)
    window.resize(980, 650)
    QTest.qWait(100)
    pane = window.findChild(QObject, 'timingAudio' if mode == 'timing' else 'translationAudio')
    backend.appearance.setValue(mode, 'audioHeight', 145)
    QTest.qWait(80)

    def descendants(item):
        for child in item.childItems():
            yield child
            yield from descendants(child)

    for item in descendants(pane):
        if not item.isVisible() or not item.property('activeFocusOnTab'):
            continue
        origin = item.mapToItem(pane, QPointF(0, 0))
        assert origin.x() >= 0 and origin.y() >= 0
        assert origin.x() + item.width() <= pane.width() + 1
        assert origin.y() + item.height() <= pane.height() + 1
    assert not window.grabWindow().isNull()
