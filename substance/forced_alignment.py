"""Local acoustic CTC alignment of supplied text, using verified ONNX models."""
from dataclasses import dataclass
from pathlib import Path
from difflib import SequenceMatcher
import math
import re
import tempfile
import subprocess
import wave

import numpy as np

from .document import plain_text
from .editor_tools import Proposal
from .media import ffmpeg_executable, process_options
from .transcription import SpeechJob


@dataclass(frozen=True)
class AlignmentModel:
    id: str
    title: str
    repo: str
    revision: str
    size: int
    sha256: str
    alphabet: str

    @property
    def filename(self):
        return 'ctc-' + self.id + '.onnx'

    @property
    def url(self):
        return f'https://huggingface.co/{self.repo}/resolve/{self.revision}/onnx/model_quantized.onnx'

    @property
    def vocabulary(self):
        return {ch: i + 4 for i, ch in enumerate(self.alphabet)}


MODELS = [
    AlignmentModel('ru', 'Русский · 303 МиБ', 'onnx-community/wav2vec2-large-xlsr-53-russian-ONNX',
        'df5ba1d9e0f9a34c44eec437b441f4ae43c842eb', 317349970,
        '027f226a26c4ad2bb8cd6e4f56038b9013afc3cf6ccf2cdf9aecb092c3726344', '|-ёабвгдежзийклмнопрстуфхцчшщъыьэюя'),
    AlignmentModel('en', 'Английский · 91 МиБ', 'Xenova/wav2vec2-base-960h',
        'a19f851b3d42865797e410752b4c570c871e4825', 95286046,
        'cd5040c147381580ed73258143dd8e0c28e800a09e74ee42ee2b3e8cb4d760a3', "|ETAONIHSRDLUMWCFGPYBVK'XJQZ"),
]
MODEL_BY_ID = {m.id: m for m in MODELS}


def tokenize(text, model):
    text = plain_text(text)
    text = text.upper() if model.id == 'en' else text.lower()
    text = text.replace('’', "'").replace('–', '-').replace('—', '-')
    unsupported = sorted({c for c in text if (c.isalnum() or c == "'") and c not in model.vocabulary})
    if unsupported:
        raise ValueError('Этот текст не соответствует языку модели или содержит цифры. Запишите числа словами. Неизвестные символы: ' + ' '.join(unsupported[:20]))
    text = re.sub(r'\s+', '|', ' '.join(''.join(c if c in model.vocabulary else ' ' for c in text).split()))
    return [model.vocabulary[c] for c in text]


