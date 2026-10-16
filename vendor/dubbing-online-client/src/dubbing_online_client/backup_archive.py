"""Strict, dependency-free inspection of downloadable server backups."""

import hashlib
import json
from pathlib import Path
import re
import tarfile

MAX_BYTES = 16 * 1024**3
MAX_MEMBERS = 200_000
BLOB = re.compile(r"assets/[0-9a-f]{2}/[0-9a-f]{62}$")


class _BackupTarInfo(tarfile.TarInfo):
    def _proc_pax(self, archive):
        if self.size > 16384:
            raise ValueError('Слишком большие служебные заголовки архива.')
        return super()._proc_pax(archive)

    def _proc_gnulong(self, archive):
        if self.size > 4096:
            raise ValueError('Слишком длинное имя файла в архиве.')
        return super()._proc_gnulong(archive)


def inspect_backup(path, *, destination=None, cancel=None):
    """Validate every member before extraction; never call tar.extract(all)."""
    path = Path(path)
    size = path.stat().st_size
    if size <= 0 or size > MAX_BYTES:
        raise ValueError("Размер резервной копии должен быть от 1 байта до 16 ГБ.")
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            if cancel and cancel.is_set():
                raise InterruptedError("Проверка отменена.")
            digest.update(chunk)
    names, blobs, total, manifest, dump = set(), 0, 0, None, False
    destination = Path(destination) if destination is not None else None
    if destination:
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with tarfile.open(path, 'r:*', tarinfo=_BackupTarInfo) as archive:
            for member in archive:
                if cancel and cancel.is_set():
                    raise InterruptedError("Проверка отменена.")
                name = member.name
                if name in names or len(names) >= MAX_MEMBERS:
                    raise ValueError("Повторяющиеся файлы или слишком большой архив.")
                names.add(name)
                if not member.isfile() or not (name in ('manifest.json', 'database.dump') or BLOB.fullmatch(name)):
                    raise ValueError("Неизвестный файл или небезопасный путь в резервной копии.")
                total += member.size
                if total > MAX_BYTES or member.size < 0:
                    raise ValueError("Распакованная копия превышает 16 ГБ.")
                if name == 'manifest.json' and member.size > 16384:
                    raise ValueError("Некорректное описание резервной копии.")
                source = archive.extractfile(member)
                checksum = hashlib.sha256()
                collected = bytearray()
                output = None
                if destination:
                    target = destination / name
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    output = target.open('xb')
                    target.chmod(0o600)
                try:
                    first = True
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        if cancel and cancel.is_set():
                            raise InterruptedError("Проверка отменена.")
                        if first and name == 'database.dump' and not chunk.startswith(b'PGDMP'):
                            raise ValueError("В копии нет PostgreSQL custom dump.")
                        first = False
                        checksum.update(chunk)
                        if name == 'manifest.json':
                            collected.extend(chunk)
                        if output:
                            output.write(chunk)
                    if name == 'database.dump':
                        if first:
                            raise ValueError("Пустая база данных в архиве.")
                        dump = True
                finally:
                    source.close()
                    if output:
                        output.close()
                if BLOB.fullmatch(name):
                    if checksum.hexdigest() != name.removeprefix('assets/').replace('/', ''):
                        raise ValueError("Контрольная сумма изображения или шрифта не совпадает.")
                    blobs += 1
                elif name == 'manifest.json':
                    manifest = json.loads(collected)
    except (tarfile.TarError, UnicodeError, json.JSONDecodeError, EOFError):
        raise ValueError("Файл не является целой резервной копией DubbingManager.") from None
    if (not dump or not isinstance(manifest, dict) or manifest.get('format_version') != 1
            or type(manifest.get('images')) is not int or manifest['images'] != blobs
            or manifest.get('database_revision') not in {f'{n:04}' for n in range(1, 10)}
            or not isinstance(manifest.get('created_at'), str)):
        raise ValueError("Неподдерживаемая, неполная или более новая резервная копия сервера.")
    return {**manifest, 'size': size, 'unpacked_size': total, 'sha256': digest.hexdigest(), 'blobs': blobs}
