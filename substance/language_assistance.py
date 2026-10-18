"""Translation adapters and an indexed, device-local Wiktextract dictionary."""
from __future__ import annotations

import gzip
import json
import re
import sqlite3
import ssl
import threading
import unicodedata
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

import certifi

from .document import plain_text
from .ass_formatting import _python_position

PROVIDERS = {'azure': 'Microsoft Azure', 'deepl': 'DeepL', 'libre': 'LibreTranslate'}
LANGUAGES = [
    ('en', 'Английский'), ('ru', 'Русский'), ('ja', 'Японский'), ('ko', 'Корейский'),
    ('zh', 'Китайский'), ('de', 'Немецкий'), ('fr', 'Французский'), ('es', 'Испанский'),
    ('it', 'Итальянский'), ('pt', 'Португальский'), ('uk', 'Украинский'),
    ('pl', 'Польский'), ('tr', 'Турецкий'), ('ar', 'Арабский'), ('nl', 'Нидерландский'),
]
PACKS = {
    'simple': {'title': 'Базовый английский · около 5 МБ', 'language': 'en',
               'url': 'https://kaikki.org/dictionary/downloads/simple/simple-extract.jsonl.gz'},
    'ru': {'title': 'Русская редакция · около 295 МБ', 'language': 'ru',
           'url': 'https://kaikki.org/dictionary/downloads/ru/ru-extract.jsonl.gz'},
}
POS = {'noun': 'существительное', 'verb': 'глагол', 'adj': 'прилагательное',
       'adv': 'наречие', 'pron': 'местоимение', 'prep': 'предлог', 'name': 'имя собственное',
       'intj': 'междометие', 'conj': 'союз', 'phrase': 'выражение', 'num': 'числительное'}


class AssistanceError(ValueError):
    pass


def clean_text(text):
    return ' '.join(plain_text(text).split())


def selected_plain_text(text, start, end):
    start, end = sorted((_python_position(text, start), _python_position(text, end)))
    offset, drawing, selected = 0, False, []
    for part in re.split(r'(\{[^}]*\})', text):
        if part.startswith('{') and part.endswith('}'):
            mode = re.search(r'\\p(\d+)', part)
            if mode:
                drawing = int(mode.group(1)) != 0
        elif not drawing:
            selected.append(part[max(0, start - offset):max(0, end - offset)])
        offset += len(part)
    return clean_text(''.join(selected))


def word_key(text):
    return unicodedata.normalize('NFC', text).replace('\u0301', '').casefold().strip()


