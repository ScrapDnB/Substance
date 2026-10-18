"""Appearance persistence and real QML behavior, including an uncommitted edit."""
import json
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QPointF, QSettings, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QFontDatabase, QFontInfo, QFontMetricsF
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.appearance import AppearanceSettings, DEFAULTS
from substance.backend import Backend
from substance.document import load_document
from substance import visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('mode', ['timing', 'translation'])
@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_editor_details_keep_draft_and_actions_accessible_without_video(ui, mode, theme):
    b, window, _ = ui
    b.setMode(mode)
    b.preference('theme', theme)
    # Checks must be available even with the media/context column hidden.
    b.appearance.setValue(mode, 'videoVisible', False)
    b.editor.update(0, text='Длинная строка для проверки читаемости. ' * 4)
    b._refresh()
    b._save_path(str(b.data_dir / 'details.substance'))
    b.addReview('note', 'Сохранить обращение на «вы».', '')
    QTest.qWait(40)
    editor = window.findChild(QObject, 'subtitleEditor')
    editor.setProperty('text', 'Незавершённая правка')
    editor.setProperty('cursorPosition', 7)
    b._stage_timer.stop()
    document = b.editor.document.to_dict()
    panel = window.findChild(QObject, 'timingEditor' if mode == 'timing' else 'translationEditor')

    for name in ('cueChecksToggle', 'cueReviewsToggle'):
        button = panel.findChild(QObject, name)
        assert button.isVisible() and not button.property('checked')
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(20)
        assert button.property('checked')
    assert panel.findChild(QObject, 'cueChecksDetails').isVisible()
    assert window.findChild(QObject, 'subtitleEditor') is editor
    assert editor.property('text') == 'Незавершённая правка'
    assert editor.property('cursorPosition') == 7
    assert b.draft['translation' if mode == 'translation' else 'text'] == 'Незавершённая правка'
    assert b.editor.document.to_dict() == document

    b.appearance.setValue('general', 'uiScale', 125)
    b.appearance.setValue('general', 'sidebarWidth', 340)
    window.resize(980, 650)
    QTest.qWait(40)
    # Expanding long auxiliary content must not scroll primary actions away.
    for name in ('cueChecksToggle', 'cueReviewsToggle', 'applyCueButton'):
        item = panel.findChild(QObject, name)
        point = item.mapToItem(panel, QPointF())
        assert point.x() >= 0 and point.y() >= 0
        assert point.x() + item.width() <= panel.width() + 1
        assert point.y() + item.height() <= panel.height() + 1
    assert not window.grabWindow().isNull()


def test_settings_validation_migration_persistence_and_resets(tmp_path):
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('theme', 'dark')
    settings.setValue('appearance.v1', json.dumps({
        'general': {'uiScale': 999, 'editorFont': 'bad', 'wrapRows': 'false', 'waveColor': 'not-a-color'},
        'timing': {'videoPercent': -10, 'videoSide': 'above'}, 'translation': [],
    }))
    a = AppearanceSettings(settings)
    assert a.general['uiScale'] == 125
    assert a.general['editorFont'] == 16
    assert a.general['wrapRows'] is False
    assert a.general['waveColor'] == ''
    assert a.timing['videoPercent'] == 25 and a.timing['videoSide'] == 'left'
    assert a.translation == DEFAULTS['translation']
    a.setValue('general', 'editorFont', 23)
    a.setValue('general', 'timecodeFont', 'plain')
    a.setValue('general', 'timecodeSize', 28)
    a.setValue('general', 'selectionColor', '#ffff00')
    a.setValue('lightColors', 'editorText', '#123456')
    a.setValue('darkColors', 'editorText', '#fedcba')
    a.setValue('translation', 'videoSide', 'left')
    a.resizeLayout('timing', {'videoPercent': 53, 'audioHeight': 251})
    restored = AppearanceSettings(settings)
    assert restored.general['editorFont'] == 23
    assert restored.timecodeFamily == 'Courier New'
    assert restored.general['timecodeSize'] == 28
    assert restored.timing['audioHeight'] == 251
    assert restored.lightColors['editorText'] == '#123456'
    assert restored.darkColors['editorText'] == '#fedcba'
    a.reset('timing')
    assert a.timing == DEFAULTS['timing']
    assert a.translation['videoSide'] == 'left'
    a.resetSizes()
    assert a.general['editorFont'] == 16 and a.general['selectionColor'] == '#ffff00'
    assert a.general['timecodeFont'] == 'modern'
    assert a.general['timecodeSize'] == 12
    a.setValue('general', 'timecodeSize', 100)
    assert a.general['timecodeSize'] == 28
    a.setValue('general', 'timecodeSize', -1)
    assert a.general['timecodeSize'] == 10
    a.setValue('general', 'timecodeFont', 'missing-font')
    assert a.general['timecodeFont'] == 'modern'
    assert settings.value('theme') == 'dark'
    a.preset('mint')
    assert a.general['waveColor'] == '#45a48b'
    for invalid in (float('nan'), float('inf'), {}, True):
        a.setValue('general', 'uiScale', invalid)
        assert a.general['uiScale'] == 100
    a.setValue('unknown', 'uiScale', 120)
    a.setValue('general', 'unknown', 10)
    a.resizeLayout('general', {'editorFont': 30})
    assert 'unknown' not in a.general


