"""Speech-bound phrase assembly and bounded reading-time padding."""
from dataclasses import asdict, dataclass
import math
import re


def wrap_subtitle(text, width):
    """Wrap at whitespace where possible, and at characters for CJK speech."""
    text = ' '.join(text.split())
    lines = []
    while len(text) > width:
        split = text.rfind(' ', 0, width + 1)
        split = split if split > width // 3 else width
        lines.append(text[:split])
        text = text[split:].lstrip()
    if text:
        lines.append(text)
    return r'\N'.join(lines)


@dataclass(frozen=True)
class TimingOptions:
    pause_ms: int = 450
    min_duration_ms: int = 1000
    max_duration_ms: int = 6000
    reading_cps: int = 17
    lead_ms: int = 0
    tail_ms: int = 120
    max_hold_ms: int = 800
    gap_ms: int = 80

    @classmethod
    def from_dict(cls, values=None):
        if values is not None and not isinstance(values, dict):
            raise ValueError('Некорректные настройки тайминга')
        values = values or {}
        limits = {'pause_ms': (150, 2000), 'min_duration_ms': (300, 3000),
                  'max_duration_ms': (2000, 12000), 'reading_cps': (8, 40),
                  'lead_ms': (0, 500), 'tail_ms': (0, 1000), 'max_hold_ms': (0, 3000), 'gap_ms': (0, 500)}
        converted = {}
        for key, (low, high) in limits.items():
            value = values.get(key, getattr(cls(), key))
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or int(value) != value or not low <= value <= high:
                raise ValueError('Некорректная настройка тайминга: ' + key)
            converted[key] = int(value)
        if converted['min_duration_ms'] > converted['max_duration_ms']:
            raise ValueError('Минимальная длительность больше максимальной')
        if converted['tail_ms'] > converted['max_hold_ms']:
            raise ValueError('Задержка после речи должна быть не больше максимального продления')
        return cls(**converted)

    def to_dict(self):
        return asdict(self)


def speech_word(word, intervals):
    """Undo silence stretched into a word by Whisper's VAD time mapping.

    Word endpoints can span a removed 20-second gap. Select the voice island
    with greatest overlap, then clamp both ends to its original time bounds.
    This keeps a preceding word out of the next speaker's speech island.
    """
    if not intervals:
        return None
    overlaps = [(max(0, min(word['end'], end) - max(word['start'], start)), start, end)
                for start, end in intervals if end > word['start'] and start < word['end']]
    if not overlaps:
        return None
    # Prefer the island containing the word onset. A long trailing gap must
    # not pull a word forward into a different utterance.
    onset = next((item for item in overlaps if item[1] <= word['start'] < item[2]), None)
    _, start, end = onset or max(overlaps, key=lambda item: item[0])
    result = dict(word, start=max(start, word['start']), end=min(end, word['end']))
    return result if result['end'] > result['start'] else None


def join_words(left, right):
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    if re.match(r'^[,.;:!?，。！？、：；)\]»]', right) or left[-1] in '([«':
        return left + right
    if re.search(r'[\u3000-\u9fff\uac00-\ud7af]$', left) or re.match(r'^[\u3000-\u9fff\uac00-\ud7af]', right):
        return left + right
    return left + ' ' + right


def sentence_end(text):
    if re.search(r'\b(?:Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|т|г|им)\.$', text, re.IGNORECASE):
        return False
    return bool(re.search(r'[.!?。！？]["»”\')\]]*$', text))


class PhraseAssembler:
    def __init__(self, width, options, start, end):
        self.width, self.options, self.start, self.end = width, options, start, end
        self.words = []
        self.previous_end = start

    def _text(self):
        text = ''
        for word in self.words:
            text = join_words(text, word['text'])
        return text

    def feed(self, word):
        output = []
        if not word['text'].strip() or word['end'] <= word['start']:
            return output
        if self.words:
            text = self._text()
            prospective = join_words(text, word['text'])
            overflow = len(wrap_subtitle(prospective, self.width).split(r'\N')) > 2
            # When the final word crosses the line limit, balance the complete
            # sentence instead of leaving a one-word subtitle at its end.
            if (overflow and sentence_end(word['text']) and not sentence_end(text)
                    and word['start'] - self.words[-1]['end'] < self.options.pause_ms
                    and word['end'] - self.words[0]['start'] <= self.options.max_duration_ms):
                combined = self.words + [word]
                candidates = []
                for index in range(1, len(combined)):
                    left, right = '', ''
                    for item in combined[:index]:
                        left = join_words(left, item['text'])
                    for item in combined[index:]:
                        right = join_words(right, item['text'])
                    if all(len(wrap_subtitle(part, self.width).split(r'\N')) <= 2 for part in (left, right)):
                        score = abs(len(left) - len(right))
                        if re.search(r'[,;:，；：]$', left):
                            score -= self.width // 2
                        candidates.append((score, index))
                if candidates:
                    index = min(candidates)[1]
                    self.words = combined[:index]
                    output.extend(self.finish(combined[index]['start']))
                    self.words = combined[index:]
                    return output
            split = (sentence_end(text)
                     or word['start'] - self.words[-1]['end'] >= self.options.pause_ms
                     or word['end'] - self.words[0]['start'] > self.options.max_duration_ms
                     or overflow
                     or (len(text) >= self.width and re.search(r'[,;:，；：]$', text)))
            if split:
                output.extend(self.finish(word['start']))
        self.words.append(word)
        return output

    def finish(self, next_start=None):
        if not self.words:
            return []
        options = self.options
        text = self._text()
        speech_start = self.words[0]['start']
        speech_end = max(word['end'] for word in self.words)
        start = max(self.start, self.previous_end, speech_start - options.lead_ms)
        desired = max(speech_end + options.tail_ms, start + options.min_duration_ms,
                      start + math.ceil(len(text) * 1000 / options.reading_cps))
        # Reading time is a target. Never cross the next spoken phrase, the
        # selected range, or the user's allowed hold after the final word.
        end = min(desired, speech_end + options.max_hold_ms, self.end)
        if next_start is not None:
            end = min(end, max(speech_end, next_start - options.gap_ms))
            end = min(end, next_start)
        self.words = []
        if end <= start:
            return []
        self.previous_end = end
        return [{'start': start, 'end': end, 'text': wrap_subtitle(text, self.width)}]
