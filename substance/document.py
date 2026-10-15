"""Loss-preserving subtitle IO, independent of Qt and the application shell."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os
import re
import tempfile

from .timecode import parse_time, format_time
from .ass_formatting import neutral_style_flags
from . import __version__
from .project import ReviewEntry, CharacterCard, record_from_dict, validate_project

SCHEMA_VERSION = 2
ASS_FIELDS = ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]
DEFAULT_ASS = """[Script Info]
Title: Substance
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,56,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def identity(prefix: str = "src") -> str:
    return f"{prefix}_{uuid4().hex}"


def plain_text(text: str) -> str:
    # Drawing runs are not speech. Preserve them on disk, omit them in reading metrics.
    parts = re.split(r"(\{[^}]*\})", text)
    drawing = False
    result = []
    for part in parts:
        if part.startswith("{") and part.endswith("}"):
            mode = re.search(r"\\p(\d+)", part)
            if mode:
                drawing = int(mode.group(1)) != 0
        elif not drawing:
            result.append(part)
    return "".join(result).replace(r"\N", "\n").replace(r"\n", "\n").replace(r"\h", " ")


@dataclass
class Cue:
    id: str = field(default_factory=identity)
    source_ids: list[str] = field(default_factory=list)
    start: int = 0
    end: int = 2000
    text: str = ""
    original: str = ""
    translation: str | None = None
    character: str = ""
    character_id: str = ""
    comment: bool = False
    field_order: list[str] = field(default_factory=lambda: list(ASS_FIELDS))
    ass_fields: dict[str, str] = field(default_factory=dict)
    original_line: str = ""
    baseline: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)

    @property
    def output_text(self) -> str:
        return self.translation if self.translation is not None else self.text

    def editable(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.output_text, "character": self.character, "comment": self.comment}

    def ass_line(self) -> str:
        if self.original_line and self.editable() == self.baseline:
            return self.original_line
        values = {"Layer": "0", "Style": "Default", "MarginL": "0", "MarginR": "0", "MarginV": "0", "Effect": ""}
        values.update(self.ass_fields)
        values.update(Start=format_time(self.start, ass=True), End=format_time(self.end, ass=True), Text=self.output_text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N"), Name=self.character)
        if "Actor" in self.field_order:
            values["Actor"] = self.character
        for key, member in (("Start", "start"), ("End", "end")):
            if self.baseline.get(member) == getattr(self, member) and key in self.ass_fields:
                values[key] = self.ass_fields[key]
        return ("Comment: " if self.comment else "Dialogue: ") + ",".join(values.get(key, "") for key in self.field_order)


@dataclass
class Document:
    cues: list[Cue] = field(default_factory=list)
    # None marks a parsed ASS event. All other lines are retained verbatim.
    skeleton: list[str | None] = field(default_factory=lambda: DEFAULT_ASS.splitlines())
    newline: str = "\n"
    trailing_newline: bool = True
    encoding: str = "utf-8"
    bom: bool = False
    source_lines: dict[str, dict] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    media: dict = field(default_factory=dict)
    fps: float = 23.976
    warnings: list[str] = field(default_factory=list)
    extras: dict = field(default_factory=dict)
    reviews: list[ReviewEntry] = field(default_factory=list)
    characters: list[CharacterCard] = field(default_factory=list)
    images: dict[str, str] = field(default_factory=dict)
    review_settings: dict = field(default_factory=dict)

    def register_source(self, cue: Cue) -> None:
        if not cue.source_ids:
            cue.source_ids = [cue.id]
        self.source_lines.setdefault(cue.id, {"id": cue.id, "order": len(self.source_lines), "start": cue.start / 1000, "end": cue.end / 1000, "s_raw": cue.ass_fields.get("Start", ""), "e_raw": cue.ass_fields.get("End", ""), "text": cue.original, "character": cue.character, "origin": {"event_index": len(self.source_lines)}})

    def validate(self) -> None:
        ids = [c.id for c in self.cues]
        if len(ids) != len(set(ids)):
            raise ValueError("Повторяющиеся идентификаторы реплик")
        if not 1 <= self.fps <= 120:
            raise ValueError("Некорректная частота кадров")
        for c in self.cues:
            if isinstance(c.start, bool) or isinstance(c.end, bool) or not isinstance(c.start, int) or not isinstance(c.end, int) or c.start < 0 or c.end < c.start:
                raise ValueError("Конец реплики не может быть раньше начала")
            if not isinstance(c.text, str) or not isinstance(c.original, str) or (c.translation is not None and not isinstance(c.translation, str)):
                raise ValueError("Некорректный текст реплики")
            if any(s not in self.source_lines for s in c.source_ids):
                raise ValueError("Реплика ссылается на отсутствующую исходную строку")
        validate_project(self)

    def ass_text(self, *, use_ass_styles=True) -> str:
        result: list[str | Cue] = []
        cursor = 0
        last_slot = max((i for i, line in enumerate(self.skeleton) if line is None), default=-1)
        if last_slot == -1:
            # Insert into Events, before a following section, even in an empty imported ASS.
            events = next((i for i, s in enumerate(self.skeleton) if s and s.strip().lower() == "[events]"), -1)
            if events == -1:
                skeleton = self.skeleton + ["", "[Events]", "Format: " + ", ".join(ASS_FIELDS)]
            else:
                skeleton = list(self.skeleton)
            end = next((i for i in range(events + 1, len(skeleton)) if skeleton[i] and skeleton[i].startswith("[") and skeleton[i].endswith("]")), len(skeleton)) if events >= 0 else len(skeleton)
            result = list(skeleton[:end]) + list(self.cues) + list(skeleton[end:])
        else:
            for i, line in enumerate(self.skeleton):
                if line is None:
                    if cursor < len(self.cues):
                        result.append(self.cues[cursor])
                        cursor += 1
                    if i == last_slot:
                        result.extend(self.cues[cursor:])
                        cursor = len(self.cues)
                else:
                    result.append(line)
        serialized = []
        active_order, section = list(ASS_FIELDS), ""
        for entry in result:
            if isinstance(entry, Cue):
                if entry.field_order != active_order:
                    serialized.append("Format: " + ", ".join(entry.field_order))
                    active_order = entry.field_order
                serialized.append(entry.ass_line())
            else:
                serialized.append(entry)
                if entry.strip().startswith("[") and entry.strip().endswith("]"):
                    section = entry.strip().lower()
                if section == "[events]" and entry.strip().lower().startswith("format:"):
                    active_order = [s.strip() for s in entry.split(":", 1)[1].split(",")]
        if not use_ass_styles:
            serialized = neutral_style_flags(serialized)
        return self.newline.join(serialized) + (self.newline if self.trailing_newline else "")

    def ass_bytes(self, *, use_ass_styles=True) -> bytes:
        encoding = self.encoding
        if encoding == "utf-8" and self.bom:
            encoding = "utf-8-sig"
        try:
            return self.ass_text(use_ass_styles=use_ass_styles).encode(encoding)
        except UnicodeEncodeError as exc:
            raise ValueError("Новые символы нельзя сохранить в исходной кодировке. Выберите UTF-8 в настройках документа.") from exc

    def to_dict(self, *, project_data=True) -> dict:
        result = deepcopy(self.extras)
        result.update({"format": "substance", "schema_version": SCHEMA_VERSION, "app_version": __version__, "cues": [asdict(c) for c in self.cues], "skeleton": self.skeleton, "newline": self.newline, "trailing_newline": self.trailing_newline, "encoding": self.encoding, "bom": self.bom, "source_lines": deepcopy(self.source_lines), "metadata": deepcopy(self.metadata), "media": deepcopy(self.media), "fps": self.fps, "warnings": list(self.warnings)})
        if project_data:
            result.update(reviews=[asdict(r) for r in self.reviews], characters=[asdict(c) for c in self.characters], images=dict(self.images), review_settings=deepcopy(self.review_settings))
        else:
            for cue in result['cues']:
                cue['character_id'] = ''
        return result

    @classmethod
    def from_dict(cls, data: dict) -> Document:
        if not isinstance(data, dict) or data.get("format") != "substance":
            raise ValueError("Это не проект Substance. Проекты Dubbing Manager пока не открываются.")
        if data.get("schema_version") not in (1, SCHEMA_VERSION):
            raise ValueError("Неподдерживаемая версия формата проекта")
        known = {f.name for f in fields(cls)} - {"cues", "extras", "reviews", "characters"}
        cue_known = {f.name for f in fields(Cue)} - {"extras"}
        cues = []
        for item in data["cues"]:
            extra = dict(item.get("extras", {}))
            extra.update({k: v for k, v in item.items() if k not in cue_known and k != "extras"})
            cues.append(Cue(**{k: v for k, v in item.items() if k in cue_known}, extras=extra))
        consumed = known | {"cues", "reviews", "characters", "format", "schema_version", "app_version"}
        doc = cls(cues=cues, reviews=[record_from_dict(ReviewEntry, r) for r in data.get('reviews', [])], characters=[record_from_dict(CharacterCard, c) for c in data.get('characters', [])], **{k: deepcopy(v) for k, v in data.items() if k in known}, extras={k: deepcopy(v) for k, v in data.items() if k not in consumed})
        doc.validate()
        return doc


def decode_bytes(data: bytes, encoding: str = "auto") -> tuple[str, str, bool]:
    if encoding != "auto":
        return data.decode(encoding), encoding, False
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16", True
    try:
        return data.decode("utf-8-sig"), "utf-8", data.startswith(b"\xef\xbb\xbf")
    except UnicodeDecodeError:
        return data.decode("cp1251"), "cp1251", False


def _event_parts(payload: str, order: list[str]) -> list[str]:
    text_index = order.index("Text")
    prefix = payload.split(",", text_index)
    if len(prefix) <= text_index:
        raise ValueError("Недостаточно полей события")
    suffix_count = len(order) - text_index - 1
    if suffix_count:
        tail = prefix[-1].rsplit(",", suffix_count)
        return prefix[:-1] + tail
    return prefix


def parse_ass(text: str) -> Document:
    doc = Document(skeleton=[], newline="\r\n" if "\r\n" in text else "\n", trailing_newline=text.endswith(("\n", "\r")))
    section = ""
    order = list(ASS_FIELDS)
    event_index = 0
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.lower()
        if section == "[events]" and stripped.lower().startswith("format:"):
            order = [s.strip() for s in stripped.split(":", 1)[1].split(",")]
        if section == "[events]" and stripped.startswith(("Dialogue:", "Comment:")):
            current_event_index = event_index
            event_index += 1
            try:
                if not {"Start", "End", "Text"}.issubset(order):
                    raise ValueError("Неизвестный Format событий")
                parts = _event_parts(line.split(":", 1)[1].lstrip(" "), order)
                if len(parts) != len(order):
                    raise ValueError("Число полей не совпадает с Format")
                values = dict(zip(order, parts))
                start, end = parse_time(values["Start"]), parse_time(values["End"])
                if end < start:
                    raise ValueError("Обратный интервал")
                cue = Cue(start=start, end=end, text=values["Text"], original=values["Text"], character=values.get("Name", values.get("Actor", "")), comment=stripped.startswith("Comment:"), field_order=list(order), ass_fields=values, original_line=line)
                cue.baseline = cue.editable()
                doc.cues.append(cue)
                doc.register_source(cue)
                doc.source_lines[cue.id]["origin"]["event_index"] = current_event_index
                doc.skeleton.append(None)
                continue
            except (ValueError, KeyError) as exc:
                doc.warnings.append(f"Строка {number} сохранена без изменений: {exc}")
        doc.skeleton.append(line)
    return doc


def parse_srt(text: str, *, vtt: bool = False) -> Document:
    doc = Document()
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if " --> " in line), -1)
        if timing < 0:
            if block.strip() and not (vtt and block.startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))):
                doc.warnings.append("Пропущен блок без таймкодов: " + block[:60])
            continue
        match = re.match(r"(\S+)\s+-->\s+(\S+)(.*)", lines[timing])
        if not match:
            raise ValueError("Некорректная строка таймкодов")
        start, end = parse_time(match[1]), parse_time(match[2])
        if end <= start:
            raise ValueError("Конец реплики должен быть позже начала")
        body = "\n".join(lines[timing + 1:])
        body = re.sub(r"<(b|i|u)>", lambda m: "{\\" + m[1] + "1}", body)
        body = re.sub(r"</(b|i|u)>", lambda m: "{\\" + m[1] + "0}", body)
        cue = Cue(start=start, end=end, text=body.replace("\n", r"\N"), original=body.replace("\n", r"\N"), extras={"timing_settings": match[3].strip(), "import_format": "vtt" if vtt else "srt"})
        doc.cues.append(cue)
        doc.register_source(cue)
    return doc