@pytest.mark.parametrize('raw', ['{bad json', '[]', 'null', '42'])
def test_corrupt_preferences_fall_back(tmp_path, raw):
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.Format.IniFormat)
    settings.setValue('appearance.v1', raw)
    assert AppearanceSettings(settings).general == DEFAULTS['general']


@pytest.fixture
def ui(tmp_path, monkeypatch, qt_application):
    if QQuickStyle.name() != 'Fusion':
        QQuickStyle.setStyle('Fusion')
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    b = Backend()
    b._set_document(load_document(ROOT / 'substance/resources/example.ass'), '')
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]
    QTest.qWait(100)

    def js(code):
        expr = QQmlExpression(qmlContext(window), window, code)
        result = expr.evaluate()
        assert not expr.hasError(), expr.error().toString()
        QTest.qWait(40)
        return result

    yield b, window, js
    errors = [m for m in messages if any(s in m for s in (
        'ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign',
        'failed to load', 'is not a function', 'Non-existent',
    ))]
    b.shutdown()
    shiboken6.delete(window)
    shiboken6.delete(engine)
    qInstallMessageHandler(previous)
    assert not errors, errors


def test_live_settings_preserve_edit_and_reorder_real_panels(ui):
    b, w, js = ui
    editor = w.findChild(QObject, 'subtitleEditor')
    before = b.editor.document.to_dict()
    undo_before = b.canUndo
    editor.setProperty('text', 'Незавершённая правка')
    editor.setProperty('cursorPosition', 7)
    b._stage_timer.stop()
    QTest.qWait(30)
    a = b.appearance
    a.setValue('general', 'editorFont', 24)
    a.setValue('general', 'tableFont', 19)
    a.setValue('general', 'rowHeight', 62)
    a.setValue('general', 'wrapRows', True)
    a.setValue('general', 'selectionColor', '#ffff00')
    a.setValue('general', 'accentColor', '#5522aa')
    a.setValue('general', 'waveColor', '#00aa77')
    a.setValue('lightColors', 'editorBackground', '#fff9e5')
    a.setValue('lightColors', 'editorText', '#332211')
    b.preference('theme', 'light')
    a.setValue('timing', 'videoSide', 'right')
    a.setValue('timing', 'audioPosition', 'bottom')
    QTest.qWait(100)
    assert w.findChild(QObject, 'subtitleEditor') is editor
    assert editor.property('text') == 'Незавершённая правка'
    assert editor.property('cursorPosition') == 7
    assert editor.property('font').pixelSize() == 24
    assert b.editor.document.to_dict() == before and b.canUndo == undo_before
    assert b.draft['text'] == 'Незавершённая правка'
    video = w.findChild(QObject, 'timingVideo')
    panel = w.findChild(QObject, 'timingEditor')
    assert video.x() > panel.x()
    wave = w.findChild(QObject, 'audioWaveform')
    assert wave.property('paletteColors')['wave'].name() == '#00aa77'
    assert not w.grabWindow().isNull()
    a.setValue('timing', 'videoVisible', False)
    assert not video.property('visible')
    a.setValue('timing', 'audioVisible', False)
    QTest.qWait(80)
    assert not w.findChild(QObject, 'timingAudio').property('visible')
    a.reset('timing')
    QTest.qWait(80)
    assert video.property('visible') and video.x() < panel.x()
    assert editor.property('text') == 'Незавершённая правка'


