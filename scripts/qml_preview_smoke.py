"""Verify hot reload of the real Substance window on a temporary copy of its QML."""
from pathlib import Path
import json
import shlex
import shutil
import sys
import tempfile
import time

from qml_preview import ROOT, PreviewServer, preview_environment

CHILD = '''
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, {root!r})
from PySide6.QtCore import QTimer, QUrl
import shiboken6
from substance import app as entry

class ProbeEngine(entry.QQmlApplicationEngine):
    def __init__(self):
        super().__init__()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.probe)
        self.timer.start(100)
    def load(self, url):
        super().load(QUrl.fromLocalFile({main!r}))
    def probe(self):
        if not self.rootObjects():
            return
        window = self.rootObjects()[0]
        value = window.property('previewProbe')
        if value == 2:
            self.timer.stop()
            assert window.grabWindow().save({image!r}), 'Cannot capture the reloaded window'
        Path({report!r}).write_text(json.dumps(dict(value=value, pointer=shiboken6.getCppPointer(window)[0])))
        if value == 2:
            window.close()

entry.QQmlApplicationEngine = ProbeEngine
sys.argv = ['Substance-preview', '--qml-preview', *sys.argv[1:]]
raise SystemExit(entry.main())
'''


def wait_for_value(report, expected, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = json.loads(report.read_text())
            if result['value'] == expected:
                return result
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(.1)
    raise RuntimeError(f'Hot reload did not reach value {expected}')


def main():
    output = ROOT / 'build/qa/qt612-preview'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='substance-preview-test-') as directory:
        folder = Path(directory)
        shutil.copytree(ROOT / 'substance/qml', folder / 'qml')
        (folder / 'resources').symlink_to(ROOT / 'substance/resources', target_is_directory=True)
        qml = folder / 'qml/Main.qml'
        qml.write_text(qml.read_text().replace('id: window', 'id: window\n    property int previewProbe: 1', 1))
        report = folder / 'report.json'
        child = folder / 'probe.py'
        image = output / 'hot-reload.png'
        image.unlink(missing_ok=True)
        child.write_text(CHILD.format(root=str(ROOT), main=str(qml), report=str(report), image=str(image)))
        launcher = folder / 'Substance-probe'
        launcher.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, str(child)]) + ' "$@"\n')
        launcher.chmod(0o700)
        environment = preview_environment()
        environment['SUBSTANCE_DATA_DIR'] = str(folder / 'state')
        server = PreviewServer(Path.home() / 'Qt/6.12.0/macos/bin/QmlPreviewMcpServer', environment)
        try:
            server.request('initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                           'clientInfo': {'name': 'Substance hot reload verification', 'version': '1'}})
            server.send('notifications/initialized', {})
            response = server.request('tools/call', {'name': 'run_qmlPreview',
                                      'arguments': {'executable_path': str(launcher)}})
            assert not response.get('isError'), response
            before = wait_for_value(report, 1)
            # Let Qt finish its initial watcher setup before touching the source.
            time.sleep(1)
            qml.write_text(qml.read_text().replace('previewProbe: 1', 'previewProbe: 2'))
            after = wait_for_value(report, 2)
            assert before['pointer'] == after['pointer'], (before, after)
            deadline = time.monotonic() + 5
            while (not image.is_file() or not image.stat().st_size) and time.monotonic() < deadline:
                time.sleep(.1)
            assert image.is_file() and image.stat().st_size, 'The reloaded window did not produce a screenshot'
            result = {'before': before, 'after': after, 'sameWindow': True, 'screenshot': str(image)}
            (output / 'result.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            server.close()


if __name__ == '__main__':
    main()
