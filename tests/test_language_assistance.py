import gzip
from io import BytesIO
import json
import threading
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

import pytest

from substance.language_assistance import (AssistanceError, NoRedirect, clean_text, endpoint,
    install_dictionary, lookup_dictionary, request_json, selected_plain_text, translate, word_selection)


def entry(word='charge', **values):
    return {'word': word, 'lang_code': 'en', 'lang': 'English', 'pos': 'noun',
            'forms': [{'form': word + 's'}], 'senses': [
                {'glosses': ['A price for a service.'], 'examples': [{'text': 'There is no charge.'}],
                 'translations': [{'lang_code': 'ru', 'word': 'плата'}]}], **values}


def database(tmp_path, records=None, name='en.sqlite'):
    source = tmp_path / 'source.jsonl.gz'
    with gzip.open(source, 'wt', encoding='utf-8') as stream:
        for record in records if records is not None else [entry()]:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
    destination = tmp_path / 'dictionary' / name
    install_dictionary(source, destination, 'en')
    return destination


def test_dictionary_has_multiple_senses_forms_and_examples(tmp_path):
    database(tmp_path, [entry(), entry('run', pos='verb'), entry('ran', senses=[{'glosses': ['Past of run.'], 'form_of': [{'word': 'run'}]}])])
    result = lookup_dictionary(tmp_path / 'dictionary', 'CHARGES')
    assert result[0]['word'] == 'charge'
    sense = result[0]['senses'][0]
    assert sense['examples'] == ['There is no charge.']
    assert sense['translations'] == [{'language': 'ru', 'text': 'плата'}]
    assert not lookup_dictionary(tmp_path / 'dictionary', 'charge', 'ja')
    assert {r['word'] for r in lookup_dictionary(tmp_path / 'dictionary', 'ran')} == {'ran', 'run'}


def test_broken_or_cancelled_import_keeps_existing_dictionary(tmp_path):
    destination = database(tmp_path)
    before = destination.read_bytes()
    invalid = tmp_path / 'broken.jsonl'
    invalid.write_text(json.dumps(entry('new')) + '\n{broken', encoding='utf-8')
    with pytest.raises(ValueError):
        install_dictionary(invalid, destination, 'en')
    assert destination.read_bytes() == before
    event = threading.Event()
    event.set()
    with pytest.raises(AssistanceError, match='отменена'):
        install_dictionary(invalid, destination, 'en', event)
    assert destination.read_bytes() == before
    assert not list(destination.parent.glob('*.tmp'))


def test_utf16_ass_selection_never_sends_codes_or_drawings():
    text = r'😀 {\i1}charge{\i0}\Nhere'
    # Qt positions count the leading emoji as two UTF-16 code units.
    assert selected_plain_text(text, 3, len(text.encode('utf-16-le')) // 2) == 'charge here'
    assert selected_plain_text(r'{\i1}word{\i0}', 2, 8) == 'wor'
    assert clean_text(r'{\p1}m 0 0 l 2 2{\p0}hello\Nworld') == 'hello world'
    assert word_selection("don't") and word_selection('日本語')
    assert not word_selection('hello world')


@pytest.mark.parametrize('provider', ['azure', 'deepl', 'libre'])
def test_provider_contracts_batch_autodetection_and_credentials(provider):
    calls = []
    def requester(url, body, headers):
        calls.append((url, body, headers))
        if provider == 'azure':
            return [{'detectedLanguage': {'language': 'en'}, 'translations': [{'text': t}]} for t in ['Привет', 'Мир']]
        if provider == 'deepl':
            return {'translations': [{'text': t, 'detected_source_language': 'EN'} for t in ['Привет', 'Мир']]}
        return {'translatedText': ['Привет', 'Мир'], 'detectedLanguage': [{'language': 'en'}]}
    result, detected = translate(['Hello', 'World'], 'auto', 'ru',
        {'provider': provider, 'azureRegion': 'westeurope', 'libreUrl': 'http://localhost:5000'},
        'secret:fx', 'Hello World', requester)
    assert result == ['Привет', 'Мир'] and detected == 'en'
    url, body, headers = calls[0]
    assert 'secret' not in url
    if provider == 'azure':
        assert parse_qs(urlsplit(url).query) == {'api-version': ['3.0'], 'to': ['ru']}
        assert body == [{'Text': 'Hello'}, {'Text': 'World'}]
        assert headers['Ocp-Apim-Subscription-Region'] == 'westeurope'
    elif provider == 'deepl':
        assert urlsplit(url).hostname == 'api-free.deepl.com'
        assert body == {'text': ['Hello', 'World'], 'target_lang': 'RU', 'context': 'Hello World'}
        assert headers['Authorization'] == 'DeepL-Auth-Key secret:fx'
    else:
        assert url == 'http://localhost:5000/translate'
        assert body == {'q': ['Hello', 'World'], 'source': 'auto', 'target': 'ru', 'format': 'text', 'api_key': 'secret:fx'}


def test_deepl_target_variants_and_paid_endpoint():
    calls = []
    def requester(url, body, headers):
        calls.append((url, body))
        return {'translations': [{'text': 'Hello', 'detected_source_language': 'RU'}]}
    translate(['Привет'], 'ru', 'en', {'provider': 'deepl'}, 'key', requester=requester)
    assert calls == [('https://api.deepl.com/v2/translate', {'text': ['Привет'], 'source_lang': 'RU', 'target_lang': 'EN-US'})]


def test_local_libretranslate_without_key_and_bad_provider_response():
    def requester(url, body, headers):
        assert 'api_key' not in body
        return {'translatedText': 'Привет'}
    assert translate(['Hello'], 'en', 'ru', {'provider': 'libre', 'libreUrl': 'http://localhost:5000'}, '', requester=requester)[0] == ['Привет']
    with pytest.raises(AssistanceError, match='формат'):
        translate(['Hello'], 'en', 'ru', {'provider': 'azure'}, 'key', requester=lambda *a: {})
    with pytest.raises(AssistanceError, match='неполный'):
        translate(['Hello'], 'en', 'ru', {'provider': 'azure'}, 'key', requester=lambda *a: [])
    with pytest.raises(AssistanceError, match='API-ключ'):
        translate(['Hello'], 'en', 'ru', {'provider': 'azure'}, '')


def test_http_transport_encodes_unicode_and_redacts_server_errors():
    def opener(request):
        assert json.loads(request.data) == {'q': '日本語'}
        return BytesIO(json.dumps({'translatedText': 'японский'}).encode())
    assert request_json('http://localhost:5000/translate', {'q': '日本語'}, opener=opener)['translatedText'] == 'японский'
    def failing(request):
        raise HTTPError(request.full_url, 403, 'secret and selected script', {}, BytesIO(b'private data'))
    with pytest.raises(AssistanceError) as error:
        request_json('https://example.invalid', opener=failing)
    assert 'secret' not in str(error.value) and 'private' not in str(error.value)
    assert NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid') is None


@pytest.mark.parametrize('value', ['file:///tmp/file', 'https://user:password@host', 'https://host?api_key=secret', 'http://host:bad'])
def test_endpoint_rejects_credentials_and_invalid_schemes(value):
    with pytest.raises(AssistanceError):
        endpoint(value)
