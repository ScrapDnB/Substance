"""One reviewable lead/gap/shot/frame pass with overlap protection."""
from bisect import bisect_left
from copy import deepcopy

from .editor_tools import Proposal, complex_timing
from .timecode import frame_time


def nearest_frame(value, times, fps):
    if not times:
        return frame_time(value, fps)
    at = bisect_left(times, value)
    return min(times[max(0, at - 1):at + 1], key=lambda t: abs(t - value))


def process_timing(document, indices, options, *, cuts=(), frame_times=()):
    lead = max(0, min(5000, int(options.get('lead', 100))))
    tail = max(0, min(5000, int(options.get('tail', 200))))
    gap = max(0, min(2000, int(options.get('bridgeGap', 80))))
    bias = max(0, min(100, int(options.get('bias', 100)))) / 100
    minimum = max(1, min(10000, int(options.get('minimum', 100))))
    styles = {s.strip() for s in str(options.get('styles', '')).split(',') if s.strip()}
    actors = {s.strip() for s in str(options.get('actors', '')).split(',') if s.strip()}
    ordered = sorted((i for i, c in enumerate(document.cues) if not c.comment), key=lambda i: document.cues[i].start)
    overlap, max_end = set(), -1
    for pos, i in enumerate(ordered):
        cue = document.cues[i]
        if cue.start < max_end or (pos + 1 < len(ordered) and document.cues[ordered[pos+1]].start < cue.end):
            overlap.add(i)
        max_end = max(max_end, cue.end)
    eligible, proposals = {}, []
    for i in indices:
        c = document.cues[i]
        if c.comment or (styles and c.ass_fields.get('Style', 'Default') not in styles) or (actors and c.character not in actors):
            continue
        if complex_timing(c.output_text) or (options.get('protectOverlap', True) and i in overlap):
            proposals.append(Proposal([c.id], [], 'Одновременная речь или анимация — время сохранено', False, False))
            continue
        eligible[i] = deepcopy(c)
    for pos, i in enumerate(ordered):
        if i not in eligible:
            continue
        c, new = document.cues[i], eligible[i]
        if options.get('padding', True):
            previous = document.cues[ordered[pos-1]] if pos else None
            following = document.cues[ordered[pos+1]] if pos + 1 < len(ordered) else None
            new.start = max(0, c.start - lead, previous.end if previous and previous.end <= c.start else 0)
            new.end = min(c.end + tail, following.start if following and following.start >= c.end else c.end + tail)
    if options.get('bridge', True):
        for i, j in zip(ordered, ordered[1:]):
            if i not in eligible or j not in eligible:
                continue
            a, b = eligible[i], eligible[j]
            if (a.character_id or a.character, a.ass_fields.get('Style', 'Default')) != (b.character_id or b.character, b.ass_fields.get('Style', 'Default')):
                continue
            distance = b.start - a.end
            if 0 < distance <= gap:
                meeting = a.end + round(distance * bias)
                a.end, b.start = meeting, meeting
    if options.get('trimOverlap', False):
        for i, j in zip(ordered, ordered[1:]):
            if i not in eligible:
                continue
            a, b = eligible[i], eligible.get(j, document.cues[j])
            same_actor = (a.character_id or a.character) == (b.character_id or b.character)
            if same_actor and a.start < b.start < a.end and b.start-a.start >= minimum:
                a.end = b.start
    cuts = sorted(set(cuts))
    for i, new in eligible.items():
        old = document.cues[i]
        if options.get('snapCuts', False) and cuts:
            for edge in ('start', 'end'):
                value = getattr(new, edge)
                at = bisect_left(cuts, value)
                candidates = cuts[max(0, at-1):at+1]
                near = min(candidates, key=lambda t: abs(t-value))
                key = edge + ('Before' if value < near else 'After')
                tolerance = max(0, min(2000, int(options.get(key, 120))))
                if abs(value-near) <= tolerance:
                    setattr(new, edge, near)
        if options.get('frames', False):
            new.start = nearest_frame(new.start, frame_times, document.fps)
            new.end = nearest_frame(new.end, frame_times, document.fps)
        if (new.start, new.end) == (old.start, old.end):
            continue
        if new.end - new.start < minimum:
            proposals.append(Proposal([old.id], [], 'После обработки реплика стала бы слишком короткой; время сохранено', False, False))
            eligible[i] = deepcopy(old)
    # Final validation accounts for the *result* of all three passes.
    # Reject the whole conflicting pair rather than manufacturing an overlap.
    blocked = set()
    for i, j in zip(ordered, ordered[1:]):
        a, b = eligible.get(i, document.cues[i]), eligible.get(j, document.cues[j])
        if a.end > b.start and document.cues[i].end <= document.cues[j].start:
            blocked.update(k for k in (i, j) if k in eligible)
    for i, new in eligible.items():
        old = document.cues[i]
        if (new.start, new.end) == (old.start, old.end):
            continue
        if i in blocked:
            proposals.append(Proposal([old.id], [], 'Привязка создала бы пересечение; время сохранено', False, False))
        else:
            proposals.append(Proposal([old.id], [new], 'Отступы, промежутки и привязка по выбранным правилам'))
    return proposals
