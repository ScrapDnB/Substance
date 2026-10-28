"""Audio display changes affect rendered data and remain usable in both workspaces."""
import numpy as np
import pytest
import shiboken6
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QPoint, QPointF, QSettings, QUrl, Qt, qInstallMessageHandler
from PySide6.QtGui import QImage, QInputDevice, QNativeGestureEvent, QPainter, QPointingDevice, QWheelEvent
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.appearance import AppearanceSettings
from substance.backend import Backend
from substance.document import load_document
from substance.media import MediaController
from substance.visuals import Waveform

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('saved,expected', [(None, 'wave'), ('wave', 'wave'),
                                         ('spectrum', 'spectrum'), ('tracks', 'wave'), ('invalid', 'wave')])
def test_audio_background_migrates_and_persists(qt_application, tmp_path, monkeypatch, saved, expected):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    if saved is not None:
        settings.setValue('audioDisplay', saved)
        settings.sync()
    backend = Backend()
    try:
        assert backend.tools.displayMode == expected
        assert backend.tools.editMode == 'tracks'
        backend.tools.setEditMode('boundaries')
        backend.tools.setEditMode('invalid')
        assert backend.tools.editMode == 'boundaries'
        backend.tools.setDisplayMode('tracks')
        assert backend.tools.displayMode == expected
        backend.tools.setDisplayMode('spectrum' if expected == 'wave' else 'wave')
        chosen = backend.tools.displayMode
        backend.settings.sync()
    finally:
        backend.shutdown()
    restored = Backend()
    try:
        assert restored.tools.displayMode == chosen
        assert restored.tools.editMode == 'boundaries'
    finally:
        restored.shutdown()


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
@pytest.mark.parametrize('edit_mode', ['tracks', 'boundaries'])
def test_controls_fit_small_window_with_largest_ui(ui, mode, edit_mode):
    backend, window = ui
    backend.setMode(mode)
    backend.tools.setEditMode(edit_mode)
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


