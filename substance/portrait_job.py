"""Cancellable local analysis. Results own QImages, never document mutations."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

from .images import decode_image, crop_image, encode_image
from .portrait_analysis import ANALYSIS_PROFILES, CharacterMatcher, sample_times
from .portrait_models import FaceEngine, dependencies_available, prepare_models, portrait_box, qimage_rgb
from .tool_jobs import video_identity
from .transcription import SpeechJob
from .document import identity
from .project import asset_id


class PreparePortraitsJob(SpeechJob):
    """Decode/crop/encode on a worker; only the host commits the final batch."""
    def __init__(self, choices, media_path):
        super().__init__()
        self.choices, self.media_path = choices, media_path

    def execute(self):
        records = []
        for number, (index, card_id, candidate) in enumerate(self.choices):
            self.check_cancelled()
            source_data = candidate['source']
            source_key = asset_id(source_data)
            image_key, image_data = encode_image(crop_image(decode_image(source_data), candidate['crop']))
            portrait = {'id': identity('portrait'), 'source': source_key, 'image': image_key,
                        'crop': candidate['crop'], 'media_path': self.media_path, 'time': candidate['time'],
                        'frame': {'time_ms': candidate['time']}, 'make_primary': False}
            records.append((index, card_id, portrait, {source_key: source_data, image_key: image_data}))
            self.signals.progress.emit((number + 1) / len(self.choices),
                f'Подготовлено портретов: {number + 1} из {len(self.choices)}')
        self.check_cancelled()
        self.signals.result.emit(records)


class PortraitJob(SpeechJob):
    def __init__(self, path, duration, cues, characters, images, mode, directory, speed='normal'):
        super().__init__()
        self.path, self.duration, self.cues = path, duration, cues
        self.characters, self.images, self.mode, self.directory = characters, images, mode, directory
        self.profile = ANALYSIS_PROFILES[speed]

    def execute(self):
        if not dependencies_available(self.mode):
            raise ValueError('Не установлены библиотеки распознавания. Для запуска из исходников выполните: '
                             'python -m pip install -e .')
        identity = video_identity(self.path)
        paths = prepare_models(self.mode, self.directory, self.cancelled, self.signals.progress.emit)
        self.signals.progress.emit(0, 'Загрузка локальных моделей в память…')
        engine = FaceEngine(self.mode, paths)
        self.check_cancelled()
        references = []
        for card in self.characters:
            primary = next((p for p in card.get('portraits', []) if p['id'] == card.get('primary')), None)
            if primary and primary.get('image') in self.images:
                self.check_cancelled()
                image = decode_image(self.images[primary['image']])
                if not image.isNull():
                    feature = engine.reference(qimage_rgb(image))
                    if feature is not None:
                        references.append((card['id'], feature))
        matcher = CharacterMatcher(engine, references)
        duration = self.duration
        if duration <= 0:
            probe = engine.cv.VideoCapture(self.path)
            try:
                fps = probe.get(engine.cv.CAP_PROP_FPS)
                if fps > 0:
                    duration = round(probe.get(engine.cv.CAP_PROP_FRAME_COUNT) / fps * 1000)
            finally:
                probe.release()
        times = sample_times(self.cues, duration, **{k: self.profile[k] for k in ('per_character', 'limit', 'parts')})
        if not times:
            raise ValueError('Для анализа нужны таймкоды реплик или известная длительность видео')
        cv = engine.cv
        capture = cv.VideoCapture(self.path)
        decoded, detections = 0, 0
        seen_frames = set()
        try:
            if not capture.isOpened():
                raise ValueError('Не удалось открыть видео для распознавания')
            for number, stamp in enumerate(times):
                self.check_cancelled()
                capture.set(cv.CAP_PROP_POS_MSEC, stamp)
                ok, frame = capture.read()
                if not ok:
                    continue
                actual = capture.get(cv.CAP_PROP_POS_MSEC)
                if actual > 0 and abs(actual - stamp) > 500:
                    continue
                if actual > 0:
                    stamp = round(actual)
                    if stamp in seen_frames:
                        continue
                    seen_frames.add(stamp)
                decoded += 1
                h, w = frame.shape[:2]
                if max(h, w) > self.profile['max_side']:
                    ratio = self.profile['max_side'] / max(h, w)
                    frame = cv.resize(frame, (round(w * ratio), round(h * ratio)))
                rgb = cv.cvtColor(frame, cv.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                faces = engine.detect(rgb)
                self.check_cancelled()
                detections += len(faces)
                active = [c for c in self.cues if not c.get('comment') and c['start'] <= stamp < c['end']]
                source = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
                source_data = encode_image(source, source=True)[1] if faces else ''
                for box, score, feature in faces:
                    crop = portrait_box(box, w, h)
                    cropped = crop_image(source, crop)
                    pixels = qimage_rgb(cropped)
                    sharpness = float(cv.Laplacian(cv.cvtColor(pixels, cv.COLOR_RGB2GRAY), cv.CV_32F).var())
                    quality = score * np.sqrt(max(1, box[2] * box[3])) * np.log1p(sharpness)
                    preview = cropped.scaled(256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    candidate = {'source': source_data, 'preview': preview, 'crop': crop, 'time': stamp, 'quality': float(quality)}
                    matcher.add(feature, stamp, active, candidate, single_face=len(faces) == 1)
                self.signals.progress.emit((number + 1) / len(times),
                    f'Просмотрено кадров: {number + 1} из {len(times)}')
        finally:
            capture.release()
        self.check_cancelled()
        if video_identity(self.path) != identity:
            raise ValueError('Видео изменилось во время анализа. Запустите анализ заново.')
        if not decoded:
            raise ValueError('Не удалось прочитать кадры видео. Проверьте файл и его длительность.')
        self.signals.result.emit({'identity': identity, 'rows': matcher.proposals(self.characters),
                                  'frames': decoded, 'faces': detections})
