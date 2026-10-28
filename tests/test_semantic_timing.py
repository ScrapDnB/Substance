from copy import deepcopy
import re

import numpy as np
import pytest

from substance.document import Cue, Document, load_document, plain_text, save_document
from substance.editor import Editor
from substance.editor_tools import align_words, apply_plan
from substance.semantic_timing import (Unit, ordered_matches, partition_pair, resolve_role,
                                       semantic_plan, sentence_spans, script_text, cut_positions)


class MeaningEncoder:
    """Controlled bilingual meanings let invariants run without model downloads."""
    concepts = [('cat', 'кот'), ('dog', 'собака'), ('bird', 'птица'), ('home', 'дом'),
                ('music', 'музыка'), ('school', 'школа'), ('album', 'альбом'), ('success', 'успех')]

    def encode(self, texts):
        vectors = []
        for text in texts:
            words = re.findall(r'\w+', text.lower())
            vector = np.array([sum(words.count(w) for w in group) for group in self.concepts] +
                              [0.01], dtype=np.float32)
            vectors.append(vector / np.linalg.norm(vector))
        return np.array(vectors)


def doc(*texts):
    document = Document()
    for text in texts:
        cue = Cue(text=text, original=text, start=50000, end=60000, character='Speaker')
        document.register_source(cue)
        document.cues.append(cue)
    return document


def speech(text, offset=1000, step=500):
    return [dict(text=word, start=offset+i*step, end=offset+(i+1)*step-40)
            for i, word in enumerate(text.split())]


def analyze(document, words, **options):
    return semantic_plan(document, list(range(len(document.cues))), words, MeaningEncoder(),
                         dict(role='translation', language='en', textLanguage='ru', **options),
                         detector=lambda _: ('ru', 1))


def squash(text):
    return ''.join(plain_text(text).split())


def test_sentence_boundaries_cross_rows_preserve_every_character_and_decimals():
    text = 'Dr. Smith paid 3.14 dollars. Потом он ушёл! 「こんにちは。元気ですか？」'
    parts = [text[a:b] for a, b in sentence_spans(text)]
    assert parts[0] == 'Dr. Smith paid 3.14 dollars.'
    assert parts[1] == 'Потом он ушёл!'
    assert ''.join(squash(p) for p in parts) == squash(text)
    enormous = ('Очень длинное предложение без конечной точки, ' * 2000).strip()
    spans = list(sentence_spans(enormous))
    assert max(b-a for a, b in spans) <= 240
    assert ''.join(squash(enormous[a:b]) for a, b in spans) == squash(enormous)
    title = 'Родилась песня «Название.». Потом появился альбом.'
    assert [title[a:b] for a, b in sentence_spans(title)] == ['Родилась песня «Название.».', 'Потом появился альбом.']


@pytest.mark.parametrize('translation', [None, ''])
def test_single_column_role_uses_languages_and_has_explicit_override(translation):
    cues = [Cue(text='Оригинально загруженный русский перевод', translation=translation)]
    detector = lambda t: ('en', 1) if t.startswith('English') else ('ru', 1)
    assert resolve_role(cues, 'English speech with enough letters.', {}, detector)[0] == 'translation'
    assert resolve_role(cues, 'Русская речь с достаточным количеством букв.', {}, detector)[0] == 'original'
    assert resolve_role(cues, 'English', {'role': 'original'}, detector)[0] == 'original'
    with pytest.raises(ValueError, match='роль текста'):
        resolve_role(cues, 'Yes', {}, detector)


def test_ordered_matching_skips_extra_speech_and_supports_sentence_merge():
    left = [Unit('кот.', 0, 1), Unit('собака. птица.', 1, 2), Unit('музыка.', 2, 3)]
    right = [Unit(t, i, i+1) for i, t in enumerate(['school.', 'cat.', 'dog.', 'bird.', 'music.'])]
    matches = ordered_matches(left, right, MeaningEncoder())
    assert matches[0][2] == 1
    assert any(b-a == 1 and d-c == 2 for a, b, c, d, _ in matches)
    assert matches[-1][3] == 5


