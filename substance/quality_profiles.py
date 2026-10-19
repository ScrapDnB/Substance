"""Named delivery checks and portable, escaped review reports."""
import csv
import html
import io

from .document import atomic_write, plain_text
from .editor_tools import plan
from .timecode import format_time

DEFAULT_PROFILE = {'cps': 20, 'width': 42, 'minimum': 1000, 'maximum': 6000, 'gap': 80,
                   'readingSpeed': True, 'lineLength': True, 'lineCount': True,
                   'lineCountLimit': 2, 'overlaps': True}


def validate_profile(value):
    result = dict(DEFAULT_PROFILE)
    for key, low, high in [('cps', 1, 100), ('width', 10, 200), ('minimum', 100, 20000),
                           ('maximum', 100, 60000), ('gap', 0, 2000), ('lineCountLimit', 1, 10)]:
        result[key] = int(value.get(key, result[key]))
        if not low <= result[key] <= high:
            raise ValueError('Параметры профиля вне допустимого диапазона: ' + key)
    if result['maximum'] < result['minimum']:
        raise ValueError('Максимальная длительность меньше минимальной')
    for key in ('readingSpeed', 'lineLength', 'lineCount', 'overlaps'):
        result[key] = bool(value.get(key, result[key]))
    return result


def findings(document, profile):
    options = dict(validate_profile(profile), spaces=False, punctuation=False, timing=False)
    proposals = plan(document, range(len(document.cues)), 'checks', options)
    result = []
    by_id = {c.id: (i, c) for i, c in enumerate(document.cues)}
    for proposal in proposals:
        if proposal.applicable:
            continue
        for cid in proposal.ids:
            i, cue = by_id[cid]
            result.append({'number': i + 1, 'start': format_time(cue.start), 'end': format_time(cue.end),
                           'text': plain_text(cue.output_text), 'reason': proposal.reason})
    options = validate_profile(profile)
    for i, cue in enumerate(document.cues):
        if cue.comment:
            continue
        reasons = []
        if cue.end-cue.start < options['minimum']:
            reasons.append('Слишком короткая длительность')
        if i+1 < len(document.cues) and 0 < document.cues[i+1].start-cue.end < options['gap']:
            reasons.append('Слишком короткий промежуток')
        if reasons:
            result.append({'number': i+1, 'start': format_time(cue.start), 'end': format_time(cue.end),
                           'text': plain_text(cue.output_text), 'reason': '; '.join(reasons)})
    return result


def write_report(path, rows, title='Проверка субтитров'):
    from pathlib import Path
    columns = [('number', 'Реплика'), ('start', 'Начало'), ('end', 'Конец'), ('text', 'Текст'), ('reason', 'Замечания')]
    if Path(path).suffix.lower() == '.html':
        escape = lambda v: html.escape(str(v)).replace('\n', '<br>')
        body = ''.join('<tr>' + ''.join('<td>' + escape(row.get(k, '')) + '</td>' for k, _ in columns) + '</tr>' for row in rows)
        content = '<!doctype html><html lang="ru"><meta charset="utf-8"><title>' + escape(title) + '</title><style>body{font:16px system-ui;margin:32px;color:#222}table{border-collapse:collapse;width:100%}td,th{padding:10px;border:1px solid #bbb;text-align:left;vertical-align:top}tr:nth-child(even){background:#f5f5f5}</style><h1>' + escape(title) + '</h1><p>Замечаний: ' + str(len(rows)) + '</p><table><tr>' + ''.join('<th>' + name + '</th>' for _, name in columns) + '</tr>' + body + '</table></html>'
    else:
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow([title for _, title in columns])
        for row in rows:
            values = [str(row.get(key, '')) for key, _ in columns]
            writer.writerow(["'" + v if v.lstrip().startswith(('=', '+', '-', '@')) else v for v in values])
        content = '\ufeff' + output.getvalue()
    atomic_write(path, content.encode('utf-8'))
