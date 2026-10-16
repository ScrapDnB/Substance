"""ASS exchange without inventing cue identity or changing source provenance."""

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile

from .documents import STAMP, read_subtitle, validate_document

ORIGIN_PREFIX = "; DubbingManager-Origin: "
FIELDS = [
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
]
DEFAULT_HEADER = [
    "[Script Info]",
    "ScriptType: v4.00+",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    "Style: Default,Arial,48,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1",
]


def output_text(cue):
    return cue["translation"] if cue.get("translation") is not None else cue["text"]


def ass_text(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\N")


def ass_time(ms):
    # ASS has centisecond precision. Unchanged exported values must not round the
    # authoritative millisecond timings during a return transfer.
    cs = ms // 10
    return f"{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}"


def header(skeleton):
    """Export only ASS presentation, never project/media paths or discussions."""
    result, section = [], ""
    for line in skeleton:
        if line is None:
            continue
        if re.fullmatch(r"\s*\[.*\]\s*", line):
            section = line.strip().lower()
        if section not in ("[script info]", "[v4+ styles]", "[v4 styles]"):
            continue
        if line.strip().startswith(ORIGIN_PREFIX.strip()):
            continue
        if re.match(
            r"\s*(Video File|Audio File|Video Position|Video AR Mode|Video AR Value):",
            line,
            re.I,
        ):
            continue
        result.append(line)
    while result and not result[-1].strip():
        result.pop()
    return result


def export_header(document):
    result = header(document.get("extras", {}).get(STAMP, {}).get("skeleton", []))
    if not any(s.strip().lower() == "[script info]" for s in result):
        result = DEFAULT_HEADER[:3] + result
    if not any(s.strip().lower() in ("[v4+ styles]", "[v4 styles]") for s in result):
        result += DEFAULT_HEADER[3:]
    while result and not result[-1].strip():
        result.pop()
    return result


def row_fields(cue):
    fields = {
        "Layer": "0",
        "Style": "Default",
        "Name": "",
        "MarginL": "0",
        "MarginR": "0",
        "MarginV": "0",
        "Effect": "",
    }
    fields.update(cue.get("ass_fields", {}))
    fields.update(
        Start=ass_time(cue["start"]),
        End=ass_time(cue["end"]),
        Text=ass_text(output_text(cue)),
    )
    return fields


def write_ass(path, document, origin, names=None):
    validate_document(document)
    path = Path(path)
    if path.suffix.lower() != ".ass":
        raise ValueError("Выберите файл с расширением .ass")
    lines = export_header(document)
    index = next(
        i for i, line in enumerate(lines) if line.strip().lower() == "[script info]"
    )
    lines.insert(
        index + 1,
        ORIGIN_PREFIX + json.dumps(origin, ensure_ascii=True, separators=(",", ":")),
    )
    lines += ["", "[Events]"]
    previous_order = None
    for cue in document["cues"]:
        fields = row_fields(cue)
        if names is not None and cue.get("character_id") in names:
            fields["Name"] = names[cue["character_id"]]
            if "Actor" in fields:
                fields["Actor"] = fields["Name"]
        order = list(FIELDS[:-1]) + [k for k in fields if k not in FIELDS] + ["Text"]
        if order != previous_order:
            lines.append("Format: " + ", ".join(order))
            previous_order = order
        if any(
            not isinstance(fields[k], str) or any(c in fields[k] for c in "\r\n,")
            for k in order[:-1]
        ):
            raise ValueError("Поле оформления ASS содержит запятую или перенос строки")
        lines.append(
            ("Comment: " if cue.get("comment") else "Dialogue: ")
            + ",".join(fields[k] for k in order)
        )
    raw = ("\n".join(lines) + "\n").encode("utf-8-sig")
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("ASS превышает 16 МБ")
    # Build and validate completely before replacing the destination.
    fd, temporary = tempfile.mkstemp(prefix=".ass-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_ass(path):
    path = Path(path)
    if path.suffix.lower() != ".ass":
        raise ValueError("Выберите файл ASS")
    # Read a bounded snapshot once; never reread a changing file for provenance.
    with path.open("rb") as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("ASS превышает 16 МБ")
    text = raw.decode("utf-8-sig")
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if re.fullmatch(r"\[.*\]", stripped):
            section = stripped.lower()
            continue
        if section != "[events]" or not stripped or stripped.startswith(";"):
            continue
        if stripped.lower().startswith("format:"):
            order = [part.strip() for part in stripped.split(":", 1)[1].split(",")]
            if len(set(order)) != len(order):
                raise ValueError("Повторяющееся поле Format событий ASS")
        elif not re.match(r"(Dialogue|Comment):", stripped, re.I):
            raise ValueError("Нераспознанная строка событий ASS: " + stripped[:100])
    origins = [
        line.strip()[len(ORIGIN_PREFIX) :]
        for line in text.splitlines()
        if line.strip().startswith(ORIGIN_PREFIX)
    ]
    if len(origins) > 1:
        raise ValueError("Повторное происхождение ASS")
    origin = json.loads(origins[0]) if origins else None
    if origins and not isinstance(origin, dict):
        raise ValueError("Некорректное происхождение ASS")
    # Reuse the loss-preserving parser, with no tag stripping or name splitting.
    with tempfile.TemporaryDirectory(prefix="dm-ass-") as directory:
        frozen = Path(directory) / "snapshot.ass"
        frozen.write_bytes(raw)
        wire, _, _ = read_subtitle(
            frozen, {"strip_override_tags": False, "split_character_names": False}
        )
    return {
        "origin": origin,
        "rows": wire["cues"],
        "header": header(wire["extras"][STAMP]["skeleton"]),
    }


def mapped_document(base, imported, mapping):
    """One incoming row -> one existing cue, or explicit skip. Never delete/add."""
    if set(mapping) != {str(i) for i in range(len(imported["rows"]))}:
        raise ValueError("Сопоставьте или пропустите каждую строку ASS")
    ids = {c["id"] for c in base["cues"]}
    selected = [value for value in mapping.values() if value != "skip"]
    if any(value not in ids for value in selected) or len(set(selected)) != len(
        selected
    ):
        raise ValueError(
            "Разделение/объединение ASS неоднозначно: одна реплика может быть выбрана только один раз"
        )
    result = deepcopy(base)
    targets = {c["id"]: c for c in result["cues"]}
    for i, row in enumerate(imported["rows"]):
        if mapping[str(i)] == "skip":
            continue
        cue = targets[mapping[str(i)]]
        expected = row_fields(cue)
        if row["text"] != expected["Text"]:
            cue["translation"] = row["text"]
        for key in ("start", "end"):
            if row[key] != cue[key] // 10 * 10:
                cue[key] = row[key]
        cue["comment"] = row["comment"]
        formatting_changed = False
        for key, value in row["ass_fields"].items():
            # Actor names do not rename shared cards or rebind character IDs.
            if key not in (
                "Start",
                "End",
                "Text",
                "Name",
                "Actor",
            ) and value != expected.get(key):
                cue.setdefault("ass_fields", {})[key] = value
                formatting_changed = True
        if formatting_changed:
            # Substance may reuse original_line when its editable text/timing
            # baseline is unchanged. A style-only return must invalidate it.
            details = cue.setdefault("extras", {}).setdefault(STAMP, {})
            details["original_line"] = ""
            order = details.setdefault("field_order", list(FIELDS))
            for key in row["ass_fields"]:
                if key not in order:
                    order.insert(order.index("Text"), key)
    # ASS presentation changes are a separate visible three-way comparison.
    # Keep opaque server sections and event slots, and replace only these headers.
    if any(value != "skip" for value in mapping.values()) and imported[
        "header"
    ] != export_header(base):
        skeleton = base.get("extras", {}).get(STAMP, {}).get("skeleton", [])
        retained, section = [], ""
        for line in skeleton:
            if line is not None and re.fullmatch(r"\s*\[.*\]\s*", line):
                section = line.strip().lower()
            if section not in ("[script info]", "[v4+ styles]", "[v4 styles]"):
                retained.append(line)
        if not any(line and line.strip().lower() == "[events]" for line in retained):
            retained += ["[Events]", "Format: " + ", ".join(FIELDS)] + [None] * len(
                base["cues"]
            )
        result.setdefault("extras", {}).setdefault(STAMP, {})["skeleton"] = (
            imported["header"] + retained
        )
    validate_document(result)
    return result
