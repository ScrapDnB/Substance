"""Durable ownership of generated cues and conservative repeat recognition."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

KEY = 'transcription'


def media_identity(path, track):
    path = Path(path).resolve()
    stat = path.stat()
    identity = {'path': os.path.normcase(str(path)), 'size': stat.st_size,
                'mtime_ns': stat.st_mtime_ns, 'track': track}
    # Provenance travels with online documents. Keep device-local paths out
    # of cue/source extras sent to a server.
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return {'id': digest, 'track': track}


def cue_digest(cue):
    values = {key: getattr(cue, key) for key in ('id', 'source_ids', 'start', 'end',
              'character', 'character_id', 'comment')}
    # Online authoring represents the same authored text as a translation with
    # an empty immutable original. Hash visible content, not that IO encoding.
    values['text'] = cue.output_text
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def mark_generated(document, cue, source):
    document.register_source(cue)
    record = {'version': 1, 'media': deepcopy(source), 'start': cue.start,
              'end': cue.end, 'digest': cue_digest(cue)}
    cue.extras[KEY] = record
    document.source_lines[cue.id][KEY] = deepcopy(record)


def intersects(left, right):
    return left[0] < right[1] and right[0] < left[1]


def matching_results(document, source, start, end, *, known=None):
    """Find matching results and edited/split/merged descendants.

    Older versions only wrote a session ID. Without an in-memory original we
    cannot prove such a cue is untouched, so protect it rather than erase it.
    """
    known = known or {}
    result = {}
    for cue in document.cues:
        records = [cue.extras.get(KEY)] + [document.source_lines.get(sid, {}).get(KEY) for sid in cue.source_ids]
        records = [r for r in records if isinstance(r, dict) and r.get('version') == 1 and r.get('media') == source]
        if not records and cue.extras.get('transcription_session') and not cue.extras.get(KEY):
            original = known.get(cue.id)
            records = [{'start': original.start if original else cue.start,
                        'end': original.end if original else cue.end,
                        'digest': cue_digest(original) if original else None}]
        if not records:
            continue
        bounds = [(cue.start, cue.end)] + [(r['start'], r['end']) for r in records]
        if any(intersects(bound, (start, end)) for bound in bounds):
            result[cue.id] = {'cue': cue, 'records': records, 'bounds': bounds}
    return result


def replacement_plan(document, source, start, end, *, known=None, reviewed=()):
    matches = matching_results(document, source, start, end, known=known)
    reviewed = set(reviewed) | {cid for review in document.reviews for cid in review.cue_ids}
    removable = set()
    for cue_id, entry in matches.items():
        cue, records = entry['cue'], entry['records']
        if (cue_id not in reviewed and any(r.get('digest') == cue_digest(cue) for r in records)
                and all(start <= a and b <= end for a, b in entry['bounds'])):
            removable.add(cue_id)
    protected_sources = {sid for cue in document.cues if cue.id not in removable for sid in cue.source_ids}
    removable = {cid for cid in removable if not protected_sources.intersection(matches[cid]['cue'].source_ids)}
    protected = [bound for cid, entry in matches.items() if cid not in removable for bound in entry['bounds']]
    return removable, protected


def replace_cues(document, removed, added):
    """Keep unrelated rows in place and put replacements at the old result."""
    indices = [i for i, cue in enumerate(document.cues) if cue.id in removed]
    if not indices:
        document.cues.extend(added)
        return
    first, last = min(indices), max(indices)
    retained = [cue for cue in document.cues[first:last + 1] if cue.id not in removed]
    block = sorted(retained + added, key=lambda cue: cue.start)
    document.cues = document.cues[:first] + block + document.cues[last + 1:]
