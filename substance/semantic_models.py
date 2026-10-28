"""Pinned, optional multilingual sentence embeddings; CPU inference stays local."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .transcription import ModelDownload, SpeechJob, verify_model

REPOSITORY = 'Xenova/paraphrase-multilingual-mpnet-base-v2'
REVISION = 'e5d116277351513fd260955ece953ecddde7046e'


@dataclass(frozen=True)
class SemanticFile:
    filename: str
    remote: str
    size: int
    sha256: str

    @property
    def url(self):
        return f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{self.remote}'


FILES = (
    SemanticFile('multilingual-mpnet.onnx', 'onnx/model_quantized.onnx', 278647663,
                 '280b5fe103cc79d891d672f47826067835b7feed8b0b1865e34ed38f21719b49'),
    SemanticFile('multilingual-tokenizer.json', 'tokenizer.json', 17082913,
                 'b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441'),
)


def installed(directory):
    return all((Path(directory) / f.filename).is_file() and
               (Path(directory) / f.filename).stat().st_size == f.size for f in FILES)


class SemanticDownload(SpeechJob):
    def __init__(self, directory):
        super().__init__()
        self.directory = Path(directory)

    def execute(self):
        for index, file in enumerate(FILES):
            self.check_cancelled()
            job = ModelDownload(file, self.directory)
            job.cancelled = self.cancelled
            job.signals.progress.connect(lambda value, message, i=index:
                                         self.signals.progress.emit((i + value) / len(FILES), message))
            job.execute()


class SentenceEncoder:
    """Mean-pool masked token embeddings; cache repeated candidate phrases.

    Long inputs use overlapping token windows rather than silent truncation.
    No transformers/PyTorch runtime or remote inference is required.
    """
    def __init__(self, directory, cancelled, check=lambda: None):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.check = check
        for file in FILES:
            verify_model(Path(directory) / file.filename, file, cancelled)
        self.tokenizer = Tokenizer.from_file(str(Path(directory) / FILES[1].filename))
        self.tokenizer.enable_truncation(max_length=128, stride=16)
        pad_token = '<pad>' if self.tokenizer.token_to_id('<pad>') is not None else '[PAD]'
        self.pad_id = self.tokenizer.token_to_id(pad_token)
        self.tokenizer.enable_padding(pad_id=self.pad_id, pad_token=pad_token)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(Path(directory) / FILES[0].filename),
                                           options, providers=['CPUExecutionProvider'])
        self.inputs = {i.name for i in self.session.get_inputs()}
        self.cache = {}

    def encode(self, texts):
        missing = list(dict.fromkeys(t for t in texts if t not in self.cache))
        for base in range(0, len(missing), 16):
            self.check()
            batch = missing[base:base + 16]
            encodings = self.tokenizer.encode_batch(batch)
            windows = [(owner, window) for owner, encoding in enumerate(encodings)
                       for window in [encoding] + encoding.overflowing]
            pooled = [[] for _ in batch]
            for first in range(0, len(windows), 16):
                self.check()
                chunk = windows[first:first+16]
                length = max(len(window.ids) for _, window in chunk)
                ids = np.full((len(chunk), length), self.pad_id, dtype=np.int64)
                mask = np.zeros_like(ids)
                types = np.zeros_like(ids)
                for i, (_, window) in enumerate(chunk):
                    ids[i, :len(window.ids)] = window.ids
                    mask[i, :len(window.ids)] = window.attention_mask
                    types[i, :len(window.ids)] = window.type_ids
                values = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': types}
                output = self.session.run(None, {k: v for k, v in values.items() if k in self.inputs})[0]
                for i, (owner, _) in enumerate(chunk):
                    weight = max(1, int(mask[i].sum()))
                    pooled[owner].append(((output[i] * mask[i, :, None]).sum(axis=0) / weight, weight))
            for text, items in zip(batch, pooled):
                vectors, weights = zip(*items)
                vector = np.average(vectors, axis=0, weights=weights).astype(np.float32)
                self.cache[text] = vector / max(float(np.linalg.norm(vector)), 1e-9)
        result = np.array([self.cache[t] for t in texts], dtype=np.float32)
        # Full programmes generate many short candidate phrases. Keep their
        # inference cache bounded after materializing this call's result.
        while len(self.cache) > 12000:
            self.cache.pop(next(iter(self.cache)))
        return result


def detect_language(text):
    from py3langid.langid import LanguageIdentifier, MODEL_FILE
    identifier = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
    code, confidence = identifier.classify(text[:12000])
    return code, float(confidence)
