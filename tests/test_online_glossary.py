from copy import deepcopy
import base64
import hashlib
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from PySide6.QtTest import QTest
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


def wait(backend):
    for _ in range(300):
        QTest.qWait(10)
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


def test_online_portrait_preserves_open_glossary_draft_and_permissions(backend, monkeypatch):
    messages = []
    monkeypatch.setattr(backend, 'show_error', messages.append)
    session = backend.online.glossary_session
    assert session.begin('char_1', 'character')
    draft = session.draft
    capture(backend)
    assert not backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    assert session.draft == draft and messages
    assert session.discardDraft()
    backend.online._project_state = {'roles': ['director']}
    assert not backend.savePortrait('char_1', '', 0, 0, 1, 1, True)
    assert not backend.online.repository.client.operations
