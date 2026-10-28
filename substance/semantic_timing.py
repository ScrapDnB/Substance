"""Sentence-level multilingual matching and acoustic subtitle segmentation.

Input rows are provenance, never alignment units. Both sequence alignment and
subdivision compare meaning. Uncertain candidates remain reviewable and
selectable; text without any speech interval retains its source timing.
"""
from bisect import bisect_left
from copy import deepcopy
from dataclasses import dataclass
import re

import numpy as np

from .document import identity, plain_text
from .editor_tools import (Proposal, balance, break_positions, clean_text, complex_timing,
                           flatten, visible_map)

ABBREVIATIONS = re.compile(r'(?:\b(?:mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|e\.g|i\.e|г|ул|им|т|д|др|рис|стр)|\b[A-ZА-Я])\.$', re.I)
TERMINATOR = re.compile(r'(?:[.!?。！？؟।…]+["\'»”’」』）)]*)+')


def clean(text):
    return ' '.join(plain_text(text).split())


SCRIPT_MARK = re.compile(r'(?<!\S)//\s*\(\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d+)?\s*\)|(?<!\S)/{1,2}(?!\S)')


def script_text(text, strip_marks=False):
    return clean(SCRIPT_MARK.sub(' ', text) if strip_marks else text)


def has_translation(cue):
    return bool(clean(cue.translation or ''))


def loaded_text(cue):
    return cue.translation if has_translation(cue) else (cue.text or cue.original)


def normalized_raw_map(raw, strip_marks=False):
    visible, offsets = visible_map(raw)
    excluded = set()
    if strip_marks:
        for match in SCRIPT_MARK.finditer(visible):
            excluded.update(range(match.start(), match.end()))
    chars, positions = [], []
    for i, (char, offset) in enumerate(zip(visible, offsets)):
        if i in excluded:
            continue
        if char.isspace():
            if chars and chars[-1] != ' ':
                chars.append(' '); positions.append(offset)
        else:
            chars.append(char); positions.append(offset)
    if chars and chars[-1] == ' ':
        chars.pop(); positions.pop()
    return ''.join(chars), positions