@pytest.mark.parametrize("mode", ["sentences", "precise"])
def test_translation_routing_acoustic_times_provenance_save_and_undo(tmp_path, mode):
    document = doc('Кот. Собака. Птица.')
    snapshot = deepcopy(document)
    words = speech('Cat. Dog. Bird.')
    proposals = analyze(document, words, mode=mode)
    assert document == snapshot
    assert all(p.applicable and not p.selected and p.review for p in proposals)
    for p in proposals:
        p.selected = True
    editor = Editor(document)
    assert apply_plan(editor, snapshot, proposals)
    result = editor.document
    assert len(result.cues) == 3
    assert [c.original for c in result.cues] == ['Cat.', 'Dog.', 'Bird.']
    assert [c.translation for c in result.cues] == ['Кот.', 'Собака.', 'Птица.']
    assert [c.start for c in result.cues] == [w['start'] for w in words]
    assert all(a.end <= b.start for a, b in zip(result.cues, result.cues[1:]))
    assert result.source_lines == snapshot.source_lines
    assert all(c.character == 'Speaker' and c.source_ids == snapshot.cues[0].source_ids for c in result.cues)
    path = tmp_path / 'result.substance'
    save_document(result, path)
    assert load_document(path) == result
    editor.undo()
    assert editor.document == snapshot
    editor.redo()
    assert len(editor.document.cues) == 3


def test_sentence_spanning_two_source_rows_is_one_atomic_proposal():
    document = doc('Кот и', 'собака.', 'Птица.')
    proposals = analyze(document, speech('Cat and dog. Bird.'))
    assert proposals[0].ids == [c.id for c in document.cues[:2]]
    assert squash(proposals[0].after[0].translation) == squash('Кот и собака.')
    assert proposals[0].after[0].source_ids == [c.id for c in document.cues[:2]]


def test_uncertain_sentence_is_selectable_without_losing_text_and_undoable(tmp_path):
    document = doc('Кот. Собака. Птица.')
    snapshot = deepcopy(document)
    proposals = analyze(document, speech('Cat. School. Bird.'))
    proposal = proposals[0]
    assert proposal.applicable and not proposal.selected and proposal.review
    assert 'можно выбрать и применить' in proposal.reason
    uncertain = [c for c in proposal.after if c.extras['semantic_timing']['uncertain']]
    assert len(uncertain) == 1
    assert uncertain[0].translation == 'Собака.'
    assert uncertain[0].original == 'School.'
    assert uncertain[0].start == 1500
    assert 'Неоднозначное' in uncertain[0].extras['semantic_timing']['warning']
    proposal.selected = True
    editor = Editor(document)
    assert apply_plan(editor, snapshot, proposals)
    assert ''.join(squash(c.translation) for c in editor.document.cues) == squash(snapshot.cues[0].text)
    assert editor.document.source_lines == snapshot.source_lines
    path = tmp_path / 'uncertain.substance'
    save_document(editor.document, path)
    assert load_document(path) == editor.document
    editor.undo()
    assert editor.document == snapshot


@pytest.mark.parametrize("mode", ["sentences", "precise"])
def test_related_sentences_cannot_hide_an_omitted_topic_inside_a_group(mode):
    document = doc('Кот. Собака. Дом.')
    proposals = analyze(document, speech('Cat. Dog.'), mode=mode)
    assert proposals[0].applicable and not proposals[0].selected
    assert [c.original for c in proposals[0].after] == ['Cat.', 'Dog.', '']
    missing = proposals[0].after[-1]
    assert missing.translation == 'Дом.'
    assert (missing.start, missing.end) == (50000, 60000)
    assert missing.extras['semantic_timing']['timing_preserved']
    assert 'сохранено исходное время' in missing.extras['semantic_timing']['warning']


def test_no_strong_match_still_offers_a_speech_candidate():
    document = doc('Собака.')
    proposal, = analyze(document, speech('School.'))
    assert proposal.applicable and not proposal.selected
    assert proposal.after[0].start == 1000
    assert proposal.after[0].translation == 'Собака.'
    assert proposal.after[0].extras['semantic_timing']['uncertain']


def test_uncertain_fine_partition_can_be_applied_and_consumes_all_text():
    text = 'Кот кот кот кот кот кот, кот кот кот кот кот кот.'
    words = speech('dog dog dog dog dog dog, dog dog dog dog dog dog.', step=600)
    with pytest.raises(ValueError, match='неоднозначны'):
        partition_pair(text, words, MeaningEncoder(), width=20, maximum=5000)
    proposal, = analyze(doc(text), words, width=20, maximum=5000, mode='precise')
    assert proposal.applicable and len(proposal.after) >= 2
    assert ''.join(squash(c.translation) for c in proposal.after) == squash(text)
    assert all(c.extras['semantic_timing']['uncertain'] for c in proposal.after)
    assert all(0 < c.end-c.start <= 5000 for c in proposal.after)


