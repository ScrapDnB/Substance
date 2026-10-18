"""Non-destructive timing plans in integer milliseconds."""
from bisect import bisect_right
from fractions import Fraction


MAX_TIME = 2_147_483_647  # Qt's millisecond properties use signed integers.


def point_mapping(cues, points):
    """One point offsets; multiple points linearly map each adjacent interval.

    Outside the anchors, continue the first/last segment. Both edges use the
    same continuous mapping, including cues crossing an anchor.
    """
    by_id = {c.id: c for c in cues}
    anchors = []
    for cue_id, target in points.items():
        if cue_id not in by_id:
            raise ValueError('Опорная реплика отсутствует в документе. Откройте синхронизацию заново.')
        if not isinstance(target, int) or not 0 <= target <= MAX_TIME:
            raise ValueError('Время опорной точки должно быть от 00:00:00.000 до 596:31:23.647.')
        anchors.append((by_id[cue_id].start, target))
    anchors.sort()
    if not anchors:
        return lambda t: t
    if len(anchors) == 1:
        source, target = anchors[0]
        return lambda t: t + target - source
    for (a, b), (c, d) in zip(anchors, anchors[1:]):
        if a == c:
            raise ValueError('У двух опорных реплик одинаковое начало. Оставьте одну точку для этого времени.')
        if b >= d:
            raise ValueError('Время точек должно возрастать: следующая точка должна быть позже предыдущей.')
    starts = [a for a, _ in anchors]

    def mapped(t):
        segment = max(0, min(len(anchors) - 2, bisect_right(starts, t) - 1))
        a, b = anchors[segment]
        c, d = anchors[segment + 1]
        return round(Fraction(b) + Fraction((t - a) * (d - b), c - a))

    return mapped


def timing_plan(cues, indices, *, delta=0, edges='both', points=None):
    if edges not in ('both', 'start', 'end'):
        raise ValueError('Некорректный режим сдвига')
    mapping = point_mapping(cues, points) if points is not None else lambda t: t + delta
    result = []
    for i in sorted(set(indices)):
        cue = cues[i]
        start = mapping(cue.start) if points is not None or edges in ('both', 'start') else cue.start
        end = mapping(cue.end) if points is not None or edges in ('both', 'end') else cue.end
        error = ''
        if start < 0 or end < 0:
            error = 'Время раньше нуля'
        elif end < start or (cue.end > cue.start and end == start):
            error = 'Интервал исчезнет или конец окажется раньше начала'
        elif max(start, end) > MAX_TIME:
            error = 'Время выходит за допустимый диапазон'
        result.append({'index': i, 'start': start, 'end': end, 'error': error})
    return result
