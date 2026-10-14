"""Project schema, review conflicts, character links and embedded resources."""
from copy import deepcopy
import json
import pytest
from substance.document import Document, parse_srt, save_document, load_document, export_document
from substance.editor import Editor, quality
from substance.project import sync_characters


def editor():
    e = Editor(parse_srt('1\n00:00:01,000 --> 00:00:03,000\nHello world\n'))
    e.project_mode = True
    e.update(0, character='Mika')
    return e


def test_keyboard_character_assignment_identity_creation_and_undo():
    e = editor()
    cid = e.save_character('', 'ПРАЙД', ['Pride'], 'PRIDE', '', '', '')
    e.assign_character_name([0], 'прайд')
    assert e.document.cues[0].character_id == cid
    assert e.document.cues[0].character == 'ПРАЙД'
    e.assign_character_name([0], 'pride')
    assert e.document.cues[0].character_id == cid
    before = e.document.to_dict()
    with pytest.raises(ValueError, match='Подтвердите'):
        e.assign_character_name([0], 'Новое имя')
    assert e.document.to_dict() == before
    e.assign_character_name([0], '  Новое имя  ', create=True)
    assert e.document.cues[0].character == 'Новое имя'
    assert len(e.document.characters) == len(before['characters']) + 1
    e.undo()
    assert e.document.to_dict() == before
    e.redo()
    e.assign_character_name([0], '')
    assert e.document.cues[0].character_id == ''
    assert e.document.cues[0].character == ''


def test_plain_subtitle_character_assignment_does_not_require_project():
    e = Editor(parse_srt('1\n00:00:01,000 --> 00:00:03,000\nHello\n'))
    e.assign_character_name([0], 'ПРАЙД', create=True)
    e.assign_character_name([0], 'прайд')
    assert e.document.cues[0].character == 'ПРАЙД'
    assert not e.document.cues[0].character_id
    assert not e.document.characters


def test_v1_migration_preserves_legacy_and_unknown_data():
    data = parse_srt('1\n00:00:00,000 --> 00:00:02,000\nOriginal\n').to_dict()
    data['schema_version'] = 1
    data['cues'][0]['status'] = 'done'
    data['future'] = {'keep': True}
    doc = Document.from_dict(data)
    sync_characters(doc)
    result = doc.to_dict()
    assert result['schema_version'] == 2
    assert 'status' not in result['cues'][0]
    assert result['cues'][0]['extras']['status'] == 'done'
    assert result['future'] == {'keep': True}
    assert not doc.reviews


def test_note_edit_resolve_delete_and_undo():
    e = editor()
    rid = e.add_review(e.document.cues[0].id, 'Check the name')
    e.edit_note(rid, 'Use surname')
    e.review_state(rid, 'resolved')
    assert e.document.reviews[0].state == 'resolved'
    e.undo()
    assert e.document.reviews[0].state == 'open'
    e.delete_note(rid)
    assert not e.document.reviews
    e.undo()
    assert e.document.reviews[0].text == 'Use surname'


def test_proposal_is_separate_from_text_and_application_is_atomic():
    e = editor()
    cid = e.document.cues[0].id
    rid = e.add_review(cid, 'Shorter', replacement=r'{\i1}Hello!{\i0}\NBye', target='translation')
    assert e.document.cues[0].output_text == 'Hello world'
    e.apply_proposal(rid)
    assert e.document.cues[0].translation == r'{\i1}Hello!{\i0}\NBye'
    assert e.document.cues[0].original == 'Hello world'
    assert e.document.reviews[0].state == 'applied'
    e.undo()
    assert e.document.cues[0].translation is None
    assert e.document.reviews[0].state == 'open'
    e.redo()
    assert e.document.reviews[0].state == 'applied'


def test_other_proposals_become_stale_and_cannot_overwrite_edits():
    e = editor()
    cid = e.document.cues[0].id
    first = e.add_review(cid, '', replacement='Hi')
    second = e.add_review(cid, '', replacement='Greetings')
    e.apply_proposal(first)
    before = e.document.to_dict()
    with pytest.raises(ValueError, match='Пересмотрите'):
        e.apply_proposal(second)
    assert e.document.to_dict() == before
    e.rebase_proposal(second, cid, 'Hello again', 'Reviewed current wording')
    e.apply_proposal(second)
    assert e.document.cues[0].text == 'Hello again'