def sentence_spans(text, limit=240):
    """Unicode sentence stops, guarded abbreviations/decimals, bounded clauses.

    Return offsets into the complete text, including across former row edges.
    Extremely long unpunctuated sentences are partitioned without losing bytes.
    """
    stops = []
    for m in TERMINATOR.finditer(text):
        if text[m.start():m.end()] == '.':
            if m.start() and m.end() < len(text) and text[m.start()-1].isdigit() and text[m.end()].isdigit():
                continue
            if ABBREVIATIONS.search(text[max(0, m.start()-12):m.end()]):
                continue
            if m.end() < len(text) and not text[m.end()].isspace():
                continue
        stops.append(m.end())
    cursor = 0
    for end in stops + [len(text)]:
        while cursor < end:
            while cursor < end and text[cursor].isspace():
                cursor += 1
            if cursor == end:
                break
            stop = end
            if limit is not None and end - cursor > limit:
                segment = text[cursor:cursor+limit+1]
                candidates = [p for p in break_positions(segment) if limit // 3 <= p <= limit]
                if candidates:
                    pos = min(candidates, key=lambda p: (0 if re.search(r'[,;:、，；：]$', segment[:p]) else 50) + limit-p)
                    stop = cursor + pos
                else:
                    stop = cursor + limit
            while stop > cursor and text[stop-1].isspace():
                stop -= 1
            if stop > cursor:
                yield cursor, stop
            cursor = max(stop, cursor + 1)


def spoken(words):
    output = ''
    for word in words:
        text = word['text'].strip()
        if not text:
            continue
        separator = word.get('separator', ' ')
        if re.match(r'^[,.;:!?。！？、，；：]', text):
            separator = ''
        if output and re.search(r'[\u3000-\u9fff\uac00-\ud7af]$', output) and re.match(r'^[\u3000-\u9fff\uac00-\ud7af]', text):
            separator = ''
        output += (separator if output else '') + text
    return output


@dataclass
class Unit:
    text: str
    start: int
    end: int
    run: int = 0


@dataclass
class Fragment:
    start: int
    end: int
    words: list | None
    owners: list
    warning: str = ''


def detailed_speech_units(words):
    start, chars = 0, 0
    for i, word in enumerate(words):
        chars += len(word['text'])
        end = i + 1
        duration = word['end'] - words[start]['start']
        pause = end < len(words) and words[end]['start'] - word['end'] >= 450 and duration >= 800
        stop = bool(TERMINATOR.search(word['text'])) and word['text'].rstrip()[-1:] in '.!?。！？؟।…"»”’」』'
        clause = bool(re.search(r'[,;:、，；：]$', word['text'])) and duration >= 1800
        if pause or stop or clause or chars >= 100 or duration >= 7500 or end == len(words):
            yield Unit(spoken(words[start:end]), start, end)
            start, chars = end, 0


def speech_units(words):
    # Sentence boundaries share the text's abbreviation/decimal guards. Pauses
    # and commas inside a sentence do not trigger expensive fragment matching.
    text = spoken(words)
    stops = {end for _, end in sentence_spans(text, limit=None)}
    start, position = 0, 0
    for i, word in enumerate(words):
        token = word['text'].strip()
        position = text.find(token, position) + len(token)
        end = i + 1
        duration = word['end'] - words[start]['start']
        pause = end < len(words) and words[end]['start'] - word['end'] >= 1500
        # Bound imperfect, unpunctuated ASR without cutting ordinary sentences.
        if position in stops or (pause and duration >= 20000) or duration >= 45000 or end == len(words):
            yield Unit(spoken(words[start:end]), start, end)
            start = end


def group_text(units, start, count):
    group = units[start:start+count]
    return ' '.join(u.text for u in group) if len(group) == count and group[0].run == group[-1].run else ''


def ordered_matches(left, right, encoder, check=lambda: None, progress=lambda *args: None,
                    *, allow_ambiguous=False, reuse_embeddings=False):
    """Edit-distance path with 1:1, 1:N, N:1 and 2:2 sentence correspondences.

    Skips handle ASR omissions and extra dialogue. For long programmes, mutual
    semantic anchors constrain a sparse band; stored path memory is O(n*band).
    Scores are cosine similarities, explicitly not calibrated probabilities.
    """
    n, m = len(left), len(right)
    if not n or not m:
        return []
    groups = []
    for units, counts in ((left, range(1, 4)), (right, range(1, 11))):
        texts = [[group_text(units, i, count) for i in range(len(units))] for count in counts]
        if reuse_embeddings:
            # Encode sentences once; adjacent groups reuse normalized sums rather
            # than running the transformer on every possible concatenation.
            singles = []
            for base in range(0, len(units), 16):
                check()
                progress(.72, f'Вычисляем смысл предложений: {base} / {len(units)}')
                singles.append(encoder.encode(texts[0][base:base+16]))
            single = np.concatenate(singles)
            vectors = []
            for count in counts:
                check()
                pooled = np.zeros_like(single)
                valid = len(units)-count+1
                if valid > 0:
                    for shift in range(count):
                        pooled[:valid] += single[shift:shift+valid]
                pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-9)
                vectors.append(pooled)
        else:
            vectors = []
            for values in texts:
                check()
                progress(.72, 'Точное сравнение смысла фраз…')
                vectors.append(encoder.encode(values))
        groups.append((texts, vectors))
    lg, rg = groups
    def densities(text_groups):
        return [np.array([max(1, sum(2.5 if '\u3000' <= ch <= '\u9fff' else 1
                                    for ch in text if not ch.isspace())) for text in values])
                for values in text_groups]
    left_lengths, right_lengths = densities(lg[0]), densities(rg[0])
    expected_ratio = float(np.clip(left_lengths[0].sum()/right_lengths[0].sum(), .5, 2.))
    anchors = [(0, 0), (n, m)]
    band = None
    if n * m > 2000000:
        candidates = []
        # Retrieval is blocked so no whole-episode N*M matrix is retained.
        for base in range(0, n, 128):
            check()
            sims = lg[1][0][base:base+128] @ rg[1][0].T
            for row, scores in enumerate(sims):
                j = int(scores.argmax())
                alternatives = scores.copy()
                alternatives[max(0, j-2):j+3] = -1
                if scores[j] >= .65 and scores[j] - alternatives.max() >= .06:
                    candidates.append((base+row+1, j+1))
        tails, paths, parents = [], [], []
        for k, (i, j) in enumerate(candidates):
            pos = bisect_left(tails, j)
            parents.append(paths[pos-1] if pos else -1)
            if pos == len(tails):
                tails.append(j); paths.append(k)
            else:
                tails[pos], paths[pos] = j, k
        if paths:
            path, k = [], paths[-1]
            while k >= 0:
                path.append(candidates[k]); k = parents[k]
            anchors = [(0, 0)] + list(reversed(path)) + [(n, m)]
        band = 128 + abs(n-m) // 10
    rows, back = [np.full(m+1, np.inf) for _ in range(4)], []
    rows[0][0] = 0.
    steps = tuple((a, b) for a in range(1, 4) for b in range(1, 11)
                  if not reuse_embeddings or a == 1 or b == 1)
    for i in range(n+1):
        check()
        progress(.78 + .1*i/max(1, n), f'Сопоставление предложений: {i} / {n}')
        if i:
            rows[i % 4].fill(np.inf)
        current = rows[i % 4]
        center = int(np.interp(i, [a for a, _ in anchors], [b for _, b in anchors]))
        low, high = (0, m) if band is None else (max(0, center-band), min(m, center+band))
        trace = np.zeros(high-low+1, dtype=np.uint8)
        back.append((low, trace))
        costs = {}
        if i:
            single_scores = {}
            for a, b in steps:
                if i >= a and lg[0][a-1][i-a]:
                    lo = max(0, low-b)
                    vector = lg[1][a-1][i-a]
                    score = rg[1][b-1][lo:high] @ vector
                    left_coverage = (lg[1][0][i-a:i] @ rg[1][b-1][lo:high].T).min(axis=0)
                    if a not in single_scores:
                        single_scores[a] = np.pad(rg[1][0] @ vector, (0, 10), constant_values=-1)
                    right_coverage = np.min([single_scores[a][lo+k:high+k] for k in range(b)], axis=0)
                    coverage = np.minimum(score, np.minimum(left_coverage, right_coverage))
                    # Length is a weak coverage prior, never a source of times.
                    ratio = left_lengths[a-1][i-a] / right_lengths[b-1][lo:high]
                    length_cost = np.abs(np.log(ratio/expected_ratio))*.35
                    combined = .75*score + .25*coverage
                    cost = (.60-combined+length_cost)*(a+b)/2 + .01*(a+b-2)
                    if a > 1 and not allow_ambiguous:
                        # A strong sentence must not hide an omitted one.
                        cost[left_coverage < .36] = np.inf
                    costs[a, b] = cost
        # Evaluate each transition for the complete row in NumPy. Horizontal
        # speech skips are a prefix minimum; no Python loop over every cell and
        # all thirty transitions is needed. Only the four live rows are retained.
        best = np.full(high-low+1, np.inf)
        if i == 0 and low == 0:
            best[0] = 0.
        if i and not allow_ambiguous:
            best[:] = rows[(i-1) % 4][low:high+1] + .34
            trace[np.isfinite(best)] = 2
        for step, (a, b) in enumerate(steps, 3):
            if i < a or (a, b) not in costs:
                continue
            first = max(low, b)
            if first > high:
                continue
            starts = np.arange(first-b, high-b+1)
            valid = np.array([bool(v) for v in rg[0][b-1][first-b:high-b+1]])
            values = rows[(i-a) % 4][first-b:high-b+1] + costs[a, b][starts-max(0, low-b)]
            target = best[first-low:]
            improved = valid & (values < target)
            target[improved] = values[improved]
            trace[first-low:][improved] = step
        skip = 0. if i in (0, n) else .025
        offsets = np.arange(len(best))*skip
        skipped = np.r_[np.inf, np.minimum.accumulate(best-offsets)[:-1]]+offsets
        trace[np.isfinite(skipped) & (skipped <= best+1e-12)] = 1
        current[low:high+1] = np.minimum(best, skipped)
    if not np.isfinite(rows[n % 4][m]):
        raise ValueError('Не найден последовательный путь сопоставления. Выберите меньший диапазон аудио и соответствующий текст.')
    matches, i, j = [], n, m
    while i or j:
        low, trace = back[i]
        step = int(trace[j-low])
        if step == 1:
            pi, pj = i, j-1
        elif step == 2:
            pi, pj = i-1, j
        elif step >= 3:
            a, b = steps[step-3]
            pi, pj = i-a, j-b
            score = float(lg[1][a-1][pi] @ rg[1][b-1][pj])
            matches.append((pi, i, pj, j, score))
        else:
            raise ValueError('Путь сопоставления прерван. Уменьшите диапазон анализа.')
        i, j = pi, pj
    return list(reversed(matches))


