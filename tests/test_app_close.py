"""An online close must terminate the process, including native media teardown."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_media import media as media


ROOT = Path(__file__).resolve().parents[1]

CHILD = r'''
import faulthandler
import sys
import time
from pathlib import Path

faulthandler.enable()
faulthandler.dump_traceback_later(10)
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_online import Client
from dubbing_online_client.repository import RemoteDocumentRepository
from PySide6.QtCore import QObject, Property, QTimer, Signal
from PySide6.QtGui import QWindow
from substance import app as entry
from substance.backend import Backend

mode, media_path = sys.argv[1:]
original_app_init = entry.DesktopApplication.__init__
def app_init(self, argv):
    original_app_init(self, argv)
    # Native/helper windows must not keep an accepted editor close alive.
    self.setQuitOnLastWindowClosed(False)
entry.DesktopApplication.__init__ = app_init

original_init, original_shutdown = Backend.__init__, Backend.shutdown
backends = []
def init(self):
    original_init(self)
    client = Client()
    original_request = client.request
    def delayed_request(method, path, body=None):
        if method == 'PUT':
            time.sleep(.05)
        return original_request(method, path, body)
    client.request = delayed_request
    repo = RemoteDocumentRepository(client, 'user', 'project', 'episode', self.data_dir / 'online')
    repo.open()
    document = self.online._document(repo.snapshot)
    self._set_document(document, '')
    self.online.repository = repo
    self.online.context = {'episode_name': 'Close test', 'project_id': 'project', 'episode_id': 'episode'}
    self.online._last_snapshot = document.to_dict()
    self.editor.project_mode = True
    self.editor.validator = self.online.validate_edit
    backends.append(self)

def shutdown(self):
    assert self.online.repository.client.wire['cues'][0]['translation'] == 'Последняя правка'
    assert not self.online.pending
    # Media must be unloaded before the QML-owned video sink is destroyed.
    assert self.media_controller.player.source().isEmpty()
    assert self.media_controller.player.videoSink() is None
    original_shutdown(self)
    assert all(not thread.isRunning() for thread, worker in self.media_controller._workers)
Backend.__init__, Backend.shutdown = init, shutdown

class HeadlessChrome(QObject):
    sidebarRequested = Signal()
    settingsRequested = Signal()
    @Property(bool, constant=True)
    def nativeToolbarActive(self): return False
    @Property('QVariantMap', constant=True)
    def platformPalette(self): return {}
    def __init__(self, backend, app):
        super().__init__(app)
        self.app, self.backend = app, backend
    def configure(self, window):
        self.window = window
        self.helper = QWindow()
        self.helper.show()
        def close():
            self.backend.select(0, 0)
            self.backend.stage('text', 'Последняя правка')
            window.findChild(QObject, 'autoPortraitsDialog').show()
            window.findChild(QObject, 'hardsubDialog').show()
            if mode == 'system':
                self.app.quit()
            else:
                window.close()
        QTimer.singleShot(400, close)
    def detach(self):
        assert not self.window.isVisible()
        assert not self.window.findChild(QObject, 'autoPortraitsDialog').isVisible()
        assert not self.window.findChild(QObject, 'hardsubDialog').isVisible()
        self.helper.hide()
entry.MacOSIntegration = HeadlessChrome
sys.argv = ['substance-close-test', '--media', media_path]
assert entry.main() == 0
print('CLEAN EXIT', flush=True)
'''


@pytest.mark.parametrize('mode', ['window', 'system'])
def test_online_close_exits_with_media_and_auxiliary_windows(tmp_path, media, mode):
    env = dict(os.environ, SUBSTANCE_DATA_DIR=str(tmp_path), SUBSTANCE_STYLE='Fusion',
               QT_QPA_PLATFORM='offscreen', QT_FFMPEG_DECODING_HW_DEVICE_TYPES=',')
    result = subprocess.run([sys.executable, '-c', CHILD, mode, str(media)], cwd=ROOT,
                            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CLEAN EXIT' in result.stdout