def parse_txt(text: str) -> Document:
    doc = Document()
    for line in text.splitlines():
        if not line.strip():
            continue
        character = ""
        match = re.match(r"^([^:]{1,40}):\s+(.+)$", line)
        if match:
            character, line = match.groups()
        # Placeholder intervals are labelled as untimed; they are not inferred timing.
        cue = Cue(start=len(doc.cues) * 2000, end=(len(doc.cues) + 1) * 2000, text=line, original=line, character=character, extras={"untimed": True})
        doc.cues.append(cue)
        doc.register_source(cue)
    return doc


def load_document(path: str | Path, encoding: str = "auto") -> Document:
    path = Path(path)
    data = path.read_bytes()
    if len(data) > 100 * 1024 * 1024:
        raise ValueError("Файл субтитров слишком большой (больше 100 МБ)")
    if path.suffix.lower() == ".substance":
        return Document.from_dict(json.loads(data.decode("utf-8")))
    text, detected, bom = decode_bytes(data, encoding)
    suffix = path.suffix.lower()
    if suffix in (".ass", ".ssa"):
        doc = parse_ass(text)
        doc.encoding, doc.bom = detected, bom
        sidecar = path.with_name(path.name + ".substance")
        if sidecar.exists():
            try:
                saved = json.loads(sidecar.read_text(encoding="utf-8"))
                if saved.get("ass_sha256") == hashlib.sha256(data).hexdigest():
                    return Document.from_dict(saved)
                doc.warnings.append("ASS изменён вне Substance; старый файл перевода не применён.")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                doc.warnings.append("Не удалось прочитать данные перевода: " + str(exc))
    elif suffix == ".srt":
        doc = parse_srt(text)
    elif suffix == ".vtt":
        doc = parse_srt(text, vtt=True)
    elif suffix == ".txt":
        doc = parse_txt(text)
    else:
        raise ValueError("Поддерживаются ASS, SSA, SRT, VTT, TXT и проекты .substance")
    doc.metadata.update(source_path=str(path), source_format=suffix, source_sha256=hashlib.sha256(data).hexdigest())
    return doc


