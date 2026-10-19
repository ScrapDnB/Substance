from copy import deepcopy
from pathlib import Path

import pytest

from substance.backend import Backend
from substance.batch_processing import BatchJob, fingerprint, prepare_file
from substance.document import Cue, Document, parse_ass, parse_txt
from substance.editor import Editor
from substance.quality_profiles import validate_profile, write_report
from substance.transfer import Pair, pair_lines, transfer


def document(rows):
    doc = Document()
    for start, text in rows:
        cue = Cue(start=start, end=start+800, text=text, original=text)
        doc.register_source(cue)
        doc.cues.append(cue)
    return doc


def test_comparison_keeps_missing_lines_and_source_identity():
    left = document([(1000, 'Hello'), (3000, 'World')])
    right = document([(1100, 'Hello'), (2000, 'Inserted'), (3100, 'World')])
    pairs = pair_lines(left.cues, right.cues)
    assert [(p.current,p.reference) for p in pairs] == [(0,0),(None,1),(1,2)]
    editor, snapshot = Editor(left), deepcopy(left)
    for p in pairs:
        p.chosen = True
    transfer(editor, snapshot, right, pairs, ['time'], structure=True)
    assert [c.start for c in editor.document.cues] == [1100,2000,3100]
    assert editor.document.cues[0].id == left.cues[0].id
    assert editor.document.cues[0].source_ids == left.cues[0].source_ids
    assert editor.document.cues[1].id != right.cues[1].id
    editor.document.validate()
    editor.undo()
    assert editor.document == snapshot
    editor.redo()
    editor.document.validate()


def test_text_only_transfer_preserves_original_and_rejects_stale():
    left, right = document([(1000, 'Original')]), document([(2000, 'Translation')])
    editor, snapshot = Editor(left), deepcopy(left)
    transfer(editor, snapshot, right, [Pair(0,0,True)], ['text'], translation=True)
    cue = editor.document.cues[0]
    assert (cue.original, cue.text, cue.translation, cue.start) == ('Original','Original','Translation',1000)
    with pytest.raises(ValueError, match='изменился'):
        transfer(editor, snapshot, right, [Pair(0,0,True)], ['time'])
    with pytest.raises(ValueError, match='нет тайминга'):
        transfer(Editor(deepcopy(snapshot)), snapshot, parse_txt('Untimed'), [Pair(0,0,True)], ['time'])


def test_style_collision_import_keeps_existing_styles():
    template = '[V4+ Styles]\nFormat: Name, Fontname\nStyle: Default,{font}\n[Events]\nFormat: Start, End, Style, Text\nDialogue: 0:00:01.00,0:00:02.00,Default,Hello'
    left = parse_ass(template.format(font='Arial'))
    right = parse_ass(template.format(font='Verdana'))
    editor = Editor(left)
    transfer(editor, deepcopy(left), right, [Pair(0,0,True)], ['format'])
    assert editor.document.cues[0].ass_fields['Style'] == 'Default (импорт)'
    ass = editor.document.ass_text()
    assert 'Style: Default,Arial' in ass and 'Style: Default (импорт),Verdana' in ass
    assert 'Dialogue: 0:00:01.00,0:00:02.00,Default (импорт),Hello' in ass