def test_structural_edits_keep_notes_and_invalidate_proposals():
    e = editor()
    cid = e.document.cues[0].id
    note = e.add_review(cid, 'Pronunciation')
    proposal = e.add_review(cid, '', replacement='Hi!')
    e.split(0, 5, 2000)
    assert e.document.reviews[0].cue_ids == [c.id for c in e.document.cues]
    with pytest.raises(ValueError):
        e.apply_proposal(proposal)
    e.merge([0, 1])
    assert e.document.reviews[0].cue_ids == [e.document.cues[0].id]
    e.delete([0])
    assert len(e.document.reviews) == 2
    assert e.document.reviews[0].context == 'Hello world'
    with pytest.raises(ValueError):
        e.apply_proposal(proposal)
    e.undo()
    assert e.document.reviews[0].cue_ids == [e.document.cues[0].id]


def test_duplicate_does_not_duplicate_review_records():
    e = editor()
    cid = e.document.cues[0].id
    e.add_review(cid, 'Note')
    e.duplicate([0])
    assert len(e.document.reviews) == 1
    assert e.document.reviews[0].cue_ids == [cid]
    assert e.document.cues[1].character_id == e.document.cues[0].character_id


def test_rename_character_keeps_links_and_export_uses_export_name(tmp_path):
    e = editor()
    cid = e.document.cues[0].character_id
    e.save_character(cid, 'Мика', ['Mika'], 'MIKA', 'Detective', 'Formal', 'Use surname')
    assert e.document.cues[0].character_id == cid
    assert e.document.cues[0].character == 'Мика'
    output = tmp_path / 'out.ass'
    export_document(e.document, output)
    assert ',MIKA,' in output.read_text()
    assert not (tmp_path / 'out.ass.substance').exists()
    e.undo()
    assert e.document.cues[0].character == 'Mika'
    with pytest.raises(ValueError):
        e.delete_character(cid)
    e.assign_character([0], '')
    e.delete_character(cid)
    assert not e.document.characters


def test_project_roundtrip_and_ass_sidecar_excludes_project_data(tmp_path):
    e = editor()
    e.add_review(e.document.cues[0].id, 'Private project note')
    e.document.review_settings = {'lineLength': False, 'readingSpeed': False}
    path = tmp_path / 'work.substance'
    save_document(e.document, path)
    assert load_document(path).to_dict() == e.document.to_dict()
    output = tmp_path / 'out.ass'
    save_document(e.document, output)
    sidecar = json.loads(output.with_name('out.ass.substance').read_text())
    assert all(k not in sidecar for k in ('reviews', 'characters', 'images', 'review_settings'))
    assert all(not c['character_id'] for c in sidecar['cues'])
    assert 'Private project note' not in output.read_text()
    assert not load_document(output).reviews


def test_warning_switches_preserve_other_issues_and_metrics():
    e = editor()
    cue = e.document.cues[0]
    cue.text = 'A' * 60 + r'\Nsecond\Nthird'
    cue.start = cue.end = 1000
    info = quality(cue, show_length=False, show_speed=False, show_lines=False)
    assert info['messages'] == ['Нулевой интервал']
    assert info['maxLine'] == 60
    assert info['characters'] == 71


def test_unknown_record_fields_survive():
    e = editor()
    e.add_review(e.document.cues[0].id, 'Note')
    data = e.document.to_dict()
    data['reviews'][0]['future'] = {'yes': 1}
    data['characters'][0]['future'] = 2
    restored = Document.from_dict(data).to_dict()
    assert restored['reviews'][0]['extras']['future'] == {'yes': 1}
    assert restored['characters'][0]['extras']['future'] == 2


@pytest.mark.parametrize('change', [lambda d: d['cues'][0].update(character_id='unknown'), lambda d: d['reviews'][0].update(state='invalid'), lambda d: d['review_settings'].update(lineLength='false'), lambda d: d['images'].update(bad='bad'), lambda d: d['characters'].append(deepcopy(d['characters'][0]))])
def test_invalid_project_rejected(change):
    e = editor()
    e.add_review(e.document.cues[0].id, 'Note')
    data = e.document.to_dict()
    change(data)
    with pytest.raises(ValueError):
        Document.from_dict(data)


def test_switching_to_translation_requires_rebase_of_text_proposal():
    e = editor()
    cid = e.document.cues[0].id
    rid = e.add_review(cid, '', replacement='Suggested text')
    e.update(0, translation='Current translation')
    with pytest.raises(ValueError, match='Пересмотрите'):
        e.apply_proposal(rid)
    e.rebase_proposal(rid, cid, 'Suggested translation', 'Updated target')
    assert e.document.reviews[0].field == 'translation'
    e.apply_proposal(rid)
    assert e.document.cues[0].translation == 'Suggested translation'
    assert e.document.cues[0].original == 'Hello world'
