from copy import deepcopy
import base64
import hashlib
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtCore import QEventLoop, QTimer
from substance.backend import Backend
from substance.repositories import online_client
online_client()
from dubbing_online_client.documents import from_lines
from dubbing_online_client.repository import RemoteDocumentRepository
from dubbing_online_client.glossary import RemoteGlossary


class Client:
    url = 'https://example.test'
    def __init__(self):
        self.wire, _, _ = from_lines([{'text': 'Hello', 's': 0, 'e': 2}])
        self.wire['cues'][0]['character_id'] = 'char_1'
        self.wire['cues'][0]['translation'] = ''
        self.rows = [{'id': 'char_1', 'kind': 'character', 'revision': 1, 'data': {'name': 'Alice', 'description': '', 'status': 'draft', 'portraits': [], 'primary': None, 'extras': {}}}]
        self.images, self.operations, self.proposals = {}, [], []
    def request(self, method, path, body=None, **kwargs):
        if kwargs.get('binary'):
            asset = 'img_' + hashlib.sha256(body).hexdigest()
            self.images[asset] = base64.b64encode(body).decode()
            return {'id': asset}
        if path == '/v1/projects/project':
            return {'roles': ['translator']}
        if method in ('PUT', 'POST') and '/glossary' in path:
            self.operations.append(deepcopy(body))
            if path.endswith('/proposals'):
                self.proposals.append(deepcopy(body))
            elif method == 'POST':
                self.rows.append({'id': 'char_2', 'kind': 'character', 'revision': 1, 'data': deepcopy(body['data'])})
            else:
                row = next(r for r in self.rows if path.endswith('/' + r['id']))
                row.update(revision=row['revision'] + 1, data=deepcopy(body['data']))
            return {}
        if path.endswith('/glossary'): return deepcopy(self.rows)
        return {'project_id': 'project', 'episode_id': 'episode', 'revision': 1, 'document': deepcopy(self.wire)}
    def image(self, project, asset):
        return self.images[asset]


