import math

import pytest

from substance.speech_timing import PhraseAssembler, TimingOptions, join_words, speech_word


def word(start, end, text):
    return {'start': start, 'end': end, 'text': text}


def phrases(words, *, options=None, width=42, start=0, end=20000):
    assembler = PhraseAssembler(width, options or TimingOptions(), start, end)
    result = []
    for row in words:
        result.extend(assembler.feed(row))
    return result + assembler.finish()


def test_vad_removes_stretched_silence_after_word_in_actual_video():
    result = speech_word(word(74500, 97560, 'careful.'), [(73810, 75470), (100020, 102260)])
    assert result == word(74500, 75470, 'careful.')


def test_word_start_in_silence_is_moved_to_real_voice():
    assert speech_word(word(97560, 100350, 'Already'), [(73810, 75470), (100020, 102260)]) == word(100020, 100350, 'Already')


def test_music_and_silence_hallucinations_do_not_become_cues():
    assert speech_word(word(0, 2000, 'Oh'), [(49580, 50320)]) is None
    assert speech_word(word(0, 2000, 'Oh'), []) is None


def test_words_never_extend_from_one_voice_island_to_next():
    assert speech_word(word(49870, 50730, 'again,'), [(49580, 50320), (50670, 52720)])['end'] == 50320


def test_phrase_starts_with_speech_and_ends_after_its_final_word():
    result = phrases([word(1000, 1300, 'Hello'), word(1350, 1600, 'there.')])
    assert result == [word(1000, 2000, 'Hello there.')]


def test_sentence_end_does_not_split_abbreviations():
    result = phrases([word(1000, 1200, 'Hello,'), word(1200, 1400, 'Ms.'), word(1400, 1800, 'Carol.')])
    assert len(result) == 1 and result[0]['text'] == 'Hello, Ms. Carol.'


def test_reading_extension_is_bounded_by_next_speech():
    result = phrases([word(1000, 1250, 'Hello.'), word(1400, 1600, 'Yes.')])
    assert result[0]['end'] == 1320
    assert result[1]['start'] == 1400


def test_reading_speed_and_min_duration_work_when_gap_is_available():
    options = TimingOptions(reading_cps=8, min_duration_ms=300, max_hold_ms=3000)
    text = 'A short sentence.'
    result = phrases([word(1000, 1500, text)], options=options)
    assert result[0]['end'] == 1000 + math.ceil(len(text) * 1000 / 8)


def test_extension_never_leaves_subtitle_during_a_long_pause():
    result = phrases([word(1000, 1400, 'An exceptionally long phrase spoken very quickly.')])
    assert result[0]['end'] == 2200


def test_custom_lead_tail_and_range_are_respected():
    options = TimingOptions(lead_ms=200, tail_ms=300, max_hold_ms=500, min_duration_ms=300, reading_cps=40)
    result = phrases([word(1000, 1500, 'Yes.')], options=options, start=950, end=1700)
    assert result == [word(950, 1700, 'Yes.')]


def test_long_pause_splits_without_punctuation():
    result = phrases([word(1000, 1500, 'Hello'), word(4000, 4500, 'world')])
    assert len(result) == 2
    assert result[0]['end'] <= 2300 and result[1]['start'] == 4000


def test_long_sentences_split_into_two_line_cues_without_losing_words():
    words = [word(i * 200, (i + 1) * 200, text) for i, text in enumerate('This sentence has many words and needs to become several readable subtitle phrases without losing any text'.split())]
    result = phrases(words, width=20)
    assert len(result) > 1
    assert all(len(row['text'].split(r'\N')) <= 2 for row in result)
    assert ' '.join(row['text'].replace(r'\N', ' ') for row in result) == ' '.join(row['text'] for row in words)
    assert all(left['end'] <= right['start'] for left, right in zip(result, result[1:]))


def test_words_do_not_drift_later_when_phrases_touch():
    result = phrases([word(1000, 1400, 'One.'), word(1400, 1800, 'Two.'), word(1800, 2200, 'Three.')])
    assert [row['start'] for row in result] == [1000, 1400, 1800]


def test_last_word_of_long_sentence_is_not_orphaned():
    text = "In the system, you've already been assigned as the lead engineer on Mason's crew."
    words = [word(i * 180, (i + 1) * 180, value) for i, value in enumerate(text.split())]
    result = phrases(words, width=42)
    assert len(result) == 2
    assert all(len(row['text'].replace(r'\N', ' ').split()) >= 3 for row in result)
    assert ' '.join(row['text'].replace(r'\N', ' ') for row in result) == text


def test_balancing_never_joins_text_across_a_long_silent_gap():
    text = "In the system you've already been assigned as the lead engineer on Mason's"
    words = [word(i * 100, (i + 1) * 100, value) for i, value in enumerate(text.split())]
    result = phrases(words + [word(15000, 15500, 'Yes.')])
    assert result[-1]['text'] == 'Yes.'
    assert result[-1]['start'] == 15000 and result[-2]['end'] < 5000


def test_cjk_punctuation_is_joined_without_spaces():
    assert join_words('こんにちは', '世界。') == 'こんにちは世界。'
    result = phrases([word(1000, 1200, 'こんにちは'), word(1200, 1600, '世界。'), word(2000, 2300, '次です。')])
    assert [row['text'] for row in result] == ['こんにちは世界。', '次です。']


@pytest.mark.parametrize('options', [{'reading_cps': 0}, {'lead_ms': -1}, {'pause_ms': float('nan')},
                                     {'tail_ms': 900, 'max_hold_ms': 100}, {'max_hold_ms': True},
                                     {'min_duration_ms': 3000, 'max_duration_ms': 2000}])
def test_invalid_timing_options_are_rejected(options):
    with pytest.raises(ValueError):
        TimingOptions.from_dict(options)
