"""Inspect every auxiliary desktop window, including native macOS frames.

Run with QT_QPA_PLATFORM=cocoa on macOS, or offscreen with SUBSTANCE_STYLE
set to Fusion/FluentWinUI3 to verify those QML styles separately.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.environ['SUBSTANCE_DATA_DIR'] = tempfile.mkdtemp(prefix='substance-dialog-qa-')
# Native QTest pointer/key helpers hold the GIL. Keep Python-painted waveform
# items on the GUI thread during this test; the application's render loop is
# unchanged. Otherwise a helper can wait for a render thread waiting for Python.
os.environ.setdefault('QSG_RENDER_LOOP', 'basic')
from PySide6.QtCore import QObject, Qt, QUrl, QPointF, QTimer, QEventLoop, qInstallMessageHandler
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtTest import QTest
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuickControls2 import QQuickStyle
import shiboken6
from substance.backend import Backend
from substance.document import load_document
from substance.images import ProjectImageProvider
from substance.macos import MacOSIntegration
from substance import visuals


def wait(ms):
    # QEventLoop releases the GIL while the threaded scene graph calls Python
    # waveform painters. QTest.qWait can deadlock a real Cocoa render loop.
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication([])
    app.setApplicationName('Substance')
    app.setQuitOnLastWindowClosed(False)
    style = os.environ.get('SUBSTANCE_STYLE', 'macOS' if app.platformName() == 'cocoa' else 'Fusion')
    QQuickStyle.setStyle(style)
    qa = root / 'build/qa/dialogs' / style
    qa.mkdir(parents=True, exist_ok=True)
    messages, checks = [], []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    b = Backend()
    b._set_document(load_document(root / 'substance/resources/example.ass'), '')
    b._save_path(str(qa / 'demo.substance'))
    b.addReview('note', 'Сохранять обращение на «вы».', '')
    b.save()
    chrome = MacOSIntegration(b, app) if app.platformName() == 'cocoa' else None
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.rootContext().setContextProperty('backend', b)
    properties = {'startupChromeReady': False}
    if chrome:
        properties['macOSIntegration'] = chrome
    engine.setInitialProperties(properties)
    window = None

    def check(ok, name):
        assert ok, name
        checks.append(name)

    def js(code):
        expression = QQmlExpression(qmlContext(window), window, code)
        expression.evaluate()
        check(not expression.hasError(), code + ': ' + expression.error().toString())

    def capture(name, dialog_name):
        wait(120)
        dialog = window.findChild(QObject, dialog_name)
        check(dialog is not None and dialog.isVisible(), name + ' visible')
        check(dialog is not window and bool(dialog.flags() & Qt.WindowType.WindowTitleHint)
              and not bool(dialog.flags() & Qt.WindowType.FramelessWindowHint), name + ' system title bar')
        check(bool(dialog.title()) and dialog.transientParent() is not None, name + ' title and owner')
        check(not dialog.grabWindow().isNull() and dialog.grabWindow().save(str(qa / (name + '-content.png'))), name + ' content rendered')
        if app.platformName() == 'cocoa':
            import objc
            from ctypes import c_void_p
            from AppKit import NSWindowStyleMaskTitled, NSWindowCloseButton
            native = objc.objc_object(c_void_p=int(dialog.winId())).window()
            check(bool(native.styleMask() & NSWindowStyleMaskTitled) and native.standardWindowButton_(NSWindowCloseButton) is not None,
                  name + ' AppKit titled window with close button')
            check(str(native.title()) == dialog.title(), name + ' AppKit title matches')
            # Whole-window capture includes the system frame and rounded corners.
            subprocess.run(['/usr/sbin/screencapture', '-x', '-o', '-l', str(native.windowNumber()), str(qa / (name + '-window.png'))], check=True, timeout=5)
        return dialog

    try:
        engine.load(QUrl.fromLocalFile(str(root / 'substance/qml/Main.qml')))
        check(bool(engine.rootObjects()), 'QML loaded')
        window = engine.rootObjects()[0]
        if chrome:
            chrome.configure(window)
        window.setProperty('startupChromeReady', True)
        window.requestActivate()
        wait(150)
        if chrome:
            from AppKit import NSApplication
            identifiers = chrome.diagnostics(window)['nativeToolbarItems']
            check('substance.play' not in identifiers and 'substance.settings' in identifiers,
                  'Native toolbar has settings and no playback button')
            item = chrome._delegate.items['substance.settings']
            check(item.image() is not None and item.isEnabled(), 'Native settings icon is available without media')
            check(NSApplication.sharedApplication().sendAction_to_from_(item.action(), item.target(), item),
                  'Native settings action connected')
            wait(60)
            check(window.findChild(QObject, 'settingsDialog').isVisible(), 'Native toolbar opens settings')
            js('settingsDialog.close()')
        for theme in ('light', 'dark'):
            b.preference('theme', theme)
            js('settingsDialog.open()')
            for index, name in enumerate(('appearance', 'sizes', 'timing', 'translation', 'checks', 'shortcuts', 'language')):
                window.findChild(QObject, 'settingsNavigation').setProperty('page', index)
                capture('settings-' + theme + '-' + name, 'settingsDialog')
                if index == 1:
                    for option in b.appearance.timecodeOptions:
                        b.appearance.setValue('general', 'timecodeFont', option['value'])
                        wait(60)
                        check(window.findChild(QObject, 'startField').property('font').family() == option['family'], 'Timecode editor font: ' + option['family'])
                        check(window.findChild(QObject, 'timecodeFontPreview').property('font').family() == option['family'], 'Timecode preview font: ' + option['family'])
                        capture('settings-' + theme + '-timecode-' + option['value'], 'settingsDialog')
                    b.appearance.setValue('general', 'timecodeSize', 28)
                    wait(60)
                    for name in ('startField', 'endField', 'mediaTimecode', 'timecodeFontPreview'):
                        check(window.findChild(QObject, name).property('font').pixelSize() == 28, 'Large timecode size: ' + name)
                    capture('settings-' + theme + '-timecode-large', 'settingsDialog')
                    b.appearance.setValue('general', 'timecodeSize', 12)
                    b.appearance.setValue('general', 'timecodeFont', 'modern')
                if index == 4:
                    spin = window.findChild(QObject, 'readingSpeedLimit')
                    value = spin.property('value')
                    point = spin.mapToScene(QPointF(spin.width() - 8, spin.height() / 2 - 5)).toPoint()
                    QTest.mouseClick(spin.window(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
                    wait(40)
                    check(spin.property('value') == value + 1 and b.cpsLimit == value + 1, 'Stepper applies reading speed')
                    field = spin.property('contentItem')
                    field.forceActiveFocus()
                    field.setProperty('text', '25')
                    QTest.keyClick(spin.window(), Qt.Key.Key_Return)
                    check(spin.property('value') == 25 and b.cpsLimit == 25, 'Typed numeric setting applies on Return')
            js('settingsDialog.close()')
        b.preference('theme', 'system')
        b.appearance.preset('mint')
        b.appearance.setValue('general', 'uiScale', 115)
        b.appearance.setValue('general', 'tableFont', 15)
        b.appearance.setValue('general', 'rowHeight', 44)
        b.appearance.setValue('general', 'wrapRows', True)
        b.appearance.setValue('general', 'timecodeSize', 28)
        b.appearance.setValue('timing', 'videoSide', 'right')
        b.appearance.setValue('timing', 'audioPosition', 'bottom')
        wait(100)
        check(window.grabWindow().save(str(qa / 'workspace-timing-custom.png')), 'Customized timing workspace rendered')
        b.setMode('translation')
        b.appearance.setValue('translation', 'videoSide', 'left')
        b.appearance.setValue('translation', 'tableFirst', False)
        b.appearance.setValue('translation', 'originalBelow', True)
        b.appearance.setValue('translation', 'contextVisible', False)
        b.appearance.setValue('translation', 'audioVisible', False)
        wait(100)
        check(window.grabWindow().save(str(qa / 'workspace-translation-custom.png')), 'Customized translation workspace rendered')
        for group in ('general', 'timing', 'translation'):
            b.appearance.reset(group)
        b.setMode('timing')
        wait(80)
        for ident in ('findDialog', 'shiftDialog', 'leadDialog', 'spellingDialog', 'reviewsDialog', 'characterDialog', 'actorDialog'):
            js(ident + '.open()')
            object_name = 'assignCharacterDialog' if ident == 'actorDialog' else ident
            capture(ident, object_name)
            if ident == 'findDialog':
                js('findDialog.replaceMode = true')
                capture('find-replace', object_name)
            elif ident == 'reviewsDialog':
                js("reviewCompose.create('note')")
                capture('note', 'reviewComposeDialog')
                js('reviewCompose.close()')
                js("reviewCompose.create('proposal')")
                capture('proposal', 'reviewComposeDialog')
                js('reviewCompose.close()')
            elif ident == 'actorDialog':
                window.findChild(QObject, 'assignCharacterName').setProperty('text', 'Новый персонаж')
                QTest.keyClick(app.focusWindow(), Qt.Key.Key_Return)
                confirm = capture('create-character', 'createCharacterConfirmation')
                QTest.keyClick(confirm, Qt.Key.Key_Escape)
                wait(50)
                check(not confirm.isVisible(), 'Nested confirmation closes on Escape')
            js(ident + '.close()')
        js('settingsDialog.open()')
        wait(100)
        widget_errors = []
        def inspect_shortcut():
            widget = app.activeModalWidget()
            try:
                check(widget is not None and widget.windowTitle() == 'Горячая клавиша', 'Shortcut editor native widget visible')
                check(widget.windowHandle().transientParent() == window.findChild(QObject, 'settingsDialog'), 'Shortcut editor belongs to settings')
                check(widget.grab().save(str(qa / 'shortcut-editor-content.png')), 'Shortcut editor rendered')
            except Exception as exc:
                widget_errors.append(str(exc))
            finally:
                if widget:
                    widget.reject()
        QTimer.singleShot(150, inspect_shortcut)
        b.editShortcutDialog('save')
        check(not widget_errors, 'Shortcut editor checks: ' + repr(widget_errors))
        js('settingsDialog.close()')
        b.save()
        for name, action in [('about', b.about), ('import-warnings', b.showImportWarnings)]:
            def inspect_message(name=name):
                widget = app.activeModalWidget()
                try:
                    check(widget is not None, name + ' native message dialog visible')
                    check(widget.grab().save(str(qa / (name + '-content.png'))), name + ' rendered')
                except Exception as exc:
                    widget_errors.append(str(exc))
                finally:
                    if widget:
                        widget.reject()
            QTimer.singleShot(150, inspect_message)
            action()
        original_file_picker = QFileDialog.getOpenFileName
        try:
            # Cancel at the track prompt, before any task reads the synthetic path.
            QFileDialog.getOpenFileName = lambda *args: (str(qa / 'not-read.mkv'), '')
            def inspect_track():
                widget = app.activeModalWidget()
                try:
                    check(widget is not None and widget.windowTitle() == 'Дорожка субтитров', 'Subtitle track native input dialog visible')
                    check(widget.grab().save(str(qa / 'subtitle-track-content.png')), 'Subtitle track dialog rendered')
                except Exception as exc:
                    widget_errors.append(str(exc))
                finally:
                    if widget:
                        widget.reject()
            QTimer.singleShot(150, inspect_track)
            b.importEmbedded()
        finally:
            QFileDialog.getOpenFileName = original_file_picker
        check(not widget_errors, 'Native widget dialogs: ' + repr(widget_errors))
        image = QImage(640, 360, QImage.Format.Format_RGB32)
        image.fill(QColor('#54879e'))
        b._begin_crop(image, {'cardId': b.current['characterId'], 'crop': [0, 0, 1, 1]})
        capture('portrait-crop', 'portraitCropDialog')
        js('portraitCropDialog.close()')
        js('settingsDialog.open()')
        b.save()
        window.close()
        wait(100)
        visible_windows = [(w.title(), w.objectName(), w.metaObject().className()) for w in app.topLevelWindows() if w.isVisible()]
        check(not visible_windows, 'Closing editor closes auxiliary windows: ' + repr(visible_windows))
        errors = [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'Duplicate method', 'failed to load', 'does not support customization'))]
        check(not errors, 'No QML runtime errors: ' + repr(errors))
        (qa / 'checks.json').write_text(json.dumps({'style': style, 'platform': app.platformName(), 'checks': checks, 'messages': messages}, ensure_ascii=False, indent=2))
    finally:
        if window:
            sidebar = window.findChild(QObject, 'nativeGlassSidebar')
            if sidebar:
                sidebar.detach()
            if chrome:
                chrome.detach()
            shiboken6.delete(window)
        shiboken6.delete(engine)
        b.shutdown()
        qInstallMessageHandler(previous)
    print(f'{len(checks)} dialog checks passed; {qa}')


if __name__ == '__main__':
    main()
