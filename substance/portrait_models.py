"""Local face engines and immutable, SHA-256 verified model downloads.

No frame or embedding is sent to a service. Network access fetches only the
explicitly listed model weights. Imports stay lazy so opening a project does
not load either inference runtime.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import ssl
import tempfile
import urllib.request
import urllib.error

import certifi
import numpy as np


class ModelCancelled(Exception):
    """Portable cancellation signal; the host application owns its worker."""


@dataclass(frozen=True)
class ModelFile:
    name: str
    repo: str
    revision: str
    remote: str
    size: int
    sha256: str

    @property
    def url(self):
        return f'https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.remote}'


MODELS = {
    'live': (
        ModelFile('yunet.onnx', 'opencv/face_detection_yunet', '3cc26e7f1014a5ee5d74a42acee58bafc9d0a310',
                  'face_detection_yunet_2023mar.onnx', 232589, '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'),
        ModelFile('sface.onnx', 'opencv/face_recognition_sface', '3d7082438a6e4551e840c9b2bb60b71e8da4b524',
                  'face_recognition_sface_2021dec.onnx', 38696353, '0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79'),
    ),
    'anime': (
        ModelFile('anime-face.onnx', 'deepghs/anime_face_detection', '784dc4c0bb692351ddcdbe6131a050b17d3025d5',
                  'face_detect_v1.4_n/model.onnx', 12102558, 'fd860b650a4377046842c3cd80d01b0b408bdfbdb4acee5759630f82c6ef04a9'),
        ModelFile('ccip.onnx', 'deepghs/ccip_onnx', 'eb2acdd29af1703388d3d0c04221add322bc9110',
                  'ccip-caformer-24-randaug-pruned/model_feat.onnx', 150248245, '4ea118d16496274f4f6e08d3afc768cc592389e8f7f32f8732ce2215c228ac5f'),
        ModelFile('ccip-metric.onnx', 'deepghs/ccip_onnx', 'eb2acdd29af1703388d3d0c04221add322bc9110',
                  'ccip-caformer-24-randaug-pruned/model_metrics.onnx', 1649, '7e4646fdfbe369ad485b227ec47ac4092c98b8deef3af44e19fdbd8ba7bc25c1'),
    ),
}


def shared_model_directory():
    """Same contract in both standalone apps; independent of their installs."""
    override = os.environ.get('DUBBING_MODELS_DIR')
    if override:
        return Path(override).expanduser() / 'portraits-v1'
    from PySide6.QtCore import QStandardPaths
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / 'DubbingTools' / 'models' / 'portraits-v1'


def verified(path, spec, cancelled):
    if not path.is_file() or path.stat().st_size != spec.size:
        return False
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            if cancelled.is_set():
                raise ModelCancelled()
            digest.update(block)
    return digest.hexdigest() == spec.sha256


def prepare_models(mode, directory, cancelled, progress):
    from filelock import FileLock, Timeout
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for spec in MODELS[mode]:
        if cancelled.is_set():
            raise ModelCancelled()
        target = directory / spec.name
        progress(0, 'Проверка модели ' + spec.name + '…')
        if verified(target, spec, cancelled):
            result[spec.name] = str(target)
            continue
        lock = FileLock(str(target) + '.lock')
        while True:
            if cancelled.is_set():
                raise ModelCancelled()
            try:
                lock.acquire(timeout=.2)
                break
            except Timeout:
                progress(0, 'Модель загружается другой программой: ' + spec.name)
        try:
            _prepare_file(target, spec, cancelled, progress)
        finally:
            lock.release()
        result[spec.name] = str(target)
    return result


def _prepare_file(target, spec, cancelled, progress):
    directory = target.parent
    if not verified(target, spec, cancelled):
        if shutil.disk_usage(directory).free < spec.size + 64 * 1024 * 1024:
            raise ValueError('Недостаточно свободного места для загрузки модели ' + spec.name)
        handle, partial = tempfile.mkstemp(prefix=spec.name + '-', suffix='.partial', dir=directory)
        try:
            digest, count = hashlib.sha256(), 0
            request = urllib.request.Request(spec.url, headers={'User-Agent': 'Substance/portrait-models'})
            with os.fdopen(handle, 'wb') as out:
                with urllib.request.urlopen(request, timeout=15, context=ssl.create_default_context(cafile=certifi.where())) as response:
                    while block := response.read(256 * 1024):
                        if cancelled.is_set():
                            raise ModelCancelled()
                        count += len(block)
                        if count > spec.size:
                            raise ValueError('Размер модели не совпадает: ' + spec.name)
                        out.write(block)
                        digest.update(block)
                        progress(0, f'Загрузка {spec.name}: {count // 1048576} / {spec.size // 1048576} МиБ')
            if count != spec.size or digest.hexdigest() != spec.sha256:
                raise ValueError('Контрольная сумма модели не совпадает: ' + spec.name)
            os.replace(partial, target)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValueError('Не удалось скачать модель ' + spec.name + '. Проверьте подключение к интернету и повторите анализ.') from exc
        finally:
            Path(partial).unlink(missing_ok=True)


def dependencies_available(mode):
    import importlib.util
    return all(importlib.util.find_spec(name) is not None for name in
               (('cv2', 'onnxruntime', 'PIL') if mode == 'anime' else ('cv2',)))


def qimage_rgb(image):
    from PySide6.QtGui import QImage
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width() * 3].reshape(image.height(), image.width(), 3).copy()


def portrait_box(box, width, height):
    """Square head crop, with hair/forehead context, clipped to actual pixels."""
    x, y, w, h = box
    side = min(max(w * 1.5, h * 1.65), width, height)
    left = min(max(0, x + w / 2 - side / 2), width - side)
    top = min(max(0, y + h * .43 - side / 2), height - side)
    return [left / width, top / height, side / width, side / height]


class FaceEngine:
    def __init__(self, mode, paths):
        import cv2
        self.cv = cv2
        self.mode = mode
        if mode == 'live':
            self.threshold = .55  # conservative cosine similarity >= .45
            self.detector = cv2.FaceDetectorYN.create(paths['yunet.onnx'], '', (320, 320), .85, .3, 100)
            self.recognizer = cv2.FaceRecognizerSF.create(paths['sface.onnx'], '')
        else:
            import onnxruntime as ort
            ort.disable_telemetry_events()
            options = ort.SessionOptions()
            options.intra_op_num_threads = min(4, os.cpu_count() or 1)
            self.detector = ort.InferenceSession(paths['anime-face.onnx'], options, providers=['CPUExecutionProvider'])
            self.recognizer = ort.InferenceSession(paths['ccip.onnx'], options, providers=['CPUExecutionProvider'])
            self.metric = ort.InferenceSession(paths['ccip-metric.onnx'], options, providers=['CPUExecutionProvider'])
            self.threshold = .17847511429108218

    def embedding(self, rgb):
        from PIL import Image
        data = np.asarray(Image.fromarray(rgb).resize((384, 384), Image.Resampling.BILINEAR), dtype=np.float32) / 255
        data = (data - np.array([.48145466, .4578275, .40821073], np.float32)) / np.array([.26862954, .26130258, .27577711], np.float32)
        return self.recognizer.run(None, {self.recognizer.get_inputs()[0].name: data.transpose(2, 0, 1)[None]})[0][0]

    def distances(self, feature, others):
        if not len(others):
            return np.empty(0)
        values = np.asarray([feature, *others], dtype=np.float32)
        if self.mode == 'anime':
            return self.metric.run(None, {self.metric.get_inputs()[0].name: values})[0][0, 1:]
        values /= np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-8)
        return np.clip(1 - values[1:] @ values[0], 0, 2)

    def detect(self, rgb):
        cv = self.cv
        height, width = rgb.shape[:2]
        faces = []
        if self.mode == 'live':
            bgr = cv.cvtColor(rgb, cv.COLOR_RGB2BGR)
            self.detector.setInputSize((width, height))
            _, found = self.detector.detect(bgr)
            for row in ([] if found is None else found):
                x, y, w, h = map(float, row[:4])
                if min(w, h) < 24:
                    continue
                vector = self.recognizer.feature(self.recognizer.alignCrop(bgr, row)).reshape(-1)
                faces.append(([x, y, w, h], float(row[-1]), vector))
        else:
            shape = self.detector.get_inputs()[0].shape
            h, w = (shape[2] if isinstance(shape[2], int) else 640), (shape[3] if isinstance(shape[3], int) else 640)
            data = cv.resize(rgb, (w, h)).astype(np.float32).transpose(2, 0, 1)[None] / 255
            output = self.detector.run(None, {self.detector.get_inputs()[0].name: data})[0][0]
            rows = output[:, output[4] >= .4].T  # one-class YOLOv8 xywh + score
            boxes, scores = [], []
            for cx, cy, bw, bh, score in rows:
                x, y = (cx - bw / 2) * width / w, (cy - bh / 2) * height / h
                bw, bh = bw * width / w, bh * height / h
                if min(bw, bh) >= 24:
                    boxes.append([float(x), float(y), float(bw), float(bh)])
                    scores.append(float(score))
            indices = cv.dnn.NMSBoxes(boxes, scores, .4, .45) if boxes else []
            indices = np.asarray(indices).reshape(-1)[:8]
            for index in indices:
                box = boxes[index]
                if len(indices) == 1:
                    # CCIP uses character appearance, including hair/clothing.
                    # Keep wider context for identity, independently of the
                    # small square crop saved as the final portrait.
                    x, y, bw, bh = box
                    left, top = max(0, round(x - 1.5 * bw)), max(0, round(y - .3 * bh))
                    right, bottom = min(width, round(x + 2.5 * bw)), min(height, round(y + 4 * bh))
                    head = rgb[top:bottom, left:right]
                else:
                    x, y, cw, ch = portrait_box(box, width, height)
                    head = rgb[round(y * height):round((y + ch) * height), round(x * width):round((x + cw) * width)]
                if head.size:
                    faces.append((box, scores[index], self.embedding(head)))
        return faces[:8]

    def reference(self, rgb):
        faces = self.detect(rgb)
        if len(faces) == 1:
            return faces[0][2]
        # Anime references are already user-authored single-character portraits.
        return self.embedding(rgb) if self.mode == 'anime' and not faces else None
