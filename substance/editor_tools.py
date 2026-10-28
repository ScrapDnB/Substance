"""Pure, reviewable subtitle repair plans. Analysis never mutates a document."""
from copy import deepcopy
from dataclasses import dataclass
from bisect import bisect_left
from heapq import heappop, heappush
import difflib
import re

from .ass_tags import BLOCK
from .document import identity, plain_text
from .editor import quality
from .project import rebind_reviews


@dataclass
class Proposal:
    ids: list
    after: list
    reason: str
    selected: bool = True
    applicable: bool = True
    review: bool = False


def text_field(cue, translation=False):
    return 'translation' if translation or cue.translation is not None else 'text'


def clean_text(text, punctuation=True, spaces=True):
    def clean(part):
        if spaces:
            part = re.sub(r'[ \t]+', ' ', part)
        if punctuation:
            part = re.sub(r' +([,.;:!?…])', r'\1', part)
        return part
    parts = re.split(r'(\{[^{}]*\}|\\[Nn])', text)
    text = ''.join(p if p.startswith('{') or p in (r'\N', r'\n') else clean(p) for p in parts)
    if spaces:
        text = re.sub(r' *\\[Nn] *', r'\\N', text)
        text = re.sub(r'(?:\\N){2,}', r'\\N', text)
        text = text.strip()
    return text


def flatten(text):
    # Whitespace outside override blocks only; keep every override byte intact.
    return ''.join(p if p.startswith('{') else re.sub(r'\\[Nn]|[\r\n]', ' ', p)
                   for p in re.split(r'(\{[^{}]*\})', text))


def visible_map(text):
    chars, offsets, i = [], [], 0
    while i < len(text):
        block = BLOCK.match(text, i)
        if block:
            i = block.end()
            continue
        if text[i:i + 2] in (r'\N', r'\n', r'\h'):
            chars.append(' ')
            offsets.append(i)
            i += 2
        else:
            chars.append(text[i])
            offsets.append(i)
            i += 1
    return ''.join(chars), offsets


def break_score(text, position):
    left, right = text[:position].rstrip(), text[position:].lstrip()
    score = abs(len(left) - len(right))
    if re.search(r'[,;:!?。！？.]$', left):
        score -= 12
    if re.search(r'\b(?:в|к|с|у|о|и|а|но|на|по|из|от|для|не|the|a|an|of|to|in|and)$', left, re.I):
        score += 30
    if len(right.split()) == 1:
        score += 12
    if left.count('(') > left.count(')') or left.count('«') > left.count('»'):
        score += 15
    return score


def break_positions(visible):
    spaces = [m.start() for m in re.finditer(r'\s+', visible) if m.start() > 0 and m.end() < len(visible)]
    if not spaces and re.search(r'[\u3000-\u9fff\uac00-\ud7af]', visible):
        spaces = list(range(1, len(visible)))
    return spaces


def balance(text, width):
    text = flatten(text).strip()
    visible, offsets = visible_map(text)
    if len(visible) <= width:
        return text
    candidates = [p for p in break_positions(visible) if len(visible[:p].rstrip()) <= width and len(visible[p:].lstrip()) <= width]
    if not candidates:
        return text  # Splitting a cue is a separate, explicit operation.
    pos = min(candidates, key=lambda p: break_score(visible, p))
    raw = offsets[pos]
    return text[:raw].rstrip() + r'\N' + text[raw:].lstrip()


def complex_timing(text):
    return bool(re.search(r'\\(?:t\s*\(|move\s*\(|fad[e]?\s*\(|[kK](?:f|o)?\d|p[1-9])', text))


def split_static(text, raw):
    """Replay static overrides at a new event boundary, including named resets."""
    if complex_timing(text):
        raise ValueError('Анимация, караоке или рисунок ASS требуют ручного разделения')
    prefix = ''.join(m[0] for m in BLOCK.finditer(text[:raw]))
    return text[:raw].rstrip(), prefix + text[raw:].lstrip()


def cue_info(cue):
    return f'{cue.start / 1000:.3f}–{cue.end / 1000:.3f} с · {quality(cue)["cps"]} зн/с\n' + plain_text(cue.output_text)