@pytest.mark.parametrize('workspace', ['timing', 'translation'])
@pytest.mark.parametrize('display', ['wave', 'spectrum'])
@pytest.mark.parametrize('edit_mode', ['tracks', 'boundaries'])
def test_trackpad_events_reach_audio_view_and_preserve_pointer_time(ui, workspace, display, edit_mode):
    backend, window = ui
    backend.setMode(workspace)
    backend.editorTools.setDisplayMode(display)
    backend.tools.setEditMode(edit_mode)
    QTest.qWait(80)
    pane = window.findChild(QObject, 'timingAudio' if workspace == 'timing' else 'translationAudio')
    wave = pane.findChild(QObject, 'audioWaveform')
    before = backend.editor.document.to_dict()
    wave.setViewport(5000, 10000)
    QTest.qWait(20)
    local = QPointF(wave.width() * 0.7, wave.height() * 0.6)
    # Exercise navigation through an actual cue's MouseArea, not empty space.
    def descendants(item):
        for child in item.childItems():
            yield child
            yield from descendants(child)

    items = list(descendants(wave.parentItem()))
    drag = next(item for item in items if item.objectName() == 'trackDrag_4')
    if edit_mode == 'tracks':
        local = wave.mapFromItem(drag, QPointF(drag.width() / 2, drag.height() / 2))
    fraction = local.x() / wave.width()
    scene = wave.mapToScene(local)
    global_pos = QPointF(window.mapToGlobal(scene.toPoint()))

    def scroll(pixels, angles=(0, 0), modifiers=Qt.KeyboardModifier.NoModifier,
               phase=Qt.ScrollPhase.ScrollUpdate):
        # Native trackpad events carry angle deltas too; Qt treats zero-angle
        # ScrollUpdate events after an accepted event as compatibility duplicates.
        event = QWheelEvent(scene, global_pos, QPoint(*pixels), QPoint(*angles),
                            Qt.MouseButton.NoButton, modifiers, phase, False)
        event.setTimestamp(scroll.timestamp)
        scroll.timestamp += 10
        QCoreApplication.sendEvent(window, event)

    scroll.timestamp = 10

    scroll((-30, 0), (-30, 0))
    assert wave.viewStart == round(5000 + 30 * 10000 / wave.width())
    assert wave.span == 10000
    scroll((-10, 0), phase=Qt.ScrollPhase.ScrollMomentum)
    assert wave.viewStart > 5000 + 30 * 10000 / wave.width()
    scroll((0, 0), phase=Qt.ScrollPhase.ScrollEnd)
    scroll((0, 0), modifiers=Qt.KeyboardModifier.MetaModifier, phase=Qt.ScrollPhase.ScrollBegin)
    anchor = wave.viewStart + wave.span * fraction
    scroll((0, 12), (0, 12), modifiers=Qt.KeyboardModifier.MetaModifier)
    scroll((0, 0), modifiers=Qt.KeyboardModifier.MetaModifier, phase=Qt.ScrollPhase.ScrollEnd)
    assert 9000 < wave.span < 10000
    assert wave.viewStart + wave.span * fraction == pytest.approx(anchor, abs=1)

    device = QPointingDevice('Test touchpad', 123, QInputDevice.DeviceType.TouchPad,
                             QPointingDevice.PointerType.Finger,
                             QInputDevice.Capability.Position, 2, 0)

    def gesture(kind, value):
        event = QNativeGestureEvent(kind, device, 2, scene, scene, global_pos, value, QPointF())
        QCoreApplication.sendEvent(window, event)

    span = wave.span
    gesture(Qt.NativeGestureType.BeginNativeGesture, 0)
    gesture(Qt.NativeGestureType.ZoomNativeGesture, 0.2)
    gesture(Qt.NativeGestureType.EndNativeGesture, 0)
    assert wave.span == pytest.approx(round(span / 1.2), abs=1)
    assert wave.viewStart + wave.span * fraction == pytest.approx(anchor, abs=1)
    # A second gesture must not reuse the previous gesture's cumulative scale.
    span = wave.span
    gesture(Qt.NativeGestureType.BeginNativeGesture, 0)
    gesture(Qt.NativeGestureType.ZoomNativeGesture, -0.1)
    gesture(Qt.NativeGestureType.EndNativeGesture, 0)
    assert wave.span == pytest.approx(round(span / 0.9), abs=1)
    assert wave.viewStart + wave.span * fraction == pytest.approx(anchor, abs=1.5)
    tracks = pane.findChild(QObject, 'subtitleTracks')
    assert tracks.property('span') == wave.span
    assert tracks.property('viewStart') == wave.viewStart
    assert backend.editor.document.to_dict() == before


@pytest.mark.parametrize('workspace', ['timing', 'translation'])
@pytest.mark.parametrize('display', ['wave', 'spectrum'])
@pytest.mark.parametrize('edit_mode', ['tracks', 'boundaries'])
def test_table_double_click_centers_tracks_without_changing_zoom(ui, monkeypatch, workspace, display, edit_mode):
    backend, window = ui
    backend.setMode(workspace)
    backend.tools.setDisplayMode(display)
    backend.tools.setEditMode(edit_mode)
    QTest.qWait(80)
    pane = window.findChild(QObject, 'timingAudio' if workspace == 'timing' else 'translationAudio')
    wave = pane.findChild(QObject, 'audioWaveform')
    tracks = pane.findChild(QObject, 'subtitleTracks')
    assert tracks.isVisible() == (edit_mode == 'tracks')
    assert wave.showCueRange == (edit_mode == 'boundaries')

    def find_visible(item, name):
        if item.objectName() == name and item.isVisible():
            return item
        for child in item.childItems():
            result = find_visible(child, name)
            if result is not None:
                return result
        return None

    label = find_visible(window.contentItem(), 'tableSource_2')
    assert label is not None
    point = label.mapToScene(QPointF(label.width() / 2, label.height() / 2)).toPoint()
    seeks = []
    monkeypatch.setattr(backend.media_controller, 'seek', seeks.append)
    before = backend.editor.document.to_dict()
    # Both a different row and the already selected row must recenter.
    for _ in range(2):
        wave.setViewport(60000, 2000)
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(20)
        assert backend.currentIndex == 2 and wave.viewStart == 60000
        QTest.mouseDClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(40)
        cue = backend.editor.document.cues[2]
        assert wave.span == 2000
        assert wave.viewStart == round((cue.start + cue.end - wave.span) / 2)
        assert seeks[-1] == cue.start
    assert backend.editor.document.to_dict() == before


