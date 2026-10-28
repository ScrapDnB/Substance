from copy import deepcopy
import pytest

from substance.document import Cue, Document, parse_ass, save_document, load_document, export_document
from substance.editor import Editor
from substance.editor_tools import (align_words, apply_plan, balance, clean_text, lane_layout,
                                    plan, shared_boundaries, split_static)


def document(*rows):
    doc = Document()
    for start, end, text, *actor in rows:
        cue = Cue(start=start, end=end, text=text, original=text, character=actor[0] if actor else '')
        doc.register_source(cue)
        doc.cues.append(cue)
    return doc


def test_repair_preserves_overrides_original_and_roundtrip(tmp_path):
    doc = document((0, 2000, r'{\pos(20, 30)\i1}Привет  , мир !'))
    snapshot = deepcopy(doc)
    proposals = plan(doc, [0], 'checks', {'timing': False})
    editor = Editor(doc)
    assert apply_plan(editor, snapshot, proposals)
    assert editor.document.cues[0].text == r'{\pos(20, 30)\i1}Привет, мир!'
    assert editor.document.source_lines == snapshot.source_lines
    assert editor.document.cues[0].original == snapshot.cues[0].original
    path = tmp_path / 'repair.substance'
    save_document(editor.document, path)
    assert load_document(path).cues[0].text == editor.document.cues[0].text
    export_document(editor.document, tmp_path / 'out.ass')
    assert parse_ass((tmp_path / 'out.ass').read_text(encoding='utf-8-sig')).cues[0].text == editor.document.cues[0].text
    editor.undo()
    assert editor.document == snapshot
    editor.redo()
    assert editor.document.cues[0].text.endswith('Привет, мир!')


def test_no_automatic_clipping_of_simultaneous_speech():
    doc = document((0, 2000, 'да да', 'A'), (500, 2500, 'Другой голос', 'B'))
    proposals = plan(doc, [0, 1], 'checks', {})
    assert any('Повтор слова' in p.reason and not p.applicable for p in proposals)
    assert not any(p.after and p.after[0].end < doc.cues[0].end for p in proposals)


def test_stale_results_and_failed_validator_are_atomic():
    doc = document((0, 2000, 'a  b'))
    editor = Editor(doc)
    snapshot = deepcopy(doc)
    proposals = plan(doc, [0], 'checks', {})
    editor.update(0, text='manual')
    with pytest.raises(ValueError, match='изменился'):
        apply_plan(editor, snapshot, proposals)
    assert editor.document.cues[0].text == 'manual'
    editor = Editor(doc)
    editor.validator = lambda d: (_ for _ in ()).throw(ValueError('no access'))
    with pytest.raises(ValueError, match='no access'):
        apply_plan(editor, snapshot, proposals)
    assert editor.document == snapshot and not editor.undo_stack


def test_split_replays_static_overrides_and_preserves_translation_links():
    text = r'{\i1\c&H112233&}One two three four five six seven eight nine ten eleven twelve.'
    doc = document((0, 8000, text))
    doc.cues[0].translation = text
    doc.cues[0].text = 'untouched source'
    snapshot = deepcopy(doc)
    proposals = plan(doc, [0], 'split', {'width': 20, 'maximum': 3000}, True)
    assert len(proposals) == 1 and len(proposals[0].after) >= 2
    assert not proposals[0].selected
    proposals[0].selected = True
    editor = Editor(doc)
    apply_plan(editor, snapshot, proposals)
    assert all(r'\i1' in c.translation and r'\c&H112233&' in c.translation for c in editor.document.cues)
    assert all(c.original == snapshot.cues[0].original for c in editor.document.cues)
    assert all(c.text == 'untouched source' for c in editor.document.cues)
    assert editor.document.source_lines == snapshot.source_lines
    assert all(a.end == b.start for a, b in zip(editor.document.cues, editor.document.cues[1:]))
    editor.undo()
    assert editor.document == snapshot


