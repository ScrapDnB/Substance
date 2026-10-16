from pathlib import Path
import hashlib
import json
import os
import pytest

from substance.document import Document, DEFAULT_ASS, parse_ass, parse_srt, load_document, save_document, export_document, plain_text
from substance.editor import Editor, quality
from substance.timecode import parse_time, format_time, frame_time


def fixture_ass():
    return DEFAULT_ASS + 'Dialogue: 4,0:00:01.00,0:00:03.20,Default,Мика,005,010,015,custom,{\\i1}Привет, мир!{\\i0}\\NЕщё строка\n'


def test_exact_roundtrip_and_unknown_sections():
    text = fixture_ass().replace('\n', '\r\n') + '[Unknown]\r\nFoo: xyz\r\n'
    doc = parse_ass(text)
    assert doc.ass_text() == text
    assert doc.cues[0].character == 'Мика'


def test_edit_only_preserves_event_fields_and_header():
    doc = parse_ass(fixture_ass())
    editor = Editor(doc)
    editor.update(0, translation='{\\i1}Hello, world!{\\i0}\\NAnother line')
    result = editor.document.ass_text()
    assert result.startswith(DEFAULT_ASS)
    assert 'Dialogue: 4,0:00:01.00,0:00:03.20,Default,Мика,005,010,015,custom,' in result
    assert editor.document.cues[0].original == doc.cues[0].original


def test_format_text_not_last_and_commas():
    text = '[Events]\nFormat: Start, Text, End, Name\nDialogue: 0:00:01.00,Hello, there,0:00:03.00,Actor\n'
    doc = parse_ass(text)
    assert doc.cues[0].text == 'Hello, there'
    assert doc.ass_text() == text


def test_sort_across_event_formats_preserves_each_cue():
    text = '[Events]\nFormat: Start, Text, End, Name\nDialogue: 0:00:04.00,Later,0:00:06.00,A\nFormat: Name, Start, End, Text\nDialogue: B,0:00:01.00,0:00:03.00,Earlier, with comma\n'
    editor = Editor(parse_ass(text))
    assert editor.document.ass_text() == text
    editor.batch([], 'sort')
    restored = parse_ass(editor.document.ass_text())
    assert [(c.start, c.text, c.character) for c in restored.cues] == [(1000, 'Earlier, with comma', 'B'), (4000, 'Later', 'A')]


def test_ssa_actor_field_survives_edits():
    doc = parse_ass('[Events]\nFormat: Marked, Start, End, Style, Actor, MarginL, MarginR, MarginV, Effect, Text\nDialogue: Marked=0,0:00:01.00,0:00:03.00,Default,A,0,0,0,,Hi\n')
    editor = Editor(doc)
    editor.update(0, character='B', translation='Привет')
    restored = parse_ass(editor.document.ass_text())
    assert restored.cues[0].character == 'B'
    assert restored.cues[0].text == 'Привет'


def test_malformed_ass_events_retained():
    text = fixture_ass() + 'Dialogue: broken\nDialogue: 0,0:00:04.00,0:00:03.00,Default,,0,0,0,,invalid\n'
    doc = parse_ass(text)
    assert len(doc.cues) == 1
    assert len(doc.warnings) == 2
    assert doc.ass_text() == text


def test_zero_length_cues_remain_editable_and_origin_uses_event_index():
    text = DEFAULT_ASS + 'Dialogue: broken\nComment: 0,0:00:00.00,0:00:00.00,Default,,0,0,0,,Note\nDialogue: 0,0:00:01.00,0:00:01.00,Default,,0,0,0,,Needs timing\n'
    doc = parse_ass(text)
    doc.validate()
    assert len(doc.cues) == 2
    assert doc.ass_text() == text
    assert [doc.source_lines[c.id]['origin']['event_index'] for c in doc.cues] == [1, 2]
    assert not quality(doc.cues[0])['warning']
    assert 'Нулевой интервал' in quality(doc.cues[1])['messages']
    editor = Editor(doc)
    editor.update(1, end=2000)
    assert editor.document.cues[1].end == 2000


def test_empty_ass_insert_before_attachments():
    doc = parse_ass(DEFAULT_ASS + '[Fonts]\nfontname: example.ttf\nabc\n')
    editor = Editor(doc)
    editor.add()
    assert editor.document.ass_text().index('Dialogue:') < editor.document.ass_text().index('[Fonts]')


def test_translation_sidecar_is_hash_guarded(tmp_path):
    editor = Editor(parse_ass(fixture_ass()))
    original = editor.document.cues[0].original
    editor.update(0, translation='Hello!')
    path = tmp_path / 'translated.ass'
    save_document(editor.document, path)
    restored = load_document(path)
    assert restored.cues[0].original == original
    assert restored.cues[0].translation == 'Hello!'
    path.write_text(path.read_text(encoding="utf-8").replace('Hello!', 'External!'), encoding="utf-8")
    changed = load_document(path)
    assert changed.cues[0].text == 'External!'
    assert changed.cues[0].translation is None
    assert changed.warnings


