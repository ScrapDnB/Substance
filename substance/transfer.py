"""Compare and transfer subtitle fields without replacing source identities."""
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
import html
import re

from .document import identity, plain_text
from .editor import Editor
from .project import rebind_reviews


@dataclass
class Pair:
    current: int | None
    reference: int | None
    chosen: bool = False


def normalized(cue):
    return ' '.join(plain_text(cue.output_text).casefold().split())


def word_highlights(left, right):
    parts = [re.findall(r'\s+|[^\s]+', plain_text(value)) for value in (left, right)]
    output = [[], []]
    for tag, a, b, x, y in SequenceMatcher(None, parts[0], parts[1], autojunk=False).get_opcodes():
        for side, start, end in ((0,a,b),(1,x,y)):
            text = html.escape(''.join(parts[side][start:end])).replace('\n','<br>')
            output[side].append('<b><u>'+text+'</u></b>' if tag != 'equal' else text)
    return [''.join(p) for p in output]


def pair_lines(current, reference):
    """Monotone alignment; missing lines stay visible instead of shifting a column."""
    matcher = SequenceMatcher(None, [normalized(c) for c in current],
                              [normalized(c) for c in reference], autojunk=False)
    result = []
    for tag, a, b, x, y in matcher.get_opcodes():
        if tag == 'equal':
            result.extend(Pair(i, j) for i, j in zip(range(a, b), range(x, y)))
            continue
        n, m = b - a, y - x
        # Bound memory for wholly unrelated large files.
        if n * m > 40000:
            result.extend(Pair(i if i < b else None, j if j < y else None)
                          for i, j in zip(range(a, a + max(n, m)), range(x, x + max(n, m))))
            continue
        costs = [[0.] * (m + 1) for _ in range(n + 1)]
        moves = {}
        for i in range(1, n + 1):
            costs[i][0] = i * .7
        for j in range(1, m + 1):
            costs[0][j] = j * .7
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                left, right = current[a + i - 1], reference[x + j - 1]
                ratio = SequenceMatcher(None, normalized(left), normalized(right), autojunk=False).ratio()
                time = max(0., 1 - abs(left.start - right.start) / 1500)
                match = 2.2 * (1 - max(ratio, .85 * time))
                candidates = [(costs[i-1][j-1] + match, 'pair'),
                              (costs[i-1][j] + .7, 'left'), (costs[i][j-1] + .7, 'right')]
                costs[i][j], moves[i, j] = min(candidates, key=lambda p: p[0])
        rows, i, j = [], n, m
        while i or j:
            move = moves.get((i, j), 'left' if i else 'right')
            if move == 'pair':
                rows.append(Pair(a + i - 1, x + j - 1)); i -= 1; j -= 1
            elif move == 'left':
                rows.append(Pair(a + i - 1, None)); i -= 1
            else:
                rows.append(Pair(None, x + j - 1)); j -= 1
        result.extend(reversed(rows))
    return result


def differences(left, right):
    if left is None:
        return ['Добавлена в другом файле']
    if right is None:
        return ['Отсутствует в другом файле']
    result = []
    if left.output_text != right.output_text:
        result.append('Текст')
    if (left.start, left.end) != (right.start, right.end):
        result.append('Время')
    if left.character != right.character:
        result.append('Персонаж')
    if left.ass_fields != right.ass_fields:
        # Parsed Start/End/Text are redundant fields, not formatting.
        ignore = {'Start', 'End', 'Text', 'Name', 'Actor'}
        if {k: v for k, v in left.ass_fields.items() if k not in ignore} != {k: v for k, v in right.ass_fields.items() if k not in ignore}:
            result.append('Оформление')
    return result


def import_sources(doc, source, cues):
    """Import only referenced provenance; remap conflicting source IDs."""
    mapping = {}
    for cue in cues:
        for sid in cue.source_ids:
            if sid in mapping:
                continue
            record = deepcopy(source.source_lines[sid])
            target = sid if sid not in doc.source_lines or doc.source_lines[sid] == record else identity('src')
            record['id'] = target
            doc.source_lines[target] = record
            mapping[sid] = target
        cue.source_ids = [mapping[s] for s in cue.source_ids]
        cue.character_id = ''  # ProjectEdits reconciles by the visible character name.