def split_cue(cue, width, max_duration, translation=False):
    if complex_timing(cue.output_text):
        return None
    text = flatten(cue.output_text).strip()
    result, start = [], cue.start
    total = max(1, len(plain_text(text)))
    original_duration = cue.end - cue.start
    while True:
        visible, offsets = visible_map(text)
        remaining_duration = cue.end - start
        if len(visible) <= width * 2 and remaining_duration <= max_duration:
            break
        candidates = break_positions(visible)
        if not candidates:
            return None
        target = min(width * 2, max(1, int(len(visible) * max_duration / max(1, remaining_duration))))
        candidates = [p for p in candidates if p <= target] or candidates[:1]
        # Favor sentence boundaries, but avoid an excessively short first cue.
        pos = min(candidates, key=lambda p: abs(p - target * .8) + (0 if re.search(r'[.!?。！？]$', visible[:p]) else 12))
        first, text = split_static(text, offsets[pos])
        stop = min(cue.end - 1, start + max(1, round(original_duration * len(plain_text(first)) / total)))
        if stop <= start or cue.end - stop < 10:
            return None
        part = deepcopy(cue)
        part.id = cue.id if not result else identity('frag')
        part.start, part.end = start, stop
        part.extras.pop('authoring', None)
        setattr(part, text_field(cue, translation), balance(first, width))
        result.append(part)
        start = stop
    part = deepcopy(cue)
    part.id = identity('frag') if result else cue.id
    part.start = start
    part.extras.pop('authoring', None)
    setattr(part, text_field(cue, translation), balance(text, width))
    result.append(part)
    return result if len(result) > 1 else None


def plan(document, indices, kind, options, translation=False):
    proposals = []
    width = max(20, min(100, int(options.get('width', 42))))
    gap = max(0, min(1000, int(options.get('gap', 80))))
    minimum = max(100, int(options.get('minimum', 1000)))
    maximum = max(minimum, int(options.get('maximum', 6000)))
    selected = set(indices)
    consumed = set()
    starts = sorted(c.start for c in document.cues if not c.comment)
    for i in sorted(selected):
        cue = document.cues[i]
        if cue.comment or cue.id in consumed:
            continue
        result, reasons = deepcopy(cue), []
        if kind == 'checks':
            if options.get('spaces', True) or options.get('punctuation', True):
                value = clean_text(cue.output_text, options.get('punctuation', True), options.get('spaces', True))
                if value != cue.output_text:
                    setattr(result, text_field(cue, translation), value)
                    reasons.append('Пробелы, пунктуация и пустые строки')
            if options.get('timing', True):
                # Deliberate overlap (e.g. simultaneous speakers) is never clipped.
                at = bisect_left(starts, max(cue.end, cue.start + 1))
                following = starts[at] if at < len(starts) else None
                if cue.end <= cue.start:
                    result.end = min(cue.start + minimum, following) if following and following > cue.start else cue.start + minimum
                    reasons.append('Нулевой интервал')
                elif cue.end - cue.start < minimum:
                    proposed = cue.start + minimum
                    if following is not None:
                        proposed = min(proposed, max(cue.end, following - gap))
                    if proposed > cue.end:
                        result.end = proposed
                        reasons.append('Короткая длительность')
                if following is not None and 0 < following - result.end < gap:
                    end = following - gap
                    if end - result.start >= minimum:
                        result.end = end
                        reasons.append('Короткий промежуток')
            if result != cue:
                proposals.append(Proposal([cue.id], [result], '; '.join(reasons)))
            # Findings with no universally correct automatic repair.
            messages = quality(result, cps_limit=float(options.get('cps', 20)),
                               line_limit=max(10, min(200, int(options.get('width', 42)))),
                               show_speed=options.get('readingSpeed', document.review_settings.get('readingSpeed', True)),
                               show_length=options.get('lineLength', document.review_settings.get('lineLength', True)),
                               show_lines=options.get('lineCount', document.review_settings.get('lineCount', True)),
                               show_overlaps=options.get('overlaps', document.review_settings.get('overlaps', True)),
                               line_count_limit=options.get('lineCountLimit', document.review_settings.get('lineCountLimit', 2)),
                               next_cue=document.cues[i + 1] if i + 1 < len(document.cues) else None)['messages']
            if result.end - result.start > maximum:
                messages.append('Слишком длинная длительность')
            if re.search(r'\b([^\W\d_]+)\s+\1\b', plain_text(cue.output_text), re.I):
                messages.append('Повтор слова — проверьте по смыслу')
            cuts = options.get('cuts', [])
            if any(0 < abs(edge - cut) <= 100 for cut in cuts for edge in (cue.start, cue.end)):
                messages.append('Граница близко к монтажной склейке — проверьте кадр')
            if cue.output_text.count('{') != cue.output_text.count('}'):
                messages.append('Незакрытый блок ASS-тегов')
            if messages:
                proposals.append(Proposal([cue.id], [], '; '.join(messages), False, False))
        elif kind == 'balance':
            value = balance(cue.output_text, width)
            if value != cue.output_text:
                setattr(result, text_field(cue, translation), value)
                proposals.append(Proposal([cue.id], [result], 'Баланс строк'))
            elif any(len(line) > width for line in plain_text(value).splitlines()):
                proposals.append(Proposal([cue.id], [], 'Для соблюдения длины требуется разделение реплики', False, False))
        elif kind == 'split':
            parts = split_cue(cue, width, maximum, translation)
            if parts:
                proposals.append(Proposal([cue.id], parts, 'Разделение; время распределено приблизительно — прослушайте', False))
            elif len(plain_text(cue.output_text)) > width * 2 or cue.end - cue.start > maximum:
                proposals.append(Proposal([cue.id], [], 'Требуется ручное разделение: сложное ASS-оформление или недостаточный интервал', False, False))
        elif kind == 'merge' and i + 1 in selected:
            other = document.cues[i + 1]
            same_actor = (cue.character_id or cue.character) == (other.character_id or other.character)
            fields = ('Style', 'Layer', 'Effect', 'MarginL', 'MarginR', 'MarginV')
            same_style = all(cue.ass_fields.get(k, '') == other.ass_fields.get(k, '') for k in fields)
            if (other.comment or not same_actor or not same_style
                    or complex_timing(cue.output_text + other.output_text)
                    or not 0 <= other.start - cue.end <= gap
                    or other.end - cue.start > maximum
                    or min(cue.end - cue.start, other.end - other.start) >= minimum):
                continue
            # Reset inherited formatting of the second original event explicitly.
            text = flatten(cue.output_text).rstrip() + r'{\r' + other.ass_fields.get('Style', 'Default') + '} ' + flatten(other.output_text).lstrip()
            if len(plain_text(text)) > width * 2:
                continue
            result.id = identity('frag')
            result.end = other.end
            result.source_ids = list(dict.fromkeys(cue.source_ids + other.source_ids))
            result.original = r'\N'.join(document.source_lines[s]['text'] for s in result.source_ids)
            result.extras.pop('authoring', None)
            setattr(result, text_field(cue, translation or other.translation is not None), balance(text, width))
            proposals.append(Proposal([cue.id, other.id], [result], 'Объединение коротких реплик одного персонажа'))
            consumed.update((cue.id, other.id))
    return proposals


