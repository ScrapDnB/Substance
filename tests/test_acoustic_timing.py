import numpy as np
import pytest

from substance.document import Cue, Document
from substance.editor import Editor
from substance.editor_tools import apply_plan
from substance.forced_alignment import MODEL_BY_ID, ctc_align, tokenize
from substance.frame_index import step_position, validate_times
from substance.timing_processing import process_timing


def test_ctc_aligns_supplied_repeated_tokens_with_blank_separation():
    # Greedy decoding includes an unrelated token 3. Forced alignment must
    # consume the supplied [1,1,2] and use a blank to separate the repeated 1s.
    logits = np.full((10,4),-8.,dtype=np.float32)
    for t, token in enumerate([0,1,1,0,1,0,3,2,2,0]):
        logits[t,token]=-.01
    logits[6,0]=-.1
    spans=ctc_align(logits,[1,1,2])
    assert spans[0][:2] == (1,3)
    assert spans[1][:2] == (4,5)
    assert spans[2][:2] == (7,9)
    assert all(0 < s[2] <= 1 for s in spans)


def test_acoustic_models_use_the_exact_published_vocabularies():
    assert tokenize('Hello!',MODEL_BY_ID['en']) == [11,5,15,15,8]
    assert tokenize('Привет',MODEL_BY_ID['ru']) == [22,23,15,9,12,25]
    with pytest.raises(ValueError,match='числа'):
        tokenize('Hello 123',MODEL_BY_ID['en'])
    with pytest.raises(ValueError,match='недостаточно'):
        ctc_align(np.zeros((1,4)),[1,2])


def test_actual_frame_times_drive_steps_and_rounding_with_undo():
    times=[0,40,120,160,280]
    assert step_position(times,40,1,25) == 120
    assert step_position(times,120,-1,25) == 40
    assert step_position(times,280,1,25) == 280
    doc=Document(cues=[Cue(start=45,end=200,text='Hi',original='Hi')])
    editor=Editor(doc)
    editor.batch([0],'frames',frame_times=times)
    assert (editor.document.cues[0].start,editor.document.cues[0].end) == (40,160)
    editor.undo(); assert editor.document == doc
    with pytest.raises(ValueError): validate_times([0,40,40])


def test_processor_protects_simultaneous_speech_and_does_not_mutate():
    doc=Document(cues=[Cue(start=1000,end=1800,text='One'),Cue(start=1500,end=2000,text='Two'),Cue(start=3000,end=3600,text='Three')])
    proposals=process_timing(doc,range(3),{'lead':100,'tail':200})
    assert sum(not p.applicable for p in proposals) == 2
    assert len([p for p in proposals if p.applicable]) == 1
    editor=Editor(doc);apply_plan(editor,doc,proposals)
    assert [(c.start,c.end) for c in editor.document.cues] == [(1000,1800),(1500,2000),(2900,3800)]
    editor.undo(); assert editor.document == doc


def test_processor_rejects_new_overlap_after_snapping():
    doc=Document(cues=[Cue(start=1000,end=1900,text='One'),Cue(start=1950,end=2600,text='Two')])
    p=process_timing(doc,[0],{'padding':False,'bridge':False,'snapCuts':True,'endBefore':200},cuts=[2000])
    assert p and all(not v.applicable for v in p)
