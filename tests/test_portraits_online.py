from copy import deepcopy

import pytest

from test_online_glossary import backend, wait, wait_events


def prepare_auto_portraits(backend, tmp_path):
    from test_portraits_controller import ready
    path = tmp_path / 'auto-video.mp4'
    path.write_bytes(b'local video fixture')
    backend.media_controller.path = str(path)
    p = ready(backend)
    p._revisions = {r['id']: r['revision'] for r in backend.online.glossary_session.entries}
    return p


def wait_auto(backend):
    for _ in range(500):
        wait_events(10)
        if not backend.portraits.busy:
            return
    pytest.fail('Automatic portrait sync timed out')


def test_auto_portraits_use_existing_revision_protected_outbox(backend, tmp_path):
    p = prepare_auto_portraits(backend, tmp_path)
    snapshot = deepcopy(backend.online.repository.snapshot)
    assert p.apply(False)
    wait_auto(backend)
    assert p.rows[0]['applied']
    assert p.saveVisible and p.saveProgress == 1
    assert '1 из 1' in p.saveStatus
    operation = backend.online.repository.client.operations[-1]
    assert operation['base_revision'] == 1 and operation['operation_id']
    assert operation['data']['portraits'][0]['frame'] == {'time_ms': 500}
    assert backend.online.repository.snapshot == snapshot
    assert not backend.editor.undo_stack


def test_auto_portraits_stop_on_changed_card_before_sending(backend, tmp_path):
    p = prepare_auto_portraits(backend, tmp_path)
    backend.online.glossary_session.repository.state['items'][0]['revision'] = 2
    assert p.apply(False)
    wait_auto(backend)
    assert not backend.online.repository.client.operations
    assert 'изменилась' in p.status


def test_auto_portraits_unknown_result_reuses_durable_operation(backend, tmp_path):
    from dubbing_online_client.api import ApiError
    p = prepare_auto_portraits(backend, tmp_path)
    client = backend.online.repository.client
    original_request = client.request
    attempts = []
    def fail_write(method, path, body=None, **kwargs):
        if method == 'PUT' and '/glossary/' in path:
            attempts.append(deepcopy(body))
            raise ApiError('network_error')
        return original_request(method, path, body, **kwargs)
    client.request = fail_write
    assert p.apply(False)
    wait_auto(backend)
    session = backend.online.glossary_session
    assert session.pending and p.rows[0]['pending']
    assert not p.canApply
    queued = deepcopy(session.repository.state['pending']['body'])
    assert queued['operation_id'] == attempts[0]['operation_id']
    client.request = original_request
    session.retry()
    wait(backend)
    p.reconcilePending()
    assert p.rows[0]['applied'] and not p.rows[0]['pending']
    assert client.operations[-1]['operation_id'] == queued['operation_id']


def test_new_character_and_portrait_use_one_online_operation(backend, tmp_path):
    p = prepare_auto_portraits(backend, tmp_path)
    assert p.createCharacter(0, 'New Hero')
    assert p.apply(False)
    wait_auto(backend)
    assert p.rows[0]['applied'] and not p.stale, p.status
    assert not p._new_characters
    card = next(c for c in backend.editor.document.characters if c.name == 'New Hero')
    assert card.primary and p._rows[0]['cardId'] == card.id
    operations = backend.online.repository.client.operations
    assert len(operations) == 1
    assert operations[0].get('base_revision', 0) == 0 and operations[0]['data']['name'] == 'New Hero'
    assert not backend.editor.undo_stack