def test_translation_layout_independence_and_settings_navigation(ui):
    b, w, js = ui
    b.setMode('translation')
    QTest.qWait(80)
    a = b.appearance
    editor = w.findChild(QObject, 'subtitleEditor')
    editor.setProperty('text', 'Черновик перевода')
    a.setValue('translation', 'videoSide', 'left')
    a.setValue('translation', 'tableFirst', False)
    a.setValue('translation', 'originalBelow', True)
    a.setValue('translation', 'contextVisible', False)
    a.setValue('translation', 'audioVisible', False)
    QTest.qWait(80)
    assert w.findChild(QObject, 'subtitleEditor') is editor
    assert editor.property('text') == 'Черновик перевода'

    assert w.findChild(QObject, 'editorTextLayout').property('columns') == 1
    assert not w.findChild(QObject, 'translationAudio').property('visible')
    video = w.findChild(QObject, 'translationVideo')
    panel = w.findChild(QObject, 'translationEditor')
    assert video.mapToScene(QPointF(0, 0)).x() < panel.mapToScene(QPointF(0, 0)).x()
    button = w.findChild(QObject, 'toolbarSettings')
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint())
    QTest.qWait(60)
    assert w.findChild(QObject, 'settingsDialog').isVisible()
    nav = w.findChild(QObject, 'settingsNavigation')
    dialog = w.findChild(QObject, 'settingsDialog')
    for page in range(7):
        nav.setProperty('page', page)
        QTest.qWait(60)
        assert not dialog.grabWindow().isNull()
    # A user edits the numeric field, rather than calling a backend setter.
    nav.setProperty('page', 1)
    QTest.qWait(40)
    spin = w.findChild(QObject, 'setting_general_editorFont')
    field = spin.property('contentItem')
    field.forceActiveFocus()
    field.setProperty('text', '21')
    QTest.keyClick(dialog, Qt.Key.Key_Return)
    QTest.qWait(40)
    assert a.general['editorFont'] == 21
    assert editor.property('font').pixelSize() == 21
    search = w.findChild(QObject, 'settingsSearch')
    search.setProperty('text', 'аудио')
    QTest.qWait(40)
    def visual_items(item):
        yield item
        for child in item.childItems():
            yield from visual_items(child)
    pages = {item.objectName(): item for item in visual_items(nav) if item.objectName().startswith('settingsPage')}
    assert pages['settingsPage2'].property('visible')
    assert not pages['settingsPage5'].property('visible')
    search.setProperty('text', '')
    a.reset('translation')
    QTest.qWait(80)
    assert a.timing == DEFAULTS['timing']
    assert w.findChild(QObject, 'editorTextLayout').property('columns') == 2
    assert editor.property('text') == 'Черновик перевода'


def test_manual_split_resize_is_saved_and_large_text_stays_accessible(ui):
    b, w, js = ui
    video = w.findChild(QObject, 'timingVideo')
    before = b.appearance.timing['videoPercent']
    split = w.findChild(QObject, 'timingTopSplit')
    for _ in range(150):
        if split.width() > 0 and abs(video.width() / split.width() * 100 - before) < 1:
            break
        QTest.qWait(20)
    assert split.width() > 0 and abs(video.width() / split.width() * 100 - before) < 1
    point = video.mapToScene(QPointF(video.width() + 2, video.height() / 2)).toPoint()
    QTest.mouseMove(w, point, 30)
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(w, point + QPointF(50, 0).toPoint(), 30)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point + QPointF(50, 0).toPoint())
    QTest.qWait(80)
    assert b.appearance.timing['videoPercent'] > before
    assert AppearanceSettings(b.settings).timing['videoPercent'] == b.appearance.timing['videoPercent']
    b.editor.update(0, text='Длинная реплика для проверки переноса. ' * 15)
    b._refresh()
    b.appearance.setValue('general', 'tableFont', 22)
    b.appearance.setValue('general', 'timecodeSize', 28)
    b.appearance.setValue('general', 'wrapRows', True)
    b.appearance.setValue('general', 'uiScale', 125)
    w.resize(980, 650)
    QTest.qWait(100)
    viewport = w.findChild(QObject, 'tableHorizontalViewport')
    assert viewport.property('contentWidth') > viewport.width()
    table = w.findChild(QObject, 'subtitleTable')
    rows = [item for item in table.property('contentItem').childItems() if item.property('sourceIndex') == 0]
    assert rows and rows[0].height() > b.appearance.general['rowHeight']
    assert not w.grabWindow().isNull()


