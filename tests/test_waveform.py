"""Waveform timing accuracy, transient preservation, and high DPI rendering."""
import numpy as np
import pytest
import shiboken6
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QPainter, QWheelEvent

from substance.media import MediaController, WAVEFORM_PEAK_MS
from substance.visuals import Waveform, waveform_envelope


@pytest.fixture
def navigation_wave(qt_application):
    wave = Waveform()
    wave.setWidth(1000)
    wave.setViewport(5000, 10000)
    yield wave
    shiboken6.delete(wave)


def wheel(wave, pixels=(0, 0), angles=(0, 0), modifiers=Qt.KeyboardModifier.NoModifier,
          x=750, phase=Qt.ScrollPhase.ScrollUpdate, inverted=False):
    event = QWheelEvent(QPointF(x, 60), QPointF(x, 60), QPoint(*pixels), QPoint(*angles),
                        Qt.MouseButton.NoButton, modifiers, phase, inverted)
    wave.wheelEvent(event)
    assert event.isAccepted()


@pytest.mark.parametrize('pixels', [(-37, 0), (0, -37), (-37, -2)])
def test_trackpad_scroll_uses_pixels_and_dominant_axis(navigation_wave, pixels):
    wave = navigation_wave
    wheel(wave, pixels=pixels, angles=(0, -120))
    assert wave.viewStart == 5370  # Ignore angle fallback when pixels are present.
    assert wave.span == 10000
    wheel(wave, pixels=tuple(-v for v in pixels), inverted=True)
    assert wave.viewStart == 5000  # OS direction is already encoded in the deltas.


def test_trackpad_scroll_accumulates_submillisecond_steps_and_stops_at_zero(navigation_wave):
    wave = navigation_wave
    wave.setViewport(0, 1000)
    wave.setWidth(10000)
    for _ in range(10):
        wheel(wave, pixels=(-1, 0))
    assert wave.viewStart == 1
    wheel(wave, pixels=(100, 0))
    assert wave.viewStart == 0
    for _ in range(10):
        wheel(wave, pixels=(-1, 0))
    assert wave.viewStart == 1


@pytest.mark.parametrize('modifiers', [Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.MetaModifier])
def test_wheel_zoom_is_continuous_and_anchored_to_pointer(navigation_wave, modifiers):
    wave = navigation_wave
    anchor = wave.viewStart + wave.span * 0.75
    wheel(wave, angles=(0, 120), modifiers=modifiers)
    assert wave.span == 8000 and wave.viewStart == 6500
    wheel(wave, pixels=(0, 10), modifiers=modifiers)
    assert 7500 < wave.span < 8000
    assert wave.viewStart + wave.span * 0.75 == pytest.approx(anchor, abs=0.5)
    wheel(wave, pixels=(0, -10), modifiers=modifiers)
    assert wave.span == 8000


def test_empty_scroll_phases_and_zoom_limits_do_not_move_view(navigation_wave):
    wave = navigation_wave
    for phase in (Qt.ScrollPhase.ScrollBegin, Qt.ScrollPhase.ScrollEnd):
        wheel(wave, modifiers=Qt.KeyboardModifier.ControlModifier, phase=phase)
    assert (wave.viewStart, wave.span) == (5000, 10000)
    for span, factor in ((1000, 0.5), (300000, 2)):
        wave.setViewport(5000, span)
        wave.zoomAt(factor, 750)
        assert (wave.viewStart, wave.span) == (5000, span)
    wave.setViewport(0, 1000)
    wave.zoomAt(2, 750)
    assert wave.viewStart == 0 and wave.span == 2000
    for invalid in (0, -1, float('nan'), float('inf')):
        wave.zoomAt(invalid, 750)
    assert (wave.viewStart, wave.span) == (0, 2000)


def test_ordinary_mouse_wheel_still_pans(navigation_wave):
    wheel(navigation_wave, angles=(0, -120))
    assert navigation_wave.viewStart == 6250


@pytest.mark.parametrize('view,span,columns', [(0, 1000, 137), (123.25, 500, 300), (990, 100, 100)])
def test_zoomed_out_wave_preserves_transients_and_end_of_audio(view, span, columns):
    peaks = np.zeros(4000, dtype=np.float32)
    peaks[[0, 499, 501, 2501, 3999]] = [0.3, 0.5, 1, 0.75, 0.9]
    actual = waveform_envelope(peaks, view, span, columns)
    expected = []
    for x in range(columns):
        begin = int((view + x * span / columns) / WAVEFORM_PEAK_MS)
        end = int((view + (x + 1) * span / columns) / WAVEFORM_PEAK_MS)
        selected = peaks[begin:end]
        expected.append(float(selected.max()) if len(selected) else 0)
    np.testing.assert_allclose(actual, expected)


def test_extreme_zoom_interpolates_envelope_and_leaves_eof_blank():
    peaks = np.array([0, 1, 0], dtype=np.float32)
    values = waveform_envelope(peaks, 0, 1, 16)
    assert values[3] < values[4] < values[5]
    assert values[6] > values[7] > values[8]
    assert np.all(values[12:] == 0)
    assert not waveform_envelope(peaks, 1000, 1, 16).any()
    assert not waveform_envelope(np.empty(0), 0, 1000, 100).any()


def test_retina_wave_has_detail_within_one_logical_pixel(qt_application):
    media = MediaController()
    wave = Waveform()
    wave.setWidth(1000)
    wave.setHeight(160)
    wave.media = media
    wave.span = 1000
    wave.start, wave.end = 5000, 6000
    media.peaks = np.tile(np.array([0.1, 0.1, 0.9, 0.9], dtype=np.float32), 1000)
    try:
        image = QImage(2000, 320, QImage.Format.Format_RGB32)
        image.setDevicePixelRatio(2)
        painter = QPainter(image)
        try:
            wave.paint(painter)
        finally:
            painter.end()
        # Adjacent device pixels in a single logical pixel resolve separate peaks.
        assert image.pixelColor(246, 140) != image.pixelColor(247, 140)
        # The envelope is antialiased, including intermediate edge coverage.
        colors = {image.pixelColor(246, y).red() for y in range(90, 180)}
        assert len(colors) > 2
    finally:
        shiboken6.delete(wave)
        media.shutdown()
