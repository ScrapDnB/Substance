"""Exercise the real AppKit/Qt boundary on macOS, with isolated test state."""
from pathlib import Path
import json
import os
import sys

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ.setdefault('SUBSTANCE_DATA_DIR', '/private/tmp/substance-native-chrome-test')

from PySide6.QtCore import QObject, QPointF, Qt, QUrl, QEventLoop, QTimer, QCoreApplication, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
import shiboken6
from AppKit import NSApplication
from substance.backend import Backend
from substance.document import load_document
from substance.macos import MacOSIntegration
from substance import visuals
from substance.tooltips import NativeToolTip
from PySide6.QtQuick import QQuickItem


def wait(milliseconds):
    # QTest.qWait keeps the Python GIL on some PySide/macOS builds while Metal
    # waits for Python-painted items. A real Qt event loop releases the GIL.
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def type_text(window, text):
    for character in text:
        for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QCoreApplication.postEvent(window, QKeyEvent(kind, Qt.Key.Key_unknown, Qt.KeyboardModifier.NoModifier, character))
    wait(80)


def main():
    app = QApplication([])
    if app.platformName() != 'cocoa':
        raise RuntimeError('Run this check with QT_QPA_PLATFORM=cocoa on macOS')
    app.setApplicationName('Substance Native Test')
    QQuickStyle.setStyle('macOS')
    backend = Backend()
    backend._set_document(load_document(root / 'substance/resources/example.ass'), '')
    chrome = MacOSIntegration(backend, app)
    engine = QQmlApplicationEngine()
    from substance.images import ProjectImageProvider
    engine.addImageProvider("project", ProjectImageProvider(backend))
    engine.rootContext().setContextProperty('backend', backend)
    engine.setInitialProperties({'macOSIntegration': chrome, 'startupChromeReady': False})
    window = None
    checks = []
    def check(condition, name):
        print(name, flush=True)
        if not condition:
            raise AssertionError(name)
        checks.append(name)
    def send(item):
        return NSApplication.sharedApplication().sendAction_to_from_(item.action(), item.target(), item)
    try:
        print('Loading QML', flush=True)
        engine.load(QUrl.fromLocalFile(str(root / 'substance/qml/Main.qml')))
        window = engine.rootObjects()[0]
        print('Attaching AppKit toolbar', flush=True)
        chrome.configure(window)
        window.setProperty('startupChromeReady', True)
        window.requestActivate()
        print('Showing window', flush=True)
        wait(250)
        check(chrome.nativeToolbarActive, 'Real NSToolbar attached')
        identifiers = chrome.diagnostics(window)['nativeToolbarItems']
        media_index = identifiers.index('substance.media')
        check(identifiers[media_index + 1] == 'substance.transcribe', 'Recognition icon immediately follows video')
        check(chrome._delegate.items['substance.transcribe'].image() is not None, 'Recognition uses a real SF Symbol')
        chrome.perform('substance.transcribe')
        wait(100)
        recognition = window.findChild(QObject, 'transcriptionDialog')
        check(recognition.isVisible(), 'Native recognition action opens timing settings')
        output = root / 'build/qa/asr-timing'
        output.mkdir(parents=True, exist_ok=True)
        recognition.grabWindow().save(str(output / 'timing-settings-native.png'))
        recognition.close()
        check(all(chrome.diagnostics(window)[key] for key in ('qtContentViewPreserved', 'qtViewParentPreserved')), 'Qt content view and parent preserved')
        backend.select(3, 0)
        wait(80)
        check(backend.currentIndex == 3 and backend.current['number'] == 4, 'Native scene preserves selected subtitle line')
        backend.select(0, 0)

        available = window.screen().availableGeometry()
        # Cocoa constrains content sizes to the actual screen, including chrome.
        for requested_width, requested_height in ((1100, 760), (1560, 980), (1440, 940)):
            width, height = min(requested_width, available.width() - 20), min(requested_height, available.height() - 120)
            window.resize(width, height)
            wait(100)
            check(window.width() == width and window.height() == height, f'Qt geometry {width}x{height}')

        sidebar = window.findChild(QObject, 'nativeGlassSidebar')
        check(sidebar.active == chrome.liquidGlassAvailable, 'Glass navigation follows runtime availability')
        if sidebar.active:
            host = sidebar._host
            import objc
            from Foundation import NSIndexSet
            check(objc.pyobjc_id(host.effect.contentView()) == objc.pyobjc_id(host.content),
                  'Navigation controls are embedded in glass contentView')
            check(not host.effect.isHidden() and host.effect.frame().size.width > 180,
                  'Native glass follows the QML sidebar geometry')
            check(host.outline.numberOfRows() == 5, 'AppKit outline exposes five accessible navigation filters')
            pending, visited, native_accessible = [chrome._window], set(), False
            while pending and len(visited) < 1000:
                element = pending.pop()
                pointer = int(objc.pyobjc_id(element))
                if pointer in visited:
                    continue
                visited.add(pointer)
                if pointer == int(objc.pyobjc_id(host.outline)):
                    native_accessible = True
                    break
                if element.respondsToSelector_('accessibilityAttributeValue:'):
                    pending.extend(element.accessibilityAttributeValue_('AXChildren') or [])
            check(native_accessible, 'Native navigation is reachable in the window accessibility tree')
            host.outline.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(1), False)
            check(backend.activeFilter == 'warnings', 'Native sidebar filter reaches the backend')
            backend.setFilter('all')
            check(host.outline.selectedRow() == 0, 'Native navigation follows programmatic filter changes')
            host.character.selectItemAtIndex_(1)
            check(NSApplication.sharedApplication().sendAction_to_from_(host.character.action(), host.character.target(), host.character),
                  'Native character popup action connected')
            check(backend._character_filter == backend.characters[0], 'Native character popup filters the document')
            backend.setCharacterFilter('')
            check(host.character.indexOfSelectedItem() == 0, 'Native character popup restores backend selection')
            expression = QQmlExpression(qmlContext(window), window, 'findDialog.open()')
            expression.evaluate()
            wait(80)
            check(not expression.hasError() and window.property('modalOpen') and host.effect.isHidden(),
                  'QML modal overlay immediately hides native glass')
            QQmlExpression(qmlContext(window), window, 'findDialog.close()').evaluate()
            wait(80)
            check(not host.effect.isHidden(), 'Native glass returns after the overlay closes')

        # Register actual AppKit regions and exercise geometry, clipping and teardown.
        viewport = QQuickItem(window.contentItem())
        viewport.setPosition(QPointF(30, 30))
        viewport.setWidth(100)
        viewport.setHeight(40)
        viewport.setClip(True)
        target = QQuickItem(viewport)
        target.setPosition(QPointF(85, 0))
        target.setWidth(100)
        target.setHeight(40)
        tip = NativeToolTip()
        tip.text = 'Нативная подсказка'
        tip.setParentItem(target)
        window.update()
        wait(80)
        region = tip._region
        check(region is not None and region.tag is not None
              and str(region.owner) == tip.text and tip._state[:4] == (115, 30, 15, 40),
              'AppKit tooltip registered with its string owner and clipped viewport')
        target.setX(60)
        window.update()
        wait(80)
        check(tip._state[:4] == (90, 30, 40, 40), 'Native tooltip follows moving and scrolling content')
        tip.text = 'Обновлённая подсказка'
        wait(80)
        check(str(region.owner) == tip.text, 'Native tooltip updates dynamic shortcut and warning text')
        target.setVisible(False)
        window.update()
        wait(80)
        check(region.tag is None and region.owner is None, 'Hidden items remove their native tooltip regions')
        target.setVisible(True)
        window.update()
        wait(80)
        check(region.tag is not None, 'Native tooltip returns when its item becomes visible')
        shiboken6.delete(tip)
        check(region.tag is None, 'Destroyed delegates release native tooltip registrations')
        shiboken6.delete(viewport)

        play = window.findChild(QObject, 'playCueButton')
        apply = window.findChild(QObject, 'applyCueButton')
        image = play.findChild(QObject, 'image')
        image_center = image.mapToScene(QPointF(image.width() / 2, image.height() / 2))
        margins = engine.newQObject(play.property('background')).property('layoutMargins')
        top, bottom = margins.property('top').toNumber(), margins.property('bottom').toNumber()
        play_center = play.mapToScene(QPointF(play.width() / 2, top + (play.height() - top - bottom) / 2))
        check(play.width() >= 44 and image.property('paintedWidth') >= 19 and image.property('paintedHeight') >= 19
              and (image_center - play_center).manhattanLength() < 0.1,
              'Cue playback icon has full size and follows the native bezel center')
        check(play.height() == apply.height() and abs(play.mapToScene(QPointF()).y()
              - apply.mapToScene(QPointF()).y()) < 0.1, 'Playback and apply buttons share height and baseline')
        cue_buttons = {'height': play.height(), 'iconWidth': image.property('paintedWidth'),
                       'iconHeight': image.property('paintedHeight')}

        wave = window.findChild(QObject, 'audioWaveform')
        backend.preference('theme', 'dark')
        wait(80)
        dark = chrome.platformPalette['surface']
        check(max(dark.red(), dark.green(), dark.blue()) - min(dark.red(), dark.green(), dark.blue()) < 2
              and dark.lightnessF() < .25 and wave.property('paletteColors')['surface'] == dark,
              'Native dark semantic palette reaches the waveform')
        backend.preference('theme', 'light')
        wait(80)
        light = chrome.platformPalette['surface']
        check(light.lightnessF() > .9 and wave.property('paletteColors')['surface'] == light,
              'Native light semantic palette reaches the waveform')
        backend.preference('theme', 'system')
        wait(80)

        field = window.findChild(QObject, 'subtitleEditor')
        field.forceActiveFocus()
        field.setProperty('text', '')
        type_text(window, 'Native toolbar draft')
        control = chrome._delegate.mode_control
        control.setSelectedSegment_(1)
        check(send(control), 'Native segmented control action connected')
        wait(100)
        check(backend.mode == 'translation' and backend.editor.document.cues[0].text == 'Native toolbar draft', 'Mode action commits pending text')
        field = window.findChild(QObject, 'subtitleEditor')
        field.forceActiveFocus()
        type_text(window, 'Translation')
        wait(600)
        check(backend.editor.document.cues[0].translation == 'Translation' and field.hasActiveFocus(), 'Typing and focus survive native toolbar')

        backend.stage('start', '00:00:09.000')
        control.setSelectedSegment_(0)
        send(control)
        check(backend.mode == 'translation' and control.selectedSegment() == 1, 'Invalid pending time rejects native mode action')
        if sidebar.active:
            host.outline.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex_(1), False)
            check(backend.activeFilter == 'all' and host.outline.selectedRow() == 0,
                  'Invalid pending time rejects native navigation and restores selection')
        backend.stage('start', '00:00:01.000')
        backend.flush()
        backend.editor.saved_revision = backend.editor.revision
        backend.preference('theme', 'dark')
        wait(80)
        check(str(chrome._window.appearance().name()) == 'NSAppearanceNameDarkAqua', 'Native chrome follows dark theme')
        backend.preference('theme', 'light')
        wait(80)
        check(str(chrome._window.appearance().name()) == 'NSAppearanceNameAqua', 'Native chrome follows light theme')
        backend.preference('theme', 'system')
        check(chrome._window.appearance() is None, 'Native chrome restores system appearance')

        check(send(chrome._delegate.items[chrome.SIDEBAR]), 'Native sidebar action connected')
        wait(80)
        check(not window.property('sidebarVisible'), 'Sidebar hides through native toolbar action')
        if sidebar.active:
            check(host.effect.isHidden(), 'Collapsing the sidebar hides its native view')
        send(chrome._delegate.items[chrome.SIDEBAR])
        wait(80)
        check(window.property('sidebarVisible'), 'Sidebar restores through native toolbar action')
        if sidebar.active:
            check(not host.effect.isHidden(), 'Restoring the sidebar restores its native view')

        backend.stage('text', 'Changed translation')
        backend.flush()
        check(send(chrome._delegate.items['substance.undo']), 'Native undo action connected')
        check(backend.editor.document.cues[0].translation == 'Translation', 'Native undo restores translated text')
        check(send(chrome._delegate.items['substance.redo']), 'Native redo action connected')
        check(backend.editor.document.cues[0].translation == 'Changed translation', 'Native redo reapplies translated text')
        check(all(chrome.diagnostics(window)[key] for key in ('qtContentViewPreserved', 'qtViewParentPreserved')), 'Qt hierarchy preserved after all interactions')
        report = chrome.diagnostics(window) | {'checks': checks,
            'cueButtons': cue_buttons,
            'nativeSurface': {'dark': dark.name(), 'light': light.name()}}
    finally:
        if window:
            window.hide()
            sidebar = window.findChild(QObject, 'nativeGlassSidebar')
            if sidebar and sidebar.active:
                host = sidebar._host
                effect = host.effect
                sidebar.detach()
                check(effect.superview() is None and host.delegate.host is None,
                      'Native glass teardown removes views and releases backend callbacks')
            chrome.detach()
            shiboken6.delete(window)
        shiboken6.delete(engine)
        backend.shutdown()
    report['checks'] = checks
    output = Path(os.environ.get('SUBSTANCE_NATIVE_REPORT', str(root / 'build/qa/native-chrome-checks.json')))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(checks)} native checks passed; {output}')


if __name__ == '__main__':
    main()