@pytest.mark.parametrize('mode', ['timing', 'translation'])
def test_timecode_font_choice_updates_all_clocks_without_touching_draft(ui, mode):
    b, w, js = ui
    b.setMode(mode)
    QTest.qWait(60)
    editor = w.findChild(QObject, 'subtitleEditor')
    editor.setProperty('text', 'Незавершённый текст')
    editor.setProperty('cursorPosition', 5)
    # Keep a pending draft while cycling through all fonts; the ordinary
    # 550 ms idle commit is independent of appearance changes.
    b._stage_timer.stop()
    before = b.editor.document.to_dict()
    start = w.findChild(QObject, 'startField')
    end = w.findChild(QObject, 'endField')
    original_times = start.property('text'), end.property('text')
    js('settingsDialog.open()')
    w.findChild(QObject, 'settingsNavigation').setProperty('page', 1)
    QTest.qWait(40)
    combo = w.findChild(QObject, 'setting_general_timecodeFont')
    assert combo.property('count') == 5
    spin = w.findChild(QObject, 'setting_general_timecodeSize')
    field = spin.property('contentItem')
    field.forceActiveFocus()
    field.setProperty('text', '28')
    QTest.keyClick(w.findChild(QObject, 'settingsDialog'), Qt.Key.Key_Return)
    QTest.qWait(50)
    assert b.appearance.general['timecodeSize'] == 28
    assert AppearanceSettings(b.settings).general['timecodeSize'] == 28
    w.resize(980, 650)
    def descendants(item):
        for child in item.childItems():
            yield child
            yield from descendants(child)
    for index, option in enumerate(b.appearance.timecodeOptions):
        combo.setProperty('currentIndex', index)
        combo.activated.emit(index)
        QTest.qWait(50)
        assert b.appearance.general['timecodeFont'] == option['value']
        assert AppearanceSettings(b.settings).timecodeFamily == option['family']
        for name in ('startField', 'endField', 'mediaTimecode', 'timecodeFontPreview'):
            assert w.findChild(QObject, name).property('font').family() == option['family']
            assert w.findChild(QObject, name).property('font').bold() == (option['value'] == 'chakra')
            assert w.findChild(QObject, name).property('font').pixelSize() == 28
        assert b.appearance.general['editorFont'] == 16
        media_clock = w.findChild(QObject, 'mediaTimecode')
        assert not media_clock.property('truncated')
        assert media_clock.height() >= media_clock.property('paintedHeight')
        if media_clock.parentItem().property('stacked'):
            assert media_clock.width() >= media_clock.parentItem().width() - 1
        layout = w.findChild(QObject, 'timecodeFieldsLayout')
        for clock in (start, end):
            metrics = QFontMetricsF(clock.property('font'))
            assert clock.width() >= metrics.horizontalAdvance(clock.property('text')) + clock.property('leftPadding') + clock.property('rightPadding')
            assert clock.mapToItem(layout, QPointF(0, 0)).x() + clock.width() <= layout.width() + 1
        if option['value'] == 'chakra':
            assert option['label'] == 'Chakra Petch Bold'
            assert QFontInfo(start.property('font')).family() == 'Chakra Petch'
            assert QFontInfo(start.property('font')).styleName() == 'Bold'
        for wave in w.findChildren(QObject, 'audioWaveform'):
            assert wave.property('timecodeFont').family() == option['family']
            assert wave.property('timecodeFont').pixelSize() == 28
        table = w.findChild(QObject, 'subtitleTable')
        labels = [item for item in descendants(table) if item.property('text') in original_times]
        assert labels and all(label.property('font').family() == option['family'] for label in labels)
        for label in labels:
            assert label.property('font').pixelSize() == 28
            metrics = QFontMetricsF(label.property('font'))
            assert label.width() >= metrics.horizontalAdvance(label.property('text'))
            assert label.height() >= metrics.height()
        assert (start.property('text'), end.property('text')) == original_times
        assert editor.property('text') == 'Незавершённый текст'
        assert editor.property('cursorPosition') == 5
        assert b.editor.document.to_dict() == before
        assert b.draft['translation' if mode == 'translation' else 'text'] == 'Незавершённый текст'
    assert not w.findChild(QObject, 'settingsDialog').grabWindow().isNull()


def test_system_timecode_follows_text_font(ui):
    b, w, js = ui
    b.appearance.setValue('general', 'timecodeFont', 'system')
    for family in ('', 'Arial', 'Georgia', ''):
        b.appearance.setValue('general', 'textFamily', family)
        QTest.qWait(50)
        text_font = w.findChild(QObject, 'subtitleEditor').property('font')
        clock_font = w.findChild(QObject, 'startField').property('font')
        assert QFontInfo(clock_font).family() == QFontInfo(text_font).family()
        assert AppearanceSettings(b.settings).timecodeFamily == b.appearance.timecodeFamily
        assert b.appearance.general['timecodeFont'] == 'system'
    b.appearance.setValue('general', 'timecodeFont', 'classic')
    assert b.appearance.timecodeFamily == 'Verdana'
    assert 'обычный ноль' in b.appearance.timecodeOptions[1]['label']


def test_bundled_chakra_font_and_license_are_packaged(tmp_path):
    import tomllib
    from substance.appearance import register_timecode_font
    assert register_timecode_font() == 'Chakra Petch'
    assert 'Bold' in QFontDatabase.styles('Chakra Petch')
    a = AppearanceSettings(QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat))
    a.setValue('general', 'timecodeFont', 'chakra')
    restored = AppearanceSettings(a.settings)
    assert restored.timecodeFamily == 'Chakra Petch' and restored.timecodeBold
    license_text = (ROOT / 'substance/resources/fonts/ChakraPetch-OFL.txt').read_text()
    assert 'SIL OPEN FONT LICENSE Version 1.1' in license_text
    package = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    assert 'resources/fonts/*' in package['tool']['setuptools']['package-data']['substance']