def apply_plan(editor, snapshot, proposals):
    if editor.document != snapshot:
        raise ValueError('Документ изменился после анализа. Повторите анализ перед применением.')
    selected = [p for p in proposals if p.selected and p.applicable]
    used = set()
    for p in selected:
        if used.intersection(p.ids):
            raise ValueError('Предложения пересекаются; повторите анализ')
        used.update(p.ids)
    def edit(doc):
        for p in selected:
            indices = [i for i, c in enumerate(doc.cues) if c.id in p.ids]
            if len(indices) != len(p.ids) or indices != list(range(indices[0], indices[-1] + 1)):
                raise ValueError('Структура реплик изменилась')
            added = deepcopy(p.after)
            for c in added:
                if c.end <= c.start or c.start < 0:
                    raise ValueError('Недопустимый интервал')
            doc.cues[indices[0]:indices[-1] + 1] = added
            if len(added) != len(p.ids) or [c.id for c in added] != p.ids:
                rebind_reviews(doc, set(p.ids), [c.id for c in added])
            for c in added:
                _sync_authored(doc, c)
    return editor.transact('Применение предложенных исправлений', edit)


def _sync_authored(doc, cue):
    from .editor import Editor
    values = {'start': cue.start, 'end': cue.end, 'text': cue.text}
    if cue.translation is not None:
        values['translation'] = cue.translation
    Editor._sync_authored(doc, cue, values)


def normalized(text):
    return ''.join(c.lower().replace('ё', 'е') for c in plain_text(text) if c.isalnum())