def atomic_write(path: str | Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_document(doc: Document, path: str | Path, *, use_ass_styles=True) -> None:
    doc.validate()
    path = Path(path)
    if path.suffix.lower() == ".substance":
        data = json.dumps(doc.to_dict(), ensure_ascii=False, indent=2).encode("utf-8")
        if len(data) > 100 * 1024 * 1024:
            raise ValueError("Проект больше 100 МБ. Удалите ненужные изображения.")
        atomic_write(path, data)
    else:
        data = doc.ass_bytes(use_ass_styles=use_ass_styles)
        sidecar = doc.to_dict(project_data=False)
        sidecar["ass_sha256"] = hashlib.sha256(data).hexdigest()
        # Sidecar first: a failed ASS write cannot make a mismatching translation load.
        atomic_write(path.with_name(path.name + ".substance"), json.dumps(sidecar, ensure_ascii=False, indent=2).encode("utf-8"))
        atomic_write(path, data)


def export_document(doc: Document, path: str | Path, *, originals: bool = False, use_ass_styles=True) -> None:
    path = Path(path)
    doc = deepcopy(doc)
    cards = {c.id: c for c in doc.characters}
    for cue in doc.cues:
        if cue.character_id in cards:
            cue.character = cards[cue.character_id].export_name or cards[cue.character_id].name
    if originals:
        for cue in doc.cues:
            cue.text, cue.translation = cue.original, None
    suffix = path.suffix.lower()
    if suffix == ".ass":
        atomic_write(path, doc.ass_bytes(use_ass_styles=use_ass_styles or originals))
    elif suffix in (".srt", ".vtt"):
        blocks = []
        for cue in doc.cues:
            if cue.comment:
                continue
            body = plain_text(cue.output_text)
            index = len(blocks) + 1
            blocks.append(f"{index}\n{format_time(cue.start, srt=suffix == '.srt')} --> {format_time(cue.end, srt=suffix == '.srt')}\n{body}")
        result = ("WEBVTT\n\n" if suffix == ".vtt" else "") + "\n\n".join(blocks) + "\n"
        atomic_write(path, result.encode("utf-8"))
    elif suffix == ".txt":
        atomic_write(path, "\n".join((c.character + ": " if c.character else "") + plain_text(c.output_text).replace("\n", " ") for c in doc.cues if not c.comment).encode("utf-8"))
    else:
        raise ValueError("Экспорт: ASS, SRT, VTT или TXT")
