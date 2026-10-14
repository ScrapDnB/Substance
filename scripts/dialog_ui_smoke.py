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
from PySide6.QtCore import QObject, Qt, QUrl, QPointF, QTimer, qInstallMessageHandler
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
        QTest.qWait(120)
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
        QTest.qWait(150)
        for theme in ('light', 'dark'):
            b.preference('theme', theme)
            js('settingsDialog.open()')
            for index, name in enumerate(('interface', 'document', 'shortcuts')):
                window.findChild(QObject, 'settingsTabs').setProperty('page', index)
                capture('settings-' + theme + '-' + name, 'settingsDialog')
                if index == 0:
                    spin = window.findChild(QObject, 'readingSpeedLimit')
                    value = spin.property('value')
                    point = spin.mapToScene(QPointF(spin.width() - 8, spin.height() / 2 - 5)).toPoint()
                    QTest.mouseClick(spin.window(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
                    QTest.qWait(40)
                    check(spin.property('value') == value + 1 and b.cpsLimit == value + 1, 'Stepper applies reading speed')
                    field = spin.property('contentItem')
                    field.forceActiveFocus()
                    field.setProperty('text', '25')
                    QTest.keyClick(spin.window(), Qt.Key.Key_Return)
                    check(spin.property('value') == 25 and b.cpsLimit == 25, 'Typed numeric setting applies on Return')
            js('settingsDialog.close()')
        b.preference('theme', 'system')
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
                QTest.qWait(50)
                check(not confirm.isVisible(), 'Nested confirmation closes on Escape')
            js(ident + '.close()')
        js('settingsDialog.open()')
        QTest.qWait(100)
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
        QTest.qWait(100)
        visible_windows = [(w.title(), w.objectName(), w.metaObject().className()) for w in app.topLevelWindows() if w.isVisible()]
        check(not visible_windows, 'Closing editor closes auxiliary windows: ' + repr(visible_windows))
        errors = [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'Duplicate method', 'failed to load'))]
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