def align_words(document, indices, words, max_shift=1000, lead=0, tail=120, edges='both', cps=17, original=True):
    """Conservative ordered matching against an independently recognized transcript.

    This is ASR-assisted retiming, not acoustic forced alignment. Low-confidence
    candidates remain opt-in; unmatchable lines have no fabricated timestamps.
    """
    proposals = []
    for i in indices:
        cue = document.cues[i]
        if cue.comment or complex_timing(cue.output_text) or re.search(r'\\(?:pos|move|p[1-9])', cue.output_text):
            continue
        if original and cue.translation is not None and sum(c.source_ids == cue.source_ids for c in document.cues) > 1:
            proposals.append(Proposal([cue.id], [], 'Разделённый оригинал: требуется ручная проверка', False, False))
            continue
        target = normalized((cue.original or cue.text) if original else cue.output_text)
        near = [w for w in words if w['end'] >= cue.start - max_shift and w['start'] <= cue.end + max_shift]
        heard, times = '', []
        for word in near:
            chars = normalized(word['text'])
            heard += chars
            times.extend([(word['start'], word['end'])] * len(chars))
        if not target or not heard:
            proposals.append(Proposal([cue.id], [], 'Речь не найдена', False, False))
            continue
        matcher = difflib.SequenceMatcher(None, target, heard, autojunk=False)
        blocks = [b for b in matcher.get_matching_blocks() if b.size]
        coverage = sum(b.size for b in blocks) / len(target)
        if not blocks or coverage < .65 or blocks[0].a > max(1, len(target) * .15) or blocks[-1].a + blocks[-1].size < len(target) * .85:
            proposals.append(Proposal([cue.id], [], f'Текст не совпал с речью ({coverage:.0%}); увеличьте окно поиска или проверьте язык и оригинал', False, False))
            continue
        first, last = times[blocks[0].b][0], times[blocks[-1].b + blocks[-1].size - 1][1]
        result = deepcopy(cue)
        if edges != 'end':
            result.start = max(0, first - lead)
        if edges != 'start':
            result.end = max(last + tail, result.start + round(len(plain_text(cue.output_text)) * 1000 / max(1, cps)))
            result.end = min(result.end, last + max(800, tail))
        safe = coverage >= .9 and len(target) >= 4 and heard.count(target) <= 1
        if max(abs(result.start - cue.start), abs(result.end - cue.end)) > max_shift:
            safe = False
        # Preserve legitimate overlaps, flag newly introduced ones for review.
        for other in document.cues:
            if other.id != cue.id and not other.comment and other.start < result.end and result.start < other.end:
                if not (other.start < cue.end and cue.start < other.end):
                    safe = False
        if result.end <= result.start:
            proposals.append(Proposal([cue.id], [], 'Границы не согласованы; требуется ручная проверка', False, False))
        elif (result.start, result.end) != (cue.start, cue.end):
            result.extras.pop('untimed', None)
            proposals.append(Proposal([cue.id], [result], f'Совпадение текста {coverage:.0%}' + (' · прослушайте перед применением' if not safe else ''), safe, review=not safe))
    originals = {c.id: c for c in document.cues}
    candidates = [p for p in proposals if p.applicable and p.after]
    for index, left in enumerate(candidates):
        for right in candidates[index + 1:]:
            a, b = left.after[0], right.after[0]
            old_a, old_b = originals[left.ids[0]], originals[right.ids[0]]
            if a.start < b.end and b.start < a.end and not (old_a.start < old_b.end and old_b.start < old_a.end):
                for p in (left, right):
                    p.selected = False
                    p.review = True
                    if 'пересечение' not in p.reason:
                        p.reason += ' · новое пересечение — проверьте вместе'
    return proposals


def shared_boundaries(cues):
    """Unambiguous touching edges, with room for two intervals of at least 10 ms."""
    starts, ends = {}, {}
    for index, cue in enumerate(cues):
        if not cue.comment and cue.start < cue.end:
            starts.setdefault(cue.start, []).append(index)
            ends.setdefault(cue.end, []).append(index)
    joints = []
    for time, left in ends.items():
        right = starts.get(time, [])
        if len(left) == len(right) == 1:
            minimum, maximum = cues[left[0]].start + 10, cues[right[0]].end - 10
            if minimum <= maximum:
                joints.append({'left': left[0], 'right': right[0], 'time': time,
                               'minimum': minimum, 'maximum': maximum})
    return joints


def lane_layout(cues):
    """Pack each connected overlap group into its own anonymous visual lanes.

    Touching intervals belong to separate groups. Lane counts are local to a
    group, so an isolated cue fills the audio pane regardless of distant overlaps.
    No simultaneous cues share a lane; actors and ASS layers do not affect it.
    """
    lanes = []
    active, available, group = [], [], []
    group_end, lane_count = 0, 0

    def finish_group():
        for item in group:
            item['laneCount'] = lane_count

    items = [(i, cue) for i, cue in enumerate(cues) if not cue.comment]
    start_joints, end_joints = {}, {}
    for joint in shared_boundaries(cues):
        start_joints[joint['right']] = joint
        end_joints[joint['left']] = joint
    for index, cue in sorted(items, key=lambda item: (item[1].start, item[1].end, item[0])):
        if cue.start >= group_end:
            finish_group()
            active, available, group = [], [], []
            lane_count = 0
        while active and active[0][0] <= cue.start:
            _, released = heappop(active)
            heappush(available, released)
        if available:
            lane_index = heappop(available)
        else:
            lane_index = lane_count
            lane_count += 1
            if lane_index == len(lanes):
                lanes.append({'items': []})
        item = {'index': index, 'id': cue.id, 'start': cue.start, 'end': cue.end,
                'text': plain_text(cue.output_text),
                'startJoint': start_joints.get(index), 'endJoint': end_joints.get(index)}
        lanes[lane_index]['items'].append(item)
        group.append(item)
        heappush(active, (cue.end, lane_index))
        group_end = max(cue.end, cue.start) if len(group) == 1 else max(group_end, cue.end)
    finish_group()
    return lanes
