"""Character clustering and name attribution, independent of the editor/UI.

Face similarity establishes visual identity; subtitle attribution is separate,
weak evidence. Repeated samples of one utterance never count as several votes.
The same analysis core can be used by DubbingManager.
"""
from collections import defaultdict
from dataclasses import dataclass, field
import numpy as np

ANALYSIS_PROFILES = {
    'normal': {'per_character': 12, 'limit': 600, 'parts': (.3, .7), 'max_side': 1280},
    'fast': {'per_character': 6, 'limit': 240, 'parts': (.5,), 'max_side': 960},
}


def candidate_key(candidate):
    crop = tuple(round(v, 6) for v in candidate.get('crop', ()))
    if candidate.get('source'):
        return 'image', candidate['source'], crop
    return 'time', candidate['time'], crop


def unique_candidates(candidates):
    result, seen = [], set()
    for candidate in candidates:
        key = candidate_key(candidate)
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def combine_named_rows(rows):
    """One result per stable character ID; keep every distinct portrait choice."""
    named, groups = {}, []
    for row in rows:
        card_id = row['cardId']
        if not card_id:
            groups.append([row])
        elif card_id in named:
            named[card_id].append(row)
        else:
            named[card_id] = [row]
            groups.append(named[card_id])
    result = []
    for group in groups:
        if len(group) == 1:
            result.append(group[0])
            continue
        # Keep the trusted/default choice, even when a weakly attributed face
        # from another shot has a higher image quality score.
        winner = max(group, key=lambda r: (r['confident'], r.get('evidence', 0), r['appearances']))
        merged = dict(winner)
        selected = candidate_key(winner['candidates'][winner['variant']])
        merged['candidates'] = unique_candidates(winner['candidates'] +
            [c for row in group if row is not winner for c in row['candidates']])
        merged['variant'] = next(i for i, c in enumerate(merged['candidates']) if candidate_key(c) == selected)
        merged['appearances'] = sum(row['appearances'] for row in group)
        merged['evidence'] = sum(row.get('evidence', 0) for row in group)
        result.append(merged)
    return result


def sample_times(cues, duration, per_character=12, limit=600, parts=(.3, .7)):
    groups = defaultdict(list)
    for cue in cues:
        if not cue.get('comment') and cue['end'] > cue['start'] >= 0:
            groups[cue.get('character_id', '')].append(cue)
    samples = set()
    # Round robin preserves rare characters when the total sample budget fills.
    selected = []
    for values in groups.values():
        values = sorted(values, key=lambda c: c['start'])
        count = min(per_character, len(values))
        selected.append([values[i] for i in np.linspace(0, len(values) - 1, count, dtype=int)])
    for rank in range(per_character):
        for values in selected:
            if rank >= len(values):
                continue
            cue = values[rank]
            for part in parts:
                stamp = round(cue['start'] + (cue['end'] - cue['start']) * part)
                if (duration <= 0 or stamp < duration) and len(samples) < limit:
                    samples.add(stamp)
    if not samples and duration > 0:
        samples.update(map(int, np.linspace(0, max(0, duration - 100), min(limit, max(1, duration // 2000)))))
    return sorted(samples)


@dataclass
class FaceGroup:
    feature: object
    count: int = 0
    times: set = field(default_factory=set)
    votes: dict = field(default_factory=dict)
    contexts: dict = field(default_factory=lambda: defaultdict(set))
    candidates: list = field(default_factory=list)


class CharacterMatcher:
    def __init__(self, engine, references=()):
        self.engine = engine
        self.references = references
        self.groups = []

    def add(self, feature, stamp, cues, candidate, *, single_face):
        distances = self.engine.distances(feature, [g.feature for g in self.groups])
        # Two faces visible simultaneously cannot be the same group. A second
        # close group is ambiguous; avoid silently merging similar characters.
        possible = sorted((float(d), i) for i, d in enumerate(distances)
                          if stamp not in self.groups[i].times and d <= self.engine.threshold)
        if possible and (len(possible) == 1 or possible[1][0] - possible[0][0] > self.engine.threshold * .12):
            group = self.groups[possible[0][1]]
            group.feature = (group.feature * min(group.count, 8) + feature) / (min(group.count, 8) + 1)
        else:
            if len(self.groups) >= 256:
                return
            group = FaceGroup(np.asarray(feature, np.float32).copy())
            self.groups.append(group)
        group.count += 1
        group.times.add(stamp)
        speakers = {c.get('character_id') for c in cues if c.get('character_id')}
        if single_face and len(speakers) == 1 and all(c.get('character_id') for c in cues):
            speaker = next(iter(speakers))
            for cue in cues:
                if cue.get('character_id') == speaker:
                    group.votes[cue['id']] = speaker
                    group.contexts[speaker].add(stamp // 10000)
        # Keep a few independent frames, without retaining the entire video.
        if candidate is not None:
            nearby = next((p for p in group.candidates if abs(p['time'] - stamp) < 1000), None)
            if nearby is None or nearby['quality'] < candidate['quality']:
                if nearby is not None:
                    group.candidates.remove(nearby)
                group.candidates.append(candidate)
                group.candidates.sort(key=lambda p: p['quality'], reverse=True)
                del group.candidates[3:]

    def proposals(self, characters):
        names = {c['id']: c['name'] for c in characters}
        occupied = {c['id'] for c in characters if c.get('primary')}
        rows = []
        for group in self.groups:
            if not group.candidates:
                continue
            votes = defaultdict(int)
            for speaker in group.votes.values():
                votes[speaker] += 1
            ranking = sorted(votes.items(), key=lambda p: p[1], reverse=True)
            card, count = ranking[0] if ranking else ('', 0)
            total = sum(votes.values())
            strong = count >= 3 and count / max(1, total) >= .8 and len(group.contexts[card]) >= 2
            reason = f'Совпадения по репликам: {count} из {total}. Требуется проверка.'
            if strong:
                reason = f'Согласованы {count} реплик в нескольких частях видео.'
            reference_scores = defaultdict(lambda: float('inf'))
            if self.references:
                distances = self.engine.distances(group.feature, [r[1] for r in self.references])
                for (recipient, _), distance in zip(self.references, distances):
                    reference_scores[recipient] = min(reference_scores[recipient], float(distance))
                references = sorted(reference_scores.items(), key=lambda p: p[1])
                recipient, distance = references[0]
                unambiguous = len(references) == 1 or references[1][1] - distance > self.engine.threshold * .2
                if distance < self.engine.threshold * .75 and unambiguous:
                    if strong and card != recipient:
                        strong = False
                        reason = 'Образец портрета и реплики указывают на разных персонажей.'
                    else:
                        card, strong = recipient, True
                        reason = 'Совпадение с существующим портретом.'
            if card not in names:
                card, strong = '', False
            rows.append({'cardId': card, 'confident': strong, 'checked': strong and card not in occupied,
                         'reason': reason, 'evidence': count, 'appearances': group.count,
                         'candidates': group.candidates, 'variant': 0, 'applied': False})
        # Competing visual identities for one name must be reviewed together.
        recipients = defaultdict(list)
        for row in rows:
            if row['cardId']:
                recipients[row['cardId']].append(row)
        for values in recipients.values():
            confident = [r for r in values if r['confident']]
            if len(confident) > 1:
                for row in confident:
                    row.update(checked=False, confident=False, reason='Несколько разных групп лиц претендуют на это имя. Выберите правильную.')
        return sorted(combine_named_rows(rows), key=lambda r: (not r['checked'], not r['confident'], -r['appearances']))