def cut_positions(text):
    positions = break_positions(text)
    protected = [m.span() for m in re.finditer(r'«[^»]*»|「[^」]*」|『[^』]*』|"[^"\n]*"', text)
                 if len(m[0]) <= 84]
    allowed = []
    for p in positions:
        left, right = text[:p].rstrip(), text[p:].lstrip()
        if re.match(r'^[,.;:!?、，。！？；：」』»”’)]', right):
            continue
        if any(a < p < b for a, b in protected):
            continue
        previous, following = re.search(r'\w+$', left), re.match(r'\w+', right)
        if previous and following and previous[0][0].isupper() and following[0][0].isupper():
            continue
        if previous and following and (previous[0].lower() in NUMBER_WORDS or previous[0].isdigit()) and following[0].lower() in NUMBER_WORDS:
            continue
        allowed.append(p)
    return allowed


FUNCTION_WORDS = set('в к с у о и а но на по из от для не что чтобы как если который это the a an of to in and or '
    'that which what who when if de du des le la les un une et que qui dans en el los las una y o del '
    'di il lo gli delle da che e der die das ein eine und oder von zu mit wenn dass do da dos das um uma '
    'os as para mas ou się nie na z do i że та й не що щоб'.split())
NUMBER_WORDS = set('ноль один два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать '
    'тринадцать четырнадцать пятнадцать шестнадцать семнадцать восемнадцать девятнадцать двадцать тридцать '
    'сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто девятосто сто двести триста четыреста '
    'тысяча тысячи тысяч первого второго третьего четвёртого пятого шестого седьмого восьмого девятого '
    'десятого год года году лет месяцев one two three four five six seven eight nine ten eleven twelve '
    'thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty '
    'seventy eighty ninety hundred thousand million years months'.split())