def test_coarse_candidate_keeps_the_entire_speech_span_when_fine_split_is_impossible():
    text = '«' + 'музыка ' * 8 + '»'
    words = speech('music ' * 15, step=700)
    proposal, = analyze(doc(text), words, width=20, maximum=2000, mode='precise')
    assert proposal.applicable and not proposal.selected
    cue, = proposal.after
    assert squash(cue.translation) == squash(text)
    assert cue.start == words[0]['start']
    assert cue.end >= words[-1]['end']
    assert 'Не удалось разбить' in cue.extras['semantic_timing']['warning']
    assert 'Превышена выбранная длительность' in cue.extras['semantic_timing']['warning']


def test_untimed_unmatched_text_gets_explicit_range_warning_and_valid_times():
    document = doc('Кот. Собака. Дом.')
    document.cues[0].start = document.cues[0].end = 0
    proposal, = analyze(document, speech('Cat. Dog.'))
    assert proposal.applicable
    missing = proposal.after[-1]
    assert missing.translation == 'Дом.'
    assert (missing.start, missing.end) == (1000, 1960)
    assert 'исходного времени нет' in missing.extras['semantic_timing']['warning']
    proposal.selected = True
    assert apply_plan(Editor(document), deepcopy(document), [proposal])


def test_partial_bilingual_match_preserves_both_columns():
    document = doc('Cat. Dog. Home.')
    document.cues[0].translation = 'Кот. Собака. Дом.'
    proposal, = analyze(document, speech('Cat. Dog.'))
    assert proposal.applicable
    assert ''.join(squash(c.original) for c in proposal.after) == squash(document.cues[0].original)
    assert ''.join(squash(c.translation) for c in proposal.after) == squash(document.cues[0].translation)
    assert proposal.after[-1].original == 'Home.'
    assert proposal.after[-1].extras['semantic_timing']['uncertain']


def test_optional_script_marks_do_not_remove_fractions_or_ordinary_slashes():
    text = '//(1:20:25) / Кот и собака. / Группа AC/DC, 1/2 и/или музыка.'
    assert script_text(text, True) == 'Кот и собака. Группа AC/DC, 1/2 и/или музыка.'
    document = doc('//(01:20) / Кот. / Собака.')
    proposals = analyze(document, speech('Cat. Dog.'), stripScriptMarks=True)
    assert proposals[0].applicable
    assert ''.join(squash(c.translation) for c in proposals[0].after) == squash('Кот. Собака.')
    assert document.cues[0].text.startswith('//(01:20)')


def test_fragment_boundaries_keep_titles_names_and_written_numbers_together():
    text = 'Слушал Ролинг СтОунс и «Экзайл он Мэйн Стрит» в девятосто девятого года.'
    cuts = cut_positions(text)
    for marker in ('Ролинг ', '«Экзайл ', '«Экзайл он ', 'девятосто ', 'девятосто девятого '):
        assert text.index(marker)+len(marker)-1 not in cuts
    long_quote = '«' + 'кот собака птица музыка ' * 20 + '»'
    assert cut_positions(long_quote)


def test_existing_original_and_translation_are_both_preserved_after_split():
    document = doc('Cat. Dog. Bird.')
    document.cues[0].translation = 'Кот. Собака. Птица.'
    proposals = analyze(document, speech('Cat. Dog. Bird.'))
    assert proposals[0].applicable
    assert ''.join(squash(c.original) for c in proposals[0].after) == squash(document.cues[0].original)
    assert ''.join(squash(c.translation) for c in proposals[0].after) == squash(document.cues[0].translation)


def test_reordered_words_inside_a_sentence_are_split_on_meaning_and_speech():
    text = 'Кот кот кот кот кот кот, собака собака собака собака.'
    words = speech('Cat cat cat cat cat cat, dog dog dog dog.', step=600)
    parts = partition_pair(text, words, MeaningEncoder(), width=20, maximum=5000)
    assert len(parts) >= 2
    assert ''.join(squash(text[a:b]) for a, b, _ in parts) == squash(text)
    assert [w for _, _, group in parts for w in group] == words
    assert all(len(text[a:b]) <= 40 for a, b, _ in parts)


def test_original_mode_does_not_create_a_translation_and_uses_edited_text():
    document = doc('Cat. Dog.')
    document.cues[0].text = 'Cat. Bird.'
    proposals = semantic_plan(document, [0], speech('Cat. Bird.'), MeaningEncoder(),
                              {'role': 'original'}, detector=lambda _: ('en', 1))
    assert proposals[0].applicable
    assert all(c.translation is None for c in proposals[0].after)
    assert ''.join(squash(c.text) for c in proposals[0].after) == squash('Cat. Bird.')