def import_styles(doc, source, cues):
    """Import referenced ASS styles, renaming collisions deterministically."""
    def styles(document):
        section, order, found = '', [], {}
        for line in document.skeleton:
            if not line:
                continue
            if line.startswith('['):
                section = line.casefold()
            elif section in ('[v4+ styles]', '[v4 styles]'):
                if line.startswith('Format:'):
                    order = [s.strip() for s in line.split(':', 1)[1].split(',')]
                elif line.startswith('Style:') and order:
                    values = line.split(':', 1)[1].strip().split(',', len(order)-1)
                    if len(values) == len(order):
                        found[values[order.index('Name')]] = (order[:], values)
        return found
    existing, incoming = styles(doc), styles(source)
    needed = {c.ass_fields.get('Style', 'Default') for c in cues}
    for c in cues:
        needed.update(re.findall(r'\\r([^\\}]+)', c.output_text))
    rename = {}
    additions = []
    for name in sorted(needed):
        if name not in incoming:
            continue
        order, values = deepcopy(incoming[name])
        target = name
        if name in existing and incoming[name] != existing[name]:
            serial = 2
            target = name + ' (импорт)'
            while target in existing:
                target = f'{name} (импорт {serial})'; serial += 1
        rename[name] = target
        if target not in existing:
            values[order.index('Name')] = target
            additions.extend(['Format: ' + ', '.join(order), 'Style: ' + ','.join(values)])
            existing[target] = (order, values)
    if additions:
        start = next((i for i, s in enumerate(doc.skeleton) if s and s.casefold() in ('[v4+ styles]', '[v4 styles]')), -1)
        end = next((i for i in range(start + 1, len(doc.skeleton)) if doc.skeleton[i] and doc.skeleton[i].startswith('[')), len(doc.skeleton))
        if start == -1:
            doc.skeleton[0:0] = ['[V4+ Styles]'] + additions + ['']
        else:
            doc.skeleton[end:end] = additions
    for cue in cues:
        style = cue.ass_fields.get('Style', 'Default')
        cue.ass_fields['Style'] = rename.get(style, style)
        field = 'translation' if cue.translation is not None else 'text'
        setattr(cue, field, re.sub(r'\\r([^\\}]+)', lambda m: r'\r' + rename.get(m[1], m[1]), cue.output_text))


def transfer(editor, snapshot, reference, pairs, fields, *, translation=False, structure=False):
    if editor.document != snapshot:
        raise ValueError('Документ изменился. Обновите сравнение перед применением.')
    if not fields and not structure:
        raise ValueError('Выберите, какие данные перенести.')
    if 'time' in fields and any(p.chosen and p.reference is not None and reference.cues[p.reference].extras.get('untimed') for p in pairs):
        raise ValueError('В источнике ещё нет тайминга. Снимите галочку «Время» или сначала задайте интервалы.')
    def apply(doc):
        output, imported, styled, changes = [], [], [], {}
        for pair in pairs:
            left = doc.cues[pair.current] if pair.current is not None else None
            right = reference.cues[pair.reference] if pair.reference is not None else None
            if not pair.chosen:
                if left is not None:
                    output.append(left)
                continue
            if left is None:
                if structure and right is not None:
                    cue = deepcopy(right)
                    cue.id = identity('frag')
                    cue.original_line, cue.baseline = '', {}
                    imported.append(cue); styled.append(cue); output.append(cue)
                continue
            if right is None:
                if not structure:
                    output.append(left)
                else:
                    changes[left.id] = []
                continue
            if 'text' in fields:
                field = 'translation' if translation or left.translation is not None else 'text'
                setattr(left, field, right.output_text)
                Editor._sync_authored(doc, left, {field: right.output_text})
            if 'time' in fields:
                left.start, left.end = right.start, right.end
            if 'character' in fields:
                left.character, left.character_id = right.character, ''
            if 'format' in fields:
                ignored = {'Start', 'End', 'Text', 'Name', 'Actor'}
                left.ass_fields = {k: v for k, v in left.ass_fields.items() if k in ignored}
                left.ass_fields.update({k: v for k, v in right.ass_fields.items() if k not in ignored})
                left.original_line = ''
                styled.append(left)
            output.append(left)
        import_sources(doc, reference, imported)
        import_styles(doc, reference, styled)
        for old, new in changes.items():
            rebind_reviews(doc, {old}, new)
        doc.cues = output
    return editor.transact('Перенос данных из другого файла', apply)