def grammar_cost(text, position):
    left, right = text[:position].rstrip(), text[position:].lstrip()
    last = re.search(r'\w+$', left)
    cost = .18 if last and last[0].lower() in FUNCTION_WORDS else 0.
    if last and re.search(r'(?:ую|ая|ое|ые|ий|ый|ого|ему|ому|ыми|ым|ой|ие)$', last[0].lower()):
        cost += .07
    if left.count('(') > left.count(')') or left.count('«') > left.count('»'):
        cost += .08
    if re.search(r'[,;:、，；：]$', left):
        cost -= .05
    if re.search(r'[.!?。！？]$', left):
        cost -= .10
    return cost


def partition_pair(text, words, encoder, width=42, maximum=6000, check=lambda: None, offset=0,
                   *, allow_ambiguous=False):
    """Joint shortest path through text fragments and acoustic word intervals.

    Optional audio skips absorb fillers and demonstrations absent from a
    translation. Every text character is consumed exactly once. Candidate
    boundaries respect names/quotes; reading speed and length are soft costs,
    never a way of manufacturing timestamps.
    """
    check()
    if (len(text) <= width*2 and words[-1]['end']-words[0]['start'] <= maximum
            and max(map(len, plain_text(balance(text, width)).splitlines())) <= width):
        return [(offset, offset+len(text), words)]
    boundaries = [0] + cut_positions(text) + [len(text)]
    sentence_ends = [b for _, b in sentence_spans(text) if b < len(text)]
    targets = []
    by_start = {}
    for a in range(len(boundaries)-1):
        for b in range(a+1, len(boundaries)):
            value = text[boundaries[a]:boundaries[b]].strip()
            if len(value) > width*2:
                break
            tokens = re.findall(r'\w+', value.lower())
            if not tokens or all(t in FUNCTION_WORDS for t in tokens):
                continue
            begin = boundaries[a] + len(text[boundaries[a]:boundaries[b]])-len(text[boundaries[a]:boundaries[b]].lstrip())
            end = boundaries[b] - len(text[boundaries[a]:boundaries[b]])+len(text[boundaries[a]:boundaries[b]].rstrip())
            if any(begin < stop < end for stop in sentence_ends):
                continue
            if max(map(len, plain_text(balance(value, width)).splitlines())) > width:
                continue
            by_start.setdefault(a, []).append(len(targets))
            targets.append((a, b, begin, end, value))
    intervals, audio_by_start = [], {}
    audio_grammar = []
    def named_boundary(position):
        if position in (0, len(words)):
            return False
        previous = re.search(r'\w+$', words[position-1]['text'])
        following = re.match(r'\w+', words[position]['text'])
        return bool(previous and following and previous[0][0].isupper() and following[0][0].isupper())
    for a in range(len(words)):
        if named_boundary(a):
            continue
        for b in range(a+1, len(words)+1):
            duration = words[b-1]['end']-words[a]['start']
            if duration > maximum:
                break
            if duration < 800:
                continue
            if named_boundary(b):
                continue
            phrase = spoken(words[a:b])
            last = re.search(r'\w+$', phrase)
            if b < len(words) and last and last[0].lower() in FUNCTION_WORDS:
                continue
            audio_by_start.setdefault(a, []).append(len(intervals))
            intervals.append((a, b, duration, phrase))
            audio_grammar.append(max(-.08, grammar_cost(phrase + ' .', len(phrase))))
    if not targets or not intervals:
        raise ValueError('Фразу нельзя разбить по доступным границам речи. Уточните диапазон или проверьте распознавание.')
    target_vectors = encoder.encode([p[4] for p in targets])
    audio_vectors = encoder.encode([p[3] for p in intervals])
    audio_lengths = np.array([max(1, len(p[3])) for p in intervals])
    durations = np.array([p[2] for p in intervals])
    expected_ratio = len(text)/max(1, len(spoken(words)))
    count, length = len(boundaries)-1, len(words)
    distance = np.full((count+1, length+1), np.inf, dtype=np.float32)
    distance[0, 0] = 0
    back = {}
    skip_cost = .025
    for a in range(count):
        check()
        # Prefix minima allow any number of unrepresented spoken filler words.
        for j in range(1, length+1):
            cost = distance[a, j-1] + skip_cost
            if cost < distance[a, j]:
                distance[a, j] = cost
                back[a, j] = (a, j-1, None)
        for candidate in by_start.get(a, []):
            _, b, begin, end, value = targets[candidate]
            scores = audio_vectors @ target_vectors[candidate]
            ratio = len(value)/audio_lengths
            length_cost = np.abs(np.log(ratio/max(.05, expected_ratio)))*.12
            reading = np.maximum(0, len(value)*1000/durations-22)*.015
            grammar = max(-.08, grammar_cost(text, boundaries[b])) if b < count else 0
            short = max(0, 25-len(value))*.02
            costs = ((.62-scores)*max(.5, len(value)/40) + length_cost +
                     reading + grammar + np.array(audio_grammar) + short + .10)
            if not allow_ambiguous:
                costs[scores < .28] = np.inf
            for j, candidates in audio_by_start.items():
                source = float(distance[a, j])
                if not np.isfinite(source):
                    continue
                for index in candidates:
                    stop = intervals[index][1]
                    cost = source + float(costs[index])
                    if cost < distance[b, stop]:
                        distance[b, stop] = cost
                        back[b, stop] = (a, j, (begin, end, j, stop))
    final = distance[count] + np.arange(length, -1, -1)*skip_cost
    j = int(final.argmin())
    if not np.isfinite(final[j]):
        raise ValueError('Части предложения неоднозначны по смыслу; требуется ручная проверка.')
    parts, a = [], count
    while a or j:
        previous, position, fragment = back[a, j]
        if fragment is not None:
            begin, end, first, last = fragment
            parts.append((offset+begin, offset+end, words[first:last]))
        a, j = previous, position
    return list(reversed(parts))