def test_animated_ass_never_silently_split_or_merged():
    with pytest.raises(ValueError):
        split_static(r'{\t(0,500,\fs30)}hello world', 24)
    doc = document((0, 9000, r'{\k20}hello ' * 25))
    assert all(not p.applicable for p in plan(doc, [0], 'split', {'width': 20}))


def test_balance_and_merge_actors_and_styles():
    assert balance(r'{\i1}one two three four five six seven', 20).startswith(r'{\i1}')
    assert r'\N' in balance('one two three four five six seven', 20)
    doc = document((0, 500, r'{\i1}one', 'A'), (550, 1500, 'two', 'A'), (1600, 1900, 'three', 'B'))
    proposals = plan(doc, [0, 1, 2], 'merge', {'gap': 100})
    assert len(proposals) == 1
    assert r'{\rDefault}' in proposals[0].after[0].text
    assert len(proposals[0].after[0].source_ids) == 2
    editor = Editor(doc)
    apply_plan(editor, deepcopy(doc), proposals)
    assert len(editor.document.cues) == 2
    assert editor.document.cues[1].character == 'B'


def test_alignment_matches_original_not_translation_and_keeps_text():
    doc = document((500, 2500, 'Hello world'))
    doc.cues[0].translation = 'Привет, мир!'
    words = [{'start': 700, 'end': 1000, 'text': 'Hello'}, {'start': 1100, 'end': 1800, 'text': 'world'}]
    proposals = align_words(doc, [0], words)
    assert len(proposals) == 1 and proposals[0].applicable
    result = proposals[0].after[0]
    assert result.start == 700 and result.end == 1920
    assert result.translation == 'Привет, мир!'
    assert result.original == 'Hello world'
    assert not align_words(doc, [0], [{'start': 700, 'end': 1000, 'text': 'unrelated'}])[0].applicable
    starts = align_words(doc, [0], words, edges='start')[0].after[0]
    assert starts.end == 2500


def test_alignment_short_words_and_new_overlaps_require_review():
    doc = document((500, 1000, 'Yes'), (1100, 2000, 'Next'))
    p = align_words(doc, [0], [{'start': 600, 'end': 1300, 'text': 'Yes'}])[0]
    assert p.applicable and not p.selected


def test_japanese_alignment_recovers_full_phrase_instead_of_first_voice_island():
    text = 'オトメゲーム君と一筋の光をという作品がある'
    doc = document((2200, 3670, text))
    words = [{'start': 2600, 'end': 3580, 'text': 'オトメゲーム'},
             {'start': 4300, 'end': 6940, 'text': '君と一筋の光をという作品がある'}]
    result = align_words(doc, [0], words, max_shift=5000)[0]
    assert result.after[0].end == 7060
    assert result.after[0].text == text
    # Once the individual tokens lie beyond the search window, a partial
    # match must not be presented as a confidently shortened full sentence.
    tokens = [{'start': 2600, 'end': 3580, 'text': 'オトメゲーム'},
              {'start': 4300, 'end': 4600, 'text': '君と'},
              {'start': 4800, 'end': 6940, 'text': '一筋の光をという作品がある'}]
    assert not align_words(doc, [0], tokens)[0].applicable


def test_lanes_are_anonymous_unlimited_and_keep_all_cues():
    doc = document(*[(0, 2000 + i, str(i), f'Actor {i}') for i in range(20)])
    rows = lane_layout(doc.cues)
    assert len(rows) == 20
    assert all(len(row['items']) == 1 and row['items'][0]['laneCount'] == 20 for row in rows)
    assert sorted(c['index'] for row in rows for c in row['items']) == list(range(20))
    assert all(set(row) == {'items'} for row in rows)
    for i, cue in enumerate(doc.cues):
        cue.character = 'different'
        cue.ass_fields['Layer'] = str(i)
    assert lane_layout(doc.cues) == rows
    nonoverlapping = document((0, 500, 'A', 'First'), (600, 1000, 'B', 'Second'))
    assert len(lane_layout(nonoverlapping.cues)) == 1