@pytest.fixture
def backend(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    backend = Backend()
    client = Client()
    repo = RemoteDocumentRepository(client, 'user', 'project', 'episode', tmp_path / 'online')
    repo.open()
    backend.online.glossary = client.rows
    doc = backend.online._document(repo.snapshot)
    backend._set_document(doc, '')
    backend.online.repository = repo
    backend.online.context = {'project_id': 'project', 'episode_id': 'episode'}
    backend.online._project_state = {'roles': ['translator']}
    backend.online._last_snapshot = doc.to_dict()
    backend.editor.project_mode = True
    backend.editor.validator = backend.online.validate_edit
    glossary = RemoteGlossary(repo)
    glossary.refresh()
    backend.online.glossary_session.attach(glossary)
    assert app is not None
    yield backend
    backend.online.disconnect()
    backend.online._executor.submit(lambda: None).result(timeout=3)
    backend.shutdown()


def test_shared_refresh_updates_undo_without_losing_text_or_sending_cards(backend):
    backend.stage('text', 'Черновик')
    assert backend.flush() and backend.canUndo
    pending = deepcopy(backend.online.repository.snapshot)
    rows = deepcopy(backend.online.glossary)
    rows[0]['data']['name'] = 'Alicia'
    rows[0]['revision'] = 2
    backend.online.apply_glossary(rows, {})
    assert backend.current['character'] == 'Alicia'
    assert backend.online.repository.snapshot == pending
    backend.undo()
    assert backend.editor.document.characters[0].name == 'Alicia'
    assert backend.editor.document.cues[0].character == 'Alicia'
    backend.redo()
    assert backend.editor.document.characters[0].name == 'Alicia'
    assert backend.editor.document.cues[0].translation == 'Черновик'


def test_server_refresh_preserves_draft_and_conflict_comparison(backend):
    session = backend.online.glossary_session
    assert session.begin('char_1', 'character')
    draft = session.draft
    draft['data']['description'] = 'Mine'
    assert session.saveDraft(draft)
    backend.online.repository.client.rows[0]['data']['description'] = 'Other'
    backend.online.repository.client.rows[0]['revision'] = 2
    session.repository.refresh()
    assert session.stale and session.conflicts[0]['field'] == 'description'
    assert not session.rebase({})
    assert session.rebase({'description': 'server'})
    assert session.draft['data']['description'] == 'Other'
    assert not session.stale


def test_read_only_roles_and_archive_disable_writes(backend):
    session = backend.online.glossary_session
    backend.online._project_state = {'roles': ['director']}
    assert not session.canEdit and not session.send()
    backend.online._project_state = {'roles': ['admin'], 'archived': True}
    assert not session.canEdit and not session.canApprove


def capture(backend):
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    backend._begin_crop(image, {'cardId': 'char_1', 'media_path': '/private/video.mkv', 'time': 1234})


def wait_events(milliseconds):
    # Release the GIL while native video/waveform rendering calls Python.
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def wait(backend):
    for _ in range(300):
        wait_events(10)
        if not backend.online.busy:
            return
    pytest.fail('Portrait sync timed out')


def test_online_portrait_uploads_shared_card_and_keeps_episode_undo(backend):
    backend.stage('text', 'Мой перевод')
    assert backend.flush()
    snapshot = deepcopy(backend.online.repository.snapshot)
    capture(backend)
    assert backend.savePortrait('char_1', '', .25, .25, .5, .5, True)
    wait(backend)
    client = backend.online.repository.client
    card = backend.editor.document.characters[0]
    assert len(card.portraits) == 1 and card.primary == card.portraits[0]['id']
    portrait = card.portraits[0]
    assert portrait['crop'] == [.25, .25, .5, .5]
    assert portrait['frame'] == {'time_ms': 1234}
    assert 'media_path' not in str(client.operations)
    assert portrait['source'] in client.images and portrait['image'] in client.images
    assert backend.online.repository.snapshot == snapshot
    backend.undo()
    assert backend.editor.document.characters[0].portraits == card.portraits
    backend.redo()
    assert backend.editor.document.cues[0].translation == 'Мой перевод'


def test_online_recrop_primary_delete_and_new_character(backend):
    capture(backend)
    assert backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    wait(backend)
    portrait_id = backend.editor.document.characters[0].primary
    backend.recropPortrait('char_1', portrait_id)
    assert backend.savePortrait('char_1', '', .25, .25, .5, .5, True)
    wait(backend)
    portraits = backend.editor.document.characters[0].portraits
    assert len(portraits) == 1 and portraits[0]['frame']['time_ms'] == 1234
    capture(backend)
    assert backend.savePortrait('char_1', '', 0, 0, 1, 1, False)
    wait(backend)
    second = backend.editor.document.characters[0].portraits[1]['id']
    backend.portraitAction('char_1', second, 'primary')
    wait(backend)
    assert backend.editor.document.characters[0].primary == second
    backend.portraitAction('char_1', second, 'delete')
    wait(backend)
    assert backend.editor.document.characters[0].primary == portrait_id
    capture(backend)
    assert backend.savePortrait('', 'Bob', 0, 0, 1, 1, True)
    wait(backend)
    assert backend.editor.document.characters[1].name == 'Bob'
    assert backend.editor.document.characters[1].portraits


def test_online_approved_portrait_uses_proposal(backend):
    backend.online.repository.client.rows[0]['data']['status'] = 'approved'
    backend.online.glossary_session.repository.refresh()
    capture(backend)
    assert backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    wait(backend)
    client = backend.online.repository.client
    assert len(client.proposals) == 1 and client.proposals[0]['data']['portraits']
    assert not backend.editor.document.characters[0].portraits


@pytest.mark.parametrize('edited', [False, True])
def test_online_portrait_preserves_open_glossary_draft(backend, edited):
    session = backend.online.glossary_session
    assert session.begin('char_1', 'character')
    draft = session.draft
    if edited:
        draft['data']['description'] = 'Unsent description'
        assert session.saveDraft(draft)
    capture(backend)
    assert backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    wait(backend)
    assert session.draft == draft
    assert RemoteGlossary(backend.online.repository).state['draft'] == draft
    card = backend.online.repository.client.rows[0]
    assert card['data']['portraits']
    assert card['data']['description'] == ''
    assert session.stale
    assert session.rebase({})
    assert session.draft['data']['portraits'] == card['data']['portraits']
    assert session.send()
    wait(backend)
    assert backend.online.repository.client.rows[0]['data']['description'] == ('Unsent description' if edited else '')
    assert backend.online.repository.client.rows[0]['data']['portraits']


def test_online_portrait_blocks_pending_without_losing_either_operation(backend, monkeypatch):
    messages = []
    monkeypatch.setattr(backend, 'show_error', messages.append)
    session = backend.online.glossary_session
    assert session.begin('char_1', 'character')
    session.repository.enqueue()
    pending = deepcopy(session.repository.state['pending'])
    capture(backend)
    assert not backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    assert session.repository.state['pending'] == pending
    assert 'Повторите отправку' in messages[-1]
    session.refresh()
    wait(backend)
    assert backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    wait(backend)
    assert backend.online.repository.client.rows[0]['data']['portraits']


def test_online_portrait_respects_permissions(backend, monkeypatch):
    messages = []
    monkeypatch.setattr(backend, 'show_error', messages.append)
    capture(backend)
    backend.online._project_state = {'roles': ['director']}
    assert not backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    assert 'Нет прав' in messages[-1]
    assert not backend.online.repository.client.operations


def test_portrait_lost_ack_preserves_form_and_retries_same_payload(backend, monkeypatch):
    from dubbing_online_client.api import ApiError
    session = backend.online.glossary_session
    assert session.begin('', 'term')
    draft = session.draft
    draft['data'].update(name='Unsent term', translation='Черновик')
    assert session.saveDraft(draft)
    client = backend.online.repository.client
    original = client.request
    attempts = []

    def request(method, path, body=None, **kwargs):
        if method == 'PUT':
            attempts.append(deepcopy(body))
            if len(attempts) == 1:
                raise ApiError('network_error')
        return original(method, path, body, **kwargs)

    monkeypatch.setattr(client, 'request', request)
    capture(backend)
    assert backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    wait(backend)
    assert session.pending and not session.canRestore
    restored = RemoteGlossary(backend.online.repository)
    assert restored.state['draft'] == draft
    assert restored.state['pending']['images']
    assert restored.state['pending']['images_uploaded']
    session.attach(restored)
    session.retry()
    wait(backend)
    assert not session.pending and session.draft == draft
    assert len(attempts) == 2 and attempts[0] == attempts[1]
    assert client.rows[0]['data']['portraits']


def test_portrait_disk_failure_keeps_form_and_does_not_send(backend, monkeypatch):
    messages = []
    monkeypatch.setattr(backend, 'show_error', messages.append)
    session = backend.online.glossary_session
    assert session.begin('char_1', 'character')
    draft = session.draft

    def fail(*args):
        raise OSError('disk full')

    monkeypatch.setattr('dubbing_online_client.glossary.atomic_json', fail)
    capture(backend)
    assert not backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    assert session.draft == draft and not session.pending
    assert 'disk full' in messages[-1]
    assert not backend.online.repository.client.operations
    assert not backend.online.repository.client.images


def test_qml_video_portrait_saves_with_open_glossary_form(backend, tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import shiboken6
    from PySide6.QtCore import QObject, QPointF, Qt, QUrl, qInstallMessageHandler
    from PySide6.QtQml import QQmlApplicationEngine
    from substance import visuals  # registers Substance QML types
    from substance.images import ProjectImageProvider
    from substance.media import ffmpeg_executable, process_options

    video = tmp_path / 'portrait.mp4'
    subprocess.run([ffmpeg_executable(), '-nostdin', '-v', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=320x180:rate=24:duration=1', '-c:v', 'libx264',
                    '-y', str(video)], check=True, timeout=30, **process_options())
    session = backend.online.glossary_session
    assert session.begin('char_1', 'character')
    draft = session.draft
    draft['data']['description'] = 'Keep this unsent'
    assert session.saveDraft(draft)
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(backend))
    engine.rootContext().setContextProperty('backend', backend)
    root = Path(__file__).resolve().parents[1]
    try:
        engine.load(QUrl.fromLocalFile(str(root / 'substance/qml/Main.qml')))
        assert engine.rootObjects(), messages
        window = engine.rootObjects()[0]
        backend.setMode('translation')
        backend.openMediaPath(str(video))
        for _ in range(300):
            wait_events(10)
            if backend.media_controller.hasVideo and backend.media_controller._sink.videoFrame().isValid():
                break
        assert backend.media_controller.hasVideo
        wait_events(100)
        button = next(b for b in window.findChildren(QObject, 'capturePortraitButton') if b.isVisible())
        assert button.property('enabled') and button.width() > 60 and button.height() > 20

        def screenshot(name):
            if folder := os.environ.get('SUBSTANCE_PORTRAIT_QA'):
                target = Path(folder)
                target.mkdir(parents=True, exist_ok=True)
                assert window.grabWindow().save(str(target / (name + '.png')))

        screenshot('video-button')
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        wait_events(100)
        crop = window.findChild(QObject, 'portraitCropDialog')
        assert crop.isVisible()
        assert crop.property('lockedRatio') == 1
        assert crop.property('cropW') * 320 / (crop.property('cropH') * 180) == pytest.approx(1)
        if folder := os.environ.get('SUBSTANCE_PORTRAIT_QA'):
            assert crop.grabWindow().save(str(Path(folder) / 'square-crop.png'))
        save = crop.findChild(QObject, 'savePortraitCrop')
        assert save.property('enabled')
        point = save.mapToScene(QPointF(save.width() / 2, save.height() / 2)).toPoint()
        QTest.mouseClick(crop, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        wait(backend)
        assert not crop.isVisible()
        assert backend.online.repository.client.rows[0]['data']['portraits']
        assert session.draft == draft
        assert backend.online.repository.client.rows[0]['data']['description'] == ''
        # A genuinely pending operation has a recovery route beside the crop;
        # inspecting it must keep the captured image and selection available.
        session.repository.enqueue()
        session.changed.emit()
        capture(backend)
        wait_events(80)
        saved_crop = [crop.property(k) for k in ('cropX', 'cropY', 'cropW', 'cropH')]
        assert not save.property('enabled')
        open_glossary = crop.findChild(QObject, 'portraitOpenGlossary')
        point = open_glossary.mapToScene(QPointF(open_glossary.width() / 2, open_glossary.height() / 2)).toPoint()
        QTest.mouseClick(crop, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        wait_events(80)
        glossary_window = window.findChild(QObject, 'onlineGlossaryDialog')
        assert glossary_window.isVisible() and glossary_window.transientParent() == crop
        glossary_window.close()
        assert crop.isVisible()
        assert [crop.property(k) for k in ('cropX', 'cropY', 'cropW', 'cropH')] == saved_crop
        wait(backend)
        assert not session.pending and save.property('enabled')
        errors = [m for m in messages if any(s in m for s in (
            'ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign',
            'failed to load', 'does not support customization',
        ))]
        assert not errors, errors
    finally:
        if engine.rootObjects():
            shiboken6.delete(engine.rootObjects()[0])
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)