def ctc_align(log_probs, tokens, check=lambda: None, offset=0):
    """CTC Viterbi with real blank/repeat transitions and bounded backtracking.

    Long sequences split at acoustically recognized exact anchors; every segment
    is still forced to the supplied tokens. No proportional timestamps are used.
    """
    frames, _ = log_probs.shape
    count = len(tokens)
    if not count or frames < count:
        raise ValueError('В выбранном аудио недостаточно времени для заданного текста.')
    if frames * (2 * count + 1) > 60000000:
        best = log_probs.argmax(axis=1)
        greedy, stamps, previous = [], [], -1
        for t, value in enumerate(best):
            if value and value != previous:
                greedy.append(int(value)); stamps.append(t)
            previous = value
        matches = SequenceMatcher(None, tokens, greedy, autojunk=False).get_matching_blocks()
        anchors = [m for m in matches if m.size >= 8 and 0 < m.a + m.size//2 < count-1]
        if not anchors:
            raise ValueError('В большом фрагменте не найдены надёжные опорные слова. Выберите меньший диапазон или проверьте текст и язык.')
        anchor = min(anchors, key=lambda m: abs(m.a+m.size//2-count/2))
        split = anchor.a + anchor.size//2
        frame = stamps[anchor.b + anchor.size//2]
        if not 0 < frame < frames:
            raise ValueError('Не удалось разделить длинный фрагмент по речи. Уменьшите диапазон.')
        return ctc_align(log_probs[:frame], tokens[:split], check, offset) + ctc_align(log_probs[frame:], tokens[split:], check, offset+frame)
    labels = np.zeros(2 * count + 1, dtype=np.int64)
    labels[1::2] = tokens
    states = len(labels)
    previous = np.full(states, -np.inf, dtype=np.float32)
    previous[0] = 0
    back = np.zeros((frames, states), dtype=np.uint8)
    skip_allowed = np.zeros(states, dtype=bool)
    skip_allowed[2:] = (labels[2:] != 0) & (labels[2:] != labels[:-2])
    for t in range(frames):
        if t % 100 == 0:
            check()
        stay = previous
        advance = np.concatenate(([-np.inf], previous[:-1]))
        skip = np.concatenate(([-np.inf, -np.inf], previous[:-2]))
        skip[~skip_allowed] = -np.inf
        options = np.stack((stay, advance, skip))
        move = np.argmax(options, axis=0)
        back[t] = move
        previous = options[move, np.arange(states)] + log_probs[t, labels]
    state = states - 1 if previous[-1] >= previous[-2] else states - 2
    if not np.isfinite(previous[state]):
        raise ValueError('Не удалось выровнять текст с повторяющимися звуками. Проверьте диапазон.')
    spans = [[] for _ in tokens]
    for t in range(frames-1, -1, -1):
        if state % 2:
            spans[state//2].append(t)
        state -= int(back[t, state])
    if any(not span for span in spans):
        raise ValueError('Часть слов не получила акустических меток. Проверьте текст.')
    return [(offset + min(span), offset + max(span)+1,
             float(np.exp(log_probs[span, token]).max())) for span, token in zip(spans, tokens)]


class ForcedAlignmentJob(SpeechJob):
    def __init__(self, document, indices, path, track, model, model_path, start, end, *, original=True):
        super().__init__()
        self.document, self.indices = document, indices
        self.path, self.track, self.model, self.model_path = path, track, model, Path(model_path)
        self.start, self.end, self.original = start, end, original

    def execute(self):
        import onnxruntime as ort
        from .transcription import verify_model
        verify_model(self.model_path, self.model, self.cancelled)
        cues, tokens, ranges = [], [], []
        for i in self.indices:
            cue = self.document.cues[i]
            if cue.comment:
                continue
            text = cue.original if self.original and cue.original else cue.output_text
            part = tokenize(text, self.model)
            if not part:
                continue
            if tokens:
                tokens.append(self.model.vocabulary['|'])
            ranges.append((len(tokens), len(tokens)+len(part)))
            tokens.extend(part)
            cues.append(cue)
        if not tokens:
            raise ValueError('В выбранных репликах нет текста для выравнивания.')
        self.signals.progress.emit(0, 'Читаем аудиодорожку…')
        with tempfile.TemporaryDirectory(prefix='substance-align-') as directory:
            target = Path(directory) / 'audio.wav'
            self.process = subprocess.Popen([ffmpeg_executable(), '-nostdin', '-v', 'error', '-ss', str(self.start/1000),
                '-i', self.path, '-t', str((self.end-self.start)/1000), '-map', f'0:a:{max(0, self.track)}',
                '-vn', '-sn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-y', str(target)],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **process_options())
            _, error = self.process.communicate()
            self.check_cancelled()
            if self.process.returncode:
                raise ValueError('Не удалось прочитать аудио: ' + error.decode('utf-8', errors='replace')[-1000:])
            session_options = ort.SessionOptions()
            session_options.intra_op_num_threads = 2
            session_options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(self.model_path), sess_options=session_options, providers=['CPUExecutionProvider'])
            emissions, stamps = [], []
            # 20-second windows, one second overlap on either side. Retain the
            # middle to avoid artificial word boundaries at each model window.
            with wave.open(str(target), 'rb') as audio:
                total = audio.getnframes()
                for base in range(0, total, 18*16000):
                    self.check_cancelled()
                    first, last = max(0, base-16000), min(total, base+19*16000)
                    audio.setpos(first)
                    signal = np.frombuffer(audio.readframes(last-first), dtype='<i2').astype(np.float32) / 32768
                    if signal.size < 400:
                        break
                    signal = (signal-signal.mean()) / math.sqrt(float(signal.var())+1e-7)
                    inputs = {'input_values': signal[None]}
                    if any(i.name == 'attention_mask' for i in session.get_inputs()):
                        inputs['attention_mask'] = np.ones((1, len(signal)), dtype=np.int64)
                    logits = session.run(None, inputs)[0][0].astype(np.float32)
                    times = (first + np.arange(len(logits))*320 + 200) / 16
                    keep = (times >= base/16) & (times < min(total, base+18*16000)/16)
                    logits, times = logits[keep], times[keep]
                    logits -= logits.max(axis=1, keepdims=True)
                    logits -= np.log(np.exp(logits).sum(axis=1, keepdims=True))
                    emissions.append(logits); stamps.extend(times.tolist())
                    self.signals.progress.emit(.8 * min(total, base+18*16000)/total, 'Ищем звучание заданных слов…')
            self.check_cancelled()
            if not emissions:
                raise ValueError('В выбранном диапазоне нет аудио.')
            spans = ctc_align(np.concatenate(emissions), tokens, self.check_cancelled)
            proposals = []
            from copy import deepcopy
            for cue, (a, b) in zip(cues, ranges):
                confidence = sum(p[2] for p in spans[a:b]) / (b-a)
                if confidence < .2:
                    proposals.append(Proposal([cue.id], [], 'Слова не подтверждены звуком. Проверьте язык и соответствие сценарию.', False, False))
                    continue
                new = deepcopy(cue)
                new.extras.pop('untimed', None)
                new.start = self.start + max(0, round(stamps[spans[a][0]] - 10))
                new.end = min(self.end, self.start + round(stamps[min(len(stamps)-1, spans[b-1][1]-1)] + 10))
                if new.end <= new.start:
                    continue
                # Acoustic estimates always require audition before committing.
                proposals.append(Proposal([cue.id], [new], f'Границы заданного текста по звуку · уверенность {confidence:.0%}', False, True, True))
            self.signals.progress.emit(1, 'Тайминг подготовлен. Прослушайте реплики перед применением.')
            self.signals.result.emit(proposals)