def test_paste_fields_targets_only_frozen_selection(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR',str(tmp_path))
    b = Backend()
    try:
        b._set_document(document([(0,'One'),(1000,'Two'),(2000,'Three')]),'')
        b.selection = {1}
        b.transfer.open('paste')
        b.transfer._load(document([(9000,'Replacement')]),'Fixture')
        assert len(b.transfer.rows) == 1
        assert b.transfer.apply()
        assert [c.output_text for c in b.editor.document.cues] == ['One','Replacement','Three']
        assert b.editor.document.cues[1].start == 1000
        b.undo()
        assert b.editor.document.cues[1].output_text == 'Two'
    finally:
        b.shutdown()


def test_profiles_reports_and_batch_preserve_inputs(tmp_path):
    source = tmp_path/'episode.srt'
    source.write_text('1\n00:00:01,000 --> 00:00:01,500\nHello  world\n')
    original = source.read_bytes()
    options = {'format':'srt','shift':250,'replacements':'Hello → Welcome', 'profile':validate_profile({})}
    prepared = prepare_file(source,options)
    assert prepared['document'].cues[0].start == 1250
    assert prepared['document'].cues[0].output_text == 'Welcome  world'
    assert prepared['document'].cues[0].original == 'Hello  world'
    assert prepared['issues']
    job = BatchJob([],options,prepared=[prepared],destination=str(tmp_path))
    results=[];job.signals.result.connect(results.append)
    job.execute()
    output = Path(results[0]['destination'])
    assert (output/'episode.srt').exists()
    assert (output/'Проверка.html').exists()
    assert source.read_bytes() == original
    source.write_text('Changed')
    second = BatchJob([],options,prepared=[prepared],destination=str(tmp_path))
    results=[];second.signals.result.connect(results.append);second.execute()
    assert 'изменился' in results[0]['log'][0]['error']
    assert not (Path(results[0]['destination'])/'episode.srt').exists()


def test_report_escapes_markup_and_spreadsheet_formulas(tmp_path):
    rows=[{'text':'<script>alert(1)</script>', 'reason':'=1+1'}]
    write_report(tmp_path/'report.html',rows)
    assert '<script>' not in (tmp_path/'report.html').read_text(encoding='utf-8')
    write_report(tmp_path/'report.csv',rows)
    assert "'=1+1" in (tmp_path/'report.csv').read_text(encoding='utf-8-sig')
    with pytest.raises(ValueError):
        validate_profile({'minimum':2000,'maximum':1000})


def test_batch_detects_sidecar_change(tmp_path):
    path=tmp_path/'test.ass';path.write_text('[Events]')
    before=fingerprint(path)
    Path(str(path)+'.substance').write_text('{}')
    assert before != fingerprint(path)


def test_difference_kinds_filter_visible_rows_and_keep_marks(tmp_path,monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR',str(tmp_path))
    b=Backend()
    try:
        source=document([(1000,'One'),(3000,'Two'),(5000,'Three'),(7000,'Four'),(9000,'Gone')])
        reference=deepcopy(source)
        reference.cues.pop()
        reference.cues[0].text='One changed'
        reference.cues[1].start+=100
        reference.cues[1].end+=100
        reference.cues[2].character='Alice'
        reference.cues[3].ass_fields['Style']='Sign'
        extra=Cue(start=12000,end=13000,text='Extra',original='Extra')
        reference.register_source(extra);reference.cues.append(extra)
        b._set_document(source,'')
        b.transfer.open('compare');b.transfer._load(reference,'Kinds')
        expected={'text':('1','1'),'time':('2','2'),'character':('3','3'),
                  'format':('4','4'),'added':('—','5'),'removed':('5','—')}
        for kind,(left,right) in expected.items():
            b.transfer.setDifferenceFilter(kind)
            assert len(b.transfer.rows)==1, (kind,b.transfer.rows)
            assert b.transfer.preview['left']['number']==left
            assert b.transfer.preview['right']['number']==right
            assert b.transfer.previewIndex==0
        b.transfer.setDifferenceFilter('text')
        b.transfer.toggleCurrent()
        assert b.transfer.chosenCount==1
        b.transfer.setDifferenceFilter('time')
        b.transfer.checkAll(True)
        assert b.transfer.chosenCount==2
        b.transfer.checkAll(False)
        assert b.transfer.chosenCount==1
        b.transfer.setDifferenceFilter('all')
        assert len(b.transfer.rows)==6 and b.transfer.rows[0]['checked']
        b.transfer.setDifferenceFilter('text')
        b.transfer.setField('differences',False)
        assert b.transfer.differenceFilter=='all' and not b.transfer.differencesOnly
        b.transfer.open('compare')
        assert b.transfer.differencesOnly and b.transfer.differenceFilter=='all'
    finally:
        b.shutdown()
