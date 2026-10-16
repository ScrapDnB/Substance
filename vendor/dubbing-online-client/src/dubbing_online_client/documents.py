"""Portable document adapters shared by desktop clients; no Qt or server imports."""

from copy import deepcopy
import base64
from decimal import Decimal, InvalidOperation
import hashlib
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

STAMP = "__substance_v1__"
CUE_FIELDS = (
    "id",
    "source_ids",
    "start",
    "end",
    "text",
    "original",
    "translation",
    "character_id",
    "comment",
    "ass_fields",
)
CHARACTER_FIELDS = (
    "name",
    "export_name",
    "aliases",
    "description",
    "speech",
    "pronunciation",
    "relationships",
    "notes",
    "portraits",
    "primary",
    "status",
    "archived",
    "extras",
)
TERM_FIELDS = (
    "name",
    "translation",
    "category",
    "pronunciation",
    "alternatives",
    "forbidden",
    "description",
    "example",
    "status",
    "archived",
    "extras",
)


def identity(kind, value):
    return kind + "_" + uuid5(NAMESPACE_URL, "dubbing-online/" + value).hex


def milliseconds(seconds):
    if isinstance(seconds, bool):
        raise ValueError("Некорректный таймкод")
    try:
        value = Decimal(str(seconds)) * 1000
        if not value.is_finite() or value < 0:
            raise ValueError("Некорректный таймкод")
        return int(value.to_integral_value())
    except (InvalidOperation, TypeError) as exc:
        raise ValueError("Некорректный таймкод") from exc


def from_substance(snapshot):
    """Return a wire document, import glossary and embedded images separately."""
    if not isinstance(snapshot, dict):
        raise ValueError("Некорректный файл Substance")
    if (
        snapshot.get("format") != "substance"
        or type(snapshot.get("schema_version")) is not int
        or snapshot["schema_version"] != 2
    ):
        raise ValueError("Неподдерживаемая версия Substance")
    if not isinstance(snapshot.get("source_lines"), dict) or not isinstance(
        snapshot.get("cues"), list
    ):
        raise ValueError("Некорректная структура документа")
    images = snapshot.get("images", {})
    if not isinstance(images, dict):
        raise ValueError("Некорректные изображения")
    for identifier, encoded in images.items():
        raw = base64.b64decode(encoded, validate=True)
        if (
            len(raw) > 6 * 1024 * 1024
            or identifier != "img_" + hashlib.sha256(raw).hexdigest()
            or not raw.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
        ):
            raise ValueError("Повреждённое или слишком большое изображение")
    wire = {
        "schema_version": 1,
        "source_lines": {},
        "cues": [],
        "metadata": deepcopy(snapshot.get("metadata", {})),
        "extras": {
            STAMP: {
                k: deepcopy(v)
                for k, v in snapshot.items()
                if k
                not in {
                    "format",
                    "schema_version",
                    "cues",
                    "source_lines",
                    "metadata",
                    "media",
                    "characters",
                    "images",
                    "terms",
                }
            }
        },
    }
    preserved = wire["extras"][STAMP]
    if "skeleton" in preserved:
        preserved["skeleton"] = [
            line
            for line in preserved["skeleton"]
            if line is None
            or not re.match(
                r"\s*(Video File|Audio File|Video Position|Video AR Mode|Video AR Value):",
                line,
                re.I,
            )
        ]
    for sid, source in snapshot.get("source_lines", {}).items():
        wire["source_lines"][sid] = {
            "id": sid,
            "text": source["text"],
            "start": milliseconds(source["start"]),
            "end": milliseconds(source["end"]),
            "character": source.get("character", ""),
            "extras": {STAMP: deepcopy(source)},
        }
    for cue in snapshot.get("cues", []):
        row = {
            k: deepcopy(cue.get(k, "" if k in ("text", "original") else None))
            for k in CUE_FIELDS
        }
        row["character_id"] = cue.get("character_id") or None
        row["comment"] = bool(cue.get("comment", False))
        row["ass_fields"] = deepcopy(cue.get("ass_fields", {}))
        row["extras"] = {
            STAMP: {k: deepcopy(v) for k, v in cue.items() if k not in CUE_FIELDS}
        }
        wire["cues"].append(row)
    entries = []
    cards = deepcopy(snapshot.get("characters", []))
    known = {c["id"] for c in cards}
    names = {c["name"]: c["id"] for c in cards if not c.get("archived")}
    for cue, original in zip(wire["cues"], snapshot.get("cues", [])):
        name = original.get("character", "").strip()
        if not cue["character_id"] and name:
            if name not in names:
                key = identity("char", name)
                cards.append({"id": key, "name": name})
                names[name] = key
                known.add(key)
            cue["character_id"] = names[name]
        if cue["character_id"] and cue["character_id"] not in known:
            raise ValueError("Реплика ссылается на отсутствующую карточку")
    for kind, records, fields in [
        ("character", cards, CHARACTER_FIELDS),
        ("term", snapshot.get("terms", []), TERM_FIELDS),
    ]:
        for record in records:
            data = {k: deepcopy(v) for k, v in record.items() if k in fields}
            extras = data.setdefault("extras", {})
            for key in fields:
                if key not in data and key in extras:
                    data[key] = deepcopy(extras[key])
            extras.update(
                {
                    k: deepcopy(v)
                    for k, v in record.items()
                    if k not in fields and k != "id"
                }
            )
            if kind == "character":
                data["primary"] = data.get("primary") or None
                data["portraits"] = [
                    {
                        k: deepcopy(p[k])
                        for k in ("id", "source", "image", "crop")
                        if k in p
                    }
                    for p in data.get("portraits", [])
                ]
                if record.get("portraits"):
                    extras["portrait_provenance"] = [
                        {
                            k: deepcopy(v)
                            for k, v in portrait.items()
                            if k != "media_path"
                        }
                        for portrait in record["portraits"]
                    ]
            entries.append(
                {"id": record["id"], "kind": kind, "target_id": None, "data": data}
            )
    validate_document(wire)
    return wire, entries, deepcopy(snapshot.get("images", {}))


