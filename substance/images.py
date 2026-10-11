"""Bounded embedded images, crop processing and the QML image provider."""
import base64
import math
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QTransform
from PySide6.QtQuick import QQuickImageProvider
from .project import asset_id

MAX_SIDE = 2048


def bounded_image(image):
    if image.isNull():
        raise ValueError('Не удалось получить изображение')
    if max(image.width(), image.height()) > MAX_SIDE:
        image = image.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return image.convertToFormat(QImage.Format.Format_ARGB32 if image.hasAlphaChannel() else QImage.Format.Format_RGB32)


def load_image(path):
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    if not size.isValid() or size.width() * size.height() > 100_000_000:
        raise ValueError('Изображение слишком большое или имеет неизвестный формат')
    if max(size.width(), size.height()) > MAX_SIDE:
        reader.setScaledSize(size.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio))
    return bounded_image(reader.read())


def encode_image(image, *, source=False):
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    jpeg = source and not image.hasAlphaChannel()
    if not image.save(buffer, 'JPEG' if jpeg else 'PNG', 92 if jpeg else -1):
        raise ValueError('Не удалось сохранить изображение')
    encoded = base64.b64encode(bytes(data)).decode('ascii')
    return asset_id(encoded), encoded


def decode_image(encoded):
    return QImage.fromData(base64.b64decode(encoded, validate=True))


def crop_image(image, crop):
    if len(crop) != 4 or any(not math.isfinite(v) for v in crop):
        raise ValueError('Некорректная рамка обрезки')
    x, y, w, h = crop
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x+w <= 1.000001 and y+h <= 1.000001):
        raise ValueError('Рамка выходит за границы изображения')
    left, top = round(x * image.width()), round(y * image.height())
    right, bottom = min(image.width(), round((x+w)*image.width())), min(image.height(), round((y+h)*image.height()))
    if right-left < 8 or bottom-top < 8:
        raise ValueError('Выберите область не меньше 8 × 8 пикселей')
    result = image.copy(QRect(left, top, right-left, bottom-top))
    if max(result.width(), result.height()) > 768:
        result = result.scaled(768, 768, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    return result


def frame_image(frame):
    image = frame.toImage()
    if image.isNull():
        raise ValueError('Этот видеокадр не удалось преобразовать в изображение')
    rotation = int(frame.rotation().value)
    if rotation:
        image = image.transformed(QTransform().rotate(rotation))
    if frame.mirrored():
        image = image.flipped(Qt.Orientation.Horizontal)
    return bounded_image(image)


class ProjectImageProvider(QQuickImageProvider):
    def __init__(self, backend):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.backend = backend

    def requestImage(self, image_id, size, requested_size):
        key = image_id.split('?')[0]
        image = self.backend._capture_image if key == 'capture' else decode_image(self.backend.editor.document.images[key]) if key in self.backend.editor.document.images else QImage()
        if requested_size.isValid() and not image.isNull():
            image = image.scaled(requested_size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image