def word_selection(text):
    # Keep apostrophes/hyphens within words. Unsegmented CJK is resolved against
    # the dictionary first; a missing entry can still be translated as a phrase.
    return bool(text) and len(text) <= 100 and bool(re.fullmatch(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", text, re.UNICODE))


def endpoint(value):
    value = value.strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise AssistanceError('Укажите адрес сервера http://… или https://… без ключа и параметров.')
    try:
        parsed.port
    except ValueError as exc:
        raise AssistanceError('Некорректный порт сервера LibreTranslate.') from exc
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # In particular, never forward provider credentials to a redirect host.
        return None


def network_open(request, timeout=12):
    return build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(request, timeout=timeout)


def request_json(url, payload=None, headers=None, opener=network_open):
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
    request = Request(url, data=data, headers={
        'User-Agent': 'Substance/0.1 (dictionary and translation)',
        'Accept': 'application/json', 'Content-Type': 'application/json; charset=utf-8', **(headers or {})})
    try:
        with opener(request) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise AssistanceError('Слишком большой ответ сервиса.')
        return json.loads(raw)
    except HTTPError as exc:
        # Server bodies can echo the submitted text or credentials. Do not put
        # them (or credential-bearing request URLs) in UI errors/logs.
        messages = {400: 'Сервис не поддерживает запрос или выбранную пару языков.',
                    401: 'Проверьте API-ключ.', 403: 'Нет доступа: проверьте ключ, регион и квоту.',
                    404: 'Сервис не найден. Проверьте адрес сервера.',
                    429: 'Достигнут лимит запросов. Попробуйте позже.',
                    456: 'Лимит символов DeepL исчерпан.'}
        raise AssistanceError(messages.get(exc.code, f'Сервис вернул ошибку HTTP {exc.code}.')) from None
    except (URLError, OSError, TimeoutError):
        raise AssistanceError('Не удалось подключиться. Проверьте сеть и адрес сервера.') from None
    except (ValueError, UnicodeError):
        raise AssistanceError('Сервис вернул некорректный ответ.') from None


def translate(texts, source, target, config, key, context='', requester=request_json):
    """One bounded batch; source='auto' is omitted where the provider expects it."""
    provider = config['provider']
    if provider not in PROVIDERS:
        raise AssistanceError('Выберите сервис перевода.')
    if provider != 'libre' and not key:
        raise AssistanceError('Добавьте API-ключ в настройках «Словарь и перевод».')
    if not texts or sum(map(len, texts)) > 12000:
        raise AssistanceError('Выделите фрагмент длиной до 12 000 символов.')
    try:
        if provider == 'azure':
            language = lambda code: {'zh': 'zh-Hans', 'pt': 'pt'}.get(code, code)
            params = {'api-version': '3.0', 'to': language(target)}
            if source != 'auto':
                params['from'] = language(source)
            headers = {'Ocp-Apim-Subscription-Key': key}
            if config.get('azureRegion'):
                headers['Ocp-Apim-Subscription-Region'] = config['azureRegion']
            result = requester('https://api.cognitive.microsofttranslator.com/translate?' + urlencode(params),
                               [{'Text': text} for text in texts], headers)
            if not isinstance(result, list):
                raise TypeError('Expected an array')
            translated = [item['translations'][0]['text'] for item in result]
            detected = result[0].get('detectedLanguage', {}).get('language', source) if result else source
        elif provider == 'deepl':
            plan = config.get('deeplPlan', 'auto')
            free = plan == 'free' or (plan == 'auto' and key.endswith(':fx'))
            url = 'https://api-free.deepl.com/v2/translate' if free else 'https://api.deepl.com/v2/translate'
            language = lambda code: {'en': 'EN-US', 'pt': 'PT-PT', 'zh': 'ZH-HANS'}.get(code, code.upper())
            body = {'text': texts, 'target_lang': language(target)}
            if source != 'auto':
                body['source_lang'] = source.upper()
            if context:
                body['context'] = context[:6000]
            result = requester(url, body, {'Authorization': 'DeepL-Auth-Key ' + key})
            translated = [item['text'] for item in result['translations']]
            detected = result['translations'][0].get('detected_source_language', source).lower()
        else:
            body = {'q': texts, 'source': source, 'target': target, 'format': 'text'}
            if key:
                body['api_key'] = key
            result = requester(endpoint(config['libreUrl']) + '/translate', body, {})
            translated = result['translatedText']
            if isinstance(translated, str):
                translated = [translated]
            detected = result.get('detectedLanguage', {})
            if isinstance(detected, list):
                detected = detected[0] if detected else {}
            detected = detected.get('language', source) if isinstance(detected, dict) else source
        if not isinstance(translated, list) or len(translated) != len(texts) or any(not isinstance(s, str) or not s.strip() for s in translated):
            raise AssistanceError('Сервис вернул неполный перевод.')
        return translated, detected
    except (KeyError, IndexError, TypeError, AttributeError):
        raise AssistanceError('Сервис вернул неожиданный формат ответа.') from None


def dictionary_record(raw, definition_language, edition=None):
    word, language = raw.get('word', ''), raw.get('lang_code', '')
    if not isinstance(word, str) or not word or not isinstance(language, str) or not language:
        return None
    senses = []
    for sense in raw.get('senses', [])[:12]:
        glosses = sense.get('glosses') or sense.get('raw_glosses') or []
        gloss = '; '.join(g for g in glosses if isinstance(g, str))[:2000]
        if not gloss:
            continue
        examples = [e.get('text', '') for e in sense.get('examples', [])[:3] if isinstance(e, dict)]
        translations = list(sense.get('translations', []))
        # Some editions put translations on the entry and identify the sense.
        translations += [t for t in raw.get('translations', []) if not t.get('sense') or t.get('sense') in glosses]
        senses.append({'definition': gloss, 'examples': [e[:1000] for e in examples if isinstance(e, str) and e],
                       'translations': [{'language': t.get('lang_code', ''), 'text': t.get('word', '')}
                                        for t in translations if isinstance(t.get('word'), str)][:100],
                       'base': [f['word'] for f in sense.get('form_of', []) if isinstance(f.get('word'), str)]})
    if not senses:
        return None
    return {'word': word, 'language': language, 'languageName': raw.get('lang', language),
            'pos': POS.get(raw.get('pos'), raw.get('pos', '')), 'senses': senses,
            'definitionLanguage': definition_language,
            'url': 'https://' + (edition or definition_language) + '.wiktionary.org/wiki/' + quote(word, safe=''),
            'source': 'Wiktionary / Kaikki (CC BY-SA, GFDL)'}


def install_dictionary(source, destination, definition_language, cancelled=None, progress=None):
    """Build a replacement database, then atomically publish a complete index."""
    cancelled = cancelled or threading.Event()
    progress = progress or (lambda count: None)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.' + uuid4().hex + '.tmp')
    count = 0
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.set_progress_handler(lambda: int(cancelled.is_set()), 10000)
            db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;'
                             'CREATE TABLE entries (id INTEGER PRIMARY KEY, data TEXT);'
                             'CREATE TABLE words (word TEXT, language TEXT, entry_id INTEGER);'
                             'CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT);')
            open_file = gzip.open if str(source).endswith('.gz') else open
            with open_file(source, 'rt', encoding='utf-8') as stream:
                while True:
                    if cancelled.is_set():
                        raise AssistanceError('Установка словаря отменена.')
                    line = stream.readline(16_000_001)
                    if not line:
                        break
                    if len(line) > 16_000_000:
                        raise AssistanceError('Слишком большая запись в словаре.')
                    if not line.strip():
                        continue
                    raw = json.loads(line)
                    record = dictionary_record(raw, definition_language, 'simple' if destination.stem == 'simple' else None)
                    if record is None:
                        continue
                    cursor = db.execute('INSERT INTO entries(data) VALUES (?)', (json.dumps(record, ensure_ascii=False),))
                    keys = {word_key(record['word'])}
                    keys.update(word_key(f['form']) for f in raw.get('forms', []) if isinstance(f.get('form'), str))
                    db.executemany('INSERT INTO words VALUES (?, ?, ?)', [(k, record['language'], cursor.lastrowid) for k in keys if k])
                    count += 1
                    if count % 2000 == 0:
                        db.commit()
                        progress(count)
            if not count:
                raise AssistanceError('В файле не найдены словарные статьи Wiktextract.')
            progress(count)
            db.execute('CREATE INDEX word_lookup ON words(word, language)')
            db.executemany('INSERT INTO metadata VALUES (?, ?)', [('count', str(count)), ('language', definition_language)])
            db.commit()
        if cancelled.is_set():
            raise AssistanceError('Установка словаря отменена.')
        temporary.replace(destination)
        return count
    finally:
        temporary.unlink(missing_ok=True)


def lookup_dictionary(directory, word, source='auto', target='ru'):
    results, seen = [], set()
    # Prefer definitions already in the requested target language.
    files = sorted(Path(directory).glob('*.sqlite'), key=lambda p: (not p.stem.startswith(target), p.name))
    for path in files:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            def query(key):
                sql = 'SELECT DISTINCT e.data FROM words w JOIN entries e ON e.id=w.entry_id WHERE w.word=?'
                params = [word_key(key)]
                if source != 'auto':
                    sql += ' AND w.language=?'
                    params.append(source)
                return [json.loads(r[0]) for r in db.execute(sql + ' LIMIT 8', params)]
            entries = query(word)
            bases = {base for entry in entries for sense in entry['senses'] for base in sense.get('base', [])}
            for base in sorted(bases)[:4]:
                entries += query(base)
            for entry in entries:
                identity = (entry['word'], entry['language'], entry['pos'], entry['definitionLanguage'])
                if identity not in seen:
                    seen.add(identity)
                    results.append(entry)
            if len(results) >= 8:
                break
    return results[:8]
