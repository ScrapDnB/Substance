import numpy as np

from substance.portrait_analysis import ANALYSIS_PROFILES, CharacterMatcher, combine_named_rows, sample_times
from substance.portrait_models import portrait_box


class Engine:
    threshold = .2

    def distances(self, feature, others):
        return np.array([np.linalg.norm(feature - other) for other in others])


def candidate(time):
    return {'time': time, 'quality': 1}


def add(matcher, feature, time, speaker='a', cue=None, single=True):
    matcher.add(np.array(feature, dtype=np.float32), time,
                [{'id': cue or str(time), 'character_id': speaker}], candidate(time), single_face=single)


def test_repeated_samples_from_one_cue_do_not_create_confidence():
    m = CharacterMatcher(Engine())
    for stamp in [100, 300, 500, 700]:
        add(m, [1, 0], stamp, cue='same')
    row = m.proposals([{'id': 'a', 'name': 'Alice'}])[0]
    assert row['evidence'] == 1
    assert not row['confident'] and not row['checked']


def test_multiscene_consensus_and_ambiguous_faces():
    m = CharacterMatcher(Engine())
    for stamp in [100, 11000, 23000, 35000]:
        add(m, [1, 0], stamp)
        add(m, [0, 1], stamp + 1000, 'b', single=False)
    rows = m.proposals([{'id': 'a', 'name': 'Alice'}, {'id': 'b', 'name': 'Bob'}])
    assert rows[0]['cardId'] == 'a' and rows[0]['checked']
    assert rows[1]['cardId'] == '' and not rows[1]['checked']


def test_competing_groups_for_same_name_require_review():
    m = CharacterMatcher(Engine())
    for stamp in [100, 11000, 23000]:
        add(m, [1, 0], stamp)
        add(m, [0, 1], stamp + 1000)
    rows = m.proposals([{'id': 'a', 'name': 'Alice'}])
    assert len(rows) == 1 and len(rows[0]['candidates']) == 6
    assert not rows[0]['checked']


def test_named_duplicates_become_variants_without_merging_unknown_people():
    def row(card, stamp, confident=False):
        return {'cardId': card, 'candidates': [candidate(stamp)], 'variant': 0,
                'confident': confident, 'checked': confident, 'applied': False,
                'appearances': 1, 'reason': ''}
    rows = combine_named_rows([row('a', 1, True), row('a', 2), row('', 3), row('', 4), row('b', 5)])
    assert len(rows) == 4
    assert rows[0]['cardId'] == 'a' and len(rows[0]['candidates']) == 2
    assert rows[0]['checked'] and rows[0]['confident']
    assert rows[0]['candidates'][rows[0]['variant']]['time'] == 1
    assert [r['cardId'] for r in rows] == ['a', '', '', 'b']


def test_identical_frames_do_not_repeat_in_merged_variants():
    rows = [{'cardId': 'a', 'candidates': [{'source': 'same pixels', 'crop': [0, 0, 1, 1], 'time': stamp}],
             'variant': 0, 'confident': False, 'checked': False, 'applied': False,
             'appearances': 1, 'reason': ''} for stamp in [1, 2]]
    merged = combine_named_rows(rows)
    assert len(merged) == 1 and len(merged[0]['candidates']) == 1


def test_conflicting_portrait_reference_does_not_override_consensus():
    m = CharacterMatcher(Engine(), [('b', np.array([1, 0]))])
    for stamp in [100, 11000, 23000]:
        add(m, [1, 0], stamp)
    row = m.proposals([{'id': 'a', 'name': 'Alice'}, {'id': 'b', 'name': 'Bob'}])[0]
    assert not row['confident'] and not row['checked']


def test_reference_identifies_unlabelled_group_but_preserves_existing_primary():
    m = CharacterMatcher(Engine(), [('a', np.array([1, 0]))])
    add(m, [1, 0], 100, '')
    row = m.proposals([{'id': 'a', 'name': 'Alice', 'primary': 'portrait'}])[0]
    assert row['cardId'] == 'a' and row['confident']
    assert not row['checked']


def test_two_simultaneous_similar_faces_are_separate():
    m = CharacterMatcher(Engine())
    add(m, [1, 0], 100)
    add(m, [1, 0], 100)
    assert len(m.groups) == 2


def test_overlap_with_unnamed_speaker_does_not_attribute_visible_face():
    m = CharacterMatcher(Engine())
    for time in [100, 11000, 23000]:
        cues = [{'id': 'named' + str(time), 'character_id': 'a'}, {'id': 'unknown' + str(time), 'character_id': ''}]
        m.add(np.array([1, 0]), time, cues, candidate(time), single_face=True)
    assert not m.proposals([{'id': 'a', 'name': 'Alice'}])[0]['cardId']


def test_round_robin_sampling_includes_rare_characters_and_skips_comments():
    cues = [{'id': str(i), 'start': i * 1000, 'end': i * 1000 + 800, 'character_id': 'common'} for i in range(100)]
    cues += [{'id': 'rare', 'start': 200000, 'end': 201000, 'character_id': 'rare'},
             {'id': 'comment', 'start': 500000, 'end': 501000, 'character_id': 'unused', 'comment': True}]
    times = sample_times(cues, 600000, limit=8)
    assert any(200000 <= t < 201000 for t in times)
    assert len(times) <= 8 and not any(t >= 500000 for t in times)
    assert len(times) == len(set(times))


def test_fast_sampling_reduces_work_and_preserves_rare_characters():
    cues = [{'id': str(i), 'start': i * 2000, 'end': i * 2000 + 1000, 'character_id': 'common'} for i in range(100)]
    cues.append({'id': 'rare', 'start': 210000, 'end': 211000, 'character_id': 'rare'})
    def sample(speed):
        profile = ANALYSIS_PROFILES[speed]
        return sample_times(cues, 240000, **{k: profile[k] for k in ('per_character', 'limit', 'parts')})
    normal, fast = sample('normal'), sample('fast')
    assert len(fast) == 7 < len(normal) == 26
    assert 210500 in fast
    assert len(sample_times([], 10000000, **{k: ANALYSIS_PROFILES['fast'][k] for k in ('per_character', 'limit', 'parts')})) == 240


def test_portrait_crop_is_inside_frame_at_all_edges():
    for box in [(-10, -20, 40, 50), (990, 510, 50, 60), (0, 0, 2000, 1500)]:
        x, y, w, h = portrait_box(box, 1000, 560)
        assert 0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0
        assert x + w <= 1.000001 and y + h <= 1.000001