def test_lanes_use_local_overlap_groups_and_reuse_released_lanes():
    doc = document((0, 100, 'Solo'), (100, 400, 'Long'), (150, 250, 'Short'),
                   (250, 450, 'Next short'), (450, 600, 'Solo again'),
                   (1000, 1400, 'A'), (1100, 1500, 'B'), (1200, 1600, 'C'))
    doc.cues.append(Cue(start=0, end=2000, text='Comment', comment=True))
    # Input order must not determine overlap groups or ASS/actor placement.
    doc.cues.reverse()
    rows = lane_layout(doc.cues)
    placement = {item['text']: (lane, item['laneCount'])
                 for lane, row in enumerate(rows) for item in row['items']}
    assert placement == {'Solo': (0, 1), 'Long': (0, 2), 'Short': (1, 2),
                         'Next short': (1, 2), 'Solo again': (0, 1),
                         'A': (0, 3), 'B': (1, 3), 'C': (2, 3)}
    for row in rows:
        assert all(a['end'] <= b['start'] for a, b in zip(row['items'], row['items'][1:]))
    assert lane_layout([]) == []


def test_shared_boundaries_ignore_order_comments_gaps_and_ambiguous_edges():
    doc = document((2000, 3000, 'Right'), (0, 2000, 'Left'),
                   (3500, 4000, 'Gap'), (4000, 4500, 'One'),
                   (4000, 5000, 'Ambiguous'), (5000, 5000, 'Untimed'))
    doc.cues.append(Cue(start=2000, end=3000, text='Comment', comment=True))
    assert shared_boundaries(doc.cues) == [
        {'left': 1, 'right': 0, 'time': 2000, 'minimum': 10, 'maximum': 2990}]
    items = {c['index']: c for row in lane_layout(doc.cues) for c in row['items']}
    assert items[1]['endJoint'] == items[0]['startJoint'] == shared_boundaries(doc.cues)[0]
    assert items[2]['endJoint'] is None
    assert items[3]['startJoint'] is None


def test_clean_does_not_modify_tag_parameters():
    assert clean_text(r'{\t(0,  500,\fs30)}A  B\N\N C') == r'{\t(0,  500,\fs30)}A B\NC'


def test_imported_ass_merge_ignores_original_event_text_and_time_fields():
    from substance.document import DEFAULT_ASS
    doc = parse_ass(DEFAULT_ASS + '\nDialogue: 0,0:00:00.00,0:00:00.40,Default,A,0,0,0,,One\nDialogue: 0,0:00:00.45,0:00:01.40,Default,A,0,0,0,,Two\n')
    assert len(plan(doc, [0, 1], 'merge', {'gap': 100})) == 1


def test_combined_alignment_overlap_is_not_preselected():
    doc = document((0, 1000, 'First word'), (1100, 2000, 'Second word'))
    words = [{'text': 'First', 'start': 0, 'end': 400}, {'text': 'word', 'start': 500, 'end': 1020},
             {'text': 'Second', 'start': 1010, 'end': 1500}, {'text': 'word', 'start': 1600, 'end': 1900}]
    candidates = [p for p in align_words(doc, [0, 1], words, tail=0) if p.applicable]
    assert not any(p.selected for p in candidates)


def test_repair_rule_switches_are_independent():
    doc = document((0, 2000, 'Hello  world !'))
    p = plan(doc, [0], 'checks', {'spaces': False, 'punctuation': True, 'timing': False})[0]
    assert p.after[0].text == 'Hello  world!'
    p = plan(doc, [0], 'checks', {'spaces': True, 'punctuation': False, 'timing': False})[0]
    assert p.after[0].text == 'Hello world !'
    assert not any(p.applicable for p in plan(doc, [0], 'checks', {'spaces': False, 'punctuation': False, 'timing': False}))