def to_substance(wire):
    """Restore document IO details; project glossary/images are supplied separately."""
    validate_document(wire)
    snapshot = deepcopy(wire.get("extras", {}).get(STAMP, {}))
    snapshot.update(
        format="substance",
        schema_version=2,
        metadata=deepcopy(wire.get("metadata", {})),
        source_lines={},
        cues=[],
        media={},
    )
    for sid, source in wire["source_lines"].items():
        row = deepcopy(source.get("extras", {}).get(STAMP, {}))
        row.update(
            id=sid,
            text=source["text"],
            start=source["start"] / 1000,
            end=source["end"] / 1000,
            character=source.get("character", ""),
        )
        snapshot["source_lines"][sid] = row
    for cue in wire["cues"]:
        row = deepcopy(cue.get("extras", {}).get(STAMP, {}))
        row.update({k: deepcopy(cue.get(k)) for k in CUE_FIELDS})
        row["character_id"] = row["character_id"] or ""
        snapshot["cues"].append(row)
    return snapshot


def validate_document(document):
    ids = set()
    sources = document.get("source_lines", {})
    if not isinstance(sources, dict) or not isinstance(document.get("cues"), list):
        raise ValueError("Некорректный документ")
    for key, source in sources.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", key)
            or source.get("id") != key
            or not isinstance(source.get("text"), str)
            or len(source["text"]) > 100_000
        ):
            raise ValueError("Некорректный исходник")
    for cue in [*sources.values(), *document["cues"]]:
        for k in ("start", "end"):
            if type(cue.get(k)) is not int or cue[k] < 0:
                raise ValueError("Некорректный таймкод")
        if cue["end"] < cue["start"]:
            raise ValueError("Конец реплики раньше начала")
    for cue in document["cues"]:
        if (
            not isinstance(cue.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", cue["id"])
            or cue["id"] in ids
        ):
            raise ValueError("Некорректный или повторяющийся ID реплики")
        ids.add(cue["id"])
        if (
            not isinstance(cue.get("source_ids"), list)
            or not 1 <= len(cue["source_ids"]) <= 1000
            or len(set(cue["source_ids"])) != len(cue["source_ids"])
            or any(sid not in sources for sid in cue["source_ids"])
        ):
            raise ValueError("Реплика ссылается на отсутствующий исходник")
        if (
            not isinstance(cue.get("original"), str)
            or not isinstance(cue.get("text"), str)
            or (
                cue.get("translation") is not None
                and not isinstance(cue["translation"], str)
            )
        ):
            raise ValueError("Некорректный текст реплики")
        if any(
            len(cue.get(k) or "") > 100_000 for k in ("text", "original", "translation")
        ):
            raise ValueError("Текст реплики превышает 100 000 символов")
    if not any(
        not c.get("comment") and (c["text"].strip() or c["original"].strip())
        for c in document["cues"]
    ):
        raise ValueError("В серии нет реплик")


def from_lines(lines, metadata=None):
    sources, cues = {}, []
    for i, line in enumerate(lines):
        sid = identity("src", str(i))
        start, end = milliseconds(line.get("s", 0)), milliseconds(line.get("e", 0))
        text, name = str(line.get("text", "")), str(line.get("char", "")).strip()
        sources[sid] = {
            "id": sid,
            "text": text,
            "start": start / 1000,
            "end": end / 1000,
            "character": name,
            "order": i,
        }
        cues.append(
            {
                "id": sid,
                "source_ids": [sid],
                "start": start,
                "end": end,
                "text": text,
                "original": text,
                "translation": None,
                "character": name,
            }
        )
    return from_substance(
        {
            "format": "substance",
            "schema_version": 2,
            "source_lines": sources,
            "cues": cues,
            "metadata": metadata or {},
            "fps": (metadata or {}).get("import_config", {}).get("fps", 25.0),
        }
    )


def timecode(value):
    match = re.fullmatch(r"\s*(\d+):(\d{2}):(\d{2})[.,](\d{1,3})\s*", value)
    if not match or int(match[2]) > 59 or int(match[3]) > 59:
        raise ValueError("Некорректный таймкод: " + value)
    return ((int(match[1]) * 60 + int(match[2])) * 60 + int(match[3])) * 1000 + int(
        match[4].ljust(3, "0")
    )


def read_subtitle(path, ass_config=None, srt_config=None):
    """Loss-preserving source parsing; settings affect the initial working text."""
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Файл превышает 16 МБ")
    source_sha256 = hashlib.sha256(raw).hexdigest()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    text = raw.decode(encoding)
    snapshot = {
        "format": "substance",
        "schema_version": 2,
        "cues": [],
        "source_lines": {},
        "skeleton": [],
        "newline": "\r\n" if "\r\n" in text else "\n",
        "trailing_newline": text.endswith(("\r", "\n")),
        "encoding": "utf-8",
        "bom": encoding == "utf-8-sig",
        "metadata": {
            "import_format": path.suffix[1:].lower(),
            "source_sha256": source_sha256,
        },
    }

    def add(start, end, body, character="", **extras):
        sid = identity(
            "src", source_sha256 + "/" + str(len(snapshot["cues"]))
        )
        snapshot["source_lines"][sid] = {
            "id": sid,
            "start": start / 1000,
            "end": end / 1000,
            "text": body,
            "character": character,
            "order": len(snapshot["cues"]),
        }
        snapshot["cues"].append(
            {
                "id": sid,
                "source_ids": [sid],
                "start": start,
                "end": end,
                "original": body,
                "text": body,
                "translation": None,
                "character": character,
                **extras,
            }
        )

    if path.suffix.lower() == ".ass":
        section, order = (
            "",
            [
                "Layer",
                "Start",
                "End",
                "Style",
                "Name",
                "MarginL",
                "MarginR",
                "MarginV",
                "Effect",
                "Text",
            ],
        )
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped.lower()
            if section == "[events]" and stripped.lower().startswith("format:"):
                order = [part.strip() for part in stripped.split(":", 1)[1].split(",")]
            match = (
                re.match(r"\s*(Dialogue|Comment):\s?(.*)", line, re.I)
                if section == "[events]"
                else None
            )
            if not match:
                snapshot["skeleton"].append(line)
                continue
            if (
                "Text" not in order
                or order[-1] != "Text"
                or "Start" not in order
                or "End" not in order
            ):
                raise ValueError("Неподдерживаемый порядок полей ASS")
            parts = match[2].split(",", len(order) - 1)
            if len(parts) != len(order):
                raise ValueError("Повреждённая строка ASS")
            fields = dict(zip(order, parts))
            name = fields.get("Name", fields.get("Actor", "")).strip()
            names = [name]
            config = ass_config or {}
            if config.get("split_character_names", True) and name:
                names = [
                    part.strip()
                    for part in name.split(
                        config.get("character_separator", ";") or ";"
                    )
                    if part.strip()
                ] or [""]
            for character in names:
                add(
                    timecode(fields["Start"]),
                    timecode(fields["End"]),
                    fields["Text"],
                    character,
                    comment=match[1].lower() == "comment",
                    ass_fields=fields,
                    field_order=list(order),
                    original_line=line,
                )
                if config.get("strip_override_tags", True):
                    snapshot["cues"][-1]["text"] = re.sub(
                        r"\{[^}]*\}", "", fields["Text"]
                    )
                snapshot["skeleton"].append(None)
    elif path.suffix.lower() == ".srt":
        pattern = re.compile(
            r"^\s*(\d+:\d{2}:\d{2}[.,]\d{1,3})\s*-->\s*(\d+:\d{2}:\d{2}[.,]\d{1,3})(.*)$"
        )
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if not lines[i].strip():
                i += 1
                continue
            if lines[i].strip().isdigit():
                i += 1
            if i >= len(lines):
                raise ValueError("Повреждённый SRT")
            match = pattern.match(lines[i])
            if not match:
                raise ValueError("Повреждённый таймкод SRT")
            i += 1
            body = []
            while i < len(lines) and lines[i].strip():
                body.append(lines[i])
                i += 1
            config = srt_config or {}
            working = (
                ("\n" if config.get("keep_multiline", True) else " ").join(body).strip()
            )
            name = str(config.get("default_character", "")).strip()
            if config.get("detect_character_prefix", True):
                prefix = re.match(
                    r"^(.+?)"
                    + re.escape(config.get("character_separator", ":") or ":")
                    + r"\s*(.*)",
                    working,
                    re.S,
                )
                if prefix:
                    name, working = prefix[1].strip(), prefix[2].strip()
            add(
                timecode(match[1]),
                timecode(match[2]),
                "\\N".join(body),
                name,
                extras={"timing_settings": match[3].strip()},
            )
            snapshot["cues"][-1]["text"] = working
    else:
        raise ValueError("Выберите ASS или SRT")
    return from_substance(snapshot)