def sentence_reference(text, parts, encoder, check=lambda: None):
    """Assign whole supplied sentences monotonically, without phrase inference."""
    if len(parts) == 1:
        return [text]
    sentences = [text[a:b] for a, b in sentence_spans(text, limit=None)]
    if not sentences:
        return ['']*len(parts)
    check()
    reference = encoder.encode(sentences)
    audio = encoder.encode([spoken(part) for part in parts])
    scores = reference @ audio.T
    paths = []
    best = np.zeros(len(parts))
    for row in scores:
        check()
        # Prefix maxima allow empty subtitles while preserving original order.
        parents = np.maximum.accumulate(best)
        positions = np.arange(len(parts))
        positions[best < parents] = 0
        positions = np.maximum.accumulate(positions)
        paths.append(positions)
        best = parents + row
    result = [[] for _ in parts]
    j = int(best.argmax())
    for i in range(len(sentences)-1, -1, -1):
        result[j].append(sentences[i])
        j = int(paths[i][j])
    return [' '.join(reversed(values)) for values in result]


def partition_reference(text, parts, encoder, check=lambda: None):
    """Preserve a supplied original verbatim while assigning it to new cues."""
    check()
    if len(parts) == 1:
        return [text]
    middle = len(parts)//2
    candidates = cut_positions(text)
    if not candidates:
        # A very short original may correspond to several translated subtitles.
        return [text] + ['']*(len(parts)-1)
    candidates = sorted(candidates, key=lambda p: abs(p/len(text)-middle/len(parts)))[:24]
    target = encoder.encode([part for p in candidates for part in (text[:p].strip(), text[p:].strip())])
    audio = encoder.encode([spoken([w for part in parts[:middle] for w in part]),
                            spoken([w for part in parts[middle:] for w in part])])
    p = max(enumerate(candidates), key=lambda pair:
            float(target[2*pair[0]] @ audio[0] + target[2*pair[0]+1] @ audio[1]))[1]
    return (partition_reference(text[:p].rstrip(), parts[:middle], encoder, check) +
            partition_reference(text[p:].lstrip(), parts[middle:], encoder, check))