def test_project_unknown_fields_preserved(tmp_path):
    data = parse_ass(fixture_ass()).to_dict()
    data['future_extension'] = {'episode': '01'}
    data['cues'][0]['future_cue'] = 'keep'
    doc = Document.from_dict(data)
    path = tmp_path / 'test.substance'
    save_document(doc, path)
    restored = load_document(path).to_dict()
    assert restored['future_extension'] == {'episode': '01'}
    assert restored['cues'][0]['extras']['future_cue'] == 'keep'


def test_reject_newer_project_and_dubbing_manager():
    data = Document().to_dict()
    data['schema_version'] = 100
    with pytest.raises(ValueError):
        Document.from_dict(data)
    with pytest.raises(ValueError, match='Dubbing Manager'):
        Document.from_dict({'metadata': {'format_version': '2.0'}})


def test_encoding_bom_and_line_endings(tmp_path):
    for encoding in ('utf-8-sig', 'utf-16', 'cp1251'):
        path = tmp_path / 'test.ass'
        data = fixture_ass().replace('\n', '\r\n').encode(encoding)
        path.write_bytes(data)
        doc = load_document(path)
        assert doc.ass_bytes() == data


def test_srt_vtt_export_and_plain_tags(tmp_path):
    doc = parse_srt('1\n00:00:01,200 --> 00:00:03,400\n<i>Hello</i>\nWorld\n')
    assert doc.cues[0].start == 1200
    assert plain_text(doc.cues[0].text) == 'Hello\nWorld'
    for ext in ('srt', 'vtt'):
        path = tmp_path / ('test.' + ext)
        export_document(doc, path)
        assert load_document(path).cues[0].start == 1200


def test_explicit_rounding_and_hours():
    assert format_time(3599999, ass=True) == '1:00:00.00'
    assert parse_time('12:34:56.789') == 45296789
    assert parse_time('04:12.48') == 252480
    assert frame_time(1000, 23.976) == 1001
    with pytest.raises(ValueError):
        parse_time('00:64:00.000')


def test_transaction_rollback_and_history_saved_state():
    editor = Editor(parse_ass(fixture_ass()))
    with pytest.raises(ValueError):
        editor.shift([0], -10000)
    assert editor.document.cues[0].start == 1000
    assert not editor.dirty
    editor.update(0, text='Edited')
    editor.mark_saved()
    editor.update(0, text='Next')
    editor.undo()
    assert not editor.dirty
    editor.undo()
    assert editor.dirty
    editor.redo()
    assert not editor.dirty
    editor.update(0, text='Branch')
    assert not editor.redo_stack


def test_split_merge_provenance_and_original():
    editor = Editor(parse_ass(fixture_ass()))
    cue = editor.document.cues[0]
    source_ids = cue.source_ids[:]
    editor.update(0, translation='Hello world')
    editor.split(0, 5, 2000, translation_mode=True)
    assert len(editor.document.cues) == 2
    assert editor.document.cues[1].source_ids == source_ids
    assert editor.document.cues[1].original == cue.original
    editor.merge([0, 1])
    assert editor.document.cues[0].translation == r'Hello\Nworld'
    assert editor.document.cues[0].source_ids == source_ids


def test_duplicate_authored_line_cannot_overwrite_shared_source():
    editor = Editor()
    editor.add()
    editor.update(0, text='Original source')
    source_id = editor.document.cues[0].source_ids[0]
    editor.duplicate([0])
    editor.update(1, text='Alternate take')
    editor.update(0, text='Edited first take')
    assert editor.document.source_lines[source_id]['text'] == 'Original source'
    assert all(c.original == 'Original source' for c in editor.document.cues)
    editor.merge([0, 1])
    assert editor.document.cues[0].original == 'Original source'


def test_literal_replace_does_not_interpret_backrefs():
    editor = Editor(parse_ass(fixture_ass()))
    assert editor.replace('Привет', r'\1', [0]) == 1
    assert r'\1' in editor.document.cues[0].output_text


def test_quality_ignores_ass_drawing_and_tags():
    doc = parse_ass(fixture_ass())
    cue = doc.cues[0]
    cue.text = r'{\i1}Hi{\i0}{\p1}m 0 0 l 100 100{\p0}'
    result = quality(cue)
    assert result['characters'] == 2


REAL_FIXTURES = os.environ.get('DUBBING_MANAGER_TEST_FILES')
REAL_ASS = sorted(Path(REAL_FIXTURES).glob('*.ass')) if REAL_FIXTURES else []


@pytest.mark.parametrize('path', REAL_ASS or [None], ids=lambda p: p.name if p else 'unavailable')
def test_real_dubbing_manager_ass_byte_roundtrip(path, tmp_path):
    if path is None:
        pytest.skip('Set DUBBING_MANAGER_TEST_FILES to use private integration fixtures')
    before = path.read_bytes()
    doc = load_document(path)
    assert doc.ass_bytes() == before, path.name
    output = tmp_path / path.name
    save_document(doc, output)
    assert output.read_bytes() == before
    restored = load_document(output)
    assert len(restored.cues) == len(doc.cues)
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(before).digest()