def test_static_tags_replay_and_animated_ass_is_not_reinterpreted():
    document = doc(r'{\i1}Кот. Собака. Птица.')
    proposals = analyze(document, speech('Cat. Dog. Bird.'))
    assert all(r'{\i1}' in c.translation for c in proposals[0].after)
    document.cues[0].text = document.cues[0].original = r'{\k20}Кот. Собака. Птица.'
    proposals = analyze(document, speech('Cat. Dog. Bird.'))
    assert not proposals[0].applicable


def test_ordinary_alignment_can_match_working_text_instead_of_original():
    document = doc('Cat and dog')
    document.cues[0].translation = 'Кот и собака'
    document.cues[0].start, document.cues[0].end = 1000, 3000
    words = speech('Кот и собака')
    assert not align_words(document, [0], words, original=True)[0].applicable
    result = align_words(document, [0], words, original=False)[0]
    assert result.applicable and result.after[0].start == 1000
    assert result.after[0].original == 'Cat and dog'


def test_sentence_mode_keeps_long_sentence_and_full_acoustic_interval(monkeypatch):
    import substance.semantic_timing as timing
    text = 'Кот и собака, ' * 25 + 'музыка.'
    words = speech('Cat and dog, ' * 25 + 'music.', step=450)
    # This sentence exceeds both the former 240-character limit and the chosen
    # subtitle duration; the fast mode must never enter fine segmentation.
    monkeypatch.setattr(timing, 'partition_pair', lambda *a, **k: pytest.fail('fine pass'))
    proposal, = analyze(doc(text), words, maximum=2000, width=20)
    cue, = proposal.after
    assert squash(cue.translation) == squash(text)
    assert '\\N' not in cue.translation and '\n' not in cue.translation
    assert (cue.start, cue.end) == (words[0]['start'], words[-1]['end'])
    assert cue.extras['semantic_timing']['mode'] == 'sentences'
    assert 'Превышена выбранная длительность' not in cue.extras['semantic_timing']['warning']


def test_spoken_sentences_ignore_commas_pauses_abbreviations_and_decimals():
    from substance.semantic_timing import speech_units
    words = speech('Dr. Smith paid 3.14 dollars, and went home. A dog runs.')
    words[6]['start'] += 500  # A pause in the sentence is not its end.
    units = list(speech_units(words))
    assert [u.text for u in units] == [
        'Dr. Smith paid 3.14 dollars, and went home.', 'A dog runs.']
    assert [(u.start, u.end) for u in units] == [(0, 8), (8, 11)]


def test_sentence_matching_encodes_only_individual_sentences():
    class CountingEncoder(MeaningEncoder):
        def __init__(self):
            self.inputs = []

        def encode(self, texts):
            self.inputs.extend(texts)
            return super().encode(texts)

    encoder = CountingEncoder()
    left = [Unit(t, i, i+1) for i, t in enumerate(['кот.', 'собака.', 'птица.'])]
    right = [Unit(t, i, i+1) for i, t in enumerate(['cat.', 'dog.', 'bird.'])]
    matches = ordered_matches(left, right, encoder, reuse_embeddings=True)
    assert [(a, b, c, d) for a, b, c, d, _ in matches] == [(0, 1, 0, 1), (1, 2, 1, 2), (2, 3, 2, 3)]
    assert encoder.inputs == [u.text for u in left+right]


def test_sentence_mode_bilingual_original_never_uses_phrase_partition(monkeypatch):
    import substance.semantic_timing as timing
    monkeypatch.setattr(timing, 'partition_reference', lambda *a, **k: pytest.fail('phrase inference'))
    document = doc('Cat. Dog. Bird.')
    document.cues[0].translation = 'Кот. Собака. Птица.'
    proposal, = analyze(document, speech('Cat. Dog. Bird.'))
    assert [c.original for c in proposal.after] == ['Cat.', 'Dog.', 'Bird.']
    assert [c.translation for c in proposal.after] == ['Кот.', 'Собака.', 'Птица.']


@pytest.mark.parametrize('reuse_embeddings', [False, True])
def test_matching_cancellation_remains_available_during_sentence_encoding(reuse_embeddings):
    units = [Unit('cat.', i, i+1) for i in range(100)]
    checks = 0

    def check():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError('cancelled')

    with pytest.raises(RuntimeError, match='cancelled'):
        ordered_matches(units, units, MeaningEncoder(), check, reuse_embeddings=reuse_embeddings)