def resolve_role(cues, speech_text, options, detector):
    role = options.get('role', 'auto')
    if role not in ('auto', 'original', 'translation'):
        raise ValueError('Укажите, какой текст загружен: оригинал или перевод.')
    audio_language = options.get('language', 'auto')
    text_language = options.get('textLanguage', 'auto')
    single = [c for c in cues if not c.comment and not has_translation(c)]
    if not single:
        return 'translation', audio_language, text_language
    if role == 'auto':
        def detect(value, hint):
            if hint != 'auto':
                return hint
            code, confidence = detector(value)
            if sum(ch.isalpha() for ch in value) < 25 or confidence < .8:
                raise ValueError('Не удалось уверенно определить роль текста. Укажите языки или выберите «Оригинал» / «Перевод».')
            return code
        audio_language = detect(speech_text, audio_language)
        text_language = detect(' '.join(clean(loaded_text(c)) for c in single), text_language)
        role = 'original' if audio_language == text_language else 'translation'
    return role, audio_language, text_language


def semantic_plan(document, indices, words, encoder, options, *, detector,
                  check=lambda: None, progress=lambda *args: None):
    words = [w for w in words if w['end'] > w['start'] and w['text'].strip()]
    if not words:
        raise ValueError('В выбранном диапазоне не распознана речь.')
    cues = [document.cues[i] for i in indices]
    role, audio_language, text_language = resolve_role(cues, spoken(words), options, detector)
    width = max(20, min(80, int(options.get('width', 42))))
    maximum = max(2000, min(10000, int(options.get('maximum', 6000))))
    strip_marks = bool(options.get('stripScriptMarks', False))
    split_subtitles = options.get('mode', 'sentences') == 'precise' or bool(options.get('splitSubtitles', False))
    tail = max(0, min(500, int(options.get('tail', 120 if split_subtitles else 0))))
    # Build continuous speaker runs. Original row boundaries do not end a sentence.
    text, units, ownership, run = '', [], [], -1
    last = None
    blocked = set()
    for index in indices:
        cue = document.cues[index]
        value = loaded_text(cue)
        if cue.comment or not clean(value):
            last = None
            continue
        if complex_timing(value) or re.search(r'\\(?:pos|org|clip|iclip)\s*\(', value):
            blocked.add(index); last = None; continue
        style = tuple(cue.ass_fields.get(k, '') for k in ('Style', 'Layer', 'MarginL', 'MarginR', 'MarginV', 'Effect'))
        key = (cue.character_id, cue.character, has_translation(cue), style)
        if last is None or last[0]+1 != index or last[1] != key:
            run += 1
        begin = len(text) + (1 if text else 0)
        text += (' ' if text else '') + script_text(value, strip_marks)
        ownership.append((begin, len(text), index, run))
        last = index, key
    for r in range(run+1):
        owned = [v for v in ownership if v[3] == r]
        start, end = owned[0][0], owned[-1][1]
        units.extend(Unit(text[start+a:start+b], start+a, start+b, r) for a, b in sentence_spans(text[start:end], limit=240 if split_subtitles else None))
    audio = list(detailed_speech_units(words) if split_subtitles else speech_units(words))
    matches = ordered_matches(units, audio, encoder, check, progress,
                              reuse_embeddings=not split_subtitles)
    # Recover short continuations skipped at an arbitrary ASR clause edge.
    # The fine pass may still skip fillers inside these enlarged intervals.
    matches = [list(match) for match in matches]
    for left, right in zip(matches, matches[1:]):
        if left[1] == right[0] and 0 < right[2]-left[3] <= 2:
            gap = audio[left[3]:right[2]]
            if words[gap[-1].end-1]['end']-words[gap[0].start]['start'] <= 9000:
                vectors = encoder.encode([' '.join(u.text for u in gap),
                    ' '.join(u.text for u in units[left[0]:left[1]]),
                    ' '.join(u.text for u in units[right[0]:right[1]])])
                a, b = float(vectors[0] @ vectors[1]), float(vectors[0] @ vectors[2])
                if max(a, b) >= .35:
                    if a >= b:
                        left[3] = right[2]
                    else:
                        right[2] = left[3]
    if matches and matches[-1][1] == len(units) and 0 < len(audio)-matches[-1][3] <= 2:
        last = matches[-1]
        vectors = encoder.encode([' '.join(u.text for u in audio[last[3]:]),
                                  ' '.join(u.text for u in units[last[0]:last[1]])])
        if float(vectors[0] @ vectors[1]) >= .35:
            last[3] = len(audio)
    # Keep strong anchors. In the gaps, offer the best ordered candidate even
    # when similarity cannot establish a reliable correspondence. Never borrow
    # audio from an already matched sentence to hide an omitted translation.
    candidates = []
    previous_text = previous_audio = 0
    for a, b, c, d, score in matches + [[len(units), len(units), len(audio), len(audio), 1.]]:
        if previous_text < a and previous_audio < c:
            try:
                tentative = ordered_matches(units[previous_text:a], audio[previous_audio:c],
                                            encoder, check, allow_ambiguous=True,
                                            reuse_embeddings=not split_subtitles)
            except ValueError:
                tentative = []
            for x, y, z, t, similarity in tentative:
                candidates.append((previous_text+x, previous_text+y, previous_audio+z,
                                   previous_audio+t, similarity, True))
        if a < b:
            candidates.append((a, b, c, d, score, score < .46))
        previous_text, previous_audio = b, d
    parent = {i: i for i in indices}
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def owners(a, b):
        return [i for start, end, i, _ in ownership if start < b and a < end]
    def union(items):
        for i in items[1:]:
            parent[root(i)] = root(items[0])
    mapped, fragments = set(), []
    word_indices = {id(word): i for i, word in enumerate(words)}
    for match_index, (a, b, c, d, score, uncertain) in enumerate(candidates):
        check()
        progress(.88 + .1*match_index/max(1, len(candidates)),
                 f'Размещаем предложения по речи: {match_index+1} / {len(candidates)}')
        start, end = units[a].start, units[b-1].end
        owned = owners(start, end)
        union(owned)
        warning = 'Неоднозначное соответствие речи — проверьте смысл' if uncertain else ''
        heard = words[audio[c].start:audio[d-1].end]
        if not split_subtitles:
            parts = [(start, end, heard)]
        else:
            try:
                parts = partition_pair(text[start:end], heard, encoder, width, maximum, check, start)
            except ValueError:
                warning = 'Неоднозначное разбиение по речи — проверьте границы и смысл'
                try:
                    parts = partition_pair(text[start:end], heard, encoder, width, maximum, check, start,
                                           allow_ambiguous=True)
                except ValueError:
                    # No valid fine partition (for example an unbreakable title).
                    # Retain the whole text and the complete candidate speech span.
                    parts = [(start, end, heard)]
                    warning = 'Не удалось разбить по речи — сохранён целый фрагмент; проверьте время'
        for p, q, piece in parts:
            fragments.append(Fragment(p, q, piece, owners(p, q), warning))
        mapped.update(range(a, b))
    for i, unit in enumerate(units):
        if i not in mapped:
            owned = owners(unit.start, unit.end)
            union(owned)
            fragments.append(Fragment(unit.start, unit.end, None, owned,
                                      'Соответствие речи не найдено — сохранено исходное время'))
    groups = {}
    for index in indices:
        if document.cues[index].comment or not clean(loaded_text(document.cues[index])):
            continue
        groups.setdefault(root(index), []).append(index)
    proposals = []
    for group in groups.values():
        check()
        old = [document.cues[i] for i in group]
        ids = [c.id for c in old]
        if blocked.intersection(group):
            proposals.append(Proposal(ids, [], 'ASS-анимации, караоке или позиционирование нельзя автоматически разбить. Проверьте эффекты вручную.', False, False, True))
            continue
        parts = [f for f in fragments if set(f.owners).intersection(group)]
        parts.sort(key=lambda f: f.start)
        if not parts:
            continue
        bilingual = has_translation(old[0])
        references = None
        if bilingual:
            reference_partition = partition_reference if split_subtitles else sentence_reference
            references = reference_partition(' '.join(clean(c.original or c.text) for c in old),
                                             [p.words or [{'text': text[p.start:p.end]}] for p in parts], encoder, check)
        after = []
        invalid = False
        for k, part in enumerate(parts):
            a, b, piece, owned = part.start, part.end, part.words, part.owners
            source = document.cues[owned[0]]
            cue = deepcopy(source)
            cue.id = ids[0] if k == 0 else identity('frag')
            cue.source_ids = list(dict.fromkeys(s for i in owned for s in document.cues[i].source_ids))
            warning = part.warning
            timing_preserved = False
            if piece:
                cue.start = piece[0]['start']
                next_start = next((p.words[0]['start'] for p in parts[k+1:] if p.words),
                                  int(options.get('rangeEnd', words[-1]['end']+tail)))
                following = word_indices[id(piece[-1])] + 1
                if following < len(words):
                    next_start = min(next_start, words[following]['start'])
                # A coarse candidate must show all its speech, even when a
                # fine split could not meet the requested maximum duration.
                cue.end = min(piece[-1]['end']+tail, next_start, max(piece[-1]['end'], cue.start+maximum))
            else:
                cue.start = min(document.cues[i].start for i in owned)
                cue.end = max(document.cues[i].end for i in owned)
                timing_preserved = cue.start >= 0 and cue.end > cue.start
                if cue.start < 0 or cue.end <= cue.start:
                    cue.start, cue.end = words[0]['start'], words[-1]['end']
                    warning = 'Соответствие речи не найдено; исходного времени нет — указан весь диапазон речи'
            if cue.start < 0 or cue.end <= cue.start:
                invalid = True; break
            value = text[a:b]
            # Preserve static ASS overrides in each contributing source fragment.
            styled = []
            for begin, end, i, _ in ownership:
                if i not in owned:
                    continue
                raw = flatten(loaded_text(document.cues[i])).strip()
                visible, offsets = normalized_raw_map(raw, strip_marks)
                fragment = text[max(a, begin):min(b, end)]
                local = max(a, begin)-begin
                if visible[local:local+len(fragment)] == fragment and offsets:
                    left = offsets[local]
                    right = offsets[local+len(fragment)] if local+len(fragment) < len(offsets) else len(raw)
                    prefix = ''.join(re.findall(r'\{[^{}]*\}', raw[:left]))
                    fragment = prefix + (SCRIPT_MARK.sub(' ', raw[left:right]) if strip_marks else raw[left:right])
                else:
                    fragment = ''.join(re.findall(r'\{[^{}]*\}', raw)) + fragment
                styled.append(fragment)
            value = clean_text(' '.join(styled) or value, punctuation=False)
            if split_subtitles:
                value = balance(value, width)
            if bilingual or role == 'translation':
                original = references[k] if references is not None else spoken(piece or [])
                cue.original = cue.text = original
                cue.translation = value
            else:
                cue.original = cue.text = value
                cue.translation = None
            cue.original_line, cue.baseline = '', {}
            cue.extras.pop('authoring', None)
            cue.extras.pop('untimed', None)
            cue.extras['semantic_timing'] = {'role': 'translation' if bilingual else role,
                'mode': 'precise' if split_subtitles else 'sentences',
                'audio_language': audio_language, 'text_language': text_language,
                'uncertain': bool(warning), 'timing_preserved': timing_preserved,
                'recognized_original': bool(piece) and (references is None and role == 'translation' or
                    bilingual and all(c.extras.get('semantic_timing', {}).get('recognized_original') for c in old))}
            speed = len(clean(value))*1000/max(1, cue.end-cue.start)
            warnings = [warning] if warning else []
            if speed > int(options.get('cps', 17)):
                warnings.append('Высокая скорость чтения')
            if cue.end-cue.start < 800:
                warnings.append('Короткий показ')
            if split_subtitles and cue.end-cue.start > maximum:
                warnings.append('Превышена выбранная длительность')
            cue.extras['semantic_timing']['warning'] = ' · '.join(warnings)
            after.append(cue)
        if invalid:
            proposals.append(Proposal(ids, [], 'Некорректные границы времени; проверьте диапазон и распознавание.', False, False, True))
        else:
            label = 'перевод' if bilingual or role == 'translation' else 'оригинал'
            uncertain = sum(c.extras['semantic_timing']['uncertain'] for c in after)
            detail = (f'Неоднозначных фрагментов: {uncertain}. Вариант можно выбрать и применить; проверьте предупреждения.'
                      if uncertain else 'Границы найдены по речи; проверьте смысл, разбиение и скорость чтения.')
            proposals.append(Proposal(ids, after, f'Загружен {label} · {len(old)} → {len(after)} субтитров. '
                + detail, False, True, True))
    return proposals
