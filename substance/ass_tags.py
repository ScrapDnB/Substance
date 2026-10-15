"""ASS override tokens, selective cleanup, and lossless editor presentation."""
from collections import Counter
import re

BLOCK = re.compile(r"\{[^{}]*\}")
# Longest prefix first: e.g. \fscx must not be mistaken for \fs.
NAMES = sorted("b i u s fn fs fscx fscy fsp fr frx fry frz fax fay fe c 1c 2c 3c 4c alpha 1a 2a 3a 4a a an pos move org fad fade bord xbord ybord shad xshad yshad blur be q r t k K kf ko kt p pbo clip iclip".split(), key=len, reverse=True)


def tokens(body):
    """Yield top-level commands including their arguments; keep transforms whole."""
    starts, depth = [], 0
    for i, char in enumerate(body):
        if char == "\\" and depth == 0:
            starts.append(i)
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(body)
        raw = body[start:end]
        tail = raw[1:]
        name = next((n for n in NAMES if tail.startswith(n)), None)
        if name is None:
            match = re.match(r"[0-9]*[A-Za-z]+", tail)
            name = match[0] if match else ""
        if name:
            yield start, end, name, raw


def command_names(body):
    for _, _, name, raw in tokens(body):
        yield name
        if name == "t" and "(" in raw and raw.rstrip().endswith(")"):
            yield from command_names(raw[raw.index("(") + 1:raw.rfind(")")])


def inventory(texts):
    counts = Counter()
    lines = Counter()
    for text in texts:
        found = Counter(name for block in BLOCK.finditer(text) for name in command_names(block[0][1:-1]))
        counts.update(found)
        lines.update(found.keys())
    return [{"name": name, "label": "\\" + name, "count": counts[name], "lines": lines[name]} for name in sorted(counts)]


def _clean_body(body, selected):
    result, cursor = [], 0
    for start, end, name, raw in tokens(body):
        result.append(body[cursor:start])
        if name not in selected:
            if name == "t" and "(" in raw and raw.rstrip().endswith(")"):
                opening, closing = raw.index("("), raw.rfind(")")
                original = raw[opening + 1:closing]
                inner = _clean_body(original, selected)
                # A transform without commands has no effect.
                if inner != original:
                    raw = raw[:opening + 1] + inner + raw[closing:] if list(tokens(inner)) else ""
            result.append(raw)
        cursor = end
    result.append(body[cursor:])
    return "".join(result)


def remove_tags(text, selected):
    def replace(match):
        body = match[0][1:-1]
        cleaned = _clean_body(body, set(selected))
        if cleaned == body:
            return match[0]
        return "{" + cleaned + "}" if cleaned else ""
    return BLOCK.sub(replace, text)


def remove_document_tags(editor, selected):
    def apply(doc):
        for index, cue in enumerate(doc.cues):
            key = "translation" if cue.translation is not None else "text"
            value = remove_tags(getattr(cue, key), selected)
            if value != getattr(cue, key):
                setattr(cue, key, value)
                # Cleanup changes the output, never the immutable source snapshot.
                cue.extras.pop("authoring", None)
    return editor.transact("Удаление ASS-тегов", apply)
