"""Waveform timing accuracy, transient preservation, and high DPI rendering."""
import numpy as np
import pytest
import shiboken6
from PySide6.QtGui import QImage, QPainter

from substance.media import MediaController, WAVEFORM_PEAK_MS
from substance.visuals import Waveform, waveform_envelope


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
