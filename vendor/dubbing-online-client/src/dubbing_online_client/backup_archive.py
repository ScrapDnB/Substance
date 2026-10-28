"""Strict, dependency-free inspection of downloadable server backups."""

import hashlib
import json
from pathlib import Path
import re
import tarfile

MAX_BYTES = 1024**4  # Whole-server archives can contain many 16 GiB media files.
MAX_MEMBERS = 200_000
BLOB = re.compile(r"assets/[0-9a-f]{2}/[0-9a-f]{62}$")
PROJECT = re.compile(r"projects/(?:active/|archived/)?[\w-]{1,100}\.dub$")
MEDIA = re.compile(r"media/[0-9a-f]{64}(?:\.[a-z0-9]{1,10})?$")
MAX_MANIFEST = 16 * 1024**2
MAX_PROJECT_INDEX = 128 * 1024**2


def bundle_member(name):
    return name in ("projects.json", "README.txt") or PROJECT.fullmatch(name) or MEDIA.fullmatch(name)


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
        raise ValueError("Размер резервной копии должен быть от 1 байта до 1 ТБ.")
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            if cancel and cancel.is_set():
                raise InterruptedError("Проверка отменена.")
            digest.update(chunk)
    names, blobs, total, manifest, dump = set(), 0, 0, None, False
    extra_hashes, project_index, dump_sha256 = {}, None, None
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
                if not member.isfile() or not (name in ('manifest.json', 'database.dump') or BLOB.fullmatch(name) or bundle_member(name)):
                    raise ValueError("Неизвестный файл или небезопасный путь в резервной копии.")
                total += member.size
                if total > MAX_BYTES or member.size < 0:
                    raise ValueError("Распакованная копия превышает 1 ТБ.")
                if name == 'manifest.json' and member.size > MAX_MANIFEST:
                    raise ValueError("Некорректное описание резервной копии.")
                if name == 'projects.json' and member.size > MAX_PROJECT_INDEX:
                    raise ValueError("Слишком большой список проектов в резервной копии.")
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
                        if name in ('manifest.json', 'projects.json'):
                            collected.extend(chunk)
                        if output:
                            output.write(chunk)
                    if name == 'database.dump':
                        if first:
                            raise ValueError("Пустая база данных в архиве.")
                        dump = True
                        dump_sha256 = checksum.hexdigest()
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
                elif bundle_member(name):
                    extra_hashes[name] = checksum.hexdigest()
                    if name == 'projects.json':
                        project_index = json.loads(collected)
    except (tarfile.TarError, UnicodeError, json.JSONDecodeError, EOFError):
        raise ValueError("Файл не является целой резервной копией DubbingManager.") from None
    if (not dump or not isinstance(manifest, dict) or type(manifest.get('format_version')) is not int or manifest['format_version'] not in (1, 2)
            or type(manifest.get('images')) is not int or manifest['images'] != blobs
            or manifest.get('database_revision') not in {f'{n:04}' for n in range(1, 11)}
            or not isinstance(manifest.get('created_at'), str)):
        raise ValueError("Неподдерживаемая, неполная или более новая резервная копия сервера.")
    if manifest['format_version'] == 1 and extra_hashes:
        raise ValueError("Неизвестные файлы в резервной копии прежнего формата.")
    if manifest['format_version'] == 2:
        if (not isinstance(manifest.get('files'), dict) or manifest['files'] != extra_hashes
                or manifest.get('database_sha256') != dump_sha256
                or type(manifest.get('project_count')) is not int or manifest['project_count'] < 0
                or not isinstance(project_index, dict) or not isinstance(project_index.get('projects'), list)
                or len(project_index['projects']) != manifest['project_count']):
            raise ValueError("Состав или контрольные суммы архива проектов не совпадают.")
        project_states = {}
        for snapshot in project_index['projects']:
            project = snapshot.get('project') if isinstance(snapshot, dict) else None
            if (not isinstance(project, dict) or not isinstance(project.get('id'), str)
                    or not project['id'] or project['id'] in project_states
                    or type(project.get('archived')) is not bool):
                raise ValueError("Некорректное состояние проекта в резервной копии.")
            project_states[project['id']] = project['archived']
        if manifest.get('bundle_complete'):
            projects = manifest.get('projects')
            paths = {name for name in extra_hashes if PROJECT.fullmatch(name)}
            if (not isinstance(projects, list) or len(projects) != manifest['project_count']
                    or any(not isinstance(row, dict) or not isinstance(row.get('file'), str) for row in projects)
                    or len(paths) != len(projects) or {row['file'] for row in projects} != paths):
                raise ValueError("В архиве отсутствуют автономные проекты .dub.")
            if (any(not isinstance(row.get('id'), str) or type(row.get('archived')) is not bool for row in projects)
                    or {row['id']: row['archived'] for row in projects} != project_states):
                raise ValueError("Архивность проектов в манифесте не совпадает со снимком.")
        counts = {'active_projects': sum(not archived for archived in project_states.values()),
                  'archived_projects': sum(project_states.values())}
    else:
        counts = {}
    return {**manifest, **counts, 'size': size, 'unpacked_size': total, 'sha256': digest.hexdigest(), 'blobs': blobs}