@pytest.mark.parametrize('workspace', ['timing', 'translation'])
def test_audio_tabs_switch_background_and_edit_mode_independently(ui, workspace):
    backend, window = ui
    backend.setMode(workspace)
    QTest.qWait(50)
    pane = window.findChild(QObject, 'timingAudio' if workspace == 'timing' else 'translationAudio')
    wave = pane.findChild(QObject, 'audioWaveform')
    tracks = pane.findChild(QObject, 'subtitleTracks')
    display_tabs = pane.findChild(QObject, 'audioDisplaySelector')
    edit_tabs = pane.findChild(QObject, 'audioEditModeSelector')
    assert display_tabs.property('count') == edit_tabs.property('count') == 2
    wave.setViewport(5000, 6000)
    before = backend.editor.document.to_dict()
    height = pane.height()
    selection = backend.currentIndex, set(backend.selection)
    for edit_mode, index in [('boundaries', 1), ('tracks', 0)]:
        point = edit_tabs.mapToScene(QPointF(edit_tabs.width() * (index + .5) / 2, edit_tabs.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        assert backend.tools.editMode == edit_mode
        for display, index in [('spectrum', 1), ('wave', 0)]:
            point = display_tabs.mapToScene(QPointF(display_tabs.width() * (index + .5) / 2, display_tabs.height() / 2)).toPoint()
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            QTest.qWait(20)
            assert backend.tools.displayMode == display and backend.tools.editMode == edit_mode
            assert wave.spectral == (display == 'spectrum')
            assert wave.showCueRange == (edit_mode == 'boundaries')
            assert tracks.isVisible() == (edit_mode == 'tracks')
            assert (wave.viewStart, wave.span) == (5000, 6000)
            assert pane.height() == height
    assert (backend.currentIndex, backend.selection) == selection
    assert backend.editor.document.to_dict() == before


@pytest.mark.parametrize('workspace', ['timing', 'translation'])
@pytest.mark.parametrize('display', ['wave', 'spectrum'])
@pytest.mark.parametrize('edge', ['start', 'end'])
def test_boundaries_handles_edit_current_cue_and_undo(ui, workspace, display, edge):
    backend, window = ui
    backend.setMode(workspace)
    backend.tools.setDisplayMode(display)
    backend.tools.setEditMode('boundaries')
    backend.select(2)
    QTest.qWait(50)
    pane = window.findChild(QObject, 'timingAudio' if workspace == 'timing' else 'translationAudio')
    wave = pane.findChild(QObject, 'audioWaveform')
    wave.setViewport(4000, 6000)
    wave.setProperty('snap', False)
    before = backend.editor.document.to_dict()
    cue = backend.editor.document.cues[2]
    original = cue.start, cue.end
    point = wave.mapToScene(QPointF(wave._x(getattr(cue, edge)), wave.bodyTop + 8)).toPoint()
    target = point + QPoint(40, 0)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(window, target, 30)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    QTest.qWait(30)
    cue = backend.editor.document.cues[2]
    assert (cue.start > original[0] and cue.end == original[1]) if edge == 'start' else (cue.start == original[0] and cue.end > original[1])
    assert (wave.viewStart, wave.span) == (4000, 6000)
    backend.undo()
    assert backend.editor.document.to_dict() == before
